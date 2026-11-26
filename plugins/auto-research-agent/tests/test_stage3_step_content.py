"""C11 versioned four-cell steps; fixtures do not prove research quality."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from stage3_plan.contracts import canonical_bytes  # noqa: E402
from stage3_plan.validation import check_plan  # noqa: E402
from stage3_plan.planner import draft_synthetic_plan  # noqa: E402
from stage3_plan.storage import inspect_completed_package  # noqa: E402
from stage3_plan_fixtures import make_plan, make_intake  # noqa: E402


def executable_plan():
    plan = make_plan()
    plan.update(schema_version="1.2.0", condition_dispositions=[])
    plan["resources"][0]["minimum"] = (
        "measurements.csv with response and condition columns"
    )
    plan["designs"][0]["procedure"] = (
        "Read measurements.csv; group response values by condition."
    )
    plan["analyses"][0]["method"] = (
        "Calculate mean response by condition from grouped.csv."
    )
    plan["analyses"][0]["criteria"] = [
        "Each condition has a finite mean and its sample count."
    ]
    plan["results"][0]["artifact"] = (
        "means.csv containing condition, mean_response and n"
    )
    plan["milestones"][0]["deliverable"] = (
        "grouped.csv with original rows and condition labels"
    )
    plan["milestones"][0]["step"] = {
        "inputs": ["/resources/0/minimum"],
        "operation": "/designs/0/procedure",
        "outputs": ["/milestones/0/deliverable"],
        "success_criteria": ["/analyses/0/criteria/0"],
        "named_entities": [
            {
                "kind": "file",
                "name": "measurements.csv",
                "location": "/resources/0/minimum",
            }
        ],
    }
    plan["milestones"][1]["step"] = {
        "inputs": ["/milestones/0/deliverable"],
        "operation": "/analyses/0/method",
        "outputs": ["/results/0/artifact"],
        "success_criteria": ["/analyses/0/criteria/0"],
        "named_entities": [
            {"kind": "file", "name": "means.csv", "location": "/results/0/artifact"}
        ],
    }
    return plan


class Stage3StepContentTests(unittest.TestCase):
    def test_original_generic_step_gets_read_side_notice(self):
        from stage3_plan.step_content import step_diagnostics

        plan = make_plan()
        before = canonical_bytes(plan)
        result = step_diagnostics(plan)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["steps"][0]["inputs"], None)
        self.assertEqual(canonical_bytes(plan), before)
        self.assertTrue(check_plan(plan)["structural_valid"])

    def test_complete_versioned_step_is_valid(self):
        result = check_plan(executable_plan())
        self.assertTrue(result["structural_valid"], result)
        self.assertEqual(result["step_warnings"], [])

    def test_each_missing_cell_rejects(self):
        for field in (
            "inputs",
            "operation",
            "outputs",
            "success_criteria",
            "named_entities",
        ):
            with self.subTest(field=field):
                plan = executable_plan()
                del plan["milestones"][0]["step"][field]
                self.assertFalse(check_plan(plan)["structural_valid"])

    def test_empty_cells_and_extra_fields_reject(self):
        for field, value in [
            ("inputs", []),
            ("operation", ""),
            ("outputs", []),
            ("success_criteria", []),
            ("extra", "x"),
        ]:
            with self.subTest(field=field):
                plan = executable_plan()
                plan["milestones"][0]["step"][field] = value
                self.assertFalse(check_plan(plan)["structural_valid"])

    def test_reference_must_resolve_to_text_in_appropriate_plan_field(self):
        for pointer in (
            "/designs/99/procedure",
            "/designs/0",
            "/resources/0/minimum",
            "/designs/-1/procedure",
            "/designs/00/procedure",
        ):
            with self.subTest(pointer=pointer):
                plan = executable_plan()
                plan["milestones"][0]["step"]["operation"] = pointer
                self.assertFalse(check_plan(plan)["structural_valid"])

    def test_predecessor_input_requires_declared_dependency(self):
        plan = executable_plan()
        plan["milestones"][1]["depends_on"] = []
        self.assertFalse(check_plan(plan)["structural_valid"])

    def test_cycle_and_missing_dependency_reject(self):
        for dependency in ("m2", "absent"):
            plan = executable_plan()
            plan["milestones"][0]["depends_on"] = [dependency]
            self.assertFalse(check_plan(plan)["structural_valid"])

    def test_blank_resolved_text_rejects(self):
        plan = executable_plan()
        plan["analyses"][0]["criteria"][0] = "   "
        self.assertFalse(check_plan(plan)["structural_valid"])

    def test_generic_text_and_missing_names_warn_without_claiming_quality(self):
        plan = executable_plan()
        plan["designs"][0]["procedure"] = "Use a method suited to the stated question"
        plan["milestones"][0]["step"]["named_entities"] = []
        result = check_plan(plan)
        self.assertTrue(result["structural_valid"], result)
        codes = {row["code"] for row in result["step_warnings"]}
        self.assertIn("step-unspecific-operation", codes)
        self.assertIn("step-no-named-entity", codes)
        self.assertFalse(result["execution_authorized"])

    def test_entity_must_be_present_in_a_referenced_cell(self):
        for field, value in [
            ("name", "not-in-the-plan.csv"),
            ("location", "/resources/0/fitness"),
        ]:
            plan = executable_plan()
            plan["milestones"][0]["step"]["named_entities"][0][field] = value
            self.assertFalse(check_plan(plan)["structural_valid"])

    def test_projection_preserves_plan_text_and_dependency_ids(self):
        from stage3_plan.step_content import step_diagnostics

        plan = executable_plan()
        result = step_diagnostics(plan)
        self.assertEqual(result["steps"][1]["depends_on"], ["m1"])
        self.assertEqual(
            result["steps"][0]["operation"],
            {
                "location": "/designs/0/procedure",
                "text": plan["designs"][0]["procedure"],
            },
        )
        self.assertEqual(
            result["steps"][1]["inputs"][0]["text"],
            plan["milestones"][0]["deliverable"],
        )

    def test_same_length_and_short_text_are_not_quality_scores(self):
        plan = executable_plan()
        plan["designs"][0]["procedure"] = "Read measurements.csv."
        self.assertTrue(check_plan(plan)["structural_valid"])
        self.assertNotIn("quality_score", check_plan(plan))

    def test_new_plan_save_and_cold_read_do_not_reexecute_callback(self):
        plan = executable_plan()
        intake = make_intake(plan)
        calls = []

        def callback(**request):
            calls.append(request)
            self.assertIn("named_entities", request["prompt"])
            return {
                "raw_response": canonical_bytes(plan),
                "provenance": {"kind": "synthetic-fixed-callback"},
            }

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp).resolve() / "plan"
            saved = draft_synthetic_plan(
                intake,
                target,
                callback,
                configuration={"model": "synthetic", "reasoning": "test"},
                plan_id=plan["plan_id"],
                schema_version="1.2.0",
            )
            original = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
            read = inspect_completed_package(
                target, saved["manifest"]["manifest_sha256"]
            )
            self.assertEqual(read["artifacts"]["plan.json"], plan)
            self.assertEqual(
                original,
                {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()},
            )
            self.assertEqual(len(calls), 1)

    def test_invalid_new_plan_is_retained_as_failed_not_saved_plan(self):
        from stage3_plan.contracts import Stage3Error

        plan = executable_plan()
        del plan["milestones"][0]["step"]["inputs"]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp).resolve() / "failed"
            with self.assertRaises(Stage3Error):
                draft_synthetic_plan(
                    make_intake(plan),
                    target,
                    lambda **k: {
                        "raw_response": canonical_bytes(plan),
                        "provenance": {"kind": "synthetic"},
                    },
                    configuration={"model": "synthetic", "reasoning": "test"},
                    plan_id=plan["plan_id"],
                    schema_version="1.2.0",
                )
            self.assertTrue((target / "raw-response.json").exists())
            self.assertTrue((target / "failure.json").exists())
            self.assertFalse((target / "plan.json").exists())


if __name__ == "__main__":
    unittest.main()
