"""Project-scoped readback of saved, explicitly synthetic workflow records."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN.parents[1] / "harness-ui"), str(PLUGIN / "cli")]
import test_stage3_workflow as workflow_fixture  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.decision import record_plan_decision  # noqa: E402
from stage3_plan.planner import draft_plan  # noqa: E402
from stage3_plan_review_readback import plan_review_identity, read_plan_review  # noqa: E402
from test_stage3_plan_decision import semantic_review  # noqa: E402


class ProjectStage3ReviewReadbackTests(unittest.TestCase):
    def setUp(self):
        # The existing workflow fixture substitutes admission only. Its authored
        # inputs and decision message cannot authenticate a human selection.
        self.fx = workflow_fixture.Stage3WorkflowTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(self.fx.native_call.assert_not_called)
        self.fx.attach_plan()
        self.view = self.view_for_saved_plan(self.fx.plan)

    def view_for_saved_plan(self, plan):
        checkpoint = self.fx.saved["checkpoint"]
        return {
            "project_ref": "project-synthetic-readback",
            "input_version": "synthetic-input-v1",
            "revision": 1,
            "brief_sha256": "a" * 64,
            "selection_request_sha256": "b" * 64,
            "selection_status": "recorded",
            "job": {
                "project_ref": "project-synthetic-readback",
                "request_sha256": "c" * 64,
                "outcome": "saved",
                "plan_manifest_sha256": checkpoint["bindings"]["plan"][
                    "manifest_sha256"
                ],
                "planning_status": checkpoint["status"]["planning_status"],
            },
            "plan": deepcopy(plan),
        }

    def binding(self, *, decision=None):
        return {
            "identity": plan_review_identity(self.view),
            "checkpoint": {
                "path": str(self.fx.current),
                "sha256": self.fx.saved["checkpoint_sha256"],
            },
            "decision": decision,
        }

    def attach_review(self, *, status="adequate"):
        review = semantic_review(self.fx.plan, self.fx.intake, status=status)
        ref = self.fx.file_ref("review.json", review)
        self.fx.transition("attach-review", ref)
        return ref

    def record_defer(self, review, *, host_verified=None):
        message = self.fx.root / "fixture-user-message.jsonl"
        words = "Fixture-only request to defer this synthetic displayed plan."
        message.write_bytes(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": words},
                }
            ).encode()
        )
        output = self.fx.root / f"synthetic-decision-{host_verified}"

        def fixture_verifier(binding):
            return {
                "kind": "Stage3HostDecisionVerification",
                "binding_sha256": digest(binding),
                "verified": host_verified,
                "evidence_ref": "fixture-only-verification",
            }

        with patch("stage3_plan.intake.admit_intake", return_value=self.fx.intake):
            record_plan_decision(
                self.fx.plan_dir,
                expected_manifest_sha256=self.view["job"]["plan_manifest_sha256"],
                review_path=review["path"],
                expected_review_sha256=review["sha256"],
                native_message=message,
                message_index=0,
                user_text=words,
                decision="defer",
                output_dir=output,
                planning_package="source",
                delivery_dir="delivery",
                expected_source_manifest_sha256=self.fx.plan["source_manifest_sha256"],
                verify_decision=fixture_verifier if host_verified is not None else None,
            )
        path = output / "decision.json"
        return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}

    def snapshot(self):
        return {
            p.relative_to(self.fx.root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in self.fx.root.rglob("*")
            if p.is_file()
        }

    def test_draft_bound_without_review_and_unlinked_read_are_distinct(self):
        before = self.snapshot()
        plain = read_plan_review(self.view)
        self.assertEqual(plain["readback_status"], "unlinked")
        bound = read_plan_review(self.view, trusted_binding=self.binding())
        self.assertEqual(bound["readback_status"], "bound")
        self.assertEqual(bound["planning_status"], "draft")
        self.assertEqual(bound["next_action"], "supply-semantic-review")
        self.assertIsNone(bound["review"])
        self.assertIsNone(bound["decision"])
        self.assertFalse(bound["execution_authorized"])
        self.assertEqual(self.snapshot(), before)

    def test_review_reports_missing_information_only_for_bound_plan(self):
        ref = self.attach_review(status="unknown")
        saved = read_plan_review(self.view, trusted_binding=self.binding())
        self.assertEqual(saved["planning_status"], "needs-information")
        self.assertEqual(saved["next_action"], "resolve-plan-blockers")
        self.assertEqual(saved["review"]["sha256"], ref["sha256"])
        self.assertGreater(saved["review"]["finding_counts"]["unknown"], 0)
        self.assertIsNone(saved["decision"])

    def test_awaiting_owner_and_saved_defer_stay_distinct_across_reopens(self):
        review = self.attach_review()
        waiting = read_plan_review(self.view, trusted_binding=self.binding())
        self.assertEqual(waiting["planning_status"], "ready-for-plan-review")
        self.assertEqual(waiting["next_action"], "record-version-bound-plan-decision")
        self.assertIsNone(waiting["decision"])
        decision = self.record_defer(review)
        binding = self.binding(decision=decision)
        before = self.snapshot()
        saved = read_plan_review(self.view, trusted_binding=binding)
        for _ in range(2):
            self.assertEqual(
                read_plan_review(
                    deepcopy(self.view), trusted_binding=deepcopy(binding)
                ),
                saved,
            )
        self.assertEqual(saved["decision"]["decision"], "defer")
        self.assertEqual(
            saved["decision"]["status"], "decision-recorded-pending-host-verification"
        )
        self.assertFalse(saved["decision"]["identity_authenticated"])
        self.assertIsNone(saved["next_action"])
        self.assertFalse(saved["execution_authorized"])
        self.assertNotIn("user_text", saved["decision"])
        self.assertEqual(self.snapshot(), before)

    def test_readback_uses_the_recorded_defer_status_after_host_verification(self):
        review = self.attach_review()
        for verified, status, decision_status in (
            (True, "draft", "host-verified"),
            (False, "ready-for-plan-review", "host-rejected"),
        ):
            with self.subTest(verified=verified):
                decision = self.record_defer(review, host_verified=verified)
                saved = read_plan_review(
                    self.view, trusted_binding=self.binding(decision=decision)
                )
                self.assertEqual(saved["planning_status"], status)
                self.assertEqual(saved["decision"]["status"], decision_status)
                self.assertEqual(saved["decision"]["identity_authenticated"], verified)
                self.assertIsNone(saved["next_action"])
                self.assertFalse(saved["execution_authorized"])

    def test_same_project_old_version_is_history_only(self):
        decision = self.record_defer(self.attach_review())
        previous = self.binding(decision=decision)
        old_view = deepcopy(self.view)
        v2 = deepcopy(self.fx.plan)
        v2["version"] = 2
        callback = Mock(
            return_value={
                "raw_response": canonical_bytes(v2),
                "provenance": {"kind": "synthetic"},
            }
        )
        callback.request_context = {"kind": "synthetic-readback-variation"}
        plan2 = self.fx.root / "plan2"
        with patch("stage3_plan.intake.admit_intake", return_value=self.fx.intake):
            saved = draft_plan(
                "source",
                "delivery",
                expected_manifest_sha256=v2["source_manifest_sha256"],
                output_dir=plan2,
                callback=callback,
                configuration={"model": "synthetic", "reasoning": "medium"},
                plan_id=v2["plan_id"],
                version=2,
            )
        self.fx.transition(
            "attach-plan",
            {
                "package": str(plan2),
                "manifest_sha256": saved["manifest"]["manifest_sha256"],
            },
        )
        self.view = self.view_for_saved_plan(v2)
        before = self.snapshot()
        with self.assertRaisesRegex(Stage3Error, "displayed project or plan"):
            read_plan_review(self.view, trusted_binding=previous)
        mismatched = dict(previous, identity=plan_review_identity(self.view))
        with self.assertRaisesRegex(Stage3Error, "checkpoint does not bind"):
            read_plan_review(self.view, trusted_binding=mismatched)
        current = read_plan_review(self.view, trusted_binding=self.binding())
        historical = read_plan_review(old_view, trusted_binding=previous)
        self.assertEqual(current["identity"]["plan_version"], 2)
        self.assertIsNone(current["review"])
        self.assertEqual(historical["identity"]["plan_version"], 1)
        self.assertEqual(historical["decision"]["decision"], "defer")
        self.assertEqual(callback.call_count, 1)
        self.assertEqual(self.snapshot(), before)

    def test_cross_project_and_stale_input_rejected_before_checkpoint_read(self):
        saved = self.binding()
        cross = deepcopy(self.view)
        cross["project_ref"] = cross["job"]["project_ref"] = "project-other"
        stale = dict(self.view, input_version="synthetic-input-v2")
        with patch("stage3_plan_review_readback.inspect_workflow") as opened:
            for view in (cross, stale):
                with (
                    self.subTest(view=view["project_ref"]),
                    self.assertRaisesRegex(Stage3Error, "displayed project or plan"),
                ):
                    read_plan_review(view, trusted_binding=saved)
            opened.assert_not_called()

    def test_mismatched_decision_archive_is_rejected(self):
        decision = self.record_defer(self.attach_review())
        archived = Path(decision["path"]).parent / "native-user-message.jsonl"
        archived.write_bytes(b"unrelated archived fixture")
        before = self.snapshot()
        with self.assertRaisesRegex(Stage3Error, "archived decision evidence differs"):
            read_plan_review(self.view, trusted_binding=self.binding(decision=decision))
        self.assertEqual(self.snapshot(), before)
