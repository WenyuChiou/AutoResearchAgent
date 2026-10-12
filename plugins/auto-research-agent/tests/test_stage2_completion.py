"""Real synthetic delivery/replay fixtures; no native calls or science claims."""
# ruff: noqa: E402 -- use repository CLI and existing synthetic fixtures.

import copy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

import test_stage2_content_delivery as content_fixtures
import test_stage2_delivery as delivery_fixtures
import test_stage2_topic_tables_integration as topic_fixtures
from test_stage2_checker import assessment
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.evaluation_v3 import merge_judgments_v3
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.completion import inspect_completion
from stage2_workflow.delivery import build_delivery, inspect_delivery
from stage2_workflow.evaluation_delivery import build_evaluated_delivery
from stage2_workflow.orchestration import prepare_review_batch


class Stage2CompletionTests(unittest.TestCase):
    def setUp(self):
        upstream = topic_fixtures.Stage2TopicTablesIntegrationTests()
        upstream.setUp()
        self.addCleanup(upstream.doCleanups)
        self.root, self.sources = upstream.root, upstream.sources
        self.packet, _ = upstream.prepared()
        self.packet["candidates"][0]["candidate_id"] = "candidate-1"
        for row in self.packet["research_tables"]["direction_resources"]:
            row["candidate_id"] = "candidate-1"

    def deliver(self, *, disposition="park", missing_review=False):
        fixture = delivery_fixtures.Stage2DeliveryTests()
        fixture.packet = self.packet
        path = self.root / "completion-packet.json"
        path.write_text(json.dumps(self.packet), encoding="utf-8")
        workflow = self.root / "completion-workflow"
        initialize_workflow(
            path,
            self.sources,
            workflow,
            {},
            {},
            expected_packet_sha256=canonical_hash(self.packet),
        )
        state = inspect_workflow(workflow)
        fixture.snapshot = state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        screening = [
            {
                "candidate_id": "candidate-1",
                "candidate_version": 1,
                "included": True,
                "distance": 0,
                "reason": "Synthetic screening.",
            }
        ]
        batch = prepare_review_batch(self.packet, fixture.snapshot, screening, "seed")
        check = assessment(self.packet, disposition=disposition)
        evidence = self.packet["evidence"][0]["evidence_id"]
        for row in check["checks"].values():
            row["evidence_ids"] = [evidence]
        reviews, resolutions = fixture._complete_inputs(check)
        resolutions["candidate_resolutions"][0]["resolution"]["evidence_ids"] = [
            evidence
        ]
        if missing_review:
            reviews, resolutions = (
                [],
                {
                    "candidate_resolutions": [],
                    "next_step": "Complete both independent reviewers.",
                },
            )
        self.delivery = self.root / "completion-delivery"
        self.manifest = build_delivery(
            workflow, batch, reviews, resolutions, self.delivery, state["head_sha256"]
        )
        self.inspected = inspect_delivery(
            self.delivery, self.manifest["manifest_sha256"]
        )
        return self.inspect()

    def inspect(self, evaluation=None):
        options = (
            {}
            if evaluation is None
            else {
                "evaluation_dir": self.root / "completion-evaluation",
                "expected_evaluation_manifest_sha256": evaluation["manifest_sha256"],
            }
        )
        return inspect_completion(
            self.delivery, self.manifest["manifest_sha256"], **options
        )

    def evaluated(self, *, selection=None, bundle=None, head=None):
        selection = selection or self.inspected["selection"]
        helper = content_fixtures.ContentDeliveryTests()
        bundle = bundle or helper.make_bundle(selection)
        snapshots = [
            {**row, "path": "sources/" + row["path"]}
            for row in selection["evaluation_packet"]["sources"]
        ]
        return build_evaluated_delivery(
            selection,
            snapshots,
            self.delivery / "checker" / "sources",
            bundle,
            self.root / "completion-evaluation",
            expected_bundle_sha256=canonical_hash(bundle),
            event_head=head or self.manifest["delivery_checker_event_head_sha256"],
            stored_packet_sha256=self.inspected["checker"]["manifest"][
                "stored_packet_sha256"
            ],
        )

    def test_absent_assessment_preserves_ready_zero_recommendation(self):
        result = self.deliver()
        self.assertTrue(result["research_delivery_ready"])
        self.assertEqual(self.inspected["selection"]["recommendations"], [])
        self.assertEqual(result["assessment_status"], "missing")
        self.assertFalse(result["stage2_complete"])
        self.assertEqual(result["current_packet_sha256"], canonical_hash(self.packet))
        json.dumps(result)

    def test_zero_scores_complete_without_authorizing_selection_or_formal_run(self):
        self.deliver()
        bundle = content_fixtures.ContentDeliveryTests().make_bundle(
            self.inspected["selection"]
        )
        for judgment in bundle["judgments"].values():
            for row in judgment["criteria"]:
                row["score"] = 0
        bundle["merged"] = merge_judgments_v3(
            bundle["judgments"]["R1"],
            bundle["judgments"]["R2"],
            bundle["content_view"],
            bundle["action_views"]["R1"],
            self.inspected["selection"]["evaluation_packet"],
        )
        result = self.inspect(self.evaluated(bundle=bundle))
        self.assertTrue(result["stage2_complete"])
        self.assertEqual(result["assessment_status"], "completed")
        self.assertEqual(
            {r["score"] for r in result["assessment_dimensions"].values()}, {0}
        )
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["human_selection"], "pending")
        self.assertFalse(result["stage3_execution_authorized"])
        self.assertFalse(result["formal_ready"])

    def test_missing_matrix_stays_inspectable_draft(self):
        self.packet["research_tables"] = None
        result = self.deliver()
        self.assertFalse(result["research_delivery_ready"])
        self.assertIn("topic-matrix", {r["check_id"] for r in result["blockers"]})

    def test_official_workflow_evaluation_binding_is_accepted(self):
        self.deliver()
        result = self.inspect(
            self.evaluated(head=self.manifest["workflow_head_sha256"])
        )
        self.assertTrue(result["stage2_complete"])

    def test_missing_necessary_resource_blocks_recommendation(self):
        result = self.deliver(disposition="recommend")
        self.assertFalse(result["research_delivery_ready"])
        self.assertIn(
            "candidate-1:v1:required-access",
            {r["check_id"] for r in result["blockers"]},
        )

    def test_absent_current_direction_reviews_are_not_agreement(self):
        result = self.deliver(missing_review=True)
        self.assertFalse(result["research_delivery_ready"])
        self.assertIn(
            "local-reconciliation", {r["check_id"] for r in result["blockers"]}
        )

    def test_absent_r2_retains_unknown_even_with_forged_complete_manifest_flag(self):
        self.deliver()
        bundle = content_fixtures.ContentDeliveryTests().make_bundle(
            self.inspected["selection"]
        )
        bundle["judgments"].pop("R2")
        bundle["action_views"].pop("R2")
        bundle.update(status="failed", merged=None, failure="R2 unavailable")
        manifest = self.evaluated(bundle=bundle)
        manifest["evaluation_status"] = "completed"
        manifest.pop("manifest_sha256")
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (self.root / "completion-evaluation/evaluation_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        result = self.inspect(manifest)
        self.assertEqual(result["assessment_status"], "failed")
        self.assertFalse(result["stage2_complete"])
        self.assertTrue(
            all(r["score"] is None for r in result["assessment_dimensions"].values())
        )

    def test_pending_audit_and_necessary_null_remain_visible(self):
        self.deliver()
        bundle = content_fixtures.ContentDeliveryTests().make_bundle(
            self.inspected["selection"]
        )
        for judgment in bundle["judgments"].values():
            judgment["criteria"][0].update(
                status="unknown", score=None, unknown_reason="evidence-unavailable"
            )
            judgment["central_evidence_inaccessible"] = True
        bundle.update(status="audit-required", merged=None)
        result = self.inspect(self.evaluated(bundle=bundle))
        self.assertEqual(result["assessment_status"], "audit-required")
        self.assertEqual(result["audit_status"], "required")
        self.assertIsNone(result["assessment_dimensions"]["P4"]["score"])
        self.assertFalse(result["stage2_complete"])
        self.assertFalse(result["formal_ready"])

    def test_foreign_scientific_content_is_rejected_even_after_valid_evaluation(self):
        self.deliver()
        selection = copy.deepcopy(self.inspected["selection"])
        selection["evaluation_packet"]["comparison"] += " Foreign scientific content."
        digest = canonical_hash(selection["evaluation_packet"])
        selection["packet_sha256"] = digest
        selection["action_record"]["packet_sha256"] = digest
        selection["current_options"][0]["assessment"]["packet_sha256"] = digest
        with self.assertRaisesRegex(
            Stage2Error, "completion-evaluation-delivery-binding"
        ):
            self.inspect(self.evaluated(selection=selection))

    def test_stale_checker_receipt_is_rejected(self):
        self.deliver()
        with self.assertRaisesRegex(
            Stage2Error, "completion-evaluation-delivery-binding"
        ):
            self.inspect(self.evaluated(head="b" * 64))

    def test_source_tamper_and_external_receipt_mismatch_reject(self):
        self.deliver()
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            inspect_completion(self.delivery, "b" * 64)
        source = self.inspected["checker"]["manifest"]["source_snapshots"][0][
            "stored_path"
        ]
        (self.delivery / "checker" / source).write_bytes(b"tampered")
        with self.assertRaises(Stage2Error):
            self.inspect()

    def test_evaluation_tamper_and_missing_external_receipt_reject(self):
        self.deliver()
        manifest = self.evaluated()
        with self.assertRaisesRegex(Stage2Error, "evaluation-receipt-required"):
            inspect_completion(
                self.delivery,
                self.manifest["manifest_sha256"],
                evaluation_dir=self.root / "completion-evaluation",
            )
        (self.root / "completion-evaluation/selection.html").write_bytes(b"tampered")
        with self.assertRaisesRegex(Stage2Error, "artifact-changed"):
            self.inspect(manifest)


if __name__ == "__main__":
    unittest.main()
