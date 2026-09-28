"""Contract tests for the Stage 2 orchestration module."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(PLUGIN / "tests"))

from stage2_workflow.orchestration import (  # noqa: E402
    make_followup,
    prepare_review_batch,
    reconcile_batch,
)
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment, finding  # noqa: E402


class Stage2OrchestrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.packet = write_stage2_fixture(Path(temp.name), candidate_count=4)
        self.snapshot = "a" * 64
        self.screening = [
            {
                "candidate_id": f"candidate-{index}",
                "candidate_version": 1,
                "included": index == 1,
                "distance": index,
                "reason": f"Original screening rationale {index}",
            }
            for index in range(1, 5)
        ]

    def batch(self):
        return prepare_review_batch(
            self.packet, self.snapshot, self.screening, "saved-seed"
        )

    def review(self, candidate_id, role, assessment_value=None):
        view = prepare_review(self.packet, candidate_id, self.snapshot, role)
        candidate_version = view["candidate"]["version"]
        value = assessment_value or assessment(
            self.packet, event_id=f"check-{candidate_id}"
        )
        if assessment_value is None:
            value["candidate_id"] = candidate_id
            value["candidate_version"] = candidate_version
        return {
            "role": role,
            "view_sha256": canonical_hash(view),
            "snapshot_sha256": self.snapshot,
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "assessment": value,
            "session_id": f"session-{candidate_id}-{role}",
            "native_artifact": {
                "path": f"native/{candidate_id}-{role}.jsonl",
                "sha256": canonical_hash([candidate_id, role]),
            },
            "initial": True,
            "assumptions": ["The bounded observations are comparable."],
            "strongest_alternative": "Measurement mismatch could explain the result.",
            "change_conditions": ["A source-defined mismatch changes the choice."],
        }

    @staticmethod
    def envelope(review, status="complete", error=None):
        return {
            "candidate_id": review["candidate_id"],
            "candidate_version": review["candidate_version"],
            "role": review["role"],
            "status": status,
            "review": review if status == "complete" else None,
            "error": error,
        }

    @staticmethod
    def resolutions(rows=None, next_step="Resolve pending review evidence."):
        return {"candidate_resolutions": rows or [], "next_step": next_step}

    @staticmethod
    def resolution(reviews, resolved_assessment):
        return {
            "review_sha256s": [canonical_hash(row) for row in reviews],
            "method": "synthesis",
            "reason": "The independent reviews support the bounded synthesis.",
            "evidence_ids": ["ev-1"],
            "addressed": [],
            "assessment": resolved_assessment,
            "substantive_disagreements": [],
            "changed_judgment_reason": None,
        }

    def test_batch_is_order_invariant_and_preserves_all_screening_rationales(self):
        first = self.batch()
        second = prepare_review_batch(
            self.packet, self.snapshot, list(reversed(self.screening)), "saved-seed"
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [row["reason"] for row in first["screening"]],
            [f"Original screening rationale {index}" for index in range(1, 5)],
        )
        self.assertEqual(first["main_candidate_count"], 1)
        self.assertEqual(first["audited_excluded_count"], 2)
        self.assertEqual(len(first["assignments"]), 6)
        self.assertEqual(
            {row["audit_reason"] for row in first["audit"]["selected"]},
            {"nearest-to-shortlist", "seeded-other"},
        )

    def test_screening_must_cover_exact_current_ids_and_versions(self):
        with self.assertRaisesRegex(Stage2Error, "current-candidates-mismatch"):
            prepare_review_batch(
                self.packet, self.snapshot, self.screening[:-1], "saved-seed"
            )
        stale = copy.deepcopy(self.screening)
        stale[0]["candidate_version"] = 2
        with self.assertRaisesRegex(Stage2Error, "stale-candidate-version"):
            prepare_review_batch(self.packet, self.snapshot, stale, "saved-seed")
        with self.assertRaisesRegex(Stage2Error, "snapshot-sha256"):
            prepare_review_batch(self.packet, "not-a-hash", self.screening, "seed")

    def test_tampered_batch_and_different_candidate_version_are_rejected(self):
        batch = self.batch()
        tampered = copy.deepcopy(batch)
        tampered["screening"][0]["reason"] = "Rewritten rationale"
        with self.assertRaisesRegex(Stage2Error, "batch-hash-mismatch"):
            reconcile_batch(
                self.packet, tampered, [], self.resolutions(next_step="Rebuild batch.")
            )

        revised_packet = copy.deepcopy(self.packet)
        revised = copy.deepcopy(revised_packet["candidates"][0])
        revised["version"] = 2
        revised["parent_version"] = 1
        revised_packet["candidates"].append(revised)
        with self.assertRaisesRegex(Stage2Error, "stale-candidate-version"):
            reconcile_batch(
                revised_packet, batch, [], self.resolutions(next_step="Re-screen.")
            )

    def test_missing_and_failed_reviews_remain_pending_with_separate_counts(self):
        batch = self.batch()
        target = batch["assignments"][0]["candidate_id"]
        complete = self.review(target, "challenger")
        failed = self.review(target, "feasibility")
        other = batch["assignments"][2]
        unavailable = self.review(other["candidate_id"], other["role"])
        result = reconcile_batch(
            self.packet,
            batch,
            [
                self.envelope(complete),
                self.envelope(failed, "failed", "native session exited"),
                self.envelope(
                    unavailable, "unavailable", "configured reviewer was unavailable"
                ),
            ],
            self.resolutions(),
        )
        row = next(x for x in result["candidates"] if x["candidate_id"] == target)
        self.assertEqual(row["reconciliation"]["status"], "pending-review")
        self.assertEqual(row["result_states"], {"feasibility": "failed"})
        self.assertEqual(result["candidate_counts"], {"main": 1, "audit": 2})
        self.assertEqual(result["review_counts"]["complete"], 1)
        self.assertEqual(result["review_counts"]["failed"], 1)
        self.assertEqual(result["review_counts"]["unavailable"], 1)
        self.assertEqual(result["review_counts"]["missing"], 3)
        self.assertFalse(result["local_reconciliation_ready"])
        self.assertFalse(result["actual_execution_attested"])

    def test_foreign_and_duplicate_candidate_role_results_are_rejected(self):
        batch = self.batch()
        target = batch["assignments"][0]["candidate_id"]
        row = self.envelope(self.review(target, "challenger"))
        with self.assertRaisesRegex(Stage2Error, "duplicate-review-result"):
            reconcile_batch(
                self.packet, batch, [row, copy.deepcopy(row)], self.resolutions()
            )
        foreign = copy.deepcopy(row)
        foreign["candidate_id"] = "foreign"
        foreign["review"]["candidate_id"] = "foreign"
        with self.assertRaisesRegex(Stage2Error, "foreign-review-result"):
            reconcile_batch(self.packet, batch, [foreign], self.resolutions())

    def test_matching_reviews_still_require_explicit_synthesis(self):
        packet = copy.deepcopy(self.packet)
        screening = copy.deepcopy(self.screening)
        for row in screening:
            row["included"] = row["candidate_id"] == "candidate-1"
        batch = prepare_review_batch(packet, self.snapshot, screening, "seed")
        reviews = [
            self.review("candidate-1", role) for role in ("challenger", "feasibility")
        ]
        pending = reconcile_batch(
            packet,
            batch,
            [self.envelope(row) for row in reviews],
            self.resolutions(),
        )
        first = next(
            x for x in pending["candidates"] if x["candidate_id"] == "candidate-1"
        )
        self.assertEqual(first["reconciliation"]["status"], "synthesis-required")
        self.assertFalse(first["recommendation_eligible"])

    def test_unknown_key_prerequisite_stays_blocked_after_synthesis(self):
        batch = self.batch()
        target = "candidate-1"
        parked = assessment(self.packet)
        parked["checks"]["materials"] = finding(
            "unknown", None, evidence_ids=[], blocking=True
        )
        parked["disposition"] = "park"
        parked["next_step"] = "Verify access to the required material."
        reviews = [
            self.review(target, role, copy.deepcopy(parked))
            for role in ("challenger", "feasibility")
        ]
        resolution = self.resolution(reviews, copy.deepcopy(parked))
        result = reconcile_batch(
            self.packet,
            batch,
            [self.envelope(row) for row in reviews],
            self.resolutions(
                [{"candidate_id": target, "resolution": resolution}],
                next_step="Verify materials and finish the remaining reviews.",
            ),
        )
        row = next(x for x in result["candidates"] if x["candidate_id"] == target)
        self.assertTrue(row["key_prerequisite_unknown"])
        self.assertFalse(row["recommendation_eligible"])

    def test_zero_candidates_and_zero_recommendations_require_explanation(self):
        with tempfile.TemporaryDirectory() as temp:
            packet = write_stage2_fixture(Path(temp), candidate_count=0)
        batch = prepare_review_batch(packet, self.snapshot, [], "seed")
        with self.assertRaisesRegex(Stage2Error, "zero-recommendation-next-step"):
            reconcile_batch(packet, batch, [], self.resolutions(next_step=None))
        result = reconcile_batch(
            packet,
            batch,
            [],
            self.resolutions(
                next_step="No candidates exist; return to bounded ideation."
            ),
        )
        self.assertEqual(result["candidate_counts"], {"main": 0, "audit": 0})
        self.assertEqual(result["recommendations"], [])
        self.assertTrue(result["local_reconciliation_ready"])
        self.assertNotIn("score", result)
        self.assertNotIn("confidence", result)

    def decision(self, kind="scientific"):
        return {
            "kind": kind,
            "description": "Whether material access permits this candidate to proceed.",
            "material": True,
            "changeable": True,
        }

    def attempt(
        self,
        *,
        status="empty",
        evidence_refs=None,
        version=1,
        action="Repeat catalog lookup",
    ):
        failure = None
        if status in {"failed", "interrupted", "unavailable"}:
            failure = "The bounded lookup did not complete."
        return {
            "attempt_id": f"attempt-{status}-{version}",
            "candidate_id": "candidate-1",
            "candidate_version": version,
            "snapshot_sha256": self.snapshot,
            "question": "Can the required material be accessed?",
            "decision_at_risk": self.decision(),
            "needed_evidence": ["A source-backed access statement"],
            "action": action,
            "status": status,
            "evidence_refs": evidence_refs or [],
            "failure": failure,
        }

    def followup(self, attempts, next_action="Repeat catalog lookup", decision=None):
        return make_followup(
            self.packet,
            self.snapshot,
            "candidate-1",
            "Can the required material be accessed?",
            decision or self.decision(),
            ["A source-backed access statement"],
            attempts,
            next_action,
            {"path": "portable-harness/policies/agent-budget.yaml", "sha256": "f" * 64},
        )

    def test_repeated_unchanged_lookup_stops_but_new_action_or_evidence_continues(self):
        stopped = self.followup([self.attempt()])
        self.assertTrue(stopped["stop"])
        self.assertFalse(stopped["new_evidence_available"])
        changed = self.followup(
            [self.attempt()], next_action="Read the repository data dictionary"
        )
        self.assertFalse(changed["stop"])
        self.assertTrue(changed["feasible_new_action"])
        evidenced = self.followup(
            [self.attempt(status="success", evidence_refs=["ev-1"])],
            next_action="Incorporate the new source in a revised snapshot",
        )
        self.assertFalse(evidenced["stop"])
        self.assertTrue(evidenced["new_evidence_available"])
        self.assertFalse(evidenced["model_or_tool_success_proves_scientific_claim"])

    def test_historical_success_cannot_keep_unchanged_failed_lookup_alive(self):
        attempts = [self.attempt(status="success", evidence_refs=["ev-1"])]
        for index in range(3):
            failed = self.attempt(status="failed")
            failed["attempt_id"] += str(index)
            attempts.append(failed)
        result = self.followup(attempts)
        self.assertTrue(result["stop"])
        self.assertFalse(result["new_evidence_available"])
        self.assertFalse(result["feasible_new_action"])

    def test_old_candidate_version_attempt_is_not_equivalent_and_scope_change_waits_for_human(
        self,
    ):
        revised = copy.deepcopy(self.packet["candidates"][0])
        revised["version"] = 2
        revised["parent_version"] = 1
        self.packet["candidates"].append(revised)
        old = self.attempt(version=1)
        result = self.followup(
            [old],
            next_action="Verify the revised candidate's material requirement",
            decision=self.decision("scope"),
        )
        self.assertEqual(result["candidate_version"], 2)
        self.assertEqual(result["equivalent_prior_attempts"], 0)
        self.assertFalse(result["stop"])
        self.assertTrue(result["human_decision_required"])
        self.assertNotIn("retry_budget", result)


if __name__ == "__main__":
    unittest.main()
