"""One strict snapshot per locked conditional read; no cross-write reuse."""

# ruff: noqa: E402 -- repository fixture imports.
from pathlib import Path
import sys
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage2_selection_view import (
    ProjectStage2SelectionView,
)
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from research_workspace_native.session_api import SessionApiError
from test_project_stage2_direction_intent import intent_body


class DirectionVerificationBudgetTests(Stage2SelectionFixture):
    def planning(self):
        selection, body, _ = self.prepare_choice(ProjectStage2SelectionService)
        receipt = selection.direction_intent("own", self.ref, intent_body(body))
        planning = ProjectStage3PlanningService(self.intake, selection)
        return selection, receipt, planning.direction

    def test_direction_admission_verifies_once_and_next_admission_is_fresh(self):
        _, receipt, direction = self.planning()
        original = ProjectStage2SelectionView._verify_current_context
        with patch.object(
            ProjectStage2SelectionView,
            "_verify_current_context",
            autospec=True,
            side_effect=original,
        ) as checked:
            first = direction._current("own", self.ref)
            self.assertEqual(checked.call_count, 1)
            second = direction._current("own", self.ref)
            self.assertEqual(checked.call_count, 2)
        self.assertEqual(first, second)
        self.assertEqual(first[1]["intent_sha256"], receipt["intent_sha256"])
        self.assertIsNone(first[3])

    def test_selection_read_covers_retained_preference_in_one_fresh_snapshot(self):
        selection, receipt, _ = self.planning()
        original = ProjectStage2SelectionView._verify_current_context
        with patch.object(
            ProjectStage2SelectionView,
            "_verify_current_context",
            autospec=True,
            side_effect=original,
        ) as checked:
            first = selection.read("own", self.ref)
            self.assertEqual(checked.call_count, 1)
            second = selection.read("own", self.ref)
            self.assertEqual(checked.call_count, 2)
        self.assertEqual(first, second)
        self.assertEqual(
            first["direction_intent"]["intent_sha256"], receipt["intent_sha256"]
        )
        self.assertEqual(first["selection_status"], "pending")

    def test_new_admission_rejects_frontier_drift_and_foreign_principal(self):
        _, _, direction = self.planning()
        direction._current("own", self.ref)
        with self.assertRaises(SessionApiError):
            direction._current("foreign", self.ref)
        state = self.intake._load("researcher", self.ref)
        state["stage2_frontier"]["workflow_head_sha256"] = "0" * 64
        self.intake._save(state, "synthetic-tampered-frontier", {"fixture": True})
        self.intake.db.commit()
        with self.assertRaises(SessionApiError):
            direction._current("own", self.ref)
