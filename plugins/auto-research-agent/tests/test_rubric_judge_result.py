"""Validate structured and semantic rubric-judge results."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))

from validators.rubric_judge_result import validate_result  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class RubricJudgeResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rubric = load("rubrics/aging-bidirectional-rubric.v1.json")
        cls.criteria = {
            metric["id"]: metric["criterion_ids"] for metric in cls.rubric["metrics"]
        }
        cls.major_errors = {
            metric["id"]: metric["major_error_ids"] for metric in cls.rubric["metrics"]
        }
        cls.schema = load("schemas/rubric-judge-result.v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.schema_validator = Draft202012Validator(
            cls.schema, format_checker=FormatChecker()
        )
        cls.example = load("examples/rubric-judge-result.synthetic.json")

    def metric_result(self, metric_id, unit_type, unit_id):
        return {
            "metric_id": metric_id,
            "unit_type": unit_type,
            "unit_id": unit_id,
            "score": 2,
            "hard_fact_status": "pass",
            "hard_measures": {"synthetic_check": "pass"},
            "criterion_results": [
                {
                    "criterion_id": criterion_id,
                    "outcome": "pass",
                    "evidence_ids": [f"evidence-{criterion_id.lower()}"],
                    "reason": "Synthetic evidence satisfies this criterion.",
                }
                for criterion_id in self.criteria[metric_id]
            ],
            "missing_evidence": [],
            "major_error_ids": [],
            "reason": "All applicable frozen criteria pass.",
            "confidence": "high",
            "needs_human_review": False,
        }

    def result(self, stage):
        units = {
            1: [
                ("P1", "included_work", "work-1"),
                ("P1", "central_claim", "claim-1"),
                ("P1", "stage_summary", "stage-1-summary"),
                ("P2", "literature_set", "literature-set-1"),
                ("P3", "stage1_run", "stage1-run-1"),
            ],
            2: [
                ("P4", "comparison", "comparison-1"),
                ("P5", "research_direction", "direction-1"),
                ("P5", "research_direction", "direction-2"),
                ("P6", "research_direction", "direction-1"),
                ("P6", "research_direction", "direction-2"),
                ("P6", "final_recommendation", "recommendation-1"),
            ],
            3: [
                ("P7", "proposed_study", "study-1"),
                ("P8", "validation_plan", "validation-1"),
                ("P9", "execution_plan", "plan-1"),
            ],
        }
        metric_results = [self.metric_result(*unit) for unit in units[stage]]
        expected_units = {}
        for metric_id, unit_type, unit_id in units[stage]:
            expected_units.setdefault(metric_id, {}).setdefault(unit_type, []).append(
                unit_id
            )
        return {
            "kind": "RubricJudgeResult",
            "schema_version": "1.0.0",
            "evaluation_id": f"eval-stage-{stage}",
            "run_id": "run-synthetic",
            "case_id": "aging-bidirectional-development-v1",
            "rubric_version": "aging-bidirectional-rubric-v1",
            "catalog_sha256": self.rubric["criterion_catalog"]["sha256"],
            "stage": stage,
            "expected_units": expected_units,
            "subject_artifact": {
                "path": f"evals/runs/synthetic/stage{stage}.json",
                "sha256": "a" * 64,
            },
            "judge": {
                "role": "auto-r1",
                "model": "synthetic-judge",
                "config_id": "judge-config-v1",
                "condition_blinded": True,
            },
            "study_mode": "exploratory",
            "metric_results": metric_results,
            "audit_trigger_ids": [],
            "requires_human_audit": False,
            "created_at": "2026-09-17T18:00:00-04:00",
        }

    def test_synthetic_fixture_and_all_three_stage_shapes_are_valid(self):
        self.schema_validator.validate(self.example)
        self.assertEqual(validate_result(self.example), [])
        for stage in (1, 2, 3):
            self.assertEqual(validate_result(self.result(stage)), [])

    def test_schema_rejects_numeric_metric_and_empty_hard_measures(self):
        invalid = deepcopy(self.example)
        invalid["metric_results"][0]["metric_id"] = 7
        invalid["metric_results"][0]["hard_measures"] = {}
        errors = validate_result(invalid)
        self.assertTrue(any("is not of type 'string'" in error for error in errors))
        self.assertTrue(any("should be non-empty" in error for error in errors))

    def test_metric_units_criteria_and_duplicates_fail_closed(self):
        invalid = self.result(3)
        invalid["metric_results"][0]["criterion_results"][0]["criterion_id"] = "P9.MVP"
        invalid["metric_results"].append(deepcopy(invalid["metric_results"][0]))
        errors = validate_result(invalid)
        self.assertTrue(
            any("duplicate metric_id/unit_type/unit_id" in e for e in errors)
        )
        self.assertTrue(any("criterion IDs must exactly match" in e for e in errors))

    def test_hard_facts_major_errors_and_missing_evidence_override_score(self):
        invalid = self.result(3)
        row = invalid["metric_results"][0]
        row["major_error_ids"] = [self.major_errors["P7"][0]]
        row["hard_fact_status"] = "unverifiable"
        row["missing_evidence"] = ["central-transition-source"]
        row["confidence"] = "low"
        errors = validate_result(invalid)
        self.assertTrue(any("must request human review" in e for e in errors))
        self.assertTrue(any("major errors force score 0" in e for e in errors))
        self.assertTrue(
            any("unverifiable evidence caps score at 1" in e for e in errors)
        )

    def test_p1_summary_cannot_hide_a_partial_central_item(self):
        invalid = self.result(1)
        claim = next(
            row
            for row in invalid["metric_results"]
            if row["unit_type"] == "central_claim"
        )
        claim["score"] = 1
        claim["criterion_results"][0]["outcome"] = "partial"
        errors = validate_result(invalid)
        self.assertIn(
            "P1 stage_summary cannot exceed its lowest central item score", errors
        )

    def test_stage2_direction_units_must_match(self):
        invalid = self.result(2)
        p6_direction = next(
            row
            for row in invalid["metric_results"]
            if row["metric_id"] == "P6" and row["unit_type"] == "research_direction"
        )
        p6_direction["unit_id"] = "direction-2"
        self.assertIn(
            "P5 and P6 must evaluate the same research_direction unit_ids",
            validate_result(invalid),
        )

    def test_auto_judges_are_blinded_and_adjudicators_name_inputs(self):
        unblinded = self.result(3)
        unblinded["judge"]["condition_blinded"] = False
        self.assertTrue(
            any("must be condition-blinded" in e for e in validate_result(unblinded))
        )

        adjudication = self.result(3)
        adjudication["judge"]["role"] = "auto-adj"
        self.assertTrue(any("at least two" in e for e in validate_result(adjudication)))
        adjudication["adjudicates_evaluation_ids"] = ["eval-r1", "eval-r2"]
        adjudication["audit_trigger_ids"] = ["judge-disagreement"]
        adjudication["requires_human_audit"] = True
        self.assertEqual(validate_result(adjudication), [])

    def test_scores_cannot_hide_failures_or_all_not_applicable(self):
        failed = self.result(3)
        failed["metric_results"][0]["score"] = 1
        failed["metric_results"][0]["criterion_results"][0]["outcome"] = "fail"
        failed["metric_results"][0]["criterion_results"][1]["outcome"] = "partial"
        self.assertTrue(
            any(
                "failed criterion forces score 0" in error
                for error in validate_result(failed)
            )
        )

        inapplicable = self.result(3)
        for item in inapplicable["metric_results"][0]["criterion_results"]:
            item["outcome"] = "not-applicable"
            item["evidence_ids"] = []
        self.assertTrue(
            any(
                "at least one applicable" in error
                for error in validate_result(inapplicable)
            )
        )

    def test_expected_unit_manifest_and_p6_aggregation_fail_closed(self):
        omitted = self.result(1)
        omitted["metric_results"] = [
            row for row in omitted["metric_results"] if row["unit_id"] != "claim-1"
        ]
        self.assertTrue(
            any(
                "exactly match expected unit IDs" in error
                for error in validate_result(omitted)
            )
        )

        weak_direction = self.result(2)
        direction = next(
            row
            for row in weak_direction["metric_results"]
            if row["metric_id"] == "P6" and row["unit_id"] == "direction-2"
        )
        direction["score"] = 1
        direction["criterion_results"][0]["outcome"] = "partial"
        self.assertIn(
            "P6 final recommendation cannot exceed the lowest direction score",
            validate_result(weak_direction),
        )

        too_few = self.result(2)
        too_few["metric_results"] = [
            row for row in too_few["metric_results"] if row["unit_id"] != "direction-2"
        ]
        del too_few["expected_units"]["P5"]["research_direction"][1]
        del too_few["expected_units"]["P6"]["research_direction"][1]
        self.assertIn(
            "Stage 2 requires at least two research directions",
            validate_result(too_few),
        )

    def test_human_review_and_trigger_list_stay_consistent(self):
        invalid = self.result(3)
        invalid["audit_trigger_ids"] = ["unexpected-trigger"]
        invalid["requires_human_audit"] = True
        self.assertTrue(
            any(
                "unknown audit trigger IDs" in error
                for error in validate_result(invalid)
            )
        )

        required = self.result(3)
        required["metric_results"][0]["confidence"] = "low"
        required["metric_results"][0]["needs_human_review"] = True
        required["requires_human_audit"] = True
        errors = validate_result(required)
        self.assertIn(
            "audit_trigger_ids must identify why human review is required", errors
        )
        self.assertIn("low-confidence trigger is required", errors)

        required["audit_trigger_ids"] = ["low-confidence"]
        self.assertEqual(validate_result(required), [])


if __name__ == "__main__":
    unittest.main()
