"""Fixed review content exercises a contract, not a scientific reviewer."""

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan import review as core  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402
from test_stage3_plan_decision import semantic_review  # noqa: E402


def actionable_review(plan, intake, *, status="adequate", kind="synthetic"):
    """Authored contract fixture; never a model or an authenticated decision."""
    value = semantic_review(plan, intake, status=status, kind=kind)
    value["rubric_sha256"] = digest(core.ACTIONABLE_RUBRIC)
    for finding in value["findings"]:
        finding.update(revision=None, missing_information=None)
        if status in {"needs-revision", "not-adequate"}:
            finding["revision"] = {
                "location": "/designs/0/comparisons/description",
                "action": "Compare the proposed estimator with the constant-prediction baseline on the same held-out rows.",
            }
            finding["plan_locations"].append(finding["revision"]["location"])
        elif status == "unknown":
            finding["missing_information"] = {
                "needed": "Availability of the held-out rows and their measurement dates.",
                "owner": "Dataset custodian (fixture role; not identity verification)",
            }
    return value


class Stage3ReviewContentTests(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.intake = make_intake(self.plan)

    def test_original_needs_work_is_rejected_on_creation(self):
        value = semantic_review(self.plan, self.intake, status="needs-revision")
        for finding in value["findings"]:
            finding["reason"] = "Needs work."
            finding["plan_locations"] = ["/designs/0/comparisons"]
        before = canonical_bytes(value)
        callback = Mock(return_value=value)
        with self.assertRaises(Stage3Error):
            core.review_plan(self.plan, self.intake, callback)
        self.assertEqual(callback.call_count, 1)
        self.assertEqual(canonical_bytes(value), before)

    def test_original_unknown_is_rejected_on_creation(self):
        value = semantic_review(self.plan, self.intake, status="unknown")
        with self.assertRaises(Stage3Error):
            core.review_plan(self.plan, self.intake, Mock(return_value=value))

    def test_current_review_rejects_missing_or_empty_actions(self):
        for action in (None, "", "  "):
            value = actionable_review(self.plan, self.intake, status="needs-revision")
            value["findings"][0]["revision"]["action"] = action
            with self.subTest(action=action), self.assertRaises(Stage3Error):
                core.review_plan(self.plan, self.intake, Mock(return_value=value))
        value = actionable_review(self.plan, self.intake, status="needs-revision")
        value["findings"][0].pop("revision")
        with self.assertRaises(Stage3Error):
            core.validate_review(self.plan, self.intake, value)

    def test_revision_location_must_resolve_to_a_specific_field(self):
        for location in (
            "/designs/0",
            "/designs/999/procedure",
            "/designs",
            "/",
            "/designs/-1/procedure",
            "/designs/00/procedure",
            "/designs/+0/procedure",
            3,
        ):
            value = actionable_review(self.plan, self.intake, status="needs-revision")
            finding = value["findings"][0]
            finding["revision"]["location"] = location
            finding["plan_locations"].append(location)
            with self.subTest(location=location), self.assertRaises(Stage3Error):
                core.validate_review(self.plan, self.intake, value)

    def test_revision_location_must_be_one_of_the_cited_locations(self):
        value = actionable_review(self.plan, self.intake, status="needs-revision")
        value["findings"][0]["plan_locations"] = ["/questions/0"]
        with self.assertRaises(Stage3Error):
            core.validate_review(self.plan, self.intake, value)

    def test_unknown_requires_both_information_and_owner(self):
        for key in ("needed", "owner"):
            value = actionable_review(self.plan, self.intake, status="unknown")
            value["findings"][0]["missing_information"][key] = " "
            with self.subTest(field=key), self.assertRaises(Stage3Error):
                core.validate_review(self.plan, self.intake, value)

    def test_positive_actions_and_unknowns_are_preserved(self):
        for status in ("adequate", "needs-revision", "not-adequate", "unknown"):
            value = actionable_review(self.plan, self.intake, status=status)
            before = canonical_bytes(value)
            callback = Mock(return_value=value)
            self.assertEqual(core.review_plan(self.plan, self.intake, callback), value)
            self.assertEqual(
                callback.call_args.kwargs["rubric"], core.ACTIONABLE_RUBRIC
            )
            self.assertEqual(canonical_bytes(value), before)
            self.assertFalse(value["execution_authorized"])
            self.assertEqual(callback.call_count, 1)

    def test_legacy_review_readback_preserves_bytes_and_status(self):
        for status in ("adequate", "needs-revision", "unknown"):
            value = semantic_review(self.plan, self.intake, status=status)
            before = canonical_bytes(value)
            self.assertEqual(core.validate_review(self.plan, self.intake, value), value)
            self.assertEqual(canonical_bytes(value), before)

    def test_stale_binding_and_changed_rubric_reject(self):
        for key in ("plan_sha256", "intake_sha256", "rubric_sha256"):
            value = actionable_review(self.plan, self.intake)
            value[key] = "b" * 64
            with self.subTest(binding=key), self.assertRaises(Stage3Error):
                core.validate_review(self.plan, self.intake, value)

    def test_negative_result_cannot_become_ready(self):
        value = actionable_review(
            self.plan, self.intake, status="not-adequate", kind="human-record"
        )
        self.assertEqual(
            core.plan_status(
                self.plan, self.intake, value, admission_scope="strict-selected"
            ),
            "needs-revision",
        )

    def test_nonmatching_status_content_and_malformed_shapes_reject(self):
        for field, payload in (
            ("revision", {"location": "/designs/0/procedure", "action": "Change it"}),
            ("missing_information", {"needed": "Data", "owner": "Analyst"}),
        ):
            value = actionable_review(self.plan, self.intake)
            value["findings"][0][field] = payload
            with self.subTest(field=field), self.assertRaises(Stage3Error):
                core.validate_review(self.plan, self.intake, value)
        for payload in (None, {}, [None]):
            value = actionable_review(self.plan, self.intake)
            value["findings"] = payload
            with self.subTest(payload=payload), self.assertRaises(Stage3Error):
                core.validate_review(self.plan, self.intake, value)

    def test_fixed_independent_callback_distinguishes_missing_control(self):
        def reviewer(*, plan, intake, rubric):
            status = (
                "needs-revision"
                if plan["designs"][0]["comparisons"]["description"] == "TODO"
                else "adequate"
            )
            value = actionable_review(plan, intake, status=status)
            self.assertEqual(value["rubric_sha256"], digest(rubric))
            return value

        good = core.review_plan(self.plan, self.intake, reviewer)
        bad_plan = copy.deepcopy(self.plan)
        bad_plan["designs"][0]["comparisons"]["description"] = "TODO"
        bad = core.review_plan(bad_plan, self.intake, reviewer)
        self.assertTrue(all(f["status"] == "adequate" for f in good["findings"]))
        self.assertTrue(all(f["status"] == "needs-revision" for f in bad["findings"]))
        self.assertEqual(core.plan_status(bad_plan, self.intake, bad), "needs-revision")
        self.assertTrue(
            all(
                f["revision"]["location"] == "/designs/0/comparisons/description"
                for f in bad["findings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
