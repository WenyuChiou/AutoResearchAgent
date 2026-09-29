"""Regression tests for source-supplied Stage 2 diagnostic targets."""

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

# ruff: noqa: E402 -- repository CLIs are intentionally imported without install.
from stage2_common import canonical_hash
from stage2_eval.diagnostics import (
    DiagnosticError,
    prepare_diagnostic_judge_view,
    prepare_diagnostic_prompt,
    validate_diagnostic_output,
)


CHECKS = ("opportunity", "value", "answerability", "materials", "execution")


def fact(evidence_id, work_id, version_id, text):
    return {
        "evidence_id": evidence_id,
        "work_id": work_id,
        "version_id": version_id,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def cases():
    return [
        {
            "kind": "Stage2DiagnosticCase",
            "schema_version": "2.0.0",
            "case_id": "case-claim-boundary",
            "research_candidate": {
                "id": "candidate-claim",
                "version": 2,
                "text": "Study whether the bounded association can be estimated.",
            },
            "claim_under_review": {
                "id": "claim-repeat",
                "text": "Reanalysis of the same observations is an independent-sample replication.",
            },
            "screening_action": None,
            "source_facts": [
                fact(
                    "fact-claim",
                    "work-claim",
                    "version-claim-1",
                    "The analysis reused the same observations under a revised model.",
                )
            ],
        },
        {
            "kind": "Stage2DiagnosticCase",
            "schema_version": "2.0.0",
            "case_id": "case-screening-boundary",
            "research_candidate": {
                "id": "candidate-screening",
                "version": 1,
                "text": "Evaluate a novel method with a measurable comparison.",
            },
            "claim_under_review": {
                "id": "claim-method",
                "text": "The method has already demonstrated improved performance.",
            },
            "screening_action": {
                "id": "screen-method",
                "action": "reject",
                "rationale": "No performance estimate was supplied.",
            },
            "source_facts": [
                fact(
                    "fact-screen",
                    "work-screen",
                    "version-screen-1",
                    "The proposal describes a measurable comparison but reports no performance estimate.",
                )
            ],
        },
    ]


def assessment(case, target_kind, target_id, disposition, evidence_id, quote):
    version = (
        case["research_candidate"]["version"] if target_kind == "candidate" else None
    )
    return {
        "case_id": case["case_id"],
        "case_sha256": canonical_hash(case),
        "disposition_target": {
            "kind": target_kind,
            "id": target_id,
            "version": version,
        },
        "disposition": disposition,
        "rationale": "The disposition applies only to the identified target.",
        "evidence_refs": [{"evidence_id": evidence_id, "exact_quote": quote}],
        "next_step": "Run the stated bounded follow-up check.",
        "checks": {
            key: {
                "status": "assessed",
                "score": 1,
                "rationale": f"The supplied fact supports a bounded {key} assessment.",
                "evidence_refs": [{"evidence_id": evidence_id, "exact_quote": quote}],
            }
            for key in CHECKS
        },
        "unsupported_assumptions": [],
    }


def output(rows):
    return {
        "kind": "Stage2DiagnosticOutput",
        "schema_version": "2.0.0",
        "results": rows,
    }


class Stage2DiagnosticTests(unittest.TestCase):
    def test_prompt_supplies_host_hashes_without_case_specific_answers(self):
        prompt = prepare_diagnostic_prompt(cases())
        for case in cases():
            self.assertIn(canonical_hash(case), prompt)
        instructions = prompt.split("OUTPUT CONTRACT:")[0]
        self.assertNotIn("Reanalysis of the same observations is not", instructions)
        self.assertNotIn("Do not award complexity", instructions)

    def setUp(self):
        self.cases = cases()
        claim_fact = self.cases[0]["source_facts"][0]
        screen_fact = self.cases[1]["source_facts"][0]
        self.rows = [
            assessment(
                self.cases[0],
                "claim",
                "claim-repeat",
                "reject",
                claim_fact["evidence_id"],
                claim_fact["text"],
            ),
            assessment(
                self.cases[1],
                "screening-action",
                "screen-method",
                "revise",
                screen_fact["evidence_id"],
                screen_fact["text"],
            ),
        ]

    def test_claim_and_screening_dispositions_do_not_reject_candidates(self):
        result = output(copy.deepcopy(self.rows))
        validation = validate_diagnostic_output(result, self.cases)
        self.assertEqual(
            validation,
            {
                "valid": True,
                "scope": "technical-validity-only",
                "case_count": 2,
                "semantic_correctness_established": False,
                "formal_readiness_established": False,
                "quality_score": None,
                "improvement_established": False,
            },
        )
        view = prepare_diagnostic_judge_view(result, self.cases)
        self.assertEqual(
            [row["disposition_target"]["kind"] for row in view["cases"]],
            ["claim", "screening-action"],
        )
        self.assertEqual(
            [row["research_candidate"]["id"] for row in view["cases"]],
            ["candidate-claim", "candidate-screening"],
        )
        self.assertNotIn("candidate-disposition", json.dumps(view))

    def test_prompt_has_natural_judgment_boundaries_without_expected_answers(self):
        prompt = prepare_diagnostic_prompt(self.cases)
        self.assertIn("does not itself reject the research candidate", prompt)
        self.assertIn("unresolved research questions, and unverified prerequisites", prompt)
        self.assertNotIn("expected_score", prompt)
        self.assertNotIn("expected_disposition", prompt)
        self.assertEqual(prompt.count("The analysis reused the same observations"), 1)

    def test_stale_candidate_target_is_rejected(self):
        stale = copy.deepcopy(self.rows)
        stale[0]["disposition_target"] = {
            "kind": "candidate",
            "id": "candidate-claim",
            "version": 1,
        }
        with self.assertRaisesRegex(DiagnosticError, "stale candidate version"):
            validate_diagnostic_output(output(stale), self.cases)

    def test_wrong_case_fact_identity_and_unknown_reference_are_rejected(self):
        wrong_case = copy.deepcopy(self.rows)
        wrong_case[0]["evidence_refs"] = copy.deepcopy(wrong_case[1]["evidence_refs"])
        with self.assertRaisesRegex(DiagnosticError, "unknown evidence reference"):
            validate_diagnostic_output(output(wrong_case), self.cases)
        wrong_target = copy.deepcopy(self.rows)
        wrong_target[1]["disposition_target"]["id"] = "claim-method"
        with self.assertRaisesRegex(
            DiagnosticError, "screening-action target mismatch"
        ):
            validate_diagnostic_output(output(wrong_target), self.cases)

    def test_quote_paraphrase_and_fact_hash_mismatch_are_rejected(self):
        paraphrase = copy.deepcopy(self.rows)
        paraphrase[0]["evidence_refs"][0]["exact_quote"] = (
            "The observations were reused with another model."
        )
        with self.assertRaisesRegex(
            DiagnosticError, "not exact contiguous source text"
        ):
            validate_diagnostic_output(output(paraphrase), self.cases)
        bad_cases = copy.deepcopy(self.cases)
        bad_cases[0]["source_facts"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(DiagnosticError, "source fact hash mismatch"):
            prepare_diagnostic_prompt(bad_cases)

    def test_unknown_score_stays_null_and_names_a_next_check(self):
        unknown = copy.deepcopy(self.rows)
        unknown[0]["checks"]["materials"] = {
            "status": "unknown",
            "score": None,
            "rationale": "The supplied facts do not establish access conditions.",
            "evidence_refs": [],
        }
        unknown[0]["next_step"] = "Inspect the access record for the required material."
        validate_diagnostic_output(output(unknown), self.cases)
        unknown[0]["checks"]["materials"]["score"] = 0
        with self.assertRaisesRegex(DiagnosticError, "unknown check needs null score"):
            validate_diagnostic_output(output(unknown), self.cases)
        unknown[0]["checks"]["materials"]["score"] = False
        with self.assertRaisesRegex(DiagnosticError, "unknown check needs null score"):
            validate_diagnostic_output(output(unknown), self.cases)

    def test_boolean_assessed_score_and_missing_assessed_evidence_are_rejected(self):
        boolean_score = copy.deepcopy(self.rows)
        boolean_score[0]["checks"]["value"]["score"] = True
        with self.assertRaisesRegex(DiagnosticError, "integer 0, 1, or 2"):
            validate_diagnostic_output(output(boolean_score), self.cases)
        no_evidence = copy.deepcopy(self.rows)
        no_evidence[0]["checks"]["value"]["evidence_refs"] = []
        with self.assertRaisesRegex(DiagnosticError, "assessed check needs evidence"):
            validate_diagnostic_output(output(no_evidence), self.cases)

    def test_duplicate_ids_and_exact_case_coverage_are_required(self):
        duplicate_cases = copy.deepcopy(self.cases)
        duplicate_cases[1]["case_id"] = duplicate_cases[0]["case_id"]
        with self.assertRaisesRegex(DiagnosticError, "duplicate case_id"):
            prepare_diagnostic_prompt(duplicate_cases)
        duplicate_facts = copy.deepcopy(self.cases)
        duplicate_facts[1]["source_facts"][0]["evidence_id"] = "fact-claim"
        with self.assertRaisesRegex(DiagnosticError, "duplicate evidence_id"):
            prepare_diagnostic_prompt(duplicate_facts)
        missing = output(copy.deepcopy(self.rows[:1]))
        with self.assertRaisesRegex(DiagnosticError, "exact case coverage"):
            validate_diagnostic_output(missing, self.cases)
        duplicated = output(copy.deepcopy([self.rows[0], self.rows[0]]))
        with self.assertRaisesRegex(DiagnosticError, "exact case coverage"):
            validate_diagnostic_output(duplicated, self.cases)

    def test_expected_outcomes_and_unknown_fields_are_rejected(self):
        contaminated = copy.deepcopy(self.cases)
        contaminated[0]["expected_disposition"] = "reject"
        with self.assertRaisesRegex(DiagnosticError, "case fields"):
            prepare_diagnostic_prompt(contaminated)
        malformed = output(copy.deepcopy(self.rows))
        malformed["results"][0]["quality_score"] = 2
        with self.assertRaisesRegex(DiagnosticError, "result fields"):
            validate_diagnostic_output(malformed, self.cases)
        malformed = output(copy.deepcopy(self.rows))
        malformed["results"][0]["case_id"] = ["not", "text"]
        with self.assertRaisesRegex(DiagnosticError, "result case_id"):
            validate_diagnostic_output(malformed, self.cases)


if __name__ == "__main__":
    unittest.main()
