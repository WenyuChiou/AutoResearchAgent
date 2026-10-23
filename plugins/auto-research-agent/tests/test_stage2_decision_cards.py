"""Synthetic contract tests for the pure Stage 2 decision-card projection."""

import copy
from pathlib import Path
import sys
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage2_workflow.decision_cards import derive_decision_cards  # noqa: E402


def resource(resource_id, version, *, status, alternatives=()):
    return {
        "resource_id": resource_id,
        "candidate_id": "candidate-a",
        "candidate_version": version,
        "category": "dataset",
        "name": f"Resource {resource_id}",
        "purpose": "Recorded purpose only.",
        "url": "https://example.test/resource",
        "version": "recorded-v1",
        "required": False,
        "status": status,
        "access_conditions": "Access remains unknown"
        if status == "unknown"
        else "Recorded public access",
        "license": None,
        "cost_basis": "Cost unknown" if status == "unknown" else None,
        "limitations": ["Recorded limitation"],
        "alternatives": list(alternatives),
        "evidence_ids": ["evidence-resource"] if status != "unknown" else [],
        "checked_at": None if status == "unknown" else "2026-10-22T12:00:00Z",
        "spans": [{"start": 0, "end": 1, "quote": "x"}],
    }


def question(question_id, *, status="proposal", object_="A theoretical construct"):
    return {
        "question_id": question_id,
        "text": f"What explains {question_id}?",
        "priority": "core",
        "gap_ids": ["gap-a"],
        "object": object_,
        "intended_claim": "A bounded explanation may be supported.",
        "status": status,
    }


