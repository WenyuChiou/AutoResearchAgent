"""Validate the frozen aging bidirectional rubric and criterion catalog."""

import hashlib
import json
from pathlib import Path
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
RUBRIC_ROOT = EVAL_ROOT / "rubrics"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class AgingBidirectionalRubricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rubric_path = RUBRIC_ROOT / "aging-bidirectional-rubric.v1.json"
        cls.rubric = load_json(cls.rubric_path)
        cls.catalog_path = EVAL_ROOT / cls.rubric["criterion_catalog"]["path"]
        cls.catalog = load_jsonl(cls.catalog_path)

    def test_rubric_freezes_all_stage_metrics_without_a_composite(self):
        self.assertEqual(
            [(metric["stage"], metric["id"]) for metric in self.rubric["metrics"]],
            [
                (1, "P1"),
                (1, "P2"),
                (1, "P3"),
                (2, "P4"),
                (2, "P5"),
                (2, "P6"),
                (3, "P7"),
                (3, "P8"),
                (3, "P9"),
            ],
        )
        self.assertTrue(self.rubric["evaluation_model"]["no_composite_total"])
        self.assertEqual(self.rubric["status"], "frozen")

    def test_bidirectional_scope_and_research_modes_are_explicit(self):
        scope = self.rubric["case_scope"]
        self.assertIn("Demographic", scope["forward_coupling"])
        self.assertIn("update", scope["feedback_coupling"])
        self.assertIn("may not invent", scope["demographic_transition_guardrail"])
        self.assertEqual(
            scope["allowed_research_modes"],
            [
                "confirmatory",
                "exploratory",
                "method-development",
                "simulation-discovery",
            ],
        )

    def test_catalog_is_hash_bound_unique_and_complete(self):
        binding = self.rubric["criterion_catalog"]
        self.assertEqual(
            hashlib.sha256(
                self.catalog_path.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .encode("utf-8")
            ).hexdigest(),
            binding["sha256"],
        )
        self.assertEqual(len(self.catalog), binding["record_count"])
        record_ids = [record["id"] for record in self.catalog]
        self.assertEqual(len(record_ids), len(set(record_ids)))

        expected_criteria = {
            criterion_id
            for metric in self.rubric["metrics"]
            for criterion_id in metric["criterion_ids"]
        }
        expected_errors = {
            error_id
            for metric in self.rubric["metrics"]
            for error_id in metric["major_error_ids"]
        }
        self.assertEqual(
            {row["id"] for row in self.catalog if row["record_type"] == "criterion"},
            expected_criteria,
        )
        self.assertEqual(
            {row["id"] for row in self.catalog if row["record_type"] == "major_error"},
            expected_errors,
        )

    def test_every_criterion_has_evidence_and_specific_score_anchors(self):
        required = {
            "record_type",
            "id",
            "metric_id",
            "definition",
            "required_evidence",
            "score_0",
            "score_1",
            "score_2",
        }
        for row in self.catalog:
            if row["record_type"] != "criterion":
                continue
            self.assertEqual(set(row), required)
            self.assertTrue(row["id"].startswith(f"{row['metric_id']}."))
            for field in required - {"record_type", "id", "metric_id"}:
                self.assertGreaterEqual(len(row[field]), 20)

    def test_every_metric_declares_units_and_non_averaging_aggregation(self):
        for metric in self.rubric["metrics"]:
            self.assertGreater(len(metric["evaluation_units"]), 0)
            for unit in metric["evaluation_units"]:
                self.assertEqual(set(unit), {"unit_type", "cardinality"})
            self.assertGreater(len(metric["aggregation_rule"]), 20)
        p5 = next(metric for metric in self.rubric["metrics"] if metric["id"] == "P5")
        self.assertIn("never an unweighted average", p5["aggregation_rule"])

    def test_major_errors_have_stable_ids_and_require_audit(self):
        for row in self.catalog:
            if row["record_type"] != "major_error":
                continue
            self.assertTrue(row["id"].startswith(f"{row['metric_id']}.ME."))
            self.assertTrue(row["audit_required"])
            self.assertGreaterEqual(len(row["definition"]), 20)

    def test_new_case_does_not_overwrite_the_prior_benchmark(self):
        binding = self.rubric["benchmark_binding"]
        self.assertEqual(binding["status"], "pending-v2-curation")
        self.assertIn("prior four-cluster", binding["note"])
        self.assertFalse(binding["production_runtime_may_read_answer_key"])
        self.assertEqual(len(self.rubric["coverage_clusters"]), 6)

    def test_version_specific_guide_keeps_v1_and_v2_distinct(self):
        guide = (RUBRIC_ROOT / "AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("舊的 Stage 1 v1", guide)
        self.assertIn("六個固定 clusters", guide)
        self.assertIn("四層 validation", guide)
        self.assertIn("不能拿這份", guide)


if __name__ == "__main__":
    unittest.main()
