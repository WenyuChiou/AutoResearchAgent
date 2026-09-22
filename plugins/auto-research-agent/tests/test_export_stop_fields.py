"""Do not label round presence as a passing frozen stop-evidence metric."""

from pathlib import Path
import tempfile
import unittest

import test_coverage_gate as gates
from stage1_export.bundle import export_run, validate_export
from stage1_ledger.journal import decode


class ExportStopFieldsTests(unittest.TestCase):
    def exercise(self, case):
        source = gates.CoverageGateTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        source.prepare_review(verified=case != "closest")
        source.finish_round(first=True)
        if case != "unsaturated":
            source.finish_round(failed=case == "failed")
            source.finish_round()
        source.ledger.checkpoint()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name) / "export"
        self.assertTrue(export_run(source.ledger.root, output)["valid"])
        self.assertTrue(validate_export(output)["valid"])
        inputs = decode((output / "metric_inputs.json").read_bytes(), "inputs")
        self.assertNotIn("stop_inputs_recorded", inputs["P3"])
        self.assertNotIn("S1_STOP_EVIDENCE", inputs["P3"])
        self.assertTrue(inputs["P3"]["coverage_rounds_recorded"])
        self.assertEqual(
            inputs["P3"]["operational_stop_checks_satisfied"], case == "complete"
        )
        self.assertEqual(inputs["judgment_scores"]["P3"]["status"], "not_scored")

    def test_incomplete_failed_round_is_not_stop_sufficient(self):
        self.exercise("failed")

    def test_missing_closest_verification_is_not_stop_sufficient(self):
        self.exercise("closest")

    def test_unsaturated_marginal_yield_is_not_stop_sufficient(self):
        self.exercise("unsaturated")

    def test_all_operational_checks_pass_without_awarding_frozen_score(self):
        self.exercise("complete")
