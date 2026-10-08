"""Synthetic composition tests; patched replay never authenticates native execution."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live.no_tool_call import (  # noqa: E402
    NoToolCallFailure,
    resume_no_tool_call,
    run_no_tool_call,
)
from stage2_live.no_tool_trace_capture import NoToolTraceCaptureFailure  # noqa: E402


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True).encode() + b"\n")


class NoToolCallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.output = self.base / "calls"
        self.evidence = self.base / "evidence"
        self.telemetry = self.base / "telemetry"
        self.telemetry.mkdir()
        self.expected = {
            "model": "synthetic-model",
            "reasoning": "medium",
            "sandbox_mode": "read-only",
            "approval_policy": "never",
        }
        self.config = {"model": "synthetic-model", "reasoning": "medium"}
        self.roots = {}
        self.callback_count = 0

    def archive(self, label, roots, *, rejected=False):
        archive = self.output / f"{label}.model-call"
        archive.mkdir(parents=True, exist_ok=True)
        fingerprint = hashlib.sha256(label.encode()).hexdigest()
        policy = {
            "kind": "EvaluatorModelExecutionPolicy",
            "schema_version": "3.1.0",
            "timeout_seconds": 60,
            "max_transient_transport_retries": 1,
            "evaluator_bundle_sha256": "b" * 64,
        }
        _write(
            archive / "request.json",
            {
                "archive_version": "3.1.0",
                "label": label,
                "prompt_sha256": "1" * 64,
                "schema_sha256": "2" * 64,
                "generation_schema_sha256": "3" * 64,
                "config": self.config,
                "execution_policy": policy,
                "evaluator_code_sha256": "4" * 64,
                "request_fingerprint_sha256": fingerprint,
            },
        )
        (archive / "prompt.txt").write_text("synthetic prompt", encoding="utf-8")
        _write(archive / "schema.json", {"type": "object"})
        records, stdouts = [], []
        for number, root in enumerate(roots, 1):
            stdout = (
                json.dumps({"type": "thread.started", "thread_id": root}) + "\n"
            ).encode()
            stdout_path = archive / f"attempt-{number:02d}.stdout.jsonl"
            stdout_path.write_bytes(stdout)
            final, record_path = (
                number == len(roots),
                archive / f"attempt-{number:02d}.record.json",
            )
            _write(
                record_path,
                {
                    "archive_version": "3.1.0",
                    "attempt": number,
                    "request_fingerprint_sha256": fingerprint,
                    "config": self.config,
                    "generation_status": "completed" if final else "failed",
                    "semantic_status": "rejected" if final and rejected else "accepted",
                    "failure_class": "schema-mismatch"
                    if final and rejected
                    else (None if final else "transient-transport"),
                    "files": {
                        "stdout": {
                            "path": stdout_path.name,
                            "sha256": hashlib.sha256(stdout).hexdigest(),
                        }
                    },
                },
            )
            records.append(record_path)
            stdouts.append(stdout_path)
        return archive, {
            "execution_status": "native-replayed",
            "call_archive": str(archive),
            "request_fingerprint_sha256": fingerprint,
            "config": self.config,
            "attempt": len(roots),
            "attempt_record_sha256": hashlib.sha256(
                records[-1].read_bytes()
            ).hexdigest(),
            "stdout_sha256": hashlib.sha256(stdouts[-1].read_bytes()).hexdigest(),
        }

    def trace(self, name, root, *, complete=True, tools=None):
        trace = self.telemetry / name
        _write(
            trace / "payloads/config.json",
            {
                "thread_id": root,
                "model": "synthetic-model",
                "reasoning_effort": "medium",
                "sandbox_policy": {"type": "read-only"},
                "approval_policy": "never",
            },
        )
        _write(
            trace / "trace.jsonl",
            {
                "payload": {
                    "type": "protocol_event_observed",
                    "event_type": "session_configured",
                    "event_payload": {
                        "path": "payloads/config.json",
                        "raw_payload_id": "x",
                        "kind": {"type": "test"},
                    },
                }
            },
        )
        (trace / "manifest.json").write_bytes(b"{}\n")
        _write(
            trace / "payloads/request.json",
            {"model": "synthetic-model", "input": [], "tools": tools or []},
        )
        self.roots[name] = (root, complete)

    def observation(self, trace, *_args):
        root, complete = self.roots[trace.name]
        usage = {
            "input_tokens": 5,
            "cached_input_tokens": 2,
            "cache_write_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_output_tokens": 1,
            "total_tokens": 6,
        }
        return {
            "root_thread_id": root,
            "inferences": [
                {
                    "status": "inference_completed",
                    "token_usage": usage,
                    "request_ref": "payloads/request.json",
                    "tools_inherited": False,
                }
            ]
            if complete
            else [],
            "threads": [
                {
                    "thread_id": root,
                    "terminal_status": "completed" if complete else "failed",
                    "offered_tools": {"definitions": []},
                }
            ],
            "counts": {"tool_calls": 0},
            "blockers": [] if complete else ["rollout-not-completed"],
        }

    def native_callback(self, tools=None):
        self.callback_count += 1
        self.output.mkdir()
        archives = dict(
            (archive.name, provenance)
            for archive, provenance in (
                self.archive("initial", ("retry-root", "initial-root")),
                self.archive("correction", ("correction-root",), rejected=True),
            )
        )
        self.trace("trace-a", "retry-root", complete=False, tools=tools)
        self.trace("trace-b", "initial-root", tools=tools)
        self.trace("trace-c", "correction-root", tools=tools)
        self.provenances = archives
        return {"canonical": "result", "model_call_provenance": {"kept": True}}

    def replay(self, archive, **kwargs):
        self.replay_calls.append((archive.name, kwargs))
        return {}, self.provenances[archive.name]

    def invoke(self, execution_policy="no-offered-tools-v1"):
        self.replay_calls = []
        tools = (
            [
                {
                    "type": "function",
                    "name": "unused_synthetic_tool",
                    "parameters": {"type": "object"},
                }
            ]
            if execution_policy == "no-executed-tools-v1"
            else []
        )
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=self.replay,
            ),
            patch(
                "stage2_live.no_tool_trace_capture.inspect_native_trace",
                side_effect=self.observation,
            ),
            patch(
                "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                side_effect=self.observation,
            ),
        ):
            return run_no_tool_call(
                lambda: self.native_callback(tools),
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
                execution_policy=execution_policy,
            )

    def test_calls_once_authenticates_initial_correction_and_returns_original(self):
        result = self.invoke()
        self.assertEqual(self.callback_count, 1)
        self.assertEqual(
            result.result,
            {"canonical": "result", "model_call_provenance": {"kept": True}},
        )
        self.assertEqual(set(result.evidence["units"]), {"initial", "correction"})
        calls = {name: options for name, options in self.replay_calls}
        self.assertFalse(calls["initial.model-call"]["for_correction"])
        self.assertTrue(calls["correction.model-call"]["for_correction"])
        self.assertEqual(
            len(result.evidence["units"]["initial"]["proof"]["attempts"]), 2
        )
        self.assertEqual(result.evidence["execution_policy"], "no-offered-tools-v1")
        self.assertEqual(
            result.evidence["units"]["initial"]["proof"]["kind"],
            "Stage2NoToolTraceEvidence",
        )

    def test_rejects_old_output_before_callback(self):
        self.output.mkdir()
        callback = Mock()
        with self.assertRaisesRegex(Stage2Error, "output-already-exists"):
            run_no_tool_call(
                callback,
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
            )
        callback.assert_not_called()
        self.output.rmdir()
        with self.assertRaisesRegex(Stage2Error, "path-overlap"):
            run_no_tool_call(
                callback,
                output_dir=self.output,
                evidence_dir=self.output,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
            )
        callback.assert_not_called()

    def test_callback_and_authentication_failures_preserve_recoverable_state(self):
        def failed():
            self.output.mkdir()
            (self.output / "raw.txt").write_text("retained", encoding="utf-8")
            raise RuntimeError("synthetic failure")

        with self.assertRaises(NoToolCallFailure) as caught:
            run_no_tool_call(
                failed,
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
            )
        self.assertEqual(caught.exception.phase, "call")
        self.assertIn("capture_token", caught.exception.state)
        self.assertTrue((self.output / "raw.txt").is_file())
        self.assertFalse(self.evidence.exists())

        case = NoToolCallTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=ValueError("bad archive"),
            ),
            self.assertRaises(NoToolCallFailure) as caught,
        ):
            run_no_tool_call(
                case.native_callback,
                output_dir=case.output,
                evidence_dir=case.evidence,
                telemetry_root=case.telemetry,
                expected_config=case.expected,
            )
        self.assertEqual(caught.exception.phase, "authentication")
        self.assertTrue(any(case.output.glob("*.model-call")))

    def test_capture_failure_retains_seals_completed_units_and_opaque_token(self):
        retained = {"initial": {"seal_sha256": "a" * 64}}
        completed = {"initial": {"proof": {"verification_status": "verified"}}}
        failure = NoToolTraceCaptureFailure(
            Stage2Error("after-seal"), retained, completed
        )
        self.replay_calls = []
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=self.replay,
            ),
            patch(
                "stage2_live.no_tool_call.finish_no_tool_trace_capture",
                side_effect=failure,
            ),
            self.assertRaises(NoToolCallFailure) as caught,
        ):
            run_no_tool_call(
                self.native_callback,
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
            )
        state = caught.exception.state
        self.assertEqual(caught.exception.phase, "capture")
        self.assertEqual(state["retained_seal_receipts"], retained)
        self.assertEqual(state["completed_units"], completed)
        self.assertEqual(state["execution_policy"], "no-offered-tools-v1")
        self.assertNotIsInstance(state["capture_token"], (dict, list, str))

    def test_no_execution_policy_preserves_offered_inventory(self):
        result = self.invoke(execution_policy="no-executed-tools-v1")
        proof = result.evidence["units"]["initial"]["proof"]
        self.assertEqual(result.evidence["execution_policy"], "no-executed-tools-v1")
        self.assertEqual(proof["kind"], "Stage2NoExecutionTraceEvidence")
        self.assertEqual(proof["execution_policy"], "no-executed-tools-v1")
        self.assertIn("offered_tool_inventory", proof["attempts"][1])
        self.assertEqual(
            proof["attempts"][1]["offered_tool_inventory"][0]["counts"]["function"],
            1,
        )

    def test_strict_default_rejects_unused_offered_tool(self):
        tool = {
            "type": "function",
            "name": "unused_synthetic_tool",
            "parameters": {"type": "object"},
        }
        self.replay_calls = []
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=self.replay,
            ),
            patch(
                "stage2_live.no_tool_trace_capture.inspect_native_trace",
                side_effect=self.observation,
            ),
            patch(
                "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                side_effect=self.observation,
            ),
            self.assertRaises(NoToolCallFailure) as caught,
        ):
            run_no_tool_call(
                lambda: self.native_callback([tool]),
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
            )
        self.assertEqual(caught.exception.phase, "capture")
        self.assertIn("offered-tools-nonempty", str(caught.exception.__cause__))

    def test_invalid_policy_rejects_before_callback(self):
        callback = Mock()
        with self.assertRaisesRegex(Stage2Error, "execution-policy-invalid"):
            run_no_tool_call(
                callback,
                output_dir=self.output,
                evidence_dir=self.evidence,
                telemetry_root=self.telemetry,
                expected_config=self.expected,
                execution_policy="synthetic-invalid-policy",
            )
        callback.assert_not_called()

    def test_resume_replays_and_verifies_without_callback(self):
        completed = self.invoke()
        receipts = {
            unit: value["seal_sha256"]
            for unit, value in completed.evidence["units"].items()
        }
        self.replay_calls = []
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=self.replay,
            ),
            patch(
                "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                side_effect=self.observation,
            ),
        ):
            resumed = resume_no_tool_call(
                self.output, self.evidence, receipts, expected_config=self.expected
            )
        self.assertEqual(set(resumed["proofs"]), {"initial", "correction"})
        self.assertEqual(
            (resumed["new_model_calls"], resumed["new_tool_calls"]), (0, 0)
        )
        self.assertEqual(len(self.replay_calls), 2)

    def test_resume_rejects_policy_switch_and_receipt_tamper_without_replay(self):
        completed = self.invoke(execution_policy="no-executed-tools-v1")
        receipt = completed.evidence["seal_receipt"]
        self.replay_calls = []
        with (
            patch(
                "stage2_live.no_tool_call.replay_native_model_call_archive",
                side_effect=self.replay,
            ),
            patch(
                "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                side_effect=self.observation,
            ),
        ):
            resumed = resume_no_tool_call(
                self.output,
                self.evidence,
                receipt,
                expected_config=self.expected,
                execution_policy="no-executed-tools-v1",
            )
        self.assertEqual(resumed["execution_policy"], "no-executed-tools-v1")
        self.assertEqual(self.callback_count, 1)

        replay = Mock()
        with (
            patch("stage2_live.no_tool_call.replay_native_model_call_archive", replay),
            self.assertRaisesRegex(Stage2Error, "seal-receipt-policy-mismatch"),
        ):
            resume_no_tool_call(
                self.output,
                self.evidence,
                receipt,
                expected_config=self.expected,
            )
        replay.assert_not_called()

        tampered = dict(receipt)
        tampered["receipt_sha256"] = "0" * 64
        with (
            patch("stage2_live.no_tool_call.replay_native_model_call_archive", replay),
            self.assertRaisesRegex(Stage2Error, "seal-receipt-policy-mismatch"),
        ):
            resume_no_tool_call(
                self.output,
                self.evidence,
                tampered,
                expected_config=self.expected,
                execution_policy="no-executed-tools-v1",
            )
        replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
