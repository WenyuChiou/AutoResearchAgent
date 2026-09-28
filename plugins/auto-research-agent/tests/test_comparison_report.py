"""Different required denominators never produce a complete dimension delta."""

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_ab import general, runner  # noqa: E402
from stage1_ab.comparison import capture_costs, compare_results, export_report  # noqa: E402
from stage1_eval.score import aggregate  # noqa: E402
from test_stage1_ab_general_v3 import runs  # noqa: E402
from test_stage1_general_eval import judgment, packet  # noqa: E402


def result(*, unknown=(), inapplicable=(), better=False):
    selected = {phase: judgment(phase) for phase in ("content", "process")}
    for phase in selected.values():
        for row in phase["criteria"]:
            key = row["criterion_id"]
            if better and key.startswith(("P2", "P3")):
                row["score"] = 2
            if key in unknown:
                row.update(
                    status="unverifiable",
                    score=None,
                    missing_evidence=["source unavailable"],
                )
            elif key in inapplicable:
                row.update(status="not-applicable", score=None)
    return aggregate(
        packet("evidence-audited"),
        {"selected": selected, "adjudicated_phases": []},
        evaluator_identity={"evaluator_bundle_sha256": "a" * 64, "model": "test-model"},
    )


class ComparisonReportTests(unittest.TestCase):
    def test_unknown_scores_are_not_zero_and_only_complete_dimensions_compare(self):
        a, b = result(), result(unknown=["P2V3.SCOPE"], better=True)
        report = compare_results(a, b)
        p2 = report["dimensions"]["P2"]
        self.assertIsNone(p2["delta"])
        self.assertEqual(p2["B_assessed_fraction"], 0.75)
        self.assertEqual(report["dimensions"]["P1"]["delta"], 0)
        row = next(r for r in report["criteria"] if r["criterion_id"] == "P2V3.SCOPE")
        self.assertIsNone(row["B"])
        self.assertEqual(row["B_unknown_reason"], ["source unavailable"])
        self.assertEqual(row["A_evidence_ids"], ["answer"])
        self.assertEqual(row["ineligibility_reasons"], ["B-unverifiable"])

    def test_equal_counts_with_different_applicable_sets_cannot_compare(self):
        a = result(inapplicable=["P2V3.BOUNDARIES"])
        b = result(inapplicable=["P2V3.CORE_SELECTION"], better=True)
        report = compare_results(a, b)
        row = report["dimensions"]["P2"]
        self.assertEqual(row["A_assessed_fraction"], 1)
        self.assertEqual(row["B_assessed_fraction"], 1)
        self.assertFalse(row["delta_eligible"])
        self.assertEqual(
            row["ineligibility_reasons"], ["different-applicable-criterion-set"]
        )

    def test_same_applicability_is_required_even_without_unknowns(self):
        report = compare_results(result(), result(inapplicable=["P2V3.BOUNDARIES"]))
        self.assertIsNone(report["dimensions"]["P2"]["delta"])
        matching = compare_results(
            result(inapplicable=["P2V3.BOUNDARIES"]),
            result(inapplicable=["P2V3.BOUNDARIES"], better=True),
        )
        self.assertEqual(matching["dimensions"]["P2"]["delta"], 50)

    def test_changed_evaluator_or_spec_and_missing_inputs_are_machine_readable(self):
        for key in ("evaluator_identity", "spec_sha256"):
            b = result()
            b[key] = "changed"
            report = compare_results(result(), b)
            self.assertIn("different-" + key, report["binding_ineligibility_reasons"])
            self.assertTrue(all(r["delta"] is None for r in report["criteria"]))
        b = result()
        del b["evaluator_identity"]
        self.assertIn(
            "missing-evaluator_identity",
            compare_results(result(), b)["binding_ineligibility_reasons"],
        )

    def test_atomic_score_tampering_is_rejected_before_reporting(self):
        b = result()
        b["dimensions"]["P2"]["observed_score_100"] = 100
        with self.assertRaisesRegex(runner.ExecutionBlocked, "score changed"):
            compare_results(result(), b)

    def test_actual_paired_decision_exports_rows_and_blocks_incomparable_median(self):
        lock = {"paired_repeats": runs()}
        by_run = {}
        for pair in lock["paired_repeats"]:
            for arm in ("baseline", "treatment"):
                by_run[pair[arm]["run_id"]] = {
                    "result": result(better=arm == "treatment"),
                    "result_sha256": "b" * 64,
                    "capture": {},
                }
        by_run[lock["paired_repeats"][1]["treatment"]["run_id"]]["result"] = result(
            inapplicable=["P2V3.BOUNDARIES"], better=True
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "decision.json"
            value = general._paired_decision(lock, by_run, "c" * 64, output)
            self.assertEqual(value["decision"], "inconclusive")
            self.assertIsNone(value["summary"]["P2"]["median_delta"])
            self.assertEqual(value["summary"]["P3"]["range"], [50, 50])
            with output.with_suffix(".criteria.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 30)
            self.assertEqual(
                json.loads(output.with_suffix(".report.json").read_bytes()), value
            )

    def test_html_is_inert_and_changed_report_is_not_overwritten(self):
        comparison = compare_results(result(), result(unknown=["P2V3.SCOPE"]))
        comparison["criteria"][0]["A_unknown_reason"] = ["<script>alert(1)</script>"]
        value = {
            "pairs": [{"repeat": 1, **comparison}],
            "decision": "inconclusive",
            "summary": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "decision.json"
            export_report(value, output)
            page = output.with_suffix(".html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
            changed = copy.deepcopy(value)
            changed["decision"] = "improved"
            with self.assertRaisesRegex(ValueError, "different bytes"):
                export_report(changed, output)
            self.assertEqual(
                output.with_suffix(".html").read_text(encoding="utf-8"), page
            )

    def test_capture_wall_time_and_unknown_costs_remain_separate(self):
        value = capture_costs(
            {
                "attempts": [
                    {
                        "started_at": "2026-09-27T10:00:00+00:00",
                        "ended_at": "2026-09-27T10:00:02+00:00",
                        "summary": {"usage": {"input_tokens": 7}},
                    },
                    {},
                ]
            }
        )
        self.assertEqual(value["attempt_elapsed_seconds"], [2, None])
        self.assertIsNone(value["elapsed_seconds_in_attempts"])
        self.assertIsNone(value["human_interventions"])
        self.assertIsNone(value["currency_cost"])
        self.assertEqual(
            value["observed_usage_by_attempt"], [{"input_tokens": 7}, None]
        )


if __name__ == "__main__":
    unittest.main()
