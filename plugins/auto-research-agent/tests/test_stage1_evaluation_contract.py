"""Validate frozen metric contracts with synthetic data only."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
sys.path.insert(0, str(PLUGIN_ROOT))
# ruff: noqa: E402 -- load repository validators without installing them.

from validators.stage1_evaluation_result import semantic_errors  # noqa: E402


def load(relative_path):
    return json.loads((EVAL_ROOT / relative_path).read_text(encoding="utf-8"))


class Stage1EvaluationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorecard = load("primary-scorecard.v1.json")
        cls.metric_spec = load("stage1/metric-spec.v1.json")
        cls.baseline = load("stage1/baseline-run01.summary.json")
        schema = load("schemas/stage1-evaluation-result.v1.schema.json")
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        cls.example = load("examples/stage1-evaluation-result.synthetic.json")

    def test_primary_scorecard_has_exact_stage_metric_partition(self):
        partition = {
            stage["stage"]: [metric["id"] for metric in stage["metrics"]]
            for stage in self.scorecard["stages"]
        }
        self.assertEqual(
            partition,
            {1: ["P1", "P2", "P3"], 2: ["P4", "P5", "P6"], 3: ["P7", "P8", "P9"]},
        )
        self.assertFalse(self.scorecard["scoring"]["composite_total"])

    def test_stage1_spec_is_frozen_and_keeps_answers_external(self):
        self.assertEqual(
            [metric["id"] for metric in self.metric_spec["primary_metrics"]],
            ["P1", "P2", "P3"],
        )
        isolation = self.metric_spec["evaluation_isolation"]
        self.assertFalse(isolation["runtime_readable"])
        self.assertFalse(isolation["answer_keys_committed"])
        self.assertFalse(isolation["production_queries_may_use_benchmark_titles"])
        self.assertEqual(isolation["ci_fixture_type"], "synthetic")
        anchors = self.metric_spec["benchmark_anchor_policy"]
        self.assertTrue(anchors["influenced_by_exploratory_baseline"])
        self.assertFalse(anchors["blind_holdout"])
        self.assertFalse(anchors["exhaustive_field_truth"])
        self.assertEqual(
            anchors["classic_or_most_important_claim_status"], "not-established"
        )
        self.assertEqual(len(anchors["future_curation_required_roles"]), 6)
        self.assertEqual(anchors["classic_definition"]["minimum_age_years"], 5)
        self.assertEqual(anchors["classic_definition"]["minimum_total"], 5)
        self.assertTrue(anchors["classic_definition"]["no_zero_dimension"])
        self.assertIn(
            "two raters",
            anchors["decision_critical_definition"]["must_have_rule"],
        )
        self.assertTrue(
            anchors["equally_direct_substitute_requires_human_adjudication"]
        )

    def test_exploratory_baseline_is_not_presented_as_formal_ab(self):
        self.assertFalse(self.baseline["formal_paired_ab_baseline"])
        self.assertIsNone(self.baseline["P1"]["adjudicated_score"])
        self.assertEqual(self.baseline["P2"]["adjudicated_score"], 1)
        self.assertEqual(self.baseline["P3"]["adjudicated_score"], 1)

    def test_synthetic_example_matches_schema_and_count_invariants(self):
        self.validator.validate(self.example)
        self.assertEqual(semantic_errors(self.example), [])
        facts = self.example["fact_metrics"]
        identity = facts["bibliographic_identity"]
        self.assertEqual(
            identity["correct"] + identity["incorrect"] + identity["unverifiable"],
            identity["total"],
        )
        claims = facts["claim_support"]
        self.assertEqual(
            claims["supported"]
            + claims["partial"]
            + claims["contradicted"]
            + claims["unverifiable"],
            claims["total"],
        )
        coverage = facts["coverage"]
        self.assertLessEqual(coverage["recent_works"], coverage["year_confirmed_works"])
        audit = facts["auditability"]
        for numerator, denominator in [
            ("works_with_trace", "works_total"),
            ("claims_with_locator", "claims_total"),
            ("decisions_with_reason", "decisions_total"),
            ("versions_with_access_date", "included_works_total"),
        ]:
            self.assertLessEqual(audit[numerator], audit[denominator])

    def test_metric_spec_required_counts_are_paths_in_result(self):
        for metric in self.metric_spec["primary_metrics"]:
            for path in metric["required_counts"]:
                value = self.example
                for part in path.split("."):
                    self.assertIn(part, value, path)
                    value = value[part]

    def test_semantic_validator_rejects_inconsistent_counts(self):
        invalid = deepcopy(self.example)
        invalid["fact_metrics"]["claim_support"]["total"] = 99
        invalid["fact_metrics"]["coverage"]["recent_works"] = 5
        invalid["fact_metrics"]["coverage"]["year_confirmed_works"] = 4
        invalid["fact_metrics"]["auditability"]["works_with_trace"] = 5
        invalid["fact_metrics"]["auditability"]["works_total"] = 4
        invalid["efficiency"]["failed_tool_calls"] = 9
        invalid["efficiency"]["tool_calls"] = 8
        errors = semantic_errors(invalid)
        self.assertEqual(
            errors,
            [
                "fact_metrics.claim_support parts must sum to total",
                "fact_metrics.coverage.recent_works must not exceed "
                "year_confirmed_works",
                "fact_metrics.auditability.works_with_trace must not exceed "
                "works_total",
                "efficiency.failed_tool_calls must not exceed tool_calls",
            ],
        )

    def test_semantic_validator_rejects_impossible_judgment_status(self):
        invalid = deepcopy(self.example)
        invalid["judgment_scores"]["P1"]["ADJ"] = None
        errors = semantic_errors(invalid)
        self.assertEqual(
            errors,
            ["judgment_scores.P1 adjudicated status requires R1, R2, and ADJ scores"],
        )

        pending = deepcopy(self.example)
        pending["judgment_scores"]["P2"]["status"] = "pending"
        errors = semantic_errors(pending)
        self.assertEqual(
            errors,
            ["judgment_scores.P2 pending status requires a null ADJ score"],
        )

    def test_private_evaluation_outputs_are_ignored(self):
        patterns = (EVAL_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            patterns,
            ["private/", "runs/", "raw/", "adjudication/", "*.pdf"],
        )


if __name__ == "__main__":
    unittest.main()
