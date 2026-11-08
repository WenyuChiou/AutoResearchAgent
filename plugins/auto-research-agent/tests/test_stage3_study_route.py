"""Authored study-route projection contracts; no research or model execution."""

# ruff: noqa: E402 -- repository fixture imports.

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage3_plan.contracts import Stage3Error
from stage3_plan.direction_study_route import project_study_route


def structured_result():
    phases = {}
    for name in ("baseline", "prototype", "holdout", "continuation"):
        phases[name] = {
            "title": f"Authored {name} phase",
            "inputs": f"Specified {name} inputs; permission remains unresolved.",
            "procedure": f"Proposed {name} comparison procedure.",
            "output": f"Unrun {name} output with provenance.",
            "decision": f"Record the supported {name} decision or uncertainty.",
            "if_blocked": f"Retain the {name} limitation and narrow the proposed claim.",
            "timebox": f"Bound the {name} check before its dependent phase.",
        }
    return {
        "kind": "Stage3StructuredDirectionPlanningResult",
        "schema_version": "1.0.0",
        "intent_sha256": "a" * 64,
        "planning_status": "needs-information",
        "question_plans": [
            {
                "question_ref": "authored-direction@1/question-1",
                "materials": "Authored inventory; usable access is unverified.",
                "design": "A proposed comparison with an independent check.",
                "validation": "Keep original source limitations visible.",
                "analysis": "Use the same specified outcome and unit in both methods.",
                "interpretation": "Retain support, contradiction and uncertainty.",
                "unknowns": ["Source permission remains unknown."],
                "minimum_deliverable": "A bounded unrun comparison specification.",
                "study_route": phases,
                "response_validation": {
                    "kind": "matched-response",
                    "reason": "Authored contrast requiring independent verification.",
                    "acquire": "Check a lawful measurement route; access is unknown.",
                    "pair": "Record matching keys, units and observation windows.",
                    "identify": "Specify the contrast and unresolved confounds.",
                    "train_and_lock": "Freeze development choices before verification.",
                    "predict_before_reveal": "Save both predictions before target reveal.",
                    "reveal_and_verify": "Use an independent target-reveal check.",
                    "qualified_scope": "Limit the claim to independently checked units.",
                    "if_blocked": "Retain the unanswered claim and proposed fallback.",
                },
            }
        ],
        "markdown": "Authored overview only; no observed findings.",
        "execution_authorized": False,
    }


