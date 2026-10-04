# ruff: noqa: E402 -- load repository CLI and sibling fixtures without installation.
"""Mechanics-only tests for the supplemental source-context QA gate."""

import copy
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(Path(__file__).resolve().parent)]

from stage2_common import Stage2Error
from stage2_eval.rubric_quality_v3 import evaluate_quality_v3
from stage2_eval.source_context_quality import (
    combine_quality_acceptance,
    evaluate_context_quality,
    prepare_context_quality_input,
    validate_context_quality_inputs,
)
from test_stage2_rubric_quality_v3 import batch as core_batch
from test_stage2_rubric_quality_v3 import synthetic_fixture as core_fixture


FAMILIES = {
    "attribution": "P4V3.FIDELITY",
    "existence": "P4V3.FIDELITY",
    "policy-exception": "P6V3.FEASIBILITY",
}


def synthetic_context_fixture():
    """Build contract mechanics; this is not evidence of real judge quality."""

    cases = []
    references = []
    for family, criterion_id in FAMILIES.items():
        for polarity in ("positive", "negative"):
            for index in range(2):
                case_id = f"{family}:{polarity}:{index}"
                evidence_id = f"fact:{case_id}"
                cases.append(
                    {
                        "case_id": case_id,
                        "family": family,
                        "polarity": polarity,
                        "criterion_id": criterion_id,
                        "facts": [
                            {
                                "evidence_id": evidence_id,
                                "text": "Synthetic source-context fact.",
                            }
                        ],
                        "subject_record": {
                            "text": "Synthetic subject record for schema mechanics."
                        },
                    }
                )
                references.append(
                    {
                        "case_id": case_id,
                        "status": "scored",
                        "score": 2 if polarity == "positive" else 0,
                        "major_error": polarity == "negative",
                        "reason": "Synthetic reference kept outside subject content.",
                        "critical": polarity == "negative" and index == 0,
                    }
                )
    return (
        {
            "kind": "Stage2SourceContextQualityDataset",
            "schema_version": "1.0.0",
            "cases": cases,
        },
        {
            "kind": "Stage2SourceContextQualityReference",
            "schema_version": "1.0.0",
            "judgments": references,
        },
    )


def context_batch(dataset, reference, role):
    refs = {row["case_id"]: row for row in reference["judgments"]}
    return {
        "kind": "Stage2RubricQualityBatchV3",
        "role": role,
        "judgments": [
            {
                "case_id": case["case_id"],
                "status": refs[case["case_id"]]["status"],
                "score": refs[case["case_id"]]["score"],
                "major_error": refs[case["case_id"]]["major_error"],
                "reason": "Synthetic reviewer explanation.",
                "evidence_ids": [case["facts"][0]["evidence_id"]],
            }
            for case in dataset["cases"]
        ],
    }


def core_result_bundle():
    dataset, reference, rubric = core_fixture()
    r1 = core_batch(dataset, reference, "R1")
    r2 = core_batch(dataset, reference, "R2")
    report = evaluate_quality_v3(dataset, reference, rubric, r1, r2)
    return {
        "dataset": dataset,
        "reference": reference,
        "rubric": rubric,
        "r1": r1,
        "r2": r2,
        "report": report,
    }


