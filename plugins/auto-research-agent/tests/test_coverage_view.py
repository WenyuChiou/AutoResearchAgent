"""The human stop report must expose saved evidence without new research logic."""

from pathlib import Path
import tempfile
import unittest

import test_coverage_gate as gates
from test_stage1_ledger import fixture
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.readiness import coverage_text
from stage1_ledger.validation import validate_run


class CoverageViewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def coverage(self):
        case = gates.CoverageGateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.prepare_review()
        case.finish_round(first=True)
        return case

    def test_failure_and_unplanned_coverage_are_visible_in_the_required_markdown(self):
        ledger, refs, _, _ = fixture(self.root / "run")
        checkpoint = ledger.checkpoint()
        text = (ledger.root / "coverage_and_stop.md").read_text(encoding="utf-8")
        self.assertIn("## Backend failure history", text)
        self.assertIn("rate\\_limited", text)
        self.assertIn("429", text)
        self.assertIn(refs[-1]["path"], text)
        self.assertIn("Coverage plan: unavailable", text)
        self.assertIn("| Unreviewed works | unavailable | unavailable |", text)
        self.assertIn("## Unresolved items", text)
        self.assertIn("Decision: human-review", text)
        self.assertIn(checkpoint["state_sha256"], text)
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_report_reuses_cluster_reviews_and_round_yield_at_its_checkpoint(self):
        case = self.coverage()
        case.ledger.checkpoint()
        path = case.ledger.root / "coverage_and_stop.md"
        before = path.read_text(encoding="utf-8")
        self.assertIn("## Coverage clusters", before)
        self.assertIn("| cluster-1 | 1 | 1 |", before)
        self.assertIn("Recent sweep complete: true", before)
        self.assertIn("Synthetic household record", before)
        self.assertIn(case.version, before)
        self.assertIn("| 1 | true | 1 | 1 |", before)
        self.assertIn("Metadata identity: unverified", before)
        case.ledger.decide(
            case.work,
            "exclude",
            reason="scope-reassessment",
            rationale="Synthetic reversal",
            evidence_refs=[case.source],
        )
        self.assertTrue(validate_run(case.ledger.root)["valid"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        case.ledger.checkpoint()
        after = path.read_text(encoding="utf-8")
        self.assertNotIn("Synthetic household record", after)
        self.assertIn("| cluster-1 | 0 | 1 |", after)
        self.assertIn("cluster-incomplete:cluster-1", after)
        self.assertTrue(validate_run(case.ledger.root)["valid"])

    def test_tampered_view_fails_and_recovery_only_rebuilds_the_derived_text(self):
        case = self.coverage()
        case.ledger.checkpoint()
        path = case.ledger.root / "coverage_and_stop.md"
        original = path.read_bytes()
        journal = (case.ledger.root / "stage_events.jsonl").read_bytes()
        path.write_text("Invented sufficient coverage", encoding="utf-8")
        self.assertFalse(validate_run(case.ledger.root)["valid"])
        result = case.ledger.recover()
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(
            (case.ledger.root / "stage_events.jsonl").read_bytes(), journal
        )
        self.assertTrue(validate_run(case.ledger.root)["valid"])

    def test_legacy_view_and_unknown_new_contract_are_distinguished(self):
        ledger, _, _, _ = fixture(self.root / "legacy")
        manifest = ledger.manifest
        manifest.pop("coverage_view_contract", None)
        (ledger.root / "run_manifest.json").write_bytes(canonical(manifest))
        checkpoint = ledger.checkpoint()
        self.assertEqual(
            (ledger.root / "coverage_and_stop.md").read_text(encoding="utf-8"),
            coverage_text(checkpoint),
        )
        self.assertTrue(validate_run(ledger.root)["valid"])
        manifest["coverage_view_contract"] = "unknown"
        (ledger.root / "run_manifest.json").write_bytes(canonical(manifest))
        with self.assertRaisesRegex(LedgerError, "coverage_view_contract"):
            ledger.recover()

    def test_untrusted_cells_and_large_tables_cannot_expand_the_summary(self):
        from stage1_ledger.coverage_view import table

        rows = [["source | <script>\n## fake", "a" * 1000] for _ in range(31)]
        text = table(["Source", "Reason"], rows)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("\n## fake", text)
        self.assertIn("Showing 20 of 31", text)
        self.assertNotIn("a" * 300, text)


if __name__ == "__main__":
    unittest.main()
