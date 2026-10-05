"""Synthetic native archive/trace joins; not namespace or scientific evidence."""

import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from native_trace_fixture import NativeTraceFixture
import test_stage2_judge_worker as worker_fixture
from test_stage2_judge_worker import RUN, VALUE, write_json
from stage1_eval.common import canonical
from stage2_common import Stage2Error
from stage2_live.judge_trace_replay import verify_judge_trace_unit
import stage2_live.judge_trace_replay as replay_module


class JudgeTraceReplayTests(NativeTraceFixture):
    def setUp(self):
        super().setUp()
        self.trace_parent = self.root.parent / "traces"
        self.trace_parent.mkdir()
        self.root.rename(self.trace_parent / "trace-original")
        self.root = self.trace_parent / "trace-original"
        self.worker = worker_fixture.JudgeWorkerTests()
        self.worker.setUp()
        self.addCleanup(self.worker.doCleanups)

        def success(command, **_kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(canonical(VALUE))
            rows = [
                {"type": "thread.started", "thread_id": self.rollout},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(VALUE)},
                },
                {"type": "turn.completed"},
            ]
            return SimpleNamespace(
                returncode=0,
                stdout=b"".join(canonical(row) + b"\n" for row in rows),
                stderr=b"",
            )

        self.worker.success = success
        self.completed = self.worker.completed()
        self.envelope = self.root.parent.parent / "envelope"
        self.envelope.mkdir()
        for name in ("native.stdout", "native.stderr", "native-result.json"):
            (self.envelope / name).write_bytes(b"sealed synthetic envelope")
        self.seal_file = self.root.parent.parent / "original-seal.json"
        self._inference("i1", "response1")
        self._finish()
        self.seal()

    def seal(self):
        inventory, _ = self._write()
        self.original = {
            "label": self.worker.unit["label"],
            "role": "R1",
            "request_sha256": self.worker.request_sha256,
            "worker_result_sha256": self.completed["result_sha256"],
            "traces": {self.root.name: inventory},
            **{
                key: hashlib.sha256((self.envelope / name).read_bytes()).hexdigest()
                for name, key in (
                    ("native.stdout", "native_stdout_sha256"),
                    ("native.stderr", "native_stderr_sha256"),
                    ("native-result.json", "native_result_sha256"),
                )
            },
        }
        write_json(self.seal_file, self.original)
        self.seal_sha = hashlib.sha256(self.seal_file.read_bytes()).hexdigest()

    def verify(self):
        return verify_judge_trace_unit(
            self.worker.output,
            self.completed["result_sha256"],
            request_file=self.worker.request,
            request_sha256=self.worker.request_sha256,
            codex=self.worker.codex,
            evaluator_home=self.worker.home,
            trace_root=self.trace_parent,
            seal_file=self.seal_file,
            externally_retained_seal_sha256=self.seal_sha,
            envelope_root=self.envelope,
        )

    def test_join_recomputes_usage_and_offered_tools_without_call_or_write(self):
        before = {
            p: p.read_bytes()
            for base in (self.root.parent.parent, self.worker.root)
            for p in base.rglob("*")
            if p.is_file()
        }
        with mock.patch(RUN) as run:
            result = self.verify()
        run.assert_not_called()
        self.assertTrue(result["authenticated"])
        self.assertEqual(
            result["token_usage_totals"],
            {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        self.assertEqual(result["actual_root_attempts"], 1)
        self.assertEqual(result["new_model_calls"], 0)
        self.assertEqual(
            result["observations"][0]["threads"][0]["offered_tools"]["counts"],
            {"namespace": 1, "custom": 1, "function": 1, "other": 0},
        )
        self.assertFalse(result["formal_ready"])
        self.assertEqual(result["namespace_isolation"], "not-attested-by-this-replay")
        self.assertEqual(result["semantic_validation"], "host-required")
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_original_seal_cannot_be_replaced_by_rehashing_evidence(self):
        self.original["traces"] = {}
        write_json(self.seal_file, self.original)
        with self.assertRaisesRegex(Stage2Error, "original-seal-mismatch"):
            self.verify()

    def test_request_traversal_alias_passes_only_checked_path_to_worker(self):
        checked = self.worker.request.absolute()
        alias_parent = checked.parent / "alias-component"
        alias_parent.mkdir()
        self.worker.request = alias_parent / ".." / checked.name
        with mock.patch.object(
            replay_module,
            "verify_worker_output",
            wraps=replay_module.verify_worker_output,
        ) as verify_worker:
            self.verify()
        self.assertEqual(verify_worker.call_args.kwargs["request_file"], checked)
        self.assertNotEqual(self.worker.request, checked)

    def test_wrong_unit_binding_and_native_envelope_reject(self):
        for key, changed in (
            ("role", "R2"),
            ("request_sha256", "a" * 64),
            ("worker_result_sha256", "b" * 64),
        ):
            with self.subTest(key=key):
                saved = copy.deepcopy(self.original)
                self.original[key] = changed
                write_json(self.seal_file, self.original)
                self.seal_sha = hashlib.sha256(self.seal_file.read_bytes()).hexdigest()
                with self.assertRaisesRegex(Stage2Error, "seal-binding"):
                    self.verify()
                self.original = saved
        self.seal()
        (self.envelope / "native.stdout").write_bytes(b"changed")
        with self.assertRaisesRegex(Stage2Error, "envelope-mismatch"):
            self.verify()

    def test_missing_and_foreign_trace_never_prove_complete_accounting(self):
        (self.trace_parent / "trace-extra").mkdir()
        with self.assertRaisesRegex(Stage2Error, "trace-set"):
            self.verify()
        (self.trace_parent / "trace-extra").rmdir()
        stdout = self.worker.output / (
            self.worker.unit["label"] + ".model-call/attempt-01.stdout.jsonl"
        )
        raw = stdout.read_bytes()
        # Keep a valid native archive but change trace roots by regenerating fixture.
        self.rollout = "foreign"
        self.events = json.loads(
            json.dumps(self.events).replace("root-thread", "foreign")
        )
        self.payloads = json.loads(
            json.dumps(self.payloads).replace("root-thread", "foreign")
        )
        self.seal()
        with self.assertRaisesRegex(Stage2Error, "foreign-or-duplicate-root"):
            self.verify()
        self.assertEqual(stdout.read_bytes(), raw)

    def test_rehashed_trace_change_still_needs_original_seal(self):
        (self.root / "trace.jsonl").write_bytes(b"altered")
        with self.assertRaises(Stage2Error):
            self.verify()

    def test_unknown_usage_and_unfinished_review_are_not_zero(self):
        response = next(
            value for value in self.payloads.values() if value.get("response_id")
        )
        response.pop("token_usage")
        self.seal()
        with self.assertRaisesRegex(Stage2Error, "incomplete"):
            self.verify()

    def test_tool_or_child_activity_reject_even_with_complete_native_trace(self):
        terminal = self.events[-3:]
        self.events = self.events[:-3]
        self._event(
            "tool_call_started",
            thread=self.rollout,
            turn=f"turn-{self.rollout}",
            tool_call_id="shell1",
            kind={"type": "shell"},
        )
        self._event(
            "tool_call_ended",
            thread=self.rollout,
            turn=f"turn-{self.rollout}",
            tool_call_id="shell1",
            status="completed",
        )
        self.events.extend(terminal)
        for number, row in enumerate(self.events, 1):
            row["seq"] = number
        self.seal()
        with self.assertRaisesRegex(Stage2Error, "tool-or-child"):
            self.verify()

    def test_trace_count_does_not_drop_attempts(self):
        self.original["traces"] = {}
        write_json(self.seal_file, self.original)
        self.seal_sha = hashlib.sha256(self.seal_file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "attempt-trace-count"):
            self.verify()

    def test_credentials_present_refuses_readonly_replay(self):
        (self.worker.home / "auth.json").write_bytes(b"synthetic credential canary")
        with self.assertRaisesRegex(Stage2Error, "credentials-present"):
            self.verify()

    def test_trace_link_rejects(self):
        target = self.root.parent.parent / "trace-copy"
        shutil.copytree(self.root, target)
        shutil.rmtree(self.root)
        try:
            self.root.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Creating a symlink requires host support")
        with self.assertRaisesRegex(Stage2Error, "link-path"):
            self.verify()
