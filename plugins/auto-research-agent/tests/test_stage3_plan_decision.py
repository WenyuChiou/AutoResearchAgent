"""Synthetic semantic/confirmation tests do not authenticate humans."""

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.__main__ import main  # noqa: E402
from stage3_plan.decision import record_plan_decision, revision_impact  # noqa: E402
from stage3_plan.planner import draft_plan  # noqa: E402
from stage3_plan.report import render_plan  # noqa: E402
from stage3_plan.review import RUBRIC, plan_status, review_plan, validate_review  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


def semantic_review(plan, intake, *, status="adequate", kind="human-record"):
    return {
        "kind": "Stage3SemanticReview",
        "plan_sha256": digest(plan),
        "intake_sha256": digest(intake),
        "rubric_sha256": digest(RUBRIC),
        "reviewer": {
            "actor": "synthetic-recorded-reviewer",
            "kind": kind,
            "identity_authenticated": False,
            "evidence_ref": "synthetic-review-receipt",
        },
        "findings": [
            {
                "question_ref": q["question_ref"],
                "axis": axis,
                "status": status,
                "reason": "Synthetic assessment only; no scientific quality claim.",
                "plan_locations": [f"/questions/{index}", "/designs/0"],
            }
            for index, q in enumerate(plan["questions"])
            for axis in RUBRIC["axes"]
        ],
        "execution_authorized": False,
    }


