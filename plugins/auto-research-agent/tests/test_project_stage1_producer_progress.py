"""Pure tests for the optional Stage 1 producer queue projection."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.project_stage1_producer_progress import (
    project_producer_progress,
)
from research_workspace_native.project_stage1_progress import project_progress
from research_workspace_native.session_api import SessionApiError
from test_project_stage1_progress import snapshot


def producer_queue(value, *, status="ready", phase="reading"):
    project = value["project"]
    return dict(
        kind="ProjectStage1ProducerQueue",
        schema_version="1.0.0",
        binding={
            key: project[key]
            for key in ("project_ref", "revision", "input_version", "brief_sha256")
        },
        ledger_state_sha256=value["stage1"]["ledger"]["state_sha256"],
        status=status,
        next_action=None
        if status == "idle"
        else dict(
            phase_id=phase,
            target="saved-source" if phase == "reading" else phase,
            reason="producer-" + phase + "-required",
        ),
        remaining_work_count=1,
        blocked_work_count=0,
        research_complete=False,
    )


class ProducerProgressTests(unittest.TestCase):
    def test_absent_or_idle_queue_is_exact_original_and_inputs_are_unchanged(self):
        value = snapshot()
        idle = producer_queue(value, status="idle")
        before_value, before_idle = deepcopy(value), deepcopy(idle)
        expected = project_progress(value)
        self.assertEqual(project_producer_progress(value), expected)
        self.assertEqual(project_producer_progress(value, idle), expected)
        self.assertEqual(value, before_value)
        self.assertEqual(idle, before_idle)

    def test_pending_with_zero_included_can_route_to_saved_source_reading(self):
        value = snapshot()
        original = project_progress(value)
        self.assertEqual(original["next_action"]["phase_id"], "coverage")
        queue = producer_queue(value, phase="reading")
        before_value, before_queue = deepcopy(value), deepcopy(queue)
        result = project_producer_progress(value, queue)
        self.assertEqual(result["next_action"], queue["next_action"])
        reading = next(row for row in result["phases"] if row["phase_id"] == "reading")
        self.assertEqual(reading["status"], "available")
        self.assertFalse(result["research_complete"])
        self.assertEqual((value, queue), (before_value, before_queue))

    def test_initial_pending_batch_routes_to_screening(self):
        value = snapshot()
        value["stage1"]["ledger"]["counts"]["decisions"] = 0
        queue = producer_queue(value, phase="screening")
        result = project_producer_progress(value, queue)
        self.assertEqual(result["next_action"], queue["next_action"])
        screening = next(
            row for row in result["phases"] if row["phase_id"] == "screening"
        )
        self.assertEqual(screening["status"], "available")

    def test_held_queue_is_visible_without_claiming_completion(self):
        value = snapshot()
        queue = producer_queue(value, status="held", phase="coverage")
        queue["blocked_work_count"] = 1
        result = project_producer_progress(value, queue)
        self.assertEqual(result["next_action"], queue["next_action"])
        coverage = next(
            row for row in result["phases"] if row["phase_id"] == "coverage"
        )
        self.assertEqual(coverage["status"], "held")
        self.assertEqual(coverage["reason"], queue["next_action"]["reason"])
        self.assertFalse(result["research_complete"])

    def test_original_holds_scope_planning_and_saved_barriers_win(self):
        cases = []
        held = snapshot()
        held["stage1"]["coverage_actions"]["held"] = True
        cases.append(held)
        scope = snapshot()
        scope["project"]["intake_report"]["necessary_clarification_complete"] = False
        cases.append(scope)
        planning = snapshot()
        planning["project"]["plan"] = None
        cases.append(planning)
        saved = snapshot()
        saved["stage1"]["delivery"] = dict(
            canonical_package=dict(
                status="saved-evidence-validated",
                artifact_kind="Stage1ResearchDeliverable",
                artifact_ref="artifact",
                manifest_sha256="d" * 64,
                records_sha256="e" * 64,
                handoff_sha256="f" * 64,
                ledger_state_sha256="c" * 64,
                binding=dict(
                    project_id="project-p", input_version=1, brief_sha256="a" * 64
                ),
            )
        )
        self.assertEqual(
            project_progress(saved)["next_action"]["reason"],
            "package-saved-review-required",
        )
        cases.append(saved)
        final = snapshot()
        final["stage1"]["ledger"].update(
            gate=dict(
                gate_name="stage1-coverage-readiness",
                outcome="pass",
                blocking_items=[],
            ),
            next_allowed_action="stop-sufficient",
        )
        final["stage1"]["coverage_actions"]["blockers"] = []
        cases.append(final)
        for value in cases:
            with self.subTest(reason=project_progress(value)["next_action"]):
                expected = project_progress(value)
                self.assertEqual(
                    project_producer_progress(value, producer_queue(value)), expected
                )

    def test_malformed_unbound_and_extra_queue_fields_are_refused(self):
        value = snapshot()
        valid = producer_queue(value)
        invalid = [
            [],
            {key: item for key, item in valid.items() if key != "status"},
            valid | {"unknown": None},
            valid | {"kind": "ForeignQueue"},
            valid | {"schema_version": "1.1.0"},
            valid | {"research_complete": 0},
            valid | {"remaining_work_count": False},
            valid | {"blocked_work_count": -1},
            valid | {"status": "unknown"},
            valid | {"status": []},
            valid | {"ledger_state_sha256": "0" * 64},
            valid | {"binding": valid["binding"] | {"project_ref": "foreign"}},
            valid | {"binding": valid["binding"] | {"unknown": 1}},
            valid | {"binding": valid["binding"] | {"revision": False}},
            valid | {"next_action": None},
            valid | {"next_action": valid["next_action"] | {"phase_id": "delivery"}},
            valid | {"next_action": valid["next_action"] | {"phase_id": []}},
            valid | {"next_action": valid["next_action"] | {"target": ""}},
            valid | {"next_action": valid["next_action"] | {"reason": "x" * 257}},
            producer_queue(value, status="idle")
            | {"next_action": dict(phase_id="reading", target="x", reason="x")},
        ]
        for queue in invalid:
            with self.subTest(queue=queue):
                before_value, before_queue = deepcopy(value), deepcopy(queue)
                with self.assertRaises(SessionApiError) as raised:
                    project_producer_progress(value, queue)
                self.assertEqual(raised.exception.code, "stage1-producer-queue-invalid")
                self.assertEqual(value, before_value)
                self.assertEqual(queue, before_queue)


if __name__ == "__main__":
    unittest.main()
