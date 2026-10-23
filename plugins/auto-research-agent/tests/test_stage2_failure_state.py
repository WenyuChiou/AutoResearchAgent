# ruff: noqa: E402 -- exercise repository CLI without installation.
"""Synthetic provider/deadline failures; never dispatch a model."""

import json
import hashlib
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live.failure_state import (
    ControllerNativeFailure,
    classify_controller_failure,
    describe_controller_failure,
)


def saved_failure(root, events, *, stderr=""):
    """Seal a deliberately synthetic failed native record; never execute a model."""
    root.mkdir()
    stdout = ("\n".join(json.dumps(row) for row in events) + "\n").encode()
    (root / "stdout.jsonl").write_bytes(stdout)
    (root / "stderr.txt").write_text(stderr, encoding="utf-8")
    record = {
        "kind": "Stage2NativeCapture",
        "status": "failed",
        "exit_code": 1,
        "exception": None,
        "event_summary": {"parse_error": None},
        "evidence_class": "synthetic-test-only",
        "archived_files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ["stdout.jsonl", "stderr.txt"]
        },
    }
    raw = json.dumps(record).encode()
    (root / "run.json").write_bytes(raw)
    return {**record, "record_sha256_receipt": hashlib.sha256(raw).hexdigest()}


class ControllerFailureStateTests(unittest.TestCase):
    def test_real_subprocess_deadline_is_timeout(self):
        self.assertEqual(
            classify_controller_failure(subprocess.TimeoutExpired(["synthetic"], 1)),
            "timeout",
        )

    def test_structured_http_response_and_exact_codes(self):
        for status, expected in [(401, "authentication"), (429, "rate-limit")]:
            with self.subTest(status=status):
                error = RuntimeError("provider failed")
                error.response = SimpleNamespace(status_code=status)
                self.assertEqual(classify_controller_failure(error), expected)
        self.assertEqual(
            classify_controller_failure(RuntimeError("a report mentions 429 values")),
            "unknown",
        )

    def test_parse_failure_remains_separate_from_deadline(self):
        with self.assertRaises(json.JSONDecodeError) as caught:
            json.loads("{")
        self.assertEqual(classify_controller_failure(caught.exception), "format")

    def test_failed_cleanup_is_visible_even_after_a_real_deadline(self):
        error = subprocess.TimeoutExpired(["synthetic"], 1)
        error.cleanup_report = {
            "attempted": True,
            "errors": ["reap failed"],
            "reap_status": "error",
        }
        self.assertEqual(classify_controller_failure(error), "cleanup")

    def test_capture_exception_retains_true_deadline_and_cleanup_separately(self):
        capture = {
            "status": "failed",
            "record_sha256_receipt": "a" * 64,
            "exception": {
                "type": "TimeoutExpired",
                "message": "deadline expired",
                "cleanup_report": {"errors": ["not reaped"], "reap_status": "error"},
            },
        }
        observed = describe_controller_failure(ControllerNativeFailure(capture))
        self.assertEqual(observed["primary_failure_class"], "timeout")
        self.assertEqual(observed["failure_class"], "cleanup")
        self.assertEqual(observed["capture_record_sha256"], "a" * 64)
        self.assertFalse(observed["retry_authorized"])

    def test_capture_without_a_deadline_witness_cannot_be_called_timeout(self):
        error = ControllerNativeFailure(
            {
                "status": "failed",
                "exception": None,
                "event_summary": {"parse_error": None},
            }
        )
        self.assertEqual(classify_controller_failure(error), "unknown")

    def test_receipt_bound_native_provider_errors_and_agent_text_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for code, expected in [(401, "authentication"), (429, "rate-limit")]:
                capture = saved_failure(
                    root / str(code),
                    [
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "HTTP 401"},
                        },
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "aggregated_output": "HTTP 401",
                            },
                        },
                        {
                            "type": "turn.failed",
                            "error": {
                                "message": f"HTTP {code} provider rejected request"
                            },
                        },
                    ],
                )
                error = ControllerNativeFailure(capture, root / str(code))
                observed = describe_controller_failure(error)
                self.assertEqual(observed["failure_class"], expected)
                self.assertEqual(observed["provider_observation"]["codes"], [code])
                self.assertFalse(observed["retry_authorized"])

    def test_native_provider_observation_rejects_mutated_record_and_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ["run.json", "stdout.jsonl", "stderr.txt"]:
                directory = root / name.replace(".", "-")
                capture = saved_failure(
                    directory, [{"type": "error", "message": "HTTP 429"}]
                )
                path = directory / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                observed = describe_controller_failure(
                    ControllerNativeFailure(capture, directory)
                )
                self.assertEqual(observed["failure_class"], "unknown")
                self.assertEqual(
                    observed["provider_observation"]["state"], "unavailable"
                )

    def test_native_agent_only_or_conflicting_errors_remain_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = [
                [
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "HTTP 429"},
                    }
                ],
                [
                    {"type": "error", "status_code": 401},
                    {"type": "turn.failed", "error": {"status_code": 429}},
                ],
            ]
            for index, value in enumerate(events):
                directory = root / str(index)
                capture = saved_failure(directory, value)
                self.assertEqual(
                    classify_controller_failure(
                        ControllerNativeFailure(capture, directory)
                    ),
                    "unknown",
                )

    def test_native_stderr_requires_cli_error_prefix_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, stderr, expected in [
                (
                    0,
                    "Error: provider returned HTTP 429 Too Many Requests",
                    "rate-limit",
                ),
                (1, "report text: HTTP 429", "unknown"),
            ]:
                directory = root / str(index)
                capture = saved_failure(directory, [], stderr=stderr)
                self.assertEqual(
                    classify_controller_failure(
                        ControllerNativeFailure(capture, directory)
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
