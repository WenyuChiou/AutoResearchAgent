"""Read-only package views are synthetic engineering evidence, not user choice."""

# ruff: noqa: E402 -- exercise the repository CLI and authored fixture.
from copy import deepcopy
from pathlib import Path
import shutil
import sys

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]
from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.session_api import SessionApiError
from stage2_workflow import inspect_workflow


class Stage2SelectionViewTests(Stage2SelectionFixture):
    def test_current_cards_keep_unknowns_without_workflow_or_intake_writes(self):
        view, _, workflow = self.prepare_choice()
        before = inspect_workflow(workflow)
        project = deepcopy(self.intake._load("researcher", self.ref))
        events = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events"
        ).fetchone()[0]
        result = view.read("own", self.ref)
        self.assertEqual(result["selection_status"], "pending")
        self.assertEqual(result["planning_status"], "awaiting-valid-selection")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["identity_authenticated"])
        self.assertTrue(result["cards"]["cards"])
        self.assertEqual(inspect_workflow(workflow), before)
        self.assertEqual(self.intake._load("researcher", self.ref), project)
        self.assertEqual(
            self.intake.db.execute("SELECT COUNT(*) FROM intake_events").fetchone()[0],
            events,
        )

    def test_wrong_delivery_hash_and_input_version_reject(self):
        view, _, workflow = self.prepare_choice()
        binding = deepcopy(view.bindings[self.ref])
        before = inspect_workflow(workflow)
        view.bindings[self.ref]["delivery_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(SessionApiError, "source-invalid"):
            view.read("own", self.ref)
        view.bindings[self.ref] = binding
        view.bindings[self.ref]["input_version"] += 1
        with self.assertRaisesRegex(SessionApiError, "project-stale"):
            view.read("own", self.ref)
        self.assertEqual(inspect_workflow(workflow), before)

    def test_identical_foreign_workflow_and_foreign_principal_reject(self):
        view, _, workflow = self.prepare_choice()
        foreign = self.root / "foreign-workflow"
        shutil.copytree(workflow, foreign)
        view.bindings[self.ref]["workflow_root"] = str(foreign)
        with self.assertRaisesRegex(SessionApiError, "project-workflow-differs"):
            view.read("own", self.ref)
        with self.assertRaises(SessionApiError):
            view.read("other", self.ref)

    def test_deadline_is_rechecked_after_real_package_verification(self):
        view, _, _ = self.prepare_choice()
        checks = []

        def deadline():
            checks.append(True)
            if len(checks) == 2:
                raise TimeoutError("synthetic view deadline after verification")

        with self.assertRaisesRegex(TimeoutError, "after verification"):
            view.read("own", self.ref, check_deadline=deadline)
        self.assertEqual(len(checks), 2)

    def test_missing_activation_cannot_present_a_foreign_package_as_current(self):
        view, _, workflow = self.prepare_choice()
        foreign = self.root / "foreign-unactivated-workflow"
        shutil.copytree(workflow, foreign)
        state = self.intake._load("researcher", self.ref)
        state.pop("stage2_activation")
        self.intake._save(state, "synthetic-missing-activation", {"fixture": True})
        self.intake.db.commit()
        view.bindings[self.ref]["workflow_root"] = str(foreign)
        before = inspect_workflow(workflow)
        with self.assertRaisesRegex(SessionApiError, "stage2-not-activated"):
            view.read("own", self.ref)
        self.assertEqual(inspect_workflow(workflow), before)