class Stage3StudyRouteTests(unittest.TestCase):
    def test_four_phases_and_eight_response_steps_render_in_readable_order(self):
        raw = structured_result()
        question = raw["question_plans"][0]
        projected = project_study_route(raw)["question_plans"][0]
        self.assertEqual(projected["question_ref"], question["question_ref"])
        method = projected["method"]
        phases = (
            ("baseline", "Step 1: Establish the reference"),
            ("prototype", "Step 2: Build the proposed method"),
            ("holdout", "Step 3: Test on independent evidence"),
            ("continuation", "Step 4: Decide the qualified continuation"),
        )
        positions = []
        for name, heading in phases:
            phase = question["study_route"][name]
            positions.append(method.index(heading))
            self.assertIn(phase["title"], method)
            for key, label in (
                ("inputs", "Inputs"),
                ("procedure", "Procedure"),
                ("output", "Output"),
                ("decision", "Decision"),
                ("if_blocked", "If blocked"),
                ("timebox", "Timebox"),
            ):
                self.assertIn(f"{label}: {phase[key]}", method)
        self.assertEqual(positions, sorted(positions))
        response_positions = []
        for number, (key, label) in enumerate(
            (
                ("acquire", "Acquire the evidence"),
                ("pair", "Pair observations"),
                ("identify", "Define the supported contrast"),
                ("train_and_lock", "Develop and freeze"),
                ("predict_before_reveal", "Predict before revealing targets"),
                ("reveal_and_verify", "Reveal and independently verify"),
                ("qualified_scope", "Limit the qualified scope"),
                ("if_blocked", "Stop or narrow the claim"),
            ),
            1,
        ):
            text = f"{number}. {label}: {question['response_validation'][key]}"
            response_positions.append(method.index(text))
        self.assertEqual(response_positions, sorted(response_positions))
        self.assertLess(positions[2], response_positions[0])
        self.assertLess(response_positions[-1], positions[3])

    def test_projection_preserves_unknowns_public_values_and_original_input(self):
        raw = structured_result()
        before = deepcopy(raw)
        projected = project_study_route(raw)
        expected = {
            key: value
            for key, value in before["question_plans"][0].items()
            if key not in {"study_route", "response_validation"}
        }
        actual = {
            key: value
            for key, value in projected["question_plans"][0].items()
            if key != "method"
        }
        self.assertEqual(actual, expected)
        for key in (
            "intent_sha256",
            "planning_status",
            "markdown",
            "execution_authorized",
        ):
            self.assertEqual(projected[key], before[key])
        self.assertEqual(raw, before)
        projected["question_plans"][0]["unknowns"].append("Projected copy only.")
        self.assertEqual(raw, before)

    def test_multiple_questions_project_to_the_existing_closed_public_schema(self):
        raw = structured_result()
        second = deepcopy(raw["question_plans"][0])
        second["question_ref"] = "authored-direction@1/question-2"
        second["study_route"]["baseline"]["procedure"] = "Distinct second procedure."
        raw["question_plans"].append(second)
        projected = project_study_route(raw)
        schema = json.loads(
            (PLUGIN / "schemas/stage3-direction-plan.v1.schema.json").read_bytes()
        )
        Draft202012Validator(schema).validate(projected)
        self.assertEqual(
            [row["question_ref"] for row in projected["question_plans"]],
            [row["question_ref"] for row in raw["question_plans"]],
        )
        expected_keys = set(schema["properties"]["question_plans"]["items"]["required"])
        for row in projected["question_plans"]:
            self.assertEqual(set(row), expected_keys)
            self.assertNotIn("study_route", row)
            self.assertNotIn("response_validation", row)
        self.assertIn(
            "Distinct second procedure.", projected["question_plans"][1]["method"]
        )
        self.assertNotIn(
            "Distinct second procedure.", projected["question_plans"][0]["method"]
        )

    def test_redundant_method_missing_phase_and_open_phase_shapes_are_rejected(self):
        variants = []
        redundant = structured_result()
        redundant["question_plans"][0]["method"] = "Competing unstructured method."
        variants.append(redundant)
        missing_phase = structured_result()
        del missing_phase["question_plans"][0]["study_route"]["holdout"]
        variants.append(missing_phase)
        missing_field = structured_result()
        del missing_field["question_plans"][0]["study_route"]["baseline"]["inputs"]
        variants.append(missing_field)
        extra_field = structured_result()
        extra_field["question_plans"][0]["study_route"]["prototype"].update(
            extra="Unbound."
        )
        variants.append(extra_field)
        extra_phase = structured_result()
        extra_phase["question_plans"][0]["study_route"]["unrecognized"] = {}
        variants.append(extra_phase)
        missing_response = structured_result()
        del missing_response["question_plans"][0]["response_validation"]["pair"]
        variants.append(missing_response)
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(Stage3Error):
                project_study_route(value)

    def test_not_applicable_retains_reason_without_matched_response_work(self):
        raw = structured_result()
        response = raw["question_plans"][0]["response_validation"]
        response["kind"] = "not-applicable"
        response["reason"] = (
            "This authored question requires a documented interpretation check."
        )
        for key in response.keys() - {"kind", "reason"}:
            response[key] = f"UNUSED-MATCHED-RESPONSE-{key}"
        projected = project_study_route(raw)
        method = projected["question_plans"][0]["method"]
        self.assertIn(response["reason"], method)
        self.assertNotIn("UNUSED-MATCHED-RESPONSE", method)
        self.assertEqual(
            projected["question_plans"][0]["validation"],
            raw["question_plans"][0]["validation"],
        )

    def test_malformed_values_fail_with_stage3_error(self):
        variants = [None, [], {}, "unstructured response"]
        wrong_phase = structured_result()
        wrong_phase["question_plans"][0]["study_route"]["baseline"] = []
        variants.append(wrong_phase)
        wrong_unknowns = structured_result()
        wrong_unknowns["question_plans"][0]["unknowns"] = "Unknown permission."
        variants.append(wrong_unknowns)
        wrong_response = structured_result()
        wrong_response["question_plans"][0]["response_validation"]["kind"] = "completed"
        variants.append(wrong_response)
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(Stage3Error):
                project_study_route(value)


if __name__ == "__main__":
    unittest.main()
