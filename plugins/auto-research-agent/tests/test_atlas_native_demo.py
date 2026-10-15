"""Real HTTP/SQLite/Python fake-child smoke; no real Codex/model execution."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import atlas_test_paths  # noqa: F401 -- explicit repository CLI bootstrap.
import atlas_native_demo as demo


class AtlasNativeDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "retained-demo"

    def make(self):
        self.server, self.receipt = demo.build_demo(self.root, lease=60)
        self.addCleanup(self.server.server_close)
        return self.server

    def request(self, route, body=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        headers = {"Authorization": "Bearer " + self.server.credential}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode()
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Origin": self.server.expected_origin,
                }
            )
        connection.request("GET" if body is None else "POST", route, encoded, headers)
        result = connection.getresponse()
        raw = result.read()
        connection.close()
        return result.status, json.loads(raw)

    def view(self):
        status, value = self.request("/api/native/projects/repo-case")
        self.assertEqual(status, 200, value)
        return value

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("synthetic condition not observed")

    def count(self):
        return len(
            (self.root / "views/repo-case/received.jsonl").read_bytes().splitlines()
        )

    def pending(self):
        return next(
            (q for q in self.view()["requests"] if q["status"] == "pending"), None
        )

    def message(self, text, key):
        status, offer = self.request("/api/native/projects/repo-case/offer")
        self.assertEqual(status, 200)
        body = {k: offer[k] for k in ("revision", "offer_ref", "offer_sha256")}
        body.update(text=text, key=key)
        status, result = self.request("/api/native/projects/repo-case/messages", body)
        self.assertEqual(status, 200, result)
        self.wait(lambda: self.pending() is not None)

    def answer(self, result, key):
        view = self.view()
        question = next((q for q in view["requests"] if q["status"] == "pending"), None)
        diagnostic = dict(
            phase="before-answer",
            session_failure=view["failure"],
            request_statuses=[q["status"] for q in view["requests"]],
        )
        if view["failure"] is not None or question is None:
            diagnostic["owner_status"] = self.server.native_runtime.status()
        self.assertIsNone(view["failure"], diagnostic)
        self.assertIsNotNone(question, diagnostic)
        body = {k: view[k] for k in ("revision", "index_sha256", "input_version")}
        body.update(
            key=key,
            request_ref=question["request_ref"],
            request_sha256=question["request_sha256"],
            result=result,
        )
        status, value = self.request("/api/native/projects/repo-case/answers", body)
        self.assertEqual(status, 200, value)
        self.wait(
            lambda: (
                self.pending() is None
                and not any(q["can_interrupt"] for q in self.view()["operations"])
            )
        )
        return body

    def test_answer_request_and_revision_use_one_snapshot(self):
        question = dict(
            status="pending", request_ref="request-one", request_sha256="hash-one"
        )
        view = dict(
            failure=None,
            revision=42,
            index_sha256="index-one",
            input_version="input-one",
            requests=[question],
        )
        with (
            patch.object(self, "view", return_value=view) as snapshot,
            patch.object(self, "pending", side_effect=AssertionError("extra view")),
            patch.object(self, "wait"),
            patch.object(self, "request", return_value=(200, {})) as dispatch,
        ):
            body = self.answer({"decision": "decline"}, "answer-one")
            snapshot.assert_called_once_with()
            self.assertEqual(body["revision"], 42)
            self.assertEqual(body["request_ref"], "request-one")
            self.assertEqual(body["request_sha256"], "hash-one")
            dispatch.assert_called_once_with(
                "/api/native/projects/repo-case/answers", body
            )

    def test_answer_stopped_or_missing_request_refuses_before_post(self):
        for failure, status in (
            ("session-stopped", "execution-unknown"),
            (None, "request-resolved"),
        ):
            with self.subTest(failure=failure):
                view = dict(failure=failure, requests=[dict(status=status)])
                self.server = Mock()
                self.server.native_runtime.status.return_value = {
                    "repo-case": {"failure": "pump-failed:source-check:TimeoutError"}
                }
                with (
                    patch.object(self, "view", return_value=view),
                    patch.object(self, "request") as dispatch,
                    self.assertRaisesRegex(
                        AssertionError, "before-answer.*owner_status"
                    ),
                ):
                    self.answer({"decision": "decline"}, "answer-one")
                dispatch.assert_not_called()

    def test_installed_combination_question_approval_interrupt_stage_checks_and_replay(
        self,
    ):
        server = self.make()
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        self.addCleanup(worker.join, 10)
        self.addCleanup(server.shutdown)
        self.assertFalse(self.receipt["model_executed"])
        self.assertFalse(self.receipt["original_stage1_lineage_attested"])
        count = self.count()
        self.assertIsNotNone(self.pending())
        self.assertEqual(count, self.count())  # HTTP reads never write native RPCs.
        body = self.answer(
            {"answers": {"q": {"answers": ["Review methods"]}}}, "answer-question"
        )
        count = self.count()
        status, replay = self.request("/api/native/projects/repo-case/answers", body)
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(count, self.count())
        self.message("approval", "message-approval")
        self.assertTrue(self.pending()["can_accept"])
        self.answer({"decision": "accept"}, "accept-synthetic-noop")
        self.message("question", "message-interrupt")
        view = self.view()
        operation = next(o for o in view["operations"] if o["can_interrupt"])
        body = {k: view[k] for k in ("revision", "index_sha256", "input_version")}
        body.update(
            key="interrupt-synthetic",
            action_ref=operation["action_ref"],
            action_sha256=operation["action_sha256"],
        )
        status, result = self.request("/api/native/projects/repo-case/interrupts", body)
        self.assertEqual(status, 200, result)
        self.wait(lambda: self.pending() is None)
        count = self.count()
        for stage, action in (
            (1, "checkpoint-stage1"),
            (2, "inspect-stage2"),
            (2, "review-stage"),
        ):
            status, offer = self.request(
                f"/api/stages/projects/repo-case/offers/{stage}/{action}"
            )
            self.assertEqual(status, 200, offer)
            body = {k: offer[k] for k in ("revision", "offer_ref", "offer_sha256")}
            body.update(
                {k: offer["document"][k] for k in ("index_sha256", "input_version")}
            )
            review = action == "review-stage"
            body.update(
                stage=stage,
                action=action,
                key=f"stage-{action}",
                decision="request-next" if review else None,
                note="Synthetic review only; do not run a next stage."
                if review
                else "",
                confirmed=review,
            )
            status, result = self.request(
                "/api/stages/projects/repo-case/actions", body
            )
            self.assertEqual(status, 200, result)
            self.assertEqual(result["outcome"], "succeeded")
            if review:
                self.assertFalse(result["result"]["execution_authorized"])
            status, replay = self.request(
                "/api/stages/projects/repo-case/actions", body
            )
            self.assertEqual(status, 200, replay)
            self.assertEqual(result["key"], replay["key"])
        self.assertEqual(
            count, self.count()
        )  # Offline stage checks cannot invoke the child.
        self.assertTrue(any((self.root / "outputs/stages").rglob("result.json")))

    def test_startup_output_and_browser_failures_reap_and_record(self):
        for fault in ("print", "browser"):
            with self.subTest(fault=fault):
                output = self.root.parent / fault
                server, receipt = demo.build_demo(output, lease=60)
                if fault == "print":
                    mocked = patch(
                        "builtins.print",
                        side_effect=BrokenPipeError("synthetic stdout failure"),
                    )
                else:
                    mocked = patch.object(
                        demo.webbrowser,
                        "open",
                        side_effect=OSError("synthetic browser failure"),
                    )
                with mocked, self.assertRaises((BrokenPipeError, OSError)):
                    demo.serve_demo(server, receipt, output, open_browser=True)
                completed = json.loads((output / "demo-completion.json").read_bytes())
                self.assertEqual(completed["cleanup_errors"], [])
                self.assertTrue(
                    completed["native_shutdown"]["repo-case"]["leader_reaped"]
                )
                self.assertIsNotNone(completed["host_error"])

    def test_unobserved_factory_cleanup_is_retained_in_failure_receipt(self):
        from research_workspace_native.runtime_spec import CompositionError

        error = CompositionError("synthetic unobserved cleanup")
        error.runtime, error.orphan = object(), {"store": object()}
        with patch(
            "research_workspace_native.runtime_factory.compose_runtime",
            side_effect=error,
        ):
            with self.assertRaises(CompositionError):
                demo.build_demo(self.root, lease=60)
        receipt = json.loads((self.root / "demo-failed.json").read_bytes())
        self.assertTrue(receipt["composition_cleanup_unobserved"])
        self.assertTrue(receipt["partial_runtime_retained"])
        self.assertTrue(receipt["partial_orphan_retained"])

    def test_existing_output_cannot_be_overwritten(self):
        self.root.mkdir()
        marker = self.root / "retain.txt"
        marker.write_bytes(b"old intent/failure")
        with patch(
            "research_workspace_native.runtime_factory.compose_runtime"
        ) as factory:
            with self.assertRaises(FileExistsError):
                demo.build_demo(self.root)
            factory.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"old intent/failure")


if __name__ == "__main__":
    unittest.main()
