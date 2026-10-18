"""Stage 3 graph closure and immutable-intake traceability tests."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage3_plan import check_plan
from stage3_plan_fixtures import make_intake, make_plan


def issue_codes(plan, *, intake=None):
    return {issue["code"] for issue in check_plan(plan, intake=intake)["issues"]}


class Stage3PlanTraceabilityTests(unittest.TestCase):
    def test_many_to_many_question_paths_are_valid(self):
        plan = make_plan("qualitative", 3, shared_path=True)
        intake = make_intake(plan)
        checked = check_plan(plan, intake=intake)
        self.assertTrue(checked["structural_valid"], checked["issues"])

    def test_question_ref_and_bidirectional_links_must_close(self):
        wrong_ref = make_plan()
        wrong_ref["questions"][0]["question_ref"] = "candidate-numeric@1/wrong"
        self.assertIn("question-ref-mismatch", issue_codes(wrong_ref))

        asymmetric = make_plan()
        asymmetric["designs"][0]["question_refs"] = ["candidate-numeric@1/other"]
        codes = issue_codes(asymmetric)
        self.assertIn("missing-reference", codes)
        self.assertIn("asymmetric-reference", codes)

    def test_orphan_and_broken_design_analysis_result_links_fail(self):
        orphan = make_plan()
        orphan["designs"].append(copy.deepcopy(orphan["designs"][0]))
        orphan["designs"][1]["design_id"] = "orphan-design"
        self.assertIn("asymmetric-reference", issue_codes(orphan))

        broken_analysis = make_plan()
        broken_analysis["analyses"][0]["design_ids"] = ["missing-design"]
        codes = issue_codes(broken_analysis)
        self.assertIn("missing-reference", codes)
        self.assertIn("broken-analysis-link", codes)

        broken_result = make_plan()
        broken_result["results"][0]["analysis_ids"] = ["missing-analysis"]
        codes = issue_codes(broken_result)
        self.assertIn("missing-reference", codes)
        self.assertIn("broken-result-link", codes)

    def test_cross_question_links_must_share_a_question(self):
        plan = make_plan("observational", 2)
        plan["analyses"][0]["design_ids"].append("design-2")
        self.assertIn("wrong-analysis-link", issue_codes(plan))

        plan = make_plan("observational", 2)
        plan["results"][0]["analysis_ids"].append("analysis-2")
        self.assertIn("wrong-result-link", issue_codes(plan))

    def test_unblocked_question_requires_complete_path(self):
        plan = make_plan()
        plan["question_plans"][0]["result_ids"] = []
        self.assertIn("incomplete-question-path", issue_codes(plan))

    def test_resources_require_plan_membership_and_intake_question_fit(self):
        missing = make_plan()
        missing["question_plans"][0]["resource_uses"][0]["resource_id"] = "unlisted"
        self.assertIn("missing-reference", issue_codes(missing))

        wrong_fit = make_plan("observational", 2)
        intake = make_intake(wrong_fit)
        intake["scientific_arguments"][0]["argument"]["resource_refs"] = intake[
            "scientific_arguments"
        ][0]["argument"]["resource_refs"][:1]
        self.assertIn("resource-question-fit", issue_codes(wrong_fit, intake=intake))

        absent_source = make_plan()
        intake = make_intake(absent_source)
        intake["resources"] = []
        self.assertIn(
            "source-resource-mismatch", issue_codes(absent_source, intake=intake)
        )

    def test_proposed_resource_is_legal_only_as_unknown_and_blocking(self):
        plan = make_plan()
        question_ref = plan["questions"][0]["question_ref"]
        plan["resources"].append(
            {
                "resource_id": "proposed-report",
                "origin": "proposed",
                "availability": "unknown",
                "access_conditions": "Access has not been established.",
                "fitness": "The report would address a missing evidence need.",
                "scale_basis": "The report scope must be verified after access.",
                "minimum": "A relevant extract with provenance.",
                "standard": "The complete relevant report sections.",
                "uncertainties": ["Existence, version, and access remain unverified."],
            }
        )
        plan["question_plans"][0]["resource_uses"].append(
            {
                "resource_id": "proposed-report",
                "purpose": "Fill the explicitly identified evidence gap.",
                "fit_rationale": "Its described scope may address this question.",
                "status": "unknown",
            }
        )
        plan["question_plans"][0]["blockers"].append(
            "The proposed report must be verified and admitted in a new source version."
        )
        checked = check_plan(plan, intake=make_intake(plan))
        self.assertTrue(checked["structural_valid"], checked["issues"])
        self.assertEqual(checked["blocked_questions"], [question_ref])

        unblocked = copy.deepcopy(plan)
        unblocked["question_plans"][0]["blockers"] = []
        self.assertIn("proposed-resource-unblocked", issue_codes(unblocked))

        promoted = copy.deepcopy(plan)
        promoted["question_plans"][0]["resource_uses"][1]["status"] = "available"
        self.assertIn("proposed-resource-state", issue_codes(promoted))

    def test_stage2_resource_availability_cannot_be_promoted(self):
        for source_status in ("unknown", "restricted", "unavailable"):
            with self.subTest(source_status=source_status):
                plan = make_plan()
                intake = make_intake(plan)
                intake["resources"][0]["status"] = source_status
                issues = check_plan(plan, intake=intake)["issues"]
                promotions = [
                    issue
                    for issue in issues
                    if issue["code"] == "resource-availability-promotion"
                ]
                self.assertGreaterEqual(len(promotions), 1)

    def test_intake_questions_are_immutable(self):
        plan = make_plan("qualitative", 2)
        intake = make_intake(plan)
        changed = copy.deepcopy(plan)
        changed["questions"][1]["gap_ids"] = ["rewritten-gap"]
        self.assertIn("immutable-question", issue_codes(changed, intake=intake))

        changed_id = copy.deepcopy(plan)
        changed_id["questions"][1]["question_id"] = "rewritten"
        codes = issue_codes(changed_id, intake=intake)
        self.assertIn("question-ref-mismatch", codes)
        self.assertIn("immutable-question", codes)

    def test_missing_milestone_refs_and_cycles_fail(self):
        missing = make_plan()
        missing["milestones"][1]["depends_on"] = ["unknown-milestone"]
        self.assertIn("missing-reference", issue_codes(missing))

        cyclic = make_plan()
        cyclic["milestones"][0]["depends_on"] = ["m2"]
        self.assertIn("milestone-cycle", issue_codes(cyclic))

    def test_blocking_unknown_marks_question_blocked(self):
        plan = make_plan()
        question_ref = plan["questions"][0]["question_ref"]
        plan["unknowns"] = [
            {
                "description": "A required interpretation remains unsettled.",
                "question_refs": [question_ref],
                "resolution": "Resolve through a bounded review.",
                "blocking": True,
            }
        ]
        checked = check_plan(plan)
        self.assertEqual(checked["blocked_questions"], [question_ref])
        self.assertFalse(checked["execution_authorized"])

        plan["unknowns"][0]["question_refs"] = ["candidate-numeric@1/missing"]
        self.assertIn("missing-reference", issue_codes(plan))

    def test_nonexistent_question_design_analysis_result_targets_reject(self):
        plan = make_plan()
        plan["designs"] = []
        plan["analyses"] = []
        plan["results"] = []
        for field in ("design_ids", "analysis_ids", "result_ids"):
            plan["question_plans"][0][field] = ["missing"]
        for milestone in plan["milestones"]:
            milestone["design_ids"] = []
        result = check_plan(plan)
        self.assertFalse(result["structural_valid"])
        self.assertIn("missing-reference", {row["code"] for row in result["issues"]})


if __name__ == "__main__":
    unittest.main()
