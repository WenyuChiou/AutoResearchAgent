"""Locked GET verification reuse; synthetic inputs, no native or model calls."""

# ruff: noqa: E402 -- repository fixture imports.
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parent),
]

from project_stage2_selection_fixture import Stage2SelectionFixture
from research_workspace_native.project_selection_read_context import (
    current_selection_context,
    verified_selection_read,
)
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


class PlanningReadVerificationTests(Stage2SelectionFixture):
    def planning(self):
        selection, _, _ = self.prepare_choice(ProjectStage2SelectionService)
        return selection, ProjectStage3PlanningService(self.intake, selection)

    def test_whole_read_verifies_once_and_each_new_request_verifies_again(self):
        _, planning = self.planning()
        original = ProjectStage2SelectionView._verify_current_context
        with patch.object(
            ProjectStage2SelectionView,
            "_verify_current_context",
            autospec=True,
            side_effect=original,
        ) as checked:
            first = planning.read("own", self.ref)
            self.assertEqual(checked.call_count, 1)
            second = planning.read("own", self.ref)
            self.assertEqual(checked.call_count, 2)
        self.assertEqual(first, second)
        self.assertFalse(first["execution_authorized"])

    def test_next_request_rejects_changed_hash_version_and_frontier(self):
        selection, planning = self.planning()
        planning.read("own", self.ref)
        binding = selection.bindings[self.ref]
        for field, value, error in (
            ("delivery_manifest_sha256", "0" * 64, "source-invalid"),
            ("input_version", True, "project-stale"),
        ):
            previous = binding[field]
            binding[field] = value
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(SessionApiError, error),
            ):
                planning.read("own", self.ref)
            binding[field] = previous
        state = self.intake._load("researcher", self.ref)
        state["stage2_frontier"]["workflow_head_sha256"] = "0" * 64
        self.intake._save(state, "synthetic-tampered-frontier", {"fixture": True})
        self.intake.db.commit()
        with self.assertRaises(SessionApiError):
            planning.read("own", self.ref)

    def test_path_roots_keep_original_output_and_fresh_verification(self):
        selection, planning = self.planning()
        expected = planning.read("own", self.ref)
        for view in (selection, planning.direction.selection):
            for field in ("workflow_root", "delivery_root"):
                view.bindings[self.ref][field] = Path(view.bindings[self.ref][field])
        original = ProjectStage2SelectionView._verify_current_context
        with patch.object(
            ProjectStage2SelectionView,
            "_verify_current_context",
            autospec=True,
            side_effect=original,
        ) as checked:
            self.assertEqual(planning.read("own", self.ref), expected)
            before = checked.call_count
            self.assertEqual(before, 2)
            self.assertEqual(planning.read("own", self.ref), expected)
            self.assertEqual(checked.call_count, before + 2)

    def test_deadline_failure_does_not_leave_a_verified_request(self):
        _, planning = self.planning()
        with self.assertRaises(TimeoutError):
            planning.read(
                "own", self.ref, check_deadline=Mock(side_effect=TimeoutError)
            )
        with patch.object(
            ProjectStage2SelectionView,
            "_verify_current_context",
            side_effect=SessionApiError("fresh-request-proof"),
        ):
            with self.assertRaisesRegex(SessionApiError, "fresh-request-proof"):
                planning.read("own", self.ref)


class ReadContextIsolationTests(unittest.TestCase):
    def setUp(self):
        self.intake = SimpleNamespace(_principal=lambda credential: credential)
        self.result = ({"value": []}, (object(), {"activation": []}, {}, {}, Path(".")))
        self.view = SimpleNamespace(
            intake=self.intake,
            bindings={"project-a": {}, "project-b": {}},
            _verify_current_context=Mock(side_effect=lambda *a, **k: self.result),
            _project_context=object(),
            _verified_frontier=object(),
        )

    def read(self, credential="owner", project="project-a", **kwargs):
        return current_selection_context(
            self.view,
            credential,
            project,
            validate_frontier=kwargs.get("frontier", True),
        )

    def test_returned_json_cannot_modify_reused_verified_result(self):
        with verified_selection_read(self.intake):
            first = self.read()
            first[0]["value"].append("changed")
            first[1][1]["activation"].append("changed")
            second = self.read()
            self.assertEqual(second[0], {"value": []})
            self.assertEqual(second[1][1], {"activation": []})
            second[0]["value"].append("second change")
            self.assertEqual(self.read()[0], {"value": []})
        self.assertEqual(self.view._verify_current_context.call_count, 1)

    def test_principal_project_binding_and_verifier_changes_do_not_reuse(self):
        with verified_selection_read(self.intake):
            self.read()
            self.read("other")
            self.read(project="project-b")
            self.view.bindings["project-a"]["pin"] = "changed"
            self.read()
            self.view.bindings["project-a"].clear()
            self.view._verified_frontier = object()
            self.read()
        self.assertEqual(self.view._verify_current_context.call_count, 5)

    def test_foreign_intake_and_unverified_frontier_do_not_reuse(self):
        with verified_selection_read(self.intake):
            self.read()
            self.read(frontier=False)
            self.read(frontier=1)
            self.view.intake = SimpleNamespace(_principal=lambda credential: credential)
            self.read()
        self.assertEqual(self.view._verify_current_context.call_count, 4)

    def test_failed_verification_and_closed_scope_do_not_survive(self):
        self.view._verify_current_context.side_effect = [
            ValueError("first"),
            self.result,
        ]
        with (
            self.assertRaisesRegex(ValueError, "first"),
            verified_selection_read(self.intake),
        ):
            self.read()
        with verified_selection_read(self.intake):
            self.read()
            retained = copy_context()
        self.view._verify_current_context.side_effect = RuntimeError("fresh")
        with self.assertRaisesRegex(RuntimeError, "fresh"):
            retained.run(self.read)

    def test_copied_context_in_another_thread_does_not_reuse(self):
        with verified_selection_read(self.intake):
            self.read()
            context = copy_context()
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(context.run, self.read).result(timeout=5)
        self.assertEqual(self.view._verify_current_context.call_count, 2)


if __name__ == "__main__":
    unittest.main()
