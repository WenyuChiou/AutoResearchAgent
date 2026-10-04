"""Structured, evidence-bound research follow-up task tests."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error, canonical_hash
from stage2_live.controller import (
    _material_followup_policy,
    _research_followup_policy,
)
from stage2_live.research_followups import (
    build_research_followup_task,
    validate_research_followup_task,
)

POLICY = {
    "kind": "Stage2ResearchFollowupPolicy",
    "schema_version": "1.0.0",
    "canonical_policy_ref": "stage2-v3-existing-policy:test",
    "probe_boundary": {
        "max_queries_per_family": 2,
        "stop_after_repeated_no_progress": True,
    },
}


def packet():
    return {
        "schema_version": "2.1.0",
        "brief": {
            "kind": "ResearchBrief",
            "schema_version": "1.0.0",
            "original_description": "Test a bounded mechanism.",
            "needs": [
                {"need_id": "need-1", "question": "Which option is supportable?"}
            ],
            "scope_fields": [],
            "suggestions": [],
            "decisions": [],
            "previous_sha256": None,
        },
        "sources": [],
        "evidence": [],
        "literature": [],
        "comparisons": [],
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "version": 2,
                "parent_version": 1,
                "question": "Can a simple new concept test the bounded mechanism?",
                "research_mode": "exploratory",
                "opportunity": "The mechanism remains uncertain.",
                "value": "The result may improve measurement.",
                "approach": "Use a simple preregistered comparison.",
                "requirements": ["A and B must be linkable"],
                "limitations": ["Performance is unknown until tested"],
                "evidence_ids": [],
            }
        ],
        "unresolved": [],
    }


def followup(**overrides):
    value = {
        "candidate_id": "candidate-1",
        "candidate_version": 2,
        "missing_evidence": ["Check whether A and B contain linkable variables."],
        "decision_affected": "Resource linkage changes the disposition.",
        "scope_change_requested": False,
    }
    value.update(overrides)
    return value


def rehash(task):
    task["task_sha256"] = canonical_hash(
        {key: value for key, value in task.items() if key != "task_sha256"}
    )
    return task


class ResearchFollowupTests(unittest.TestCase):
    def build(self, *, source_packet=None, row=None, previous=None):
        source_packet = source_packet or packet()
        return build_research_followup_task(
            source_packet,
            "a" * 64,
            [row or followup()],
            POLICY,
            previous_task=previous,
        )

    def test_rejects_stale_candidate_version_and_evidence_revision(self):
        task = self.build()
        changed = packet()
        changed["candidates"][0]["version"] = 3
        with self.assertRaisesRegex(Stage2Error, "candidate-version-stale"):
            validate_research_followup_task(
                task,
                changed,
                "a" * 64,
                POLICY,
                expected_followups=[followup()],
            )
        evidence_changed = packet()
        evidence_changed["evidence"].append({"evidence_id": "ev-new"})
        with self.assertRaisesRegex(Stage2Error, "evidence-revision-stale"):
            validate_research_followup_task(
                task,
                evidence_changed,
                "a" * 64,
                POLICY,
                expected_followups=[followup()],
            )
        with self.assertRaisesRegex(Stage2Error, "snapshot-stale"):
            validate_research_followup_task(
                task,
                packet(),
                "b" * 64,
                POLICY,
                expected_followups=[followup()],
            )

    def test_closest_work_has_all_query_families(self):
        task = self.build()
        closest = task["tasks"][0]["closest_work"]
        self.assertEqual(
            set(closest["query_families"]),
            {
                "problem_synonyms",
                "mechanism_synonyms",
                "method_synonyms",
                "validation_synonyms",
                "cross_domain_analogues",
                "citation_chaining",
                "counterevidence",
            },
        )

    def test_metadata_only_cannot_be_verified_novelty(self):
        task = self.build()
        closest = task["tasks"][0]["closest_work"]
        self.assertEqual(closest["novelty_status"], "unknown")
        self.assertEqual(closest["scientific_support_status"], "unknown")
        self.assertFalse(closest["metadata_only_is_support"])

    def test_absent_variables_remain_distinct_from_inaccessible(self):
        task = self.build()
        statuses = task["tasks"][0]["resource_checks"]["allowed_outcomes"]
        self.assertIn("required-content-absent", statuses)
        self.assertIn("inaccessible", statuses)
        self.assertIn("unverified", statuses)

    def test_sharing_exception_requires_alternatives(self):
        task = self.build()
        checks = task["tasks"][0]["resource_checks"]
        self.assertEqual(checks["checks"]["license_and_sharing"]["status"], "unknown")
        self.assertTrue(
            checks["checks"]["license_and_sharing"]["alternatives_required"]
        )

    def test_simple_method_and_new_concept_keep_performance_unknown(self):
        task = self.build()
        decision = task["tasks"][0]["decision_state"]
        self.assertEqual(decision["feasibility"], "unknown")
        self.assertEqual(decision["scientific_performance"], "unknown")
        self.assertEqual(decision["human_budget"], "unknown")

    def test_zero_recommendation_is_not_rewarded(self):
        task = self.build(
            row=followup(
                missing_evidence=["Determine whether any option is supportable."]
            )
        )
        self.assertEqual(
            task["tasks"][0]["decision_state"]["portfolio_utility"], "unknown"
        )

    def test_unknown_price_does_not_become_zero(self):
        task = self.build()
        self.assertEqual(task["tasks"][0]["resource_checks"]["cost"], "unknown")
        self.assertNotEqual(task["tasks"][0]["resource_checks"]["cost"], 0)

    def test_joint_resources_remain_unknown_without_joint_evidence(self):
        task = self.build(
            row=followup(missing_evidence=["Check joint access to A and B."])
        )
        joint = task["tasks"][0]["resource_checks"]["joint_dependencies"]
        self.assertEqual(joint["status"], "unknown")
        self.assertTrue(joint["requires_joint_evidence"])

    def test_no_progress_stops_unchanged_issue_without_next_action(self):
        first = self.build()
        unchanged = followup(missing_evidence=[])
        second = self.build(row=unchanged, previous=first)
        self.assertEqual(second["tasks"][0]["action"], "stop-no-progress")
        self.assertEqual(second["tasks"][0]["needs"], [])
        self.assertEqual(second["prior_task_sha256"], first["task_sha256"])
        third = self.build(row=unchanged, previous=second)
        self.assertEqual(third["tasks"][0]["action"], "stop-no-progress")
        self.assertEqual(
            validate_research_followup_task(
                third,
                packet(),
                "a" * 64,
                POLICY,
                expected_followups=[unchanged],
                expected_previous_task=second,
            ),
            third,
        )
        self.assertEqual(
            validate_research_followup_task(
                second,
                packet(),
                "a" * 64,
                POLICY,
                expected_followups=[unchanged],
                expected_previous_task=first,
            ),
            second,
        )

        still_actionable = self.build(row=followup(), previous=first)
        self.assertEqual(
            still_actionable["tasks"][0]["action"], "native-research-followup"
        )

    def test_rehashed_task_cannot_change_admitted_followup_or_output(self):
        original = self.build()
        altered = []

        need = copy.deepcopy(original)
        need["tasks"][0]["needs"][0]["question"] = "Substitute an untrusted need."
        altered.append(need)

        action = copy.deepcopy(original)
        action["tasks"][0]["action"] = "stop-no-progress"
        altered.append(action)

        output = copy.deepcopy(original)
        output["tasks"][0]["output_contract"]["need_refs"] = []
        altered.append(output)

        scope = copy.deepcopy(original)
        scope["originating_followups"][0]["scope_change_requested"] = True
        scope["tasks"][0]["scope_change_requested"] = True
        altered.append(scope)

        for task in altered:
            with (
                self.subTest(field=task["tasks"][0]["action"]),
                self.assertRaisesRegex(Stage2Error, "reconstruction-mismatch"),
            ):
                validate_research_followup_task(
                    rehash(task),
                    packet(),
                    "a" * 64,
                    POLICY,
                    expected_followups=[followup()],
                )

    def test_duplicate_candidates_bool_versions_and_malformed_scopes_fail(self):
        with self.assertRaisesRegex(Stage2Error, "duplicate-candidate"):
            build_research_followup_task(
                packet(), "a" * 64, [followup(), followup()], POLICY
            )
        for row, error in (
            (followup(candidate_version=True), "candidate-version-invalid"),
            (followup(scope_change_requested=1), "scope-change-invalid"),
            (followup(scope_change_requested=None), "scope-change-invalid"),
        ):
            with (
                self.subTest(row=row),
                self.assertRaisesRegex(Stage2Error, error),
            ):
                build_research_followup_task(packet(), "a" * 64, [row], POLICY)

    def test_candidate_version_update_starts_new_research_action(self):
        first = self.build()
        revised = packet()
        revised["candidates"][0]["version"] = 3
        revised["candidates"][0]["parent_version"] = 2
        row = followup(candidate_version=3, missing_evidence=[])
        task = build_research_followup_task(
            revised, "b" * 64, [row], POLICY, previous_task=first
        )
        self.assertEqual(task["tasks"][0]["action"], "native-research-followup")
        self.assertEqual(task["tasks"][0]["candidate_version"], 3)
        self.assertEqual(
            validate_research_followup_task(
                task,
                revised,
                "b" * 64,
                POLICY,
                expected_followups=[row],
                expected_previous_task=first,
            ),
            task,
        )

    def test_policy_and_output_are_hash_bound(self):
        task = self.build()
        self.assertEqual(task["policy_sha256"], canonical_hash(POLICY))
        self.assertEqual(
            validate_research_followup_task(
                task,
                packet(),
                "a" * 64,
                POLICY,
                expected_followups=[followup()],
            ),
            task,
        )
        changed = copy.deepcopy(POLICY)
        changed["canonical_policy_ref"] = "stage2-v3-existing-policy:other"
        with self.assertRaisesRegex(Stage2Error, "policy-mismatch"):
            validate_research_followup_task(
                task,
                packet(),
                "a" * 64,
                changed,
                expected_followups=[followup()],
            )

    def test_controller_v3_policy_is_explicit_and_preserves_v2_opt_in(self):
        controller_policy = {
            "kind": "Stage2FollowupPolicy",
            "schema_version": "3.0.0",
            "investigate_material_partial": True,
            "research_task_policy": POLICY,
        }
        self.assertTrue(_material_followup_policy(controller_policy))
        self.assertEqual(_research_followup_policy(controller_policy), POLICY)
        with self.assertRaisesRegex(Stage2Error, "policy-invalid"):
            _material_followup_policy(
                {
                    **controller_policy,
                    "research_task_policy": {
                        **POLICY,
                        "canonical_policy_ref": "",
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
