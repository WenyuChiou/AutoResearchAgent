"""Historical evidence remains readable without enabling a changed-workspace resume."""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import trace_producer, producer_replay, execution_inventory  # noqa: E402
import test_stage2_trace_producer as fixtures  # noqa: E402


class ProducerHistoryTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.TraceProducerTests(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.produced = self.case._produce()
        self.receipt = self.produced["producer_receipt"]
        (self.case.workspace / "next-action.txt").write_bytes(b"later work")

    def historical(self, **updates):
        return trace_producer._verify(
            self.case._args(**updates),
            self.case.telemetry,
            self.receipt,
            allow_synthetic=True,
            workspace_mode="archived",
        )

    def test_history_verifies_after_workspace_advance_but_resume_rejects(self):
        before = (self.case.calls, self.case.rpc_calls)
        result = self.historical()
        self.assertEqual(
            result["native_capture_receipt"], self.produced["native_capture_receipt"]
        )
        with self.assertRaisesRegex(Stage2Error, "workspace-changed"):
            self.case._produce(resume=True, producer_receipt=self.receipt)
        self.assertEqual((self.case.calls, self.case.rpc_calls), before)

    def test_history_cannot_accept_changed_input_or_prompt(self):
        with self.assertRaisesRegex(Stage2Error, "binding-changed"):
            self.historical(prompt="changed task")
        self.case.brief.write_bytes(b"changed input")
        with self.assertRaisesRegex(Stage2Error, "binding-changed"):
            self.historical()
        self.assertEqual(self.case.calls, 1)

    def test_history_cannot_accept_changed_runtime_or_producer(self):
        with patch.object(trace_producer, "_source_sha", return_value="0" * 64):
            with self.assertRaisesRegex(Stage2Error, "producer-source-changed"):
                self.historical()
        self.case.codex.write_bytes(b"changed runtime")
        with self.assertRaises(Stage2Error):
            self.historical()
        self.assertEqual(self.case.calls, 1)

    def test_history_cannot_accept_tampered_trace_or_archive(self):
        trace = self.case.telemetry / self.produced["trace"]["root"] / "trace.jsonl"
        trace.write_bytes(trace.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(Stage2Error, "trace-binding-changed"):
            self.historical()
        self.assertEqual(self.case.calls, 1)

    def test_unknown_workspace_mode_is_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "verification-mode-invalid"):
            trace_producer._verify(
                self.case._args(),
                self.case.telemetry,
                self.receipt,
                allow_synthetic=True,
                workspace_mode="resume-anywhere",
            )

    def test_public_history_interfaces_reject_synthetic_archives(self):
        for verify in (
            producer_replay.verify_historical_producer_inventory,
            execution_inventory.inspect_historical_execution_inventory,
        ):
            with self.subTest(interface=verify.__name__):
                with self.assertRaisesRegex(Stage2Error, "synthetic-mode-mismatch"):
                    verify(
                        self.case.telemetry,
                        self.receipt,
                        capture_request=self.case._args(),
                    )
        self.assertEqual(self.case.calls, 1)


if __name__ == "__main__":
    unittest.main()
