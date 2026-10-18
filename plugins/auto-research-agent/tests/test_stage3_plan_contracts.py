"""Closed-shape Stage 3 research-plan contract tests."""

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage3_plan import Stage3Error, canonical_bytes, check_plan, digest, validate_plan
from stage3_plan_fixtures import make_plan


SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "stage3-research-plan.v1.schema.json"
)


class Stage3PlanContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)

    def test_canonical_bytes_and_digest_are_stable(self):
        left = {"z": "é", "a": [2, 1]}
        right = {"a": [2, 1], "z": "é"}
        self.assertEqual(canonical_bytes(left), canonical_bytes(right))
        self.assertEqual(digest(left), digest(right))
        with self.assertRaisesRegex(Stage3Error, "not canonical JSON"):
            canonical_bytes({"bad": float("nan")})

    def test_generic_plan_families_and_variable_question_counts_validate(self):
        cases = (
            ("numeric", 1, False),
            ("observational", 2, False),
            ("qualitative", 3, False),
            ("theory", 2, True),
        )
        for topic, question_count, shared_path in cases:
            with self.subTest(topic=topic, question_count=question_count):
                plan = make_plan(topic, question_count, shared_path=shared_path)
                self.assertIsNone(validate_plan(plan))
                self.assertEqual(
                    check_plan(plan),
                    {
                        "structural_valid": True,
                        "issues": [],
                        "blocked_questions": [],
                        "execution_authorized": False,
                    },
                )

    def test_schema_is_closed_and_results_are_unrun_null(self):
        extra = make_plan()
        extra["plan_status"] = "ready"
        with self.assertRaisesRegex(Stage3Error, "plan_status"):
            validate_plan(extra)

        completed = make_plan()
        completed["results"][0]["status"] = "complete"
        completed["results"][0]["observed_value"] = 7
        with self.assertRaises(Stage3Error):
            validate_plan(completed)

        missing_origin = make_plan()
        del missing_origin["resources"][0]["origin"]
        with self.assertRaises(Stage3Error):
            validate_plan(missing_origin)

    def test_proposed_resource_shape_cannot_claim_availability(self):
        plan = make_plan()
        plan["resources"][0].update(
            origin="proposed",
            availability="available",
            uncertainties=["Acquisition has not been verified."],
        )
        with self.assertRaises(Stage3Error):
            validate_plan(plan)

        plan["resources"][0].update(availability="unknown", uncertainties=[])
        with self.assertRaises(Stage3Error):
            validate_plan(plan)

    def test_blocked_core_draft_can_be_structurally_valid(self):
        plan = make_plan("theory")
        question_ref = plan["questions"][0]["question_ref"]
        plan["question_plans"][0].update(
            design_ids=[],
            analysis_ids=[],
            result_ids=[],
            blockers=["A necessary premise remains unresolved."],
        )
        plan["designs"] = []
        plan["analyses"] = []
        plan["results"] = []
        plan["milestones"][0]["design_ids"] = []
        plan["unknowns"] = [
            {
                "description": "The premise has not been established.",
                "question_refs": [question_ref],
                "resolution": "Establish or reject the premise from admissible evidence.",
                "blocking": True,
            }
        ]
        checked = check_plan(plan)
        self.assertTrue(checked["structural_valid"])
        self.assertEqual(checked["blocked_questions"], [question_ref])
        self.assertFalse(checked["execution_authorized"])

    def test_check_plan_returns_schema_diagnostics_instead_of_raising(self):
        plan = make_plan()
        del plan["questions"][0]["text"]
        with self.assertRaises(Stage3Error):
            validate_plan(plan)
        checked = check_plan(plan)
        self.assertFalse(checked["structural_valid"])
        self.assertEqual(checked["issues"][0]["code"], "schema-invalid")
        self.assertFalse(checked["execution_authorized"])

    def test_duplicate_ids_and_missing_core_are_rejected(self):
        duplicate = make_plan("observational", 2)
        duplicate["questions"][1]["question_ref"] = duplicate["questions"][0][
            "question_ref"
        ]
        duplicate["question_plans"][1]["question_ref"] = duplicate["question_plans"][0][
            "question_ref"
        ]
        codes = {issue["code"] for issue in check_plan(duplicate)["issues"]}
        self.assertIn("duplicate-id", codes)

        no_core = make_plan()
        no_core["questions"][0]["priority"] = "secondary"
        codes = {issue["code"] for issue in check_plan(no_core)["issues"]}
        self.assertIn("missing-core-question", codes)


if __name__ == "__main__":
    unittest.main()
