"""Coverage obligations are discharged only by complete saved query receipts."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from test_stage1_coverage import proposal
from test_stage1_ledger import SYNTHETIC, rewrite_for_tamper_test
from stage1_coverage.plan import compile_plan
from stage1_coverage.run import CoverageLedger
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.validation import validate_run


class CoverageRoundTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.bundle = root / "plan"
        value = proposal()
        # One synthetic cluster keeps the multi-round integration test compact.
        value["clusters"] = value["clusters"][:1]
        compile_plan(value, self.bundle, as_of="2026-09-20", actor="synthetic")
        self.ledger = CoverageLedger.create(
            root / "run", run_id="synthetic", objective=value["topic"]
        )
        self.ledger.bind_plan(self.bundle, backends=["synthetic"], limit=10)

    def observe(self, planned_id, *, failure=False, truncated=False, rows=None):
        query = self.ledger.start_planned(planned_id)
        attempt = self.ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        raw = self.ledger.save_bytes(canonical(rows or []), producer=attempt)
        stderr = self.ledger.save_bytes(b"", producer=attempt)
        self.ledger.finish(
            attempt,
            outcome="rate_limited"
            if failure
            else ("success_nonempty" if rows else "success_empty"),
            http_status=429 if failure else 200,
            exit_code=1 if failure else 0,
            stdout=raw,
            stderr=stderr,
            records=None if failure else raw,
        )
        completed = self.ledger.complete_query(query)
        self.ledger.extract()
        self.ledger.receipt(completed, truncated=truncated, note="Synthetic receipt")
        return completed

    def test_round_replays_exact_plan_and_preserves_429(self):
        self.ledger.open_round()
        ids = list(self.ledger.coverage_state().queries)
        self.observe(ids[0], rows=[SYNTHETIC])
        self.observe(ids[1], failure=True)
        self.observe(ids[2])
        summary = self.ledger.close_round()["summary"]
        self.assertFalse(summary["complete"])
        self.assertEqual(len(summary["failed_query_ids"]), 1)
        self.assertEqual(len(summary["new_discovered_work_ids"]), 1)
        self.assertEqual(summary["missing_planned_ids"], [])
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["counts"]["backend_failures"], 1)
        self.assertNotEqual(
            self.ledger.checkpoint()["stage_result"]["next_allowed_action"],
            "stop-sufficient",
        )

    def test_missing_truncated_and_unknown_receipts_are_not_complete(self):
        self.ledger.open_round()
        ids = list(self.ledger.coverage_state().queries)
        self.observe(ids[0], truncated=True)
        self.observe(ids[1], truncated=None)
        summary = self.ledger.close_round()["summary"]
        self.assertEqual(summary["missing_planned_ids"], [ids[2]])
        self.assertEqual(len(summary["truncated_query_ids"]), 2)
        self.assertFalse(summary["complete"])

    def test_complete_rounds_and_budget_do_not_claim_scientific_sufficiency(self):
        for number in range(1, 4):
            self.assertEqual(self.ledger.open_round()["round_number"], number)
            for planned in self.ledger.coverage_state().queries:
                self.observe(planned)
            self.assertTrue(self.ledger.close_round()["summary"]["complete"])
        with self.assertRaisesRegex(LedgerError, "round-budget-exhausted"):
            self.ledger.open_round()
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        self.assertNotEqual(
            self.ledger.checkpoint()["stage_result"]["next_allowed_action"],
            "stop-sufficient",
        )

    def test_unbound_search_wrong_topic_and_rebinding_fail_before_write(self):
        self.ledger.open_round()
        before = self.ledger.state_hash()
        with self.assertRaisesRegex(LedgerError, "coverage-query-binding"):
            self.ledger.start("search", {"query": "unplanned shortcut"})
        self.assertEqual(self.ledger.state_hash(), before)
        with self.assertRaisesRegex(LedgerError, "plan-already-bound"):
            self.ledger.bind_plan(self.bundle, backends=["synthetic"], limit=10)
        other = CoverageLedger.create(
            Path(self.directory.name) / "other", run_id="other", objective="Wrong topic"
        )
        with self.assertRaisesRegex(LedgerError, "plan-topic-mismatch"):
            other.bind_plan(self.bundle, backends=["synthetic"], limit=10)
        self.assertEqual(other.events(), [])

    def test_pending_query_cannot_close_and_recovery_does_not_retry(self):
        self.ledger.open_round()
        query = self.ledger.start_planned(
            next(iter(self.ledger.coverage_state().queries))
        )
        with self.assertRaisesRegex(LedgerError, "round-has-pending-actions"):
            self.ledger.close_round()
        self.assertEqual(self.ledger.recover()["pending_actions"], [query])

    def test_receipt_correction_is_append_only_and_cap_stays_incomplete(self):
        self.ledger.open_round()
        ids = list(self.ledger.coverage_state().queries)
        completed = self.observe(ids[0], truncated=None, rows=[SYNTHETIC] * 10)
        prior = self.ledger.coverage_state().receipts[completed]
        corrected = self.ledger.receipt(
            completed, truncated=False, note="Synthetic correction"
        )
        self.assertEqual(corrected["replaces_event_id"], prior["event_id"])
        for planned in ids[1:]:
            self.observe(planned)
        summary = self.ledger.close_round()["summary"]
        self.assertEqual(summary["truncated_query_ids"], [completed])
        self.assertFalse(summary["complete"])
        self.assertEqual(
            len(
                [
                    r
                    for r in self.ledger.events()
                    if r["payload"]["kind"] == "CoverageReceipt"
                ]
            ),
            4,
        )
        with self.assertRaisesRegex(LedgerError, "receipt-requires-current-query"):
            self.ledger.receipt(completed, truncated=False, note="Too late")

    def test_cli_round_uses_existing_ledger_and_reports_incomplete_plan(self):
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "cli/stage1_coverage"),
        ]
        for action in ["open-round", "close-round"]:
            result = subprocess.run(
                command + [action, "--run", str(self.ledger.root)], capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout)["summary"]
        self.assertFalse(summary["complete"])
        self.assertEqual(len(summary["missing_planned_ids"]), 3)

    def test_rehashed_round_summary_and_missing_plan_file_fail_validation(self):
        self.ledger.open_round()
        self.ledger.close_round()
        plan_ref = self.ledger.coverage_state().plan_ref
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"]["summary"].update(complete=True),
        )
        self.assertIn(
            "coverage-round-replay", " ".join(validate_run(self.ledger.root)["errors"])
        )
        (self.ledger.root / plan_ref["path"]).unlink()
        self.assertIn(
            plan_ref["path"], " ".join(validate_run(self.ledger.root)["errors"])
        )


if __name__ == "__main__":
    unittest.main()
