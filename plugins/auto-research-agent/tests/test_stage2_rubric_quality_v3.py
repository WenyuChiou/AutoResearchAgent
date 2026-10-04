"""Deterministic coverage for the fixed-denominator Stage 2 quality evaluator."""

import copy
import json
import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_eval.rubric_quality_v3 import (  # noqa: E402
    evaluate_quality_v3,
    validate_quality_batch,
    validate_quality_inputs,
)


RUBRIC_PATH = PLUGIN / "evals" / "rubrics" / "stage2-general.v3.json"
VARIANTS = ("order", "length", "prestige", "preference")


def synthetic_fixture():
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    cases, judgments = [], []
    anchors = (0, 1, 2, None)
    for criterion in rubric["criteria"]:
        criterion_id = criterion["id"]
        for anchor_index, score in enumerate(anchors):
            case_id = f"{criterion_id}:anchor-{anchor_index}"
            facts = [
                {
                    "evidence_id": f"ev-{criterion_id}-{anchor_index}",
                    "text": "synthetic fact",
                }
            ]
            cases.append(
                {
                    "case_id": case_id,
                    "criterion_id": criterion_id,
                    "variant": "anchor",
                    "base_case_id": None,
                    "facts": facts,
                    "semantic_sha256": canonical_hash(facts),
                }
            )
            judgments.append(
                {
                    "case_id": case_id,
                    "status": "unknown" if score is None else "scored",
                    "score": score,
                    "major_error": None if score is None else False,
                    "critical": score == 0,
                }
            )
            if anchor_index == 0:
                for variant in VARIANTS:
                    variant_id = f"{case_id}:{variant}"
                    cases.append(
                        {
                            "case_id": variant_id,
                            "criterion_id": criterion_id,
                            "variant": variant,
                            "base_case_id": case_id,
                            "facts": copy.deepcopy(facts),
                            "semantic_sha256": canonical_hash(facts),
                        }
                    )
                    judgments.append(
                        {
                            "case_id": variant_id,
                            "status": "scored",
                            "score": 0,
                            "major_error": False,
                            "critical": True,
                        }
                    )
    return (
        {"kind": "Stage2RubricQualityDataset", "cases": cases},
        {"kind": "Stage2RubricQualityReference", "judgments": judgments},
        rubric,
    )


def batch(dataset, reference, role="R1"):
    return {
        "kind": "Stage2RubricQualityBatchV3",
        "role": role,
        "judgments": [
            {
                "case_id": row["case_id"],
                "status": ref["status"],
                "score": ref["score"],
                "major_error": ref["major_error"],
                "reason": "synthetic evidence",
                "evidence_ids": []
                if ref["score"] is None
                else [row["facts"][0]["evidence_id"]],
            }
            for row, ref in zip(dataset["cases"], reference["judgments"])
        ],
    }


class RubricQualityV3Tests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.reference, self.rubric = synthetic_fixture()
        self.r1 = batch(self.dataset, self.reference)
        self.r2 = batch(self.dataset, self.reference, "R2")

    def report(self, r1=None, r2=None):
        return evaluate_quality_v3(
            self.dataset, self.reference, self.rubric, r1 or self.r1, r2 or self.r2
        )

    def test_fixture_has_exact_denominator_and_anchor_variant_coverage(self):
        self.assertEqual(len(self.dataset["cases"]), 72)
        self.assertEqual(len(self.reference["judgments"]), 72)
        by_id, refs = validate_quality_inputs(self.dataset, self.reference, self.rubric)
        self.assertEqual(len(by_id), 72)
        self.assertEqual(sum(row["variant"] == "anchor" for row in by_id.values()), 36)
        self.assertEqual(sum(row["variant"] != "anchor" for row in by_id.values()), 36)
        for criterion in self.rubric["criteria"]:
            anchors = [
                r
                for r in by_id.values()
                if r["criterion_id"] == criterion["id"] and r["variant"] == "anchor"
            ]
            self.assertEqual(
                {refs[r["case_id"]]["score"] for r in anchors}, {0, 1, 2, None}
            )

    def test_all_perfect_batches_pass_with_fixed_144_denominator(self):
        report = self.report()
        self.assertTrue(report["passed"])
        self.assertEqual(report["designated_judgments"], 144)
        self.assertEqual(
            report["range"], {"matched": 144, "required": 144, "percent": 100.0}
        )
        self.assertTrue(
            all(row["matched"] == 16 for row in report["per_criterion"].values())
        )

    def test_one_criterion_14_of_16_fails_per_criterion_even_above_global_threshold(
        self,
    ):
        r2 = copy.deepcopy(self.r2)
        for row in r2["judgments"][:2]:
            row["score"] = 1
        report = self.report(r2=r2)
        self.assertEqual(report["range"]["matched"], 142)
        self.assertGreaterEqual(report["range"]["percent"], 90)
        self.assertEqual(
            report["per_criterion"][self.rubric["criteria"][0]["id"]]["matched"], 14
        )
        self.assertFalse(report["passed"])

    def test_missing_case_and_evaluator_failure_do_not_shrink_denominator(self):
        missing = copy.deepcopy(self.r1)
        missing["judgments"].pop()
        with self.assertRaisesRegex(Stage2Error, "missing-or-duplicate"):
            validate_quality_batch(missing, "R1", self.dataset["cases"])
        failed = copy.deepcopy(self.r2)
        failed["judgments"][0].update(
            status="evaluator_failure", score=None, major_error=None, evidence_ids=[]
        )
        report = self.report(r2=failed)
        self.assertEqual(report["range"]["required"], 144)
        self.assertEqual(len(report["evaluator_failures"]), 1)
        self.assertFalse(report["passed"])

    def test_unknown_null_cannot_be_zero(self):
        invalid = copy.deepcopy(self.r1)
        invalid["judgments"][7]["score"] = 0
        with self.assertRaisesRegex(Stage2Error, "unknown-cannot-be-zero"):
            validate_quality_batch(invalid, "R1", self.dataset["cases"])

    def test_variant_fact_tamper_is_rejected(self):
        tampered = copy.deepcopy(self.dataset)
        tampered["cases"][4]["facts"][0]["text"] = "tampered"
        with self.assertRaisesRegex(Stage2Error, "variant-facts-changed"):
            validate_quality_inputs(tampered, self.reference, self.rubric)

    def test_disagreement_and_critical_error_fail(self):
        disagreement = copy.deepcopy(self.r2)
        disagreement["judgments"][1]["score"] = 2
        report = self.report(r2=disagreement)
        self.assertEqual(
            report["unresolved_disagreements"], [self.dataset["cases"][1]["case_id"]]
        )
        self.assertFalse(report["passed"])
        critical = copy.deepcopy(self.r2)
        critical["judgments"][0]["score"] = 1
        report = self.report(r2=critical)
        self.assertTrue(report["critical_errors"])
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
