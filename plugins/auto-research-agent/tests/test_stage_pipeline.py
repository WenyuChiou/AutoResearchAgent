# ruff: noqa: E402 -- use the repository CLI.
import sys
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))
sys.path.insert(0, str(HERE))
from stage_pipeline_fixture_helpers import StagePipelineFixture
from research_workspace_native.stage_pipeline import StagePipeline
from stage2_common import canonical_hash


class StagePipelineTests(StagePipelineFixture):
    def test_eight_budget_keeps_ninth_guard_and_publishes_pending(self):
        for _ in range(8):
            self.assertLessEqual(
                len(self.pipeline.next_task()["prompt"].encode()), 16384
            )
            self.step()
        self.assertIsNone(self.pipeline.next_task())
        self.assertEqual(self.pipeline.view()["phase"], "reconciliation-extraction")
        self.assertEqual(self.pipeline.view()["status"], "budget-pending")
        delivery = self.root / "pending-delivery"
        manifest = self.pipeline.publish(delivery)
        self.assertFalse(manifest["stage3_execution_authorized"])
        self.assertFalse(manifest["local_reconciliation_ready"])
        self.assertTrue((delivery / "selection.json").is_file())
        self.assertIn("pending", self.pipeline.view()["daily_v3_status"])

    def test_nine_injected_steps_and_reopen_never_execute(self):
        self.pipeline = StagePipeline(
            self.path,
            self.sources,
            self.root / "nine",
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
            max_calls=9,
        )
        for _ in range(9):
            self.step()
        before = len(list((self.root / "nine").rglob("*")))
        reopened = StagePipeline(
            self.path,
            self.sources,
            self.root / "nine",
            expected_packet_sha256=canonical_hash(self.packet),
            source_sha256="a" * 64,
            verify_receipt=self.verify,
            max_calls=9,
        )
        self.assertEqual(reopened.view()["status"], "incomplete-assessment")
        self.assertIsNone(reopened.next_task())
        self.assertEqual(before, len(list((self.root / "nine").rglob("*"))))


if __name__ == "__main__":
    unittest.main()