class SourceContextQualityTests(unittest.TestCase):
    def test_structured_answer_fields_cannot_leak_through_subject_record(self):
        for key, value in (
            ("score", 2),
            ("family", "attribution"),
            ("original_case_id", "attribution:positive:0"),
        ):
            dataset, reference = synthetic_context_fixture()
            dataset["cases"][0]["subject_record"][key] = value
            with self.assertRaisesRegex(Stage2Error, "content-fields-only"):
                prepare_context_quality_input(dataset, reference, "R1")

    def test_reviewer_payload_excludes_answer_labels_and_original_identifiers(self):
        import json

        dataset, reference = synthetic_context_fixture()
        payload, private_map = prepare_context_quality_input(dataset, reference, "R1")
        serialized = json.dumps(payload)
        for forbidden in (
            "polarity",
            "critical",
            "major_error",
            "score",
            "negative",
            "positive",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn(dataset["cases"][0]["case_id"], serialized)
        self.assertEqual(
            private_map["case-001"]["case_id"], dataset["cases"][0]["case_id"]
        )
        self.assertEqual(len(payload["cases"]), 12)
        self.assertEqual(reference["judgments"][0]["score"], 2)

    def test_malformed_unhashable_labels_fail_with_contract_error(self):
        for key in ("family", "polarity"):
            dataset, reference = synthetic_context_fixture()
            dataset["cases"][0][key] = []
            with self.assertRaises(Stage2Error):
                validate_context_quality_inputs(dataset, reference)
        dataset, reference = synthetic_context_fixture()
        reference["judgments"][0]["status"] = []
        with self.assertRaises(Stage2Error):
            validate_context_quality_inputs(dataset, reference)

    def setUp(self):
        self.dataset, self.reference = synthetic_context_fixture()
        self.r1 = context_batch(self.dataset, self.reference, "R1")
        self.r2 = context_batch(self.dataset, self.reference, "R2")

    def report(self, r1=None, r2=None):
        return evaluate_context_quality(
            self.dataset, self.reference, r1 or self.r1, r2 or self.r2
        )

    def context_result_bundle(self, r1=None, r2=None):
        r1 = r1 or self.r1
        r2 = r2 or self.r2
        return {
            "dataset": self.dataset,
            "reference": self.reference,
            "r1": r1,
            "r2": r2,
            "report": self.report(r1, r2),
        }

    def test_exact_family_polarity_and_designated_denominators(self):
        cases, refs = validate_context_quality_inputs(self.dataset, self.reference)
        self.assertEqual((len(cases), len(refs)), (12, 12))
        report = self.report()
        self.assertEqual(
            report["overall"], {"matched": 24, "required": 24, "percent": 100.0}
        )
        self.assertTrue(
            all(
                row == {"matched": 8, "required": 8, "percent": 100.0}
                for row in report["per_family"].values()
            )
        )
        self.assertEqual(
            report["agreement"],
            {"matched": 12, "required": 12, "percent": 100.0},
        )
        self.assertEqual(report["reviewer_judgments"]["R1"], self.r1["judgments"])
        self.assertTrue(report["passed"])
        self.assertNotIn("formal_ready", report)
        self.assertNotIn("live_validated", report)

    def test_duplicate_or_missing_cases_and_tampered_reference_fail_closed(self):
        duplicate = copy.deepcopy(self.dataset)
        duplicate["cases"][-1] = copy.deepcopy(duplicate["cases"][0])
        with self.assertRaisesRegex(Stage2Error, "duplicate-case"):
            validate_context_quality_inputs(duplicate, self.reference)

        missing = copy.deepcopy(self.reference)
        missing["judgments"].pop()
        with self.assertRaisesRegex(Stage2Error, "requires-12-cases"):
            validate_context_quality_inputs(self.dataset, missing)

        tampered = copy.deepcopy(self.reference)
        tampered["judgments"][0]["case_id"] = "foreign-case"
        with self.assertRaisesRegex(Stage2Error, "reference-case-mismatch"):
            validate_context_quality_inputs(self.dataset, tampered)

    def test_unsupported_scores_and_cross_case_evidence_are_rejected(self):
        bad_reference = copy.deepcopy(self.reference)
        bad_reference["judgments"][0]["score"] = 3
        with self.assertRaisesRegex(Stage2Error, "reference-score"):
            validate_context_quality_inputs(self.dataset, bad_reference)

        bad_score = copy.deepcopy(self.r1)
        bad_score["judgments"][0]["score"] = 3
        with self.assertRaisesRegex(Stage2Error, "scored-judgment-shape"):
            self.report(r1=bad_score)

        bad_evidence = copy.deepcopy(self.r1)
        bad_evidence["judgments"][0]["evidence_ids"] = ["foreign-evidence"]
        with self.assertRaisesRegex(Stage2Error, "unknown-evidence"):
            self.report(r1=bad_evidence)

    def test_missing_evaluator_row_does_not_shrink_denominator(self):
        missing = copy.deepcopy(self.r1)
        missing["judgments"].pop()
        with self.assertRaisesRegex(Stage2Error, "missing-or-duplicate"):
            self.report(r1=missing)

    def test_evaluator_failure_is_retained_as_null_and_never_scientific_zero(self):
        failed = copy.deepcopy(self.r2)
        failed["judgments"][0].update(
            status="evaluator_failure",
            score=None,
            major_error=None,
            evidence_ids=[],
            reason="Synthetic evaluator failure.",
        )
        report = self.report(r2=failed)
        self.assertEqual(report["overall"]["required"], 24)
        self.assertEqual(report["overall"]["matched"], 23)
        self.assertEqual(
            report["evaluator_failures"],
            [{"case_id": self.dataset["cases"][0]["case_id"], "role": "R2"}],
        )
        self.assertIsNone(report["reviewer_judgments"]["R2"][0]["score"])
        self.assertFalse(report["passed"])

    def test_each_family_must_meet_its_own_threshold(self):
        r2 = copy.deepcopy(self.r2)
        r2["judgments"][0]["score"] = 1
        report = self.report(r2=r2)
        family = self.dataset["cases"][0]["family"]
        self.assertEqual(report["overall"]["matched"], 23)
        self.assertGreaterEqual(report["overall"]["percent"], 90)
        self.assertGreaterEqual(report["agreement"]["percent"], 85)
        self.assertEqual(report["per_family"][family]["percent"], 87.5)
        self.assertFalse(report["passed"])

    def test_critical_mismatch_and_unresolved_major_error_fail(self):
        critical_index = next(
            index
            for index, row in enumerate(self.reference["judgments"])
            if row["critical"]
        )
        critical = copy.deepcopy(self.r2)
        critical["judgments"][critical_index]["score"] = 1
        report = self.report(r2=critical)
        self.assertTrue(report["critical_errors"])
        self.assertFalse(report["passed"])

        major = copy.deepcopy(self.r2)
        major["judgments"][0]["major_error"] = True
        report = self.report(r2=major)
        self.assertTrue(report["unresolved_major_errors"])
        self.assertFalse(report["passed"])

    def test_combined_gate_replays_inputs_and_preserves_historical_core(self):
        core = core_result_bundle()
        historical_report = copy.deepcopy(core["report"])
        context = self.context_result_bundle()
        combined = combine_quality_acceptance(core, context)
        self.assertEqual(core["report"], historical_report)
        self.assertEqual(
            (core["report"]["presentations"], core["report"]["designated_judgments"]),
            (72, 144),
        )
        self.assertEqual(
            (combined["presentations"], combined["designated_judgments"]),
            (84, 168),
        )
        self.assertEqual(
            (combined["core"]["status"], combined["context"]["status"]),
            ("passed", "passed"),
        )
        self.assertTrue(combined["qa_pass"])
        self.assertEqual(combined["evidence_class"], "deterministic-mechanics-only")
        self.assertNotIn("formal_ready", combined)
        self.assertNotIn("live_validated", combined)

    def test_random_or_tampered_core_pass_flags_cannot_create_acceptance(self):
        with self.assertRaisesRegex(Stage2Error, "requires-original-inputs"):
            combine_quality_acceptance({"qa_pass": True}, self.context_result_bundle())

        core = core_result_bundle()
        core["r2"]["judgments"][0].update(
            status="evaluator_failure",
            score=None,
            major_error=None,
            evidence_ids=[],
        )
        core["report"]["passed"] = True
        with self.assertRaisesRegex(Stage2Error, "does-not-match-recomputation"):
            combine_quality_acceptance(core, self.context_result_bundle())

    def test_tampered_context_report_is_rejected_before_combination(self):
        context = self.context_result_bundle()
        context["report"]["passed"] = False
        with self.assertRaisesRegex(Stage2Error, "does-not-match-recomputation"):
            combine_quality_acceptance(core_result_bundle(), context)


if __name__ == "__main__":
    unittest.main()
