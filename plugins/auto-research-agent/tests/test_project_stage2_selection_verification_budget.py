"""Deterministic metadata budget and retained frontier checks; no native calls."""

import unittest
from unittest.mock import patch

from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.session_api import SessionApiError


class SelectionVerificationBudgetTests(Stage2SelectionFixture):
    def prepare_choice(self):
        return super().prepare_choice(ProjectStage2SelectionService)

    def test_choice_uses_bounded_full_verification_and_keeps_strict_frontier(self):
        ui, body, _ = self.prepare_choice()
        original = ProjectStage2Service._activation_context
        calls = []

        def bounded(service, *args, **kwargs):
            calls.append(args[0])
            if len(calls) > 3:
                raise SessionApiError("synthetic-source-verification-budget-exhausted")
            return original(service, *args, **kwargs)

        with patch.object(ProjectStage2Service, "_activation_context", bounded):
            saved = ui.select("own", self.ref, body)
        self.assertEqual(saved["status"], "saved")
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"],
            saved["workflow_head_sha256"],
        )
        self.assertFalse(saved["execution_authorized"])

    def test_saved_frontier_state_tamper_is_rejected_on_same_key_replay(self):
        ui, body, _ = self.prepare_choice()
        saved = ui.select("own", self.ref, body)
        state = self.intake._load("researcher", self.ref)
        state["stage2_frontier"]["workflow_head_sha256"] = "0" * 64
        self.intake._save(state, "synthetic-frontier-state-tamper", {"fixture": True})
        self.intake.db.commit()
        with self.assertRaises(SessionApiError):
            ui.select("own", self.ref, body)
        self.assertEqual(saved["status"], "saved")
        count = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_each_read_revalidates_activation_without_cross_request_cache(self):
        ui, _, _ = self.prepare_choice()
        original = ProjectStage2Service._activation_context
        with patch.object(
            ProjectStage2Service,
            "_activation_context",
            autospec=True,
            side_effect=original,
        ) as checked:
            first = ui.read("own", self.ref)
            before = checked.call_count
            second = ui.read("own", self.ref)
            self.assertGreater(checked.call_count, before)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