class Stage2DecisionCardsTests(unittest.TestCase):
    def selection(self):
        scientific_argument = {
            "questions": [
                question("question-mapped"),
                question("question-unmapped", object_="A conceptual distinction"),
                question("question-unknown", status="unknown"),
            ],
            "resource_refs": [
                {
                    "resource_id": "resource-current",
                    "question_ids": ["question-mapped"],
                    "purpose": "Evaluate the recorded relation.",
                    "fit_status": "supported",
                    "evidence_ids": ["evidence-fit"],
                },
                {
                    "resource_id": "resource-unknown",
                    "question_ids": ["question-unknown"],
                    "purpose": "Possible input if access is established.",
                    "fit_status": "unknown",
                    "evidence_ids": [],
                },
            ],
            "contribution_claims": [
                {
                    "text": "The conceptual distinction may be clarified.",
                    "question_ids": ["question-unmapped"],
                    "status": "proposal",
                }
            ],
        }
        candidate = {
            "candidate_id": "candidate-a",
            "version": 2,
            "question": "Which bounded explanation is supportable?",
            "research_mode": "theory",
            "approach": "Compare the recorded concepts without an empirical premise.",
            "requirements": ["Keep the conceptual scope bounded."],
            "limitations": ["The explanatory boundary remains provisional."],
            "scientific_argument": scientific_argument,
        }
        assessment = {
            "next_step": "Resolve the stated conceptual boundary.",
            "checks": {
                "materials": {
                    "status": "unknown",
                    "next_check": "Verify the recorded access condition.",
                },
                "value": {"status": "assessed", "next_check": None},
            },
        }
        current = resource(
            "resource-current", 2, status="available", alternatives=("Use proxy A",)
        )
        unknown = resource("resource-unknown", 2, status="unknown")
        unused = resource(
            "resource-unused", 2, status="restricted", alternatives=("Use report B",)
        )
        old = resource("resource-current", 1, status="restricted")
        old["access_conditions"] = "Old version access condition"
        review = {
            "candidate_id": "candidate-a",
            "candidate_version": 2,
            "review_status": "bounded",
            "comparisons": [
                {
                    "work_id": "work-nearest",
                    "version_id": "work-v1",
                    "role": "closest",
                    "established": "Recorded established result",
                    "overlap": "Recorded overlap",
                    "difference": "Recorded difference",
                    "limitations": ["Recorded prior-work limit"],
                    "evidence_ids": ["evidence-prior"],
                }
            ],
            "unresolved": ["Check the recorded prior-work boundary."],
        }
        old_review = copy.deepcopy(review)
        old_review["candidate_version"] = 1
        old_review["comparisons"][0]["work_id"] = "old-work"
        return {
            "evaluation_packet": {
                "research_tables": {
                    "direction_resources": [old, current, unknown, unused]
                },
                "prior_work_reviews": [old_review, review],
            },
            "current_options": [{"candidate": candidate, "assessment": assessment}],
            "recommendations": [candidate],
        }

    def test_current_version_mapping_preserves_recorded_metadata(self):
        cards = derive_decision_cards(self.selection())
        card = cards["cards"][0]
        mapped, unmapped, unknown = card["scientific_questions"]

        self.assertEqual(mapped["resource_mapping_status"], "mapped")
        self.assertEqual(
            mapped["resource_uses"][0]["resource_ref"]["fit_status"], "supported"
        )
        self.assertEqual(mapped["resource_uses"][0]["resource"]["status"], "available")
        self.assertEqual(unmapped["resource_mapping_status"], "unmapped")
        self.assertEqual(unmapped["resource_uses"], [])
        self.assertEqual(unknown["resource_mapping_status"], "unknown")
        self.assertEqual(
            unknown["resource_uses"][0]["resource"]["access_conditions"],
            "Access remains unknown",
        )
        self.assertEqual(unknown["resource_uses"][0]["resource"]["evidence_ids"], [])
        self.assertEqual(
            card["unmapped_resources"][0]["resource"]["resource_id"],
            "resource-unused",
        )
        self.assertEqual(
            card["unmapped_resources"][0]["resource"]["status"], "restricted"
        )

    def test_old_versions_are_excluded_and_prior_work_is_exactly_current(self):
        card = derive_decision_cards(self.selection())["cards"][0]
        resources = [
            use["resource"]
            for row in card["scientific_questions"]
            for use in row["resource_uses"]
        ]

        self.assertEqual({row["candidate_version"] for row in resources}, {2})
        self.assertNotIn("Old version access condition", repr(card))
        self.assertEqual(
            card["closest_prior_work"]["review"]["comparisons"][0]["work_id"],
            "work-nearest",
        )
        self.assertNotIn("old-work", repr(card))

    def test_theory_question_is_not_forced_into_empirical_requirements(self):
        card = derive_decision_cards(self.selection())["cards"][0]
        theory = card["scientific_questions"][1]

        self.assertEqual(theory["resource_mapping_status"], "unmapped")
        self.assertEqual(theory["question"]["object"], "A conceptual distinction")
        self.assertEqual(theory["resource_uses"], [])
        self.assertEqual(
            theory["contributions"],
            [
                {
                    "text": "The conceptual distinction may be clarified.",
                    "question_ids": ["question-unmapped"],
                    "status": "proposal",
                }
            ],
        )
        self.assertNotIn("required data", repr(theory).lower())

    def test_next_checks_are_traceable_and_input_is_immutable(self):
        selection = self.selection()
        original = copy.deepcopy(selection)

        first = derive_decision_cards(selection)
        second = derive_decision_cards(selection)

        self.assertEqual(first, second)
        self.assertEqual(selection, original)
        checks = first["cards"][0]["next_checks"]
        self.assertEqual(
            [row["text"] for row in checks],
            [
                "Resolve the stated conceptual boundary.",
                "Verify the recorded access condition.",
                "Check the recorded prior-work boundary.",
            ],
        )
        self.assertTrue(all(row["source"] for row in checks))
        self.assertEqual(
            first["cards"][0]["scientific_questions"][0]["next_checks"], checks
        )
        self.assertEqual(selection["recommendations"], original["recommendations"])

    def test_candidate_fields_and_legacy_missing_argument_are_explicit(self):
        selection = self.selection()
        current = derive_decision_cards(selection)["cards"][0]
        self.assertEqual(
            current["candidate_question"], "Which bounded explanation is supportable?"
        )
        self.assertEqual(
            current["requirements"], ["Keep the conceptual scope bounded."]
        )
        self.assertEqual(current["scientific_argument_status"], "recorded")

        legacy = copy.deepcopy(selection)
        del legacy["current_options"][0]["candidate"]["scientific_argument"]
        card = derive_decision_cards(legacy)["cards"][0]
        self.assertEqual(card["scientific_argument_status"], "not-recorded")
        self.assertEqual(card["scientific_questions"], [])
        self.assertEqual(card["contribution"], [])
        self.assertEqual(
            [row["resource"]["resource_id"] for row in card["unmapped_resources"]],
            ["resource-current", "resource-unknown", "resource-unused"],
        )


if __name__ == "__main__":
    unittest.main()
