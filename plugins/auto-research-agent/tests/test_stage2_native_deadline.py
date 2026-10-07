"""Frozen native call deadlines, failure archives and legacy replay mechanics."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
import test_stage2_live_native as fixtures
from stage2_live import native
from stage2_live.controller import _ProductionAdapter


class NativeDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NativeCaptureTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_legacy_request_and_runner_remain_without_deadline(self):
        def run(command, **kwargs):
            self.assertNotIn("timeout", kwargs)
            return self.fixture.successful_runner(command, **kwargs)

        result = native.capture_native(**self.fixture.args(), process_runner=run)
        self.assertNotIn("timeout_seconds", result["stable_request_binding"])
        self.assertEqual(result["status"], "complete")

    def test_explicit_deadline_bound_and_verified_resume_does_not_execute(self):
        calls = []

        def run(command, **kwargs):
            calls.append(kwargs["timeout"])
            return self.fixture.successful_runner(command, **kwargs)

        result = native.capture_native(
            **self.fixture.args(), timeout_seconds=600, process_runner=run
        )
        self.assertEqual(result["stable_request_binding"]["timeout_seconds"], 600)
        replay = native.capture_native(
            **self.fixture.args(resume=True),
            timeout_seconds=600,
            process_runner=run,
            record_sha256_receipt=result["record_sha256_receipt"],
        )
        self.assertEqual(calls, [600])
        self.assertEqual(replay["resume_action"], "verified-replay-no-execution")
        for changed in (None, 601):
            with (
                self.subTest(changed=changed),
                self.assertRaisesRegex(native.CaptureError, "binding changed"),
            ):
                native.capture_native(
                    **self.fixture.args(resume=True),
                    timeout_seconds=changed,
                    process_runner=run,
                    record_sha256_receipt=result["record_sha256_receipt"],
                )
        self.assertEqual(calls, [600])

    def test_invalid_deadline_rejected_before_output_or_execution(self):
        for value in (True, False, 0, -1, float("nan"), float("inf"), "600"):
            with (
                self.subTest(value=value),
                patch.object(native, "run_bound_process") as run,
                self.assertRaisesRegex(native.CaptureError, "finite and positive"),
            ):
                native.capture_native(**self.fixture.args(), timeout_seconds=value)
            run.assert_not_called()
            self.assertFalse(self.fixture.output.exists())

    def test_partial_stream_and_cleanup_failure_preserved_never_resumed(self):
        error = subprocess.TimeoutExpired(["synthetic-codex"], 600)
        error.cleanup_report = {"status": "failed", "errors": ["owned reap timeout"]}

        def run(command, **kwargs):
            self.assertEqual(kwargs["timeout_seconds"], 600)
            kwargs["stdout"].write(b'{"type":"thread.started","thread_id":"partial"}\n')
            kwargs["stderr"].write(b"before deadline\n")
            raise error

        with patch.object(native, "run_bound_process", side_effect=run) as runner:
            result = native.capture_native(**self.fixture.args(), timeout_seconds=600)
        runner.assert_called_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exception"]["type"], "TimeoutExpired")
        self.assertEqual(result["exception"]["cleanup_report"], error.cleanup_report)
        self.assertEqual(
            (self.fixture.output / "stderr.txt").read_bytes(), b"before deadline\n"
        )
        self.assertIsNone(result["actual_completed_turn_usage"])
        self.assertTrue(
            (self.fixture.output / "archive/workspace-end/source.txt").is_file()
        )
        with (
            patch.object(native, "run_bound_process") as runner,
            self.assertRaisesRegex(native.CaptureError, "only a completed"),
        ):
            native.capture_native(
                **self.fixture.args(resume=True),
                timeout_seconds=600,
                record_sha256_receipt=result["record_sha256_receipt"],
            )
        runner.assert_not_called()

    def test_rehashed_invalid_deadline_binding_fails(self):
        result = native.capture_native(
            **self.fixture.args(),
            timeout_seconds=600,
            process_runner=self.fixture.successful_runner,
        )
        path = self.fixture.output / "run.json"
        original = json.loads(path.read_bytes())
        for invalid in (None, 0, True, "600"):
            with self.subTest(invalid=invalid):
                record = json.loads(json.dumps(original))
                record["stable_request_binding"]["timeout_seconds"] = invalid
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaisesRegex(native.CaptureError, "timeout binding"):
                    native.verify_capture(
                        self.fixture.output,
                        native.sha256(path.read_bytes()),
                        allow_injected_test_capture=True,
                    )
        self.assertEqual(result["status"], "complete")

    def test_controller_uses_frozen_policy_before_staging(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                home, workspace, sources = (
                    root / name for name in ("home", "workspace", "sources")
                )
                for path in (home, workspace, sources):
                    path.mkdir()
                policy = {
                    "schema_version": "3.1.0",
                    "evaluator_bundle_sha256": "b" * 64,
                    "timeout_seconds": 600 if valid else 0,
                    "max_transient_transport_retries": 1,
                    "max_semantic_corrections_per_unit": 1,
                    "retry_timeouts": False,
                }
                spec = {
                    "native": {
                        "codex": "fixture",
                        "model": "gpt-test",
                        "reasoning": "high",
                        "config_bindings": {},
                        "policy_bindings": {},
                        "extraction_policy": policy,
                    }
                }
                with (
                    patch(
                        "stage2_live.controller.preflight_for_environment",
                        return_value={},
                    ),
                    patch("stage2_live.controller.verify_environment_start"),
                    patch("stage2_live.controller.verify_environment_capture"),
                    patch(
                        "stage2_live.controller.capture_native",
                        return_value={
                            "status": "complete",
                            "record_sha256_receipt": "a" * 64,
                            "event_summary": {"thread_id": "fixture"},
                        },
                    ) as capture,
                ):
                    if valid:
                        _ProductionAdapter._capture(
                            {"prompt": "task"},
                            sources,
                            {"home": home, "workspace": workspace},
                            spec,
                            root / "output",
                        )
                        self.assertEqual(
                            capture.call_args.kwargs["timeout_seconds"], 600
                        )
                    else:
                        with self.assertRaises(ValueError):
                            _ProductionAdapter._capture(
                                {"prompt": "task"},
                                sources,
                                {"home": home, "workspace": workspace},
                                spec,
                                root / "output",
                            )
                        capture.assert_not_called()
                        self.assertEqual(list(workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
