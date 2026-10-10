"""Producer failure/ownership regressions with explicit injected native I/O."""

from copy import deepcopy
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from stage_model_fixtures import StageModelFixture, FakeChannel
from stage1_deliverable.common import sha


class StageModelSafetyTests(StageModelFixture):
    def test_truthy_admission_is_not_authority_and_unknown_never_resends(self):
        self.allowed = 1
        model = self.model()
        result = model.run(
            "refused", "interpret the controlled sources", time.monotonic() + 2
        )
        self.assertEqual(result["status"], "execution-unknown")
        self.assertIn("reservation refused", result["failure"])
        self.allowed = True
        self.assertTrue(
            model.run(
                "refused", "interpret the controlled sources", time.monotonic() + 2
            )["replayed"]
        )
        self.assertEqual(self.calls, [])

    def test_commentary_is_retained_but_final_answer_is_selected(self):
        self.mode = "commentary"
        model = self.model()
        result = model.run(
            "commentary", "interpret the controlled sources", time.monotonic() + 10
        )
        self.assertEqual(
            self.verify(model, result)["final_text"],
            "Synthetic controlled source interpretation.",
        )
        self.assertIn(
            "Reading source content", Path(result["raw_artifact"]["path"]).read_text()
        )

    def test_cleanup_failure_keeps_completed_native_frames_without_admitting_result(
        self,
    ):
        self.mode = "cleanup-fail"
        model = self.model()
        result = model.run(
            "cleanup", "interpret the controlled sources", time.monotonic() + 10
        )
        self.assertEqual(result["status"], "execution-unknown")
        self.assertEqual(result["cleanup_failure"], "CompositionError")
        self.assertTrue(Path(result["raw_artifact"]["path"]).is_file())
        with self.assertRaises(ValueError):
            self.verify(model, result)
        self.assertTrue(
            model.run(
                "cleanup", "interpret the controlled sources", time.monotonic() + 10
            )["replayed"]
        )
        self.assertEqual(len(self.calls), 1)

    def test_interrupt_and_expired_http_admission_do_not_resend(self):
        self.mode = "timeout"
        model, output = self.model(), {}
        worker = threading.Thread(
            target=lambda: output.update(
                receipt=model.run(
                    "interrupt",
                    "interpret the controlled sources",
                    time.monotonic() + 10,
                )
            )
        )
        worker.start()
        self.addCleanup(worker.join, 12)
        until, view = time.monotonic() + 5, None
        while time.monotonic() < until:
            view = model.status()["native_view"]
            if view and view["operations"]:
                break
            time.sleep(0.01)
        self.assertTrue(view and view["operations"])
        operation = view["operations"][0]
        body = dict(
            key="interrupt-once",
            revision=view["revision"],
            index_sha256=view["index_sha256"],
            input_version=view["input_version"],
            action_ref=operation["action_ref"],
            action_sha256=operation["action_sha256"],
        )
        before = len(self.runtime.channel.sent)

        def expired():
            raise TimeoutError("expired HTTP admission")

        with self.assertRaises(TimeoutError):
            model.interrupt(body, pre_admission=expired)
        self.assertEqual(len(self.runtime.channel.sent), before)
        self.assertEqual(model.interrupt(body)["status"], "write-observed")
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(output["receipt"]["status"], "execution-unknown")
        self.assertEqual(
            sum(
                m.get("method") == "turn/start" for m in self.runtime.channel.messages()
            ),
            1,
        )
        self.assertEqual(
            sum(
                m.get("method") == "turn/interrupt"
                for m in self.runtime.channel.messages()
            ),
            1,
        )

    def test_source_drift_and_prompt_bounds_reject_before_native_factory(self):
        model = self.model()
        self.user.write_bytes(b"changed account config")
        result = model.run(
            "drift", "interpret the controlled sources", time.monotonic() + 2
        )
        self.assertEqual(result["status"], "execution-unknown")
        for text in ("", "x" * 16385, "\ud800"):
            with self.assertRaises((ValueError, UnicodeError)):
                model.run("bounds", text, time.monotonic() + 2)
        self.assertEqual(self.calls, [])

    def test_missing_terminal_wrong_turn_conflicting_final_and_tools_are_incomplete(
        self,
    ):
        for mode in ("no-terminal", "wrong-turn", "conflict", "tool"):
            with self.subTest(mode=mode):
                self.mode = mode
                model = self.model()
                result = model.run(
                    mode, "interpret the controlled sources", time.monotonic() + 1.1
                )
                self.assertEqual(result["status"], "execution-unknown")
                with self.assertRaises(ValueError):
                    self.verify(model, result)

    def test_rehashed_receipt_or_raw_disk_tampering_is_refused(self):
        model = self.model()
        result = model.run(
            "tamper", "interpret the controlled sources", time.monotonic() + 10
        )
        with self.assertRaises(ValueError):
            self.verify(model, dict(result, source_sha256="a" * 64))
        artifact = Path(result["raw_artifact"]["path"])
        artifact.write_bytes(
            artifact.read_bytes().replace(
                b"Synthetic controlled", b"Fake changed content"
            )
        )
        with self.assertRaises(ValueError):
            self.verify(model, result)
        changed = deepcopy(result)
        changed["raw_artifact"]["sha256"] = sha(artifact.read_bytes())
        with self.assertRaises(ValueError):
            self.verify(model, changed)

    def test_question_answer_uses_active_bound_api_and_rejects_accept(self):
        self.mode = "question"
        model, output = self.model(), {}
        thread = threading.Thread(
            target=lambda: output.update(
                receipt=model.run(
                    "question",
                    "interpret the controlled sources",
                    time.monotonic() + 10,
                )
            )
        )
        thread.start()
        self.addCleanup(thread.join, 12)
        until = time.monotonic() + 5
        view = None
        while time.monotonic() < until:
            api = model.active_api()
            if api is not None:
                view = api.view("token", model.ref)
                if view["requests"]:
                    break
            time.sleep(0.01)
        self.assertTrue(view and view["requests"])
        request = view["requests"][0]
        body = dict(
            key="answer",
            revision=view["revision"],
            index_sha256=view["index_sha256"],
            input_version=view["input_version"],
            request_ref=request["request_ref"],
            request_sha256=request["request_sha256"],
            result=dict(answers=dict(q=dict(answers=["confirmed source scope"]))),
        )
        with self.assertRaises(ValueError):
            model.answer(dict(body, result=dict(decision="accept")))
        self.assertEqual(model.answer(body)["status"], "dispatched")
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(output["receipt"]["status"], "completed", output)
        self.verify(model, output["receipt"])

    def user_message_run(self, changed=False):
        original = FakeChannel.finish
        prompt = "interpret the controlled sources"

        def finish(channel):
            item = dict(
                type="userMessage",
                id="user-input",
                clientId=None,
                content=[
                    dict(
                        type="text",
                        text=prompt + (" changed" if changed else ""),
                        text_elements=[],
                    )
                ],
            )
            for method in ("item/started", "item/completed"):
                channel.queue(
                    dict(
                        method=method,
                        params=dict(
                            threadId="fake-thread", turnId="fake-turn", item=item
                        ),
                    )
                )
            original(channel)

        model = self.model()
        with patch.object(FakeChannel, "finish", finish):
            result = model.run(
                "changed-user" if changed else "exact-user",
                prompt,
                time.monotonic() + (1.1 if changed else 10),
            )
        return model, result

    def test_bound_native_user_messages_are_not_tools(self):
        model, result = self.user_message_run()
        self.assertEqual(result["status"], "completed", result)
        verified = self.verify(model, result)
        self.assertEqual(verified["observed_tool_items"], [])
        self.assertEqual(
            verified["final_text"], "Synthetic controlled source interpretation."
        )

    def test_changed_native_user_prompt_is_rejected(self):
        model, result = self.user_message_run(changed=True)
        self.assertEqual(result["status"], "execution-unknown", result)
        with self.assertRaises(ValueError):
            self.verify(model, result)


if __name__ == "__main__":
    unittest.main()
