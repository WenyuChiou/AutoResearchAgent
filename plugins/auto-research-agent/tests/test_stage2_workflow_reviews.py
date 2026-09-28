"""Controlled review mechanics; these are not live scientific judgments."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_workflow.reviews import (
    prepare_review,
    reconcile_reviews,
    select_excluded_audit,
    validate_review,
)
from test_stage2_checker import assessment, finding


class Stage2WorkflowReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.packet = write_stage2_fixture(Path(temp.name), candidate_count=1)
        self.snapshot = "a" * 64

    def review(self, role):
        view = prepare_review(self.packet, "candidate-1", self.snapshot, role)
        return {
            "role": role,
            "view_sha256": canonical_hash(view),
            "snapshot_sha256": self.snapshot,
            "candidate_id": "candidate-1",
            "candidate_version": 1,
            "assessment": assessment(self.packet),
            "session_id": f"session-{role}",
            "native_artifact": {
                "path": f"native/{role}.jsonl",
                "sha256": ("b" if role == "challenger" else "c") * 64,
            },
            "initial": True,
            "assumptions": ["The two observations measure the same outcome."],
            "strongest_alternative": "A measurement difference could explain the observation.",
            "change_conditions": [
                "An incompatible measurement definition changes the choice."
            ],
        }

    def resolution(self, reviews):
        return {
            "review_sha256s": [canonical_hash(row) for row in reviews],
            "method": "synthesis",
            "reason": "Both reviews examine the same bounded sources.",
            "evidence_ids": ["ev-1"],
            "addressed": [],
            "assessment": assessment(self.packet),
            "substantive_disagreements": [],
            "changed_judgment_reason": None,
        }

    def test_initial_views_omit_peer_conclusions_and_keep_source_evidence(self):
        packet = {
            **self.packet,
            "assessments": [{"disposition": "reject"}],
            "scores": {"P6": 0},
        }
        view = prepare_review(packet, "candidate-1", self.snapshot, "challenger")
        self.assertNotIn("assessments", view)
        self.assertNotIn("scores", view)
        self.assertEqual(view["evidence"], self.packet["evidence"])
        view["candidate"]["question"] = "changed"
        self.assertNotEqual(
            view["candidate"]["question"], packet["candidates"][0]["question"]
        )

    def test_missing_review_and_matching_scores_are_not_automatic_approval(self):
        rows = [self.review("challenger")]
        pending = reconcile_reviews(self.packet, "candidate-1", self.snapshot, rows)
        self.assertEqual(pending["status"], "pending-review")
        self.assertFalse(pending["recommendation_eligible"])
        rows.append(self.review("feasibility"))
        pending = reconcile_reviews(self.packet, "candidate-1", self.snapshot, rows)
        self.assertEqual(pending["status"], "synthesis-required")
        self.assertFalse(pending["recommendation_eligible"])

    def test_snapshot_and_version_changes_reject_old_initial_review(self):
        row = self.review("challenger")
        view = prepare_review(self.packet, "candidate-1", "c" * 64, "challenger")
        with self.assertRaisesRegex(Stage2Error, "view-mismatch"):
            validate_review(row, view, self.packet)
        row["candidate_version"] = 2
        view = prepare_review(self.packet, "candidate-1", self.snapshot, "challenger")
        with self.assertRaisesRegex(Stage2Error, "candidate-mismatch"):
            validate_review(row, view, self.packet)

    def test_duplicate_sessions_and_failed_receipts_do_not_pass(self):
        rows = [self.review(role) for role in ("challenger", "feasibility")]
        rows[1]["session_id"] = rows[0]["session_id"]
        with self.assertRaisesRegex(Stage2Error, "independent-native-sessions"):
            reconcile_reviews(self.packet, "candidate-1", self.snapshot, rows)
        rows[1]["session_id"] = "separate"
        rows[1]["native_artifact"] = None
        with self.assertRaisesRegex(Stage2Error, "native-artifact-required"):
            reconcile_reviews(self.packet, "candidate-1", self.snapshot, rows)

    def test_standalone_review_rejects_view_from_other_packet(self):
        row = self.review("challenger")
        view = prepare_review(self.packet, "candidate-1", self.snapshot, "challenger")
        modified = copy.deepcopy(self.packet)
        modified["candidates"][0]["question"] = "A materially different question"
        row["assessment"]["packet_sha256"] = canonical_hash(modified)
        with self.assertRaisesRegex(Stage2Error, "view-packet-mismatch"):
            validate_review(row, view, modified)

    def test_material_disagreement_requires_bound_evidence_not_voting(self):
        rows = [self.review(role) for role in ("challenger", "feasibility")]
        rows[1]["assessment"]["checks"]["materials"] = finding(
            "unknown", None, evidence_ids=[]
        )
        rows[1]["assessment"]["disposition"] = "park"
        rows[1]["assessment"]["next_step"] = "Read the variable dictionary."
        pending = reconcile_reviews(self.packet, "candidate-1", self.snapshot, rows)
        self.assertEqual(pending["disagreements"], ["materials", "disposition"])
        resolution = self.resolution(rows)
        resolution["addressed"] = pending["disagreements"]
        resolution["method"] = "majority-vote"
        with self.assertRaisesRegex(Stage2Error, "resolution-method"):
            reconcile_reviews(
                self.packet, "candidate-1", self.snapshot, rows, resolution
            )
        resolution["method"] = "source-verification"
        with self.assertRaisesRegex(Stage2Error, "changed-judgment"):
            reconcile_reviews(
                self.packet, "candidate-1", self.snapshot, rows, resolution
            )
        resolution["changed_judgment_reason"] = (
            "The original feasibility reader missed ev-1's definition."
        )
        result = reconcile_reviews(
            self.packet, "candidate-1", self.snapshot, rows, resolution
        )
        self.assertTrue(result["recommendation_eligible"])
        self.assertFalse(result["native_execution_verified"])

    def test_rehashed_foreign_evidence_and_unknown_prerequisite_fail_closed(self):
        rows = [self.review(role) for role in ("challenger", "feasibility")]
        resolution = self.resolution(rows)
        resolution["evidence_ids"] = ["foreign-evidence"]
        with self.assertRaisesRegex(Stage2Error, "unknown evidence"):
            reconcile_reviews(
                self.packet, "candidate-1", self.snapshot, rows, resolution
            )
        resolution = self.resolution(rows)
        resolution["assessment"]["checks"]["materials"] = finding(
            "unknown", None, evidence_ids=[]
        )
        with self.assertRaisesRegex(Stage2Error, "recommendation-blocked"):
            reconcile_reviews(
                self.packet, "candidate-1", self.snapshot, rows, resolution
            )

    def test_substantive_disagreement_must_be_addressed_even_if_scores_match(self):
        rows = [self.review(role) for role in ("challenger", "feasibility")]
        resolution = self.resolution(rows)
        resolution["substantive_disagreements"] = [
            "Competing mechanism produces identical output"
        ]
        with self.assertRaisesRegex(Stage2Error, "unresolved-disagreement"):
            reconcile_reviews(
                self.packet, "candidate-1", self.snapshot, rows, resolution
            )

    def test_excluded_audit_keeps_borderline_plus_saved_seed_draw(self):
        rows = [
            {
                "candidate_id": f"D{i}",
                "candidate_version": 1,
                "included": i == 0,
                "distance": i,
                "reason": "Screening rationale",
            }
            for i in range(5)
        ]
        result = select_excluded_audit(rows, "saved-seed")
        self.assertEqual(
            result, select_excluded_audit(list(reversed(rows)), "saved-seed")
        )
        self.assertEqual(result["selected"][0]["candidate_id"], "D1")
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(result["excluded_count"], 4)
        for n in (0, 1, 2):
            small = copy.deepcopy(rows[1 : n + 1])
            self.assertEqual(len(select_excluded_audit(small, "s")["selected"]), n)
        with self.assertRaisesRegex(Stage2Error, "saved-seed"):
            select_excluded_audit(rows, "")


if __name__ == "__main__":
    unittest.main()
