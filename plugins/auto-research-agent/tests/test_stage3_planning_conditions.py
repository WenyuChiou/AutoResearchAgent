import copy
import math
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from cli.stage3_plan.contracts import Stage3Error, digest  # noqa: E402
from cli.stage3_plan.planning_conditions import (  # noqa: E402
    condition_diagnostics,
    condition_sources,
)


def _unknown(
    unknown_id,
    question_ref,
    *,
    kind="other",
    resolve_before="plan-review",
    resource_ids=None,
    blocking=True,
    disposition="unresolved",
    scope_change_required=False,
):
    return {
        "unknown_id": unknown_id,
        "description": f"Unresolved premise {unknown_id}.",
        "kind": kind,
        "question_refs": [question_ref],
        "resolution": "Resolve from admissible evidence.",
        "blocking": blocking,
        "resolve_before": resolve_before,
        "resource_ids": list(resource_ids or []),
        "owner": None,
        "resolution_evidence_needed": f"Evidence for {unknown_id}.",
        "recheck_trigger": f"Recheck {unknown_id} when evidence changes.",
        "fallback": f"Keep {unknown_id} out of scope if unresolved.",
        "scope_change_required": scope_change_required,
        "disposition": disposition,
    }


def _plan():
    q1 = "candidate-a@v1/question-a"
    q2 = "candidate-b@v1/question-b"
    return {
        "schema_version": "1.1.0",
        "questions": [{"question_ref": q1}, {"question_ref": q2}],
        "resources": [{"resource_id": "resource-a"}],
        "question_plans": [
            {
                "question_ref": q1,
                "blockers": [],
                "resource_uses": [{"resource_id": "resource-a", "status": "unknown"}],
            },
            {"question_ref": q2, "blockers": [], "resource_uses": []},
        ],
        "unknowns": [
            _unknown(
                "unknown-resource",
                q1,
                kind="feasibility",
                resolve_before="resource-planning",
                resource_ids=["resource-a"],
            ),
            _unknown(
                "unknown-scope",
                q2,
                kind="question-meaning",
                resolve_before="question-definition",
                blocking=False,
                disposition="deferred",
                scope_change_required=True,
            ),
        ],
        "condition_dispositions": [],
    }


def _intake():
    return {
        "selection_conditions": [{"label": "condition-a", "limit": 3}],
        "unresolved": [{"label": "premise-a", "known": False}],
        "legacy_mapping": {"packet_unresolved": []},
    }


def _disposition(condition_ref, source_value, question_refs, unknown_ids):
    return {
        "condition_ref": condition_ref,
        "source_sha256": digest(source_value),
        "question_refs": question_refs,
        "interpretation": "A proposed interpretation for planning.",
        "disposition": "planned",
        "response": "Keep the dependency visible until it is resolved.",
        "unknown_ids": unknown_ids,
    }


class PlanningConditionTests(unittest.TestCase):
    def test_condition_sources_preserve_order_digest_and_input(self):
        intake = _intake()
        intake["legacy_mapping"]["packet_unresolved"] = ["legacy premise"]
        original = copy.deepcopy(intake)

        sources = condition_sources(intake)

        self.assertEqual(
            [row["condition_ref"] for row in sources],
            ["selection_conditions/0", "unresolved/0", "packet_unresolved/0"],
        )
        self.assertEqual(sources[1]["source_sha256"], digest(intake["unresolved"][0]))
        sources[0]["value"]["limit"] = 99
        self.assertEqual(intake, original)

    def test_condition_sources_reject_malformed_or_noncanonical_values(self):
        with self.assertRaisesRegex(Stage3Error, "/unresolved must be an array"):
            condition_sources({"unresolved": {}})
        with self.assertRaises(Stage3Error):
            condition_sources({"selection_conditions": [math.nan]})

    def test_v1_returns_empty_diagnostics_without_mutation(self):
        plan = {"schema_version": "1.0.0", "sentinel": [1]}
        original = copy.deepcopy(plan)

        result = condition_diagnostics(plan, intake={"unresolved": "ignored for v1"})

        self.assertEqual(
            result,
            {
                "issues": [],
                "blocked_questions": [],
                "resolution_schedule": [],
                "execution_authorized": False,
            },
        )
        self.assertEqual(plan, original)

    def test_valid_conditions_block_dependencies_and_sort_schedule(self):
        plan = _plan()
        intake = _intake()
        q1, q2 = [row["question_ref"] for row in plan["questions"]]
        plan["condition_dispositions"] = [
            _disposition(
                "selection_conditions/0",
                intake["selection_conditions"][0],
                [q2],
                [],
            ),
            _disposition(
                "unresolved/0",
                intake["unresolved"][0],
                [q1],
                ["unknown-resource"],
            ),
        ]
        original_plan = copy.deepcopy(plan)
        original_intake = copy.deepcopy(intake)

        result = condition_diagnostics(plan, intake=intake)

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["blocked_questions"], [q1, q2])
        self.assertEqual(
            [row["unknown_id"] for row in result["resolution_schedule"]],
            ["unknown-scope", "unknown-resource"],
        )
        self.assertIsNone(result["resolution_schedule"][0]["owner"])
        self.assertFalse(result["execution_authorized"])
        result["resolution_schedule"][0]["fallback"] = "changed"
        self.assertEqual(plan, original_plan)
        self.assertEqual(intake, original_intake)

    def test_rejects_source_coverage_ghost_refs_duplicates_and_late_deadline(self):
        plan = _plan()
        intake = _intake()
        q1 = plan["questions"][0]["question_ref"]
        plan["unknowns"].append(copy.deepcopy(plan["unknowns"][0]))
        plan["unknowns"][0]["resolve_before"] = "before-access-use"
        plan["unknowns"][0]["question_refs"] = ["ghost-question"]
        plan["unknowns"][0]["resource_ids"] = ["ghost-resource"]
        ghost = _disposition(
            "ghost/0",
            {"invented": True},
            [q1],
            ["ghost-unknown"],
        )
        plan["condition_dispositions"] = [ghost, copy.deepcopy(ghost)]

        result = condition_diagnostics(plan, intake=intake)
        codes = [issue["code"] for issue in result["issues"]]

        self.assertIn("duplicate-id", codes)
        self.assertIn("missing-reference", codes)
        self.assertIn("late-resolution-deadline", codes)
        self.assertIn("missing-condition-source", codes)
        self.assertIn("unknown-condition-source", codes)

    def test_rehashed_or_nonblocking_unresolved_source_does_not_clear_resource(self):
        plan = _plan()
        intake = _intake()
        q1 = plan["questions"][0]["question_ref"]
        plan["unknowns"][0]["blocking"] = False
        plan["unknowns"][0]["disposition"] = "assumption"
        plan["condition_dispositions"] = [
            _disposition(
                "selection_conditions/0",
                intake["selection_conditions"][0],
                [q1],
                [],
            ),
            _disposition(
                "unresolved/0",
                {"rehash": "replacement"},
                [q1],
                ["unknown-resource"],
            ),
        ]

        result = condition_diagnostics(plan, intake=intake)
        codes = [issue["code"] for issue in result["issues"]]

        self.assertIn("condition-source-mismatch", codes)
        self.assertIn("unresolved-source-unblocked", codes)
        self.assertIn("unknown-resource-unlinked", codes)
        self.assertEqual(
            result["blocked_questions"], [q1, plan["questions"][1]["question_ref"]]
        )


if __name__ == "__main__":
    unittest.main()
