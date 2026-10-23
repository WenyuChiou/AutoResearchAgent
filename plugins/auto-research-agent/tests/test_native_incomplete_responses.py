"""Provider incomplete events are not local timeouts or retryable noise."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage1_eval.common import EvaluationError  # noqa: E402
from stage1_eval.model import call_model  # noqa: E402
from stage1_eval.model_calls import _completed_agent_json  # noqa: E402
from stage1_eval.native_failures import incomplete_response_failure  # noqa: E402


class IncompleteNativeResponseTests(unittest.TestCase):
    def exercise(self, reason, *, stderr=b"", returncode=1):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        home = root / "home"
        home.mkdir()
        codex = root / "codex"
        codex.write_bytes(b"offline-test-executable")
        schema = root / "schema.json"
        schema.write_text(
            json.dumps(
                {"type": "object", "properties": {}, "additionalProperties": False}
            )
        )
        message = "Incomplete response returned, reason: " + reason
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "error",
                    "message": "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable host.",
                },
            },
            {"type": "turn.started"},
            {"type": "error", "message": message},
            {"type": "turn.failed", "error": {"message": message}},
        ]
        stdout = ("\n".join(json.dumps(e) for e in events) + "\n").encode()
        output = root / "output"
        with mock.patch(
            "stage1_eval.model_calls._execute_bound_process",
            return_value=SimpleNamespace(
                returncode=returncode, stdout=stdout, stderr=stderr
            ),
        ) as run:
            with self.assertRaises(EvaluationError):
                call_model(
                    "explicit synthetic test",
                    schema,
                    output,
                    "plan",
                    codex=codex,
                    evaluator_home=home,
                    model="synthetic-model",
                    reasoning="low",
                    timeout=600,
                    execution_policy={
                        "schema_version": "3.1.0",
                        "timeout_seconds": 600,
                        "max_transient_transport_retries": 1,
                        "evaluator_bundle_sha256": "a" * 64,
                        "tools": "none",
                        "execution_authorized": False,
                    },
                )
        archive = output / "plan.model-call"
        record = json.loads((archive / "attempt-01.record.json").read_bytes())
        self.assertEqual((archive / "attempt-01.stdout.jsonl").read_bytes(), stdout)
        self.assertFalse(record["timed_out"])
        self.assertEqual(record["timeout_seconds"], 600)
        self.assertEqual(record["generation_status"], "failed")
        self.assertEqual((archive / "attempt-01.output.json").read_bytes(), b"")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(list(archive.glob("attempt-*.record.json"))), 1)
        return record

    def test_max_output_limit_is_explicit_and_never_transport_retry(self):
        record = self.exercise("max_output_tokens", stderr=b"earlier request: HTTP 429")
        self.assertEqual(record["failure_class"], "provider-output-limit")
        self.assertIn("max_output_tokens", record["failure_detail"])
        self.assertIn("unknown", record["failure_detail"])

    def test_other_incomplete_reason_stays_separate(self):
        record = self.exercise("content_filter")
        self.assertEqual(record["failure_class"], "provider-incomplete")
        self.assertIn("content_filter", record["failure_detail"])

    def test_incomplete_with_zero_exit_still_fails_without_retry(self):
        record = self.exercise("max_output_tokens", returncode=0)
        self.assertEqual(record["failure_class"], "provider-output-limit")

    def test_startup_warning_with_completed_json_is_not_incomplete(self):
        rows = [
            {
                "type": "item.completed",
                "item": {
                    "type": "error",
                    "message": "Code Mode is unavailable because code-mode host is disabled.",
                },
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"ok":true}'},
            },
            {"type": "turn.completed"},
        ]
        raw = ("\n".join(json.dumps(row) for row in rows)).encode()
        self.assertIsNone(incomplete_response_failure(raw))
        self.assertEqual(_completed_agent_json(raw), {"ok": True})

    def test_model_text_and_malformed_events_do_not_assert_provider_cause(self):
        cases = [
            b"not json",
            b"null",
            b"[]",
            b'{"type":"error","message":42}',
            b'{"type":"turn.failed","error":null}',
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "Incomplete response returned, reason: max_output_tokens",
                    },
                }
            ).encode(),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertIsNone(incomplete_response_failure(raw))

    def test_completed_terminal_keeps_existing_success_after_earlier_error(self):
        rows = [
            {
                "type": "error",
                "message": "Incomplete response returned, reason: max_output_tokens",
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"ok":true}'},
            },
            {"type": "turn.completed"},
        ]
        raw = ("\n".join(json.dumps(row) for row in rows)).encode()
        self.assertIsNone(incomplete_response_failure(raw))
        self.assertEqual(_completed_agent_json(raw), {"ok": True})

    def test_stage3_failed_package_and_resume_never_dispatch_twice(self):
        from stage3_plan.native import NativePlanner
        from stage3_plan.planner import draft_synthetic_plan
        from stage3_plan_fixtures import make_intake, make_plan

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            codex = root / "codex"
            codex.write_bytes(b"offline-stage3-executable")
            home = root / "home"
            home.mkdir()
            callback = NativePlanner(
                codex=codex,
                codex_home=home,
                capture_dir=root / "capture",
                timeout_seconds=600,
            )
            expected = make_plan()
            intake = make_intake(expected)
            arguments = {
                "configuration": {"model": "synthetic-model", "reasoning": "low"},
                "plan_id": expected["plan_id"],
            }
            message = "Incomplete response returned, reason: max_output_tokens"
            raw = (
                json.dumps({"type": "turn.failed", "error": {"message": message}})
                + "\n"
            ).encode()
            with mock.patch(
                "stage1_eval.model_calls._execute_bound_process",
                return_value=SimpleNamespace(returncode=1, stdout=raw, stderr=b""),
            ) as run:
                with self.assertRaisesRegex(Exception, "provider-output-limit"):
                    draft_synthetic_plan(intake, root / "plan", callback, **arguments)
                manifest = json.loads((root / "plan/manifest.json").read_bytes())
                self.assertEqual(manifest["state"], "failed")
                self.assertFalse(manifest["execution_authorized"])
                self.assertFalse((root / "plan/plan.json").exists())
                replay = draft_synthetic_plan(
                    intake,
                    root / "plan",
                    callback,
                    resume_manifest_sha256=manifest["manifest_sha256"],
                    **arguments,
                )
                self.assertEqual(
                    replay["resume_action"], "verified-replay-no-generation"
                )
                self.assertEqual(run.call_count, 1)

    def test_final_failure_overrides_conflicting_historical_incomplete(self):
        old = {
            "type": "error",
            "message": "Incomplete response returned, reason: max_output_tokens",
        }
        for message, expected in [
            (
                "Incomplete response returned, reason: content_filter",
                "provider-incomplete",
            ),
            ("HTTP 401 unauthorized", None),
        ]:
            with self.subTest(message=message):
                raw = (
                    "\n".join(
                        json.dumps(e)
                        for e in [
                            old,
                            {"type": "turn.failed", "error": {"message": message}},
                        ]
                    )
                ).encode()
                actual = incomplete_response_failure(raw)
                if expected is None:
                    self.assertIsNone(actual)
                else:
                    self.assertEqual(actual[0], expected)
                    self.assertIn("content_filter", actual[1])
                    self.assertNotIn("max_output_tokens", actual[1])
        raw = (
            "\n".join(
                json.dumps(e)
                for e in [old, {"type": "error", "message": "HTTP 401 unauthorized"}]
            )
        ).encode()
        self.assertIsNone(incomplete_response_failure(raw))


if __name__ == "__main__":
    unittest.main()
