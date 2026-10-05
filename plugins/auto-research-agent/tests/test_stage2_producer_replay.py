"""Public replay admission and accounting projection, without model dispatch."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import producer_replay  # noqa: E402
from stage2_live.native import CaptureError  # noqa: E402
import test_stage2_trace_producer as fixtures  # noqa: E402


class ProducerReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.request = {name: None for name in producer_replay.REQUEST_FIELDS}
        self.request["policy_bindings"] = {
            "kind": "Stage2NamedPermissionsPolicy",
            "telemetry_path": str(self.root),
        }
        self.record = {
            "trace": {"root": "trace-1", "inventory": {}, "receipt_sha256": "c" * 64},
            "capture": {"root_thread_id": "root-1"},
            "native_capture_receipt": "n" * 64,
            "runtime_observation_receipt": "o" * 64,
        }
        self.observed = {
            "root_thread_id": "root-1",
            "blockers": [],
            "counts": {
                "inferences": 6,
                "threads": 2,
                "tool_calls": 3,
                "incomplete_inferences": 0,
                "incomplete_tool_calls": 0,
            },
            "token_usage_totals": {"total_tokens": 12},
        }

    def project(self, inventory_status="observed"):
        # These seams exercise a pure projection only, never authentication.
        with (
            patch.object(
                producer_replay.trace_producer, "_verify", return_value=self.record
            ),
            patch.object(
                producer_replay.trace_observation,
                "inspect_native_trace",
                return_value=self.observed,
            ),
            patch.object(
                producer_replay.trace_producer.observation,
                "verify_runtime_observation",
                return_value={"status": inventory_status},
            ),
        ):
            return producer_replay.verify_producer_inventory(
                self.root, "p" * 64, capture_request=self.request
            )

    def test_unknown_usage_preserves_attempted_calls_and_never_promotes(self):
        self.observed["blockers"] = ["token-usage-unknown:cancelled-call"]
        self.observed["token_usage_totals"] = None
        result = self.project()
        self.assertEqual(result["counts"]["inferences"], 6)
        self.assertTrue(result["call_accounting_complete"])
        self.assertFalse(result["token_usage_complete"])
        self.assertIsNone(result["token_usage_totals"])
        self.assertIsNone(result["cost"]["amount"])
        self.assertFalse(result["formal_ready"])

    def test_structural_gap_or_incomplete_attempt_blocks_call_accounting(self):
        for key, value in (
            ("blockers", ["spawn-child-missing:spawn-1"]),
            ("counts", {**self.observed["counts"], "incomplete_inferences": 1}),
        ):
            with self.subTest(key=key):
                original = self.observed[key]
                self.observed[key] = value
                result = self.project()
                self.assertFalse(result["call_accounting_complete"])
                self.assertFalse(result["token_usage_complete"])
                self.observed[key] = original

    def test_partial_metadata_stays_partial_even_with_complete_call_counts(self):
        result = self.project("partial")
        self.assertEqual(result["inventory_status"], "partial")
        self.assertTrue(result["call_accounting_complete"])
        self.assertFalse(result["formal_ready"])

    def test_bool_and_negative_counts_are_not_valid_attempt_counts(self):
        for invalid in (True, -1, None):
            with self.subTest(value=invalid):
                self.observed["counts"]["inferences"] = invalid
                with self.assertRaisesRegex(CaptureError, "nonnegative integers"):
                    self.project()

    def test_unfrozen_fields_and_foreign_policy_reject_before_archive_access(self):
        with patch.object(producer_replay.trace_producer, "_verify") as verify:
            for request in (
                {**self.request, "process_runner": object()},
                {
                    **self.request,
                    "policy_bindings": {
                        "kind": "Stage2NamedPermissionsPolicy",
                        "telemetry_path": str(self.root / "foreign"),
                    },
                },
            ):
                with self.assertRaises(CaptureError):
                    producer_replay.verify_producer_inventory(
                        self.root, "p" * 64, capture_request=request
                    )
            verify.assert_not_called()

    def test_real_synthetic_archive_cannot_enter_public_replay(self):
        case = fixtures.TraceProducerTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        produced = case._produce()
        with self.assertRaisesRegex(Stage2Error, "synthetic-mode-mismatch"):
            producer_replay.verify_producer_inventory(
                case.telemetry,
                produced["producer_receipt"],
                capture_request=case._args(),
            )
        self.assertEqual((case.calls, case.rpc_calls), (1, 1))


if __name__ == "__main__":
    unittest.main()