class Stage3DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS temporary roots may use the system /var symlink; fixtures use physical paths.
        self.root = Path(self.temp.name).resolve()
        self.plan = make_plan(question_count=2)
        self.intake = make_intake(self.plan)
        # Full argument is only needed for saved Markdown; these are synthetic.
        argument = self.intake["scientific_arguments"][0]["argument"]
        argument.update(
            motivation={"text": "Synthetic importance", "status": "proposal"},
            current_state=[{"text": "Synthetic precedent", "status": "unknown"}],
            gaps=[{"gap_id": "gap-1", "text": "Synthetic gap"}],
            challenges=[],
            contribution_claims=[],
        )
        self.callback = Mock(
            request_context={"kind": "synthetic-injected-callback"},
            return_value={
                "raw_response": canonical_bytes(self.plan),
                "provenance": {"kind": "synthetic"},
            },
        )
        self.output = self.root / "plan"
        # Mock strict admission only; this fixture never authenticates a person or delivery.
        with patch("stage3_plan.intake.admit_intake", return_value=self.intake):
            self.saved = draft_plan(
                "synthetic-package",
                "synthetic-delivery",
                expected_manifest_sha256=self.plan["source_manifest_sha256"],
                output_dir=self.output,
                callback=self.callback,
                configuration={"model": "synthetic-model", "reasoning": "medium"},
                plan_id=self.plan["plan_id"],
            )
        self.review = semantic_review(self.plan, self.intake)
        self.review_path = self.root / "review.json"
        self.review_path.write_bytes(canonical_bytes(self.review))
        self.user_text = (
            "Confirm this displayed synthetic plan version 1 for planning only."
        )
        self.message = self.root / "user.jsonl"
        self.message.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": self.user_text},
                }
            ),
            encoding="utf-8",
        )

    def decide(self, **overrides):
        args = dict(
            expected_manifest_sha256=self.saved["manifest"]["manifest_sha256"],
            review_path=self.review_path,
            expected_review_sha256=hashlib.sha256(
                self.review_path.read_bytes()
            ).hexdigest(),
            native_message=self.message,
            message_index=0,
            user_text=self.user_text,
            decision="confirm",
            output_dir=self.root / "decision",
            current_intake=self.intake,
        )
        args.update(overrides)
        current = args.pop("current_intake")
        with patch("stage3_plan.intake.admit_intake", return_value=current):
            return record_plan_decision(
                self.output,
                planning_package="synthetic-package",
                delivery_dir="synthetic-delivery",
                expected_source_manifest_sha256=self.plan["source_manifest_sha256"],
                **args,
            )

    def test_structural_coverage_does_not_imply_semantic_acceptance(self):
        self.assertEqual(plan_status(self.plan, self.intake), "draft")
        reviewer = Mock(
            return_value=semantic_review(
                self.plan, self.intake, status="needs-revision"
            )
        )
        result = review_plan(self.plan, self.intake, reviewer)
        self.assertEqual(reviewer.call_count, 1)
        self.assertEqual(plan_status(self.plan, self.intake, result), "needs-revision")
        synthetic = semantic_review(self.plan, self.intake, kind="synthetic")
        self.assertEqual(plan_status(self.plan, self.intake, synthetic), "draft")

    def test_confirmation_records_exact_user_text_and_never_executes(self):
        result = self.decide()
        self.assertEqual(
            result["decision_status"], "decision-recorded-pending-host-verification"
        )
        self.assertNotEqual(result["plan_status"], "plan-confirmed")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["identity_authenticated"])
        self.assertEqual(result["user_text"], self.user_text)
        self.assertEqual(
            (self.root / "decision/native-user-message.jsonl").read_bytes(),
            self.message.read_bytes(),
        )
        self.assertEqual(self.callback.call_count, 1)

    def test_stale_plan_review_selection_and_misquoted_user_fail(self):
        with self.assertRaises(Stage3Error):
            self.decide(expected_manifest_sha256="b" * 64)
        with self.assertRaises(Stage3Error):
            self.decide(expected_review_sha256="b" * 64)
        with self.assertRaises(Stage3Error):
            self.decide(user_text="An agent invented an approval.")
        changed = copy.deepcopy(self.intake)
        changed["questions"][0]["text"] = "A different scientific question."
        with self.assertRaises(Stage3Error):
            self.decide(current_intake=changed)
        changed_plan = copy.deepcopy(self.plan)
        changed_plan["version"] = 2
        with self.assertRaises(Stage3Error):
            validate_review(changed_plan, self.intake, self.review)

    def test_rejecting_or_old_version_text_never_self_confirms(self):
        for index, text in enumerate(
            (
                "Do not confirm this plan; defer it.",
                "Confirm version 0, not the current version 1.",
            )
        ):
            self.message.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": text},
                    }
                ),
                encoding="utf-8",
            )
            result = self.decide(user_text=text, output_dir=self.root / str(index))
            self.assertNotEqual(result["plan_status"], "plan-confirmed")
            self.assertFalse(result["semantic_authorization_verified"])

    def test_trusted_host_verification_binds_the_actual_displayed_plan_and_intent(self):
        def verifier(binding):
            self.assertEqual(binding["version"], self.plan["version"])
            self.assertEqual(binding["user_text"], self.user_text)
            self.assertEqual(
                binding["plan_manifest_sha256"],
                self.saved["manifest"]["manifest_sha256"],
            )
            return {
                "kind": "Stage3HostDecisionVerification",
                "binding_sha256": digest(binding),
                "verified": True,
                "evidence_ref": "synthetic-trusted-host-test-seam",
            }

        result = self.decide(verify_decision=verifier)
        self.assertEqual(result["plan_status"], "plan-confirmed")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["semantic_authorization_verified"])
        with self.assertRaises(Stage3Error):
            self.decide(
                verify_decision=lambda binding: {
                    "kind": "Stage3HostDecisionVerification",
                    "binding_sha256": "b" * 64,
                    "verified": True,
                    "evidence_ref": "wrong-version",
                }
            )

    def test_explicit_synthetic_intake_cannot_be_confirmed(self):
        from stage3_plan.planner import draft_synthetic_plan

        self.output = self.root / "synthetic-plan"
        self.saved = draft_synthetic_plan(
            self.intake,
            self.output,
            self.callback,
            configuration={"model": "synthetic-model", "reasoning": "medium"},
            plan_id=self.plan["plan_id"],
        )
        with self.assertRaises(Stage3Error):
            self.decide()

    def test_incomplete_or_unknown_semantic_review_blocks_confirmation(self):
        incomplete = copy.deepcopy(self.review)
        incomplete["findings"].pop()
        with self.assertRaises(Stage3Error):
            validate_review(self.plan, self.intake, incomplete)
        incomplete = semantic_review(self.plan, self.intake, status="unknown")
        self.review_path.write_bytes(canonical_bytes(incomplete))
        with self.assertRaises(Stage3Error):
            self.decide()
        uncertain = copy.deepcopy(self.plan)
        uncertain["question_plans"][0]["resource_uses"][0]["status"] = "unknown"
        self.assertEqual(plan_status(uncertain, self.intake), "needs-information")

    def test_render_inspect_saved_evidence_without_generation(self):
        text = render_plan(
            self.output,
            expected_manifest_sha256=self.saved["manifest"]["manifest_sha256"],
        )
        self.assertIn(self.plan["questions"][0]["text"], text)
        self.assertIn("No result has been observed", text)
        self.assertIn("Not performed", text)
        self.assertEqual(self.callback.call_count, 1)
        for command in ("inspect", "check", "render"):
            with redirect_stdout(io.StringIO()) as captured:
                status = main(
                    [
                        command,
                        "--package",
                        str(self.output),
                        "--expected-manifest-sha256",
                        self.saved["manifest"]["manifest_sha256"],
                    ]
                )
            self.assertEqual(status, 0)
            self.assertIn("false", captured.getvalue())
        self.assertEqual(self.callback.call_count, 1)

    def test_dependency_sha_bound_and_revision_keeps_unaffected_evidence(self):
        changed = copy.deepcopy(self.intake)
        changed["resources"][0]["name"] = "Changed access description"
        result = revision_impact(self.plan, self.intake, changed)
        self.assertEqual(result["changed_resources"], ["resource-1"])
        self.assertEqual(
            set(result["affected_questions"]),
            {q["question_ref"] for q in self.plan["questions"]},
        )
        self.assertTrue(result["confirmation_invalidated"])
        self.assertTrue(result["unaffected_evidence_retained"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(
            revision_impact(self.plan, self.intake, self.intake)["affected_questions"],
            [],
        )
        changed = copy.deepcopy(self.intake)
        changed["scientific_arguments"][0]["argument"]["motivation"]["text"] = (
            "Changed scientific premise"
        )
        impact = revision_impact(self.plan, self.intake, changed)
        self.assertTrue(impact["return_to_stage2"])
        self.assertTrue(impact["affected_results"])


if __name__ == "__main__":
    unittest.main()
