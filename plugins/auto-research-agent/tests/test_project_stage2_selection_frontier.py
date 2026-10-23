"""Synthetic selection/recovery reuses the accepted read-side package fixture.

No model, scientific eval, research or actual user choice occurs here.
"""

# ruff: noqa: E402 -- exercise repository CLI and authored fixtures.
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage2_workflow import inspect_workflow
import research_workspace_native.project_stage2_selection as selection_module


class ActivatedSelectionFrontierTests(Stage2SelectionFixture):
    def prepare_choice(self):
        return super().prepare_choice(ProjectStage2SelectionService)

    def test_ui_selection_updates_activated_frontier_and_replay_never_reexecutes(self):
        ui, body, workflow = self.prepare_choice()
        result = ui.select("own", self.ref, body)
        current = self.service.binding(self.ref)
        self.assertEqual(
            current["workflow_head_sha256"], result["workflow_head_sha256"]
        )
        self.assertFalse(result["execution_authorized"])
        before = inspect_workflow(workflow)
        replay = ui.select("own", self.ref, body)
        self.assertTrue(replay["replayed"])
        self.assertEqual(inspect_workflow(workflow), before)
        self.assertEqual(self.service.binding(self.ref), current)
        view = ui.read("own", self.ref)
        self.assertEqual(view["planning_status"], "verified")
        self.assertFalse(view["planning_input"]["execution_authorized"])

    def test_saved_choice_recovers_only_frontier_after_transport_interruption(self):
        ui, body, workflow = self.prepare_choice()
        with patch.object(
            selection_module,
            "record_interaction",
            wraps=selection_module.record_interaction,
        ) as recorded:
            with patch.object(
                ProjectStage2Service,
                "advance_frontier",
                side_effect=SessionApiError(
                    "synthetic-frontier-transport-interruption"
                ),
            ):
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-selection-frontier-needs-recovery"
                ):
                    ui.select("own", self.ref, body)
            row = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchone()
            self.assertEqual(json.loads(row[0])["status"], "saved")
            before = inspect_workflow(workflow)
            result = ui.select("own", self.ref, body)
            self.assertTrue(result["replayed"])
            self.assertEqual(recorded.call_count, 1)
            self.assertEqual(inspect_workflow(workflow), before)
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"],
            result["workflow_head_sha256"],
        )

    def test_activated_project_rejects_even_identical_foreign_workflow_bytes(self):
        ui, _, workflow = self.prepare_choice()
        foreign = self.root / "foreign-workflow"
        shutil.copytree(workflow, foreign)
        ui.bindings[self.ref]["workflow_root"] = str(foreign)
        before = inspect_workflow(workflow)
        with self.assertRaisesRegex(
            SessionApiError, "stage2-selection-project-workflow-differs"
        ):
            ui.read("own", self.ref)
        self.assertEqual(inspect_workflow(workflow), before)

    def test_core_choice_append_then_failure_remains_held_without_resubmission(self):
        ui, body, workflow = self.prepare_choice()
        original = selection_module.record_interaction

        def append_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic interruption after core choice append")

        with patch.object(
            selection_module, "record_interaction", side_effect=append_then_fail
        ) as recorded:
            with self.assertRaises(SessionApiError):
                ui.select("own", self.ref, body)
            row = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchone()
            held = json.loads(row[0])
            self.assertEqual(held["status"], "execution-unknown")
            self.assertEqual(held["failure_phase"], "core-write-outcome-unobserved")
            before = inspect_workflow(workflow)
            self.assertNotEqual(before["head_sha256"], body["workflow_head_sha256"])
            with self.assertRaisesRegex(SessionApiError, "recovery-outcome-unverified"):
                ui.select("own", self.ref, body)
            self.assertEqual(recorded.call_count, 1)
            self.assertEqual(inspect_workflow(workflow), before)

    def test_frontier_post_work_commit_failure_recovers_without_repeating_choice(self):
        ui, body, workflow = self.prepare_choice()
        original = self.intake._save
        failed = False

        def fail_frontier_once(state, kind, payload):
            nonlocal failed
            original(state, kind, payload)
            ack = state.get("stage2_selected_planning")
            frontier = state.get("stage2_frontier")
            if (
                not failed
                and ack
                and frontier
                and frontier["workflow_head_sha256"] == ack["workflow_head_sha256"]
            ):
                failed = True
                raise OSError("synthetic frontier commit interruption")

        with patch.object(
            selection_module,
            "record_interaction",
            wraps=selection_module.record_interaction,
        ) as recorded:
            with patch.object(self.intake, "_save", side_effect=fail_frontier_once):
                with self.assertRaisesRegex(
                    SessionApiError, "stage2-selection-frontier-needs-recovery"
                ):
                    ui.select("own", self.ref, body)
            self.assertTrue(failed)
            before = inspect_workflow(workflow)
            result = ui.select("own", self.ref, body)
            self.assertTrue(result["replayed"])
            self.assertEqual(recorded.call_count, 1)
            self.assertEqual(inspect_workflow(workflow), before)
        self.assertEqual(
            self.service.binding(self.ref)["workflow_head_sha256"],
            result["workflow_head_sha256"],
        )
        self.assertFalse(result["execution_authorized"])

    def _failed_choice_registration(self):
        ui, body, workflow = self.prepare_choice()
        original = self.intake._save

        def fail_after_save(state, kind, payload):
            original(state, kind, payload)
            if kind == "stage2-select-saved":
                raise OSError(
                    "synthetic interruption after complete choice before commit"
                )

        with patch.object(self.intake, "_save", side_effect=fail_after_save):
            with self.assertRaises(SessionApiError):
                ui.select("own", self.ref, body)
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()
        held = json.loads(row[0])
        self.assertEqual(held["status"], "execution-unknown")
        self.assertEqual(held["failure_phase"], "post-work-before-commit")
        return ui, body, workflow, held

    def test_completed_choice_registration_recovers_without_repeating_core(self):
        ui, body, workflow, _ = self._failed_choice_registration()
        before = inspect_workflow(workflow)
        with patch.object(
            selection_module,
            "record_interaction",
            side_effect=AssertionError("core repeated"),
        ):
            result = ui.select("own", self.ref, body)
        self.assertEqual(result["status"], "saved")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(inspect_workflow(workflow), before)
        self.assertEqual(ui.read("own", self.ref)["planning_status"], "verified")

    def test_choice_registration_rejects_action_row_only_envelope_tamper(self):
        ui, body, workflow, held = self._failed_choice_registration()
        held.update(
            project_ref="foreign-project", key="foreign-key", request_sha256="0" * 64
        )
        self.intake.db.execute(
            "UPDATE intake_actions SET receipt=? WHERE project=? AND key=?",
            (json.dumps(held), self.ref, body["key"]),
        )
        self.intake.db.commit()
        before = inspect_workflow(workflow)
        with self.assertRaisesRegex(SessionApiError, "recovery-request-differs"):
            ui.select("own", self.ref, body)
        self.assertEqual(inspect_workflow(workflow), before)

    def test_choice_registration_rejects_duplicate_original_failure_event(self):
        ui, body, workflow, held = self._failed_choice_registration()
        self.intake.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (self.ref, "stage2-select-failed", json.dumps(held)),
        )
        self.intake.db.commit()
        before = inspect_workflow(workflow)
        with self.assertRaisesRegex(
            SessionApiError, "recovery-failure-receipt-differs"
        ):
            ui.select("own", self.ref, body)
        self.assertEqual(inspect_workflow(workflow), before)

    def test_completed_registration_recovery_requires_saved_project_activation(self):
        ui, body, workflow, _ = self._failed_choice_registration()
        state = self.intake._load("researcher", self.ref)
        state.pop("stage2_activation")
        self.intake._save(state, "synthetic-missing-activation", {"fixture": True})
        self.intake.db.commit()
        before = inspect_workflow(workflow)
        previous = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()[0]
        with self.assertRaisesRegex(SessionApiError, "stage2-not-activated"):
            ui.select("own", self.ref, body)
        self.assertFalse(
            "stage2_selected_planning" in self.intake._load("researcher", self.ref)
        )
        self.assertEqual(
            self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchone()[0],
            previous,
        )
        self.assertEqual(inspect_workflow(workflow), before)

    def test_saved_choice_replay_rejects_duplicate_saved_journal_event(self):
        ui, body, workflow = self.prepare_choice()
        ui.select("own", self.ref, body)
        saved = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
            (self.ref, body["key"]),
        ).fetchone()[0]
        self.intake.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (self.ref, "stage2-select-saved", saved),
        )
        self.intake.db.commit()
        before = inspect_workflow(workflow)
        with self.assertRaisesRegex(SessionApiError, "recovery-saved-receipt-differs"):
            ui.select("own", self.ref, body)
        self.assertEqual(inspect_workflow(workflow), before)

    def test_new_key_cannot_bypass_unknown_selection_before_core_append(self):
        ui, body, workflow = self.prepare_choice()
        before = inspect_workflow(workflow)
        with patch.object(
            selection_module,
            "record_interaction",
            side_effect=OSError("synthetic pre-append I/O interruption"),
        ) as recorded:
            with self.assertRaises(SessionApiError):
                ui.select("own", self.ref, body)
            next_body = dict(
                body,
                key="different-key",
                revision=self.intake._load("researcher", self.ref)["revision"],
            )
            count = self.intake.db.execute(
                "SELECT COUNT(*) FROM intake_actions WHERE project=?", (self.ref,)
            ).fetchone()[0]
            with self.assertRaisesRegex(SessionApiError, "stage2-selection-unresolved"):
                ui.select("own", self.ref, next_body)
            self.assertEqual(recorded.call_count, 1)
            self.assertEqual(
                self.intake.db.execute(
                    "SELECT COUNT(*) FROM intake_actions WHERE project=?", (self.ref,)
                ).fetchone()[0],
                count,
            )
            held = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE project=? AND key=?",
                (self.ref, body["key"]),
            ).fetchone()[0]
            for version in [None, "1", 2]:
                altered = json.loads(held)
                if version is None:
                    altered["request"].pop("input_version")
                else:
                    altered["request"]["input_version"] = version
                self.intake.db.execute(
                    "UPDATE intake_actions SET receipt=? WHERE project=? AND key=?",
                    (json.dumps(altered), self.ref, body["key"]),
                )
                self.intake.db.commit()
                with self.assertRaisesRegex(SessionApiError, "prior-intent-invalid"):
                    ui.select("own", self.ref, next_body)
                self.assertEqual(recorded.call_count, 1)
            self.intake.db.execute(
                "UPDATE intake_actions SET receipt=? WHERE project=? AND key=?",
                (held, self.ref, body["key"]),
            )
            self.intake.db.commit()
            with self.assertRaisesRegex(SessionApiError, "recovery-outcome-unverified"):
                ui.select("own", self.ref, body)
            self.assertEqual(recorded.call_count, 1)
        self.assertEqual(inspect_workflow(workflow), before)


if __name__ == "__main__":
    unittest.main()
