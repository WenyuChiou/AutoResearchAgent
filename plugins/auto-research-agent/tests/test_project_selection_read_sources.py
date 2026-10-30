"""One locked read reuses source verification; each new request verifies again."""

# ruff: noqa: E402 -- use the existing deterministic direct-delivery fixture.
from pathlib import Path
from contextvars import copy_context
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from research_workspace_native import project_stage2_direct_import as direct
from research_workspace_native import project_stage2_selection_view as view_module
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.project_selection_read_context import (
    verified_selection_read,
    verified_source_read,
)
import test_project_stage2_direct_cli as direct_fixture
from stage1_deliverable import common as output_guard


class SelectionReadSourcesTests(unittest.TestCase):
    def setUp(self):
        fixture = direct_fixture.DirectDeliveryCliTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.eligible_delivery()
        registered = fixture.import_package()
        self.fixture, self.ref = fixture, registered["project_ref"]
        self.selection = ProjectStage2SelectionService(
            fixture.intake, {self.ref: registered["selection_binding"]}
        )
        self.planning = ProjectStage3PlanningService(fixture.intake, self.selection)

    def inspect_spy(self):
        spy = Mock(wraps=direct.inspect_delivery)
        self.enterContext(patch.object(direct, "inspect_delivery", spy))
        self.enterContext(patch.object(view_module, "inspect_delivery", spy))
        return spy

    def test_planning_read_verifies_same_delivery_once_per_request(self):
        spy = self.inspect_spy()
        first = self.planning.read("synthetic-owner", self.ref)
        self.assertEqual(first["selection_status"], "pending")
        self.assertFalse(first["execution_authorized"])
        self.assertEqual(spy.call_count, 1)
        spy.reset_mock()
        self.assertEqual(self.planning.read("synthetic-owner", self.ref), first)
        self.assertEqual(spy.call_count, 1)

    def test_selection_read_verifies_same_delivery_once(self):
        spy = self.inspect_spy()
        result = self.selection.read("synthetic-owner", self.ref)
        self.assertEqual(result["selection_status"], "pending")
        self.assertEqual(spy.call_count, 1)

    def test_changed_source_is_rejected_on_the_next_request(self):
        self.planning.read("synthetic-owner", self.ref)
        path = self.fixture.delivery_root / "input_packet.json"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            with self.assertRaises(SessionApiError):
                self.planning.read("synthetic-owner", self.ref)
        finally:
            path.write_bytes(original)


class SourceReadScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.path = self.root / "source.txt"
        self.path.write_text("original", encoding="utf-8")
        self.intake = object()
        self.verify = Mock(
            side_effect=lambda root, pin: {"text": (root / pin).read_text()}
        )

    def read(self, intake=None, verifier=None, pin="source.txt"):
        return verified_source_read(
            self.intake if intake is None else intake,
            self.verify if verifier is None else verifier,
            self.root,
            pin,
        )

    def test_scope_ends_and_returns_independent_snapshots(self):
        with verified_selection_read(self.intake):
            first = self.read()
            first["text"] = "caller mutation"
            with verified_selection_read(self.intake):
                self.assertEqual(self.read(), {"text": "original"})
            self.assertEqual(self.read(), {"text": "original"})
            self.assertEqual(self.verify.call_count, 1)
        self.path.write_text("changed", encoding="utf-8")
        with verified_selection_read(self.intake):
            self.assertEqual(self.read(), {"text": "changed"})
        self.read()
        self.assertEqual(self.verify.call_count, 3)

    def test_foreign_intake_threads_and_verifiers_do_not_share(self):
        with verified_selection_read(self.intake):
            self.read()
            self.read(intake=object())
            result = []
            context = copy_context()
            worker = Thread(target=lambda: result.append(context.run(self.read)))
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [{"text": "original"}])
            other = Mock(return_value={"text": "other verifier"})
            self.assertEqual(self.read(verifier=other), {"text": "other verifier"})
        self.assertEqual(self.verify.call_count, 3)
        self.assertEqual(other.call_count, 1)

    def test_failure_is_not_retained_and_pins_remain_distinct(self):
        with verified_selection_read(self.intake):
            with self.assertRaises(FileNotFoundError):
                self.read(pin="new.txt")
            (self.root / "new.txt").write_text("new", encoding="utf-8")
            self.assertEqual(self.read(pin="new.txt"), {"text": "new"})
            self.assertEqual(self.read(), {"text": "original"})
        self.assertEqual(self.verify.call_count, 3)

    def test_forbidden_alias_cannot_reuse_an_accepted_root(self):
        alias = self.root / "synthetic-link"
        original_resolve = Path.resolve
        original_reject = output_guard.reject_links

        def resolve(path, *args, **kwargs):
            return (
                self.root if path == alias else original_resolve(path, *args, **kwargs)
            )

        def reject(path):
            if Path(path) == alias:
                raise output_guard.DeliverableError("synthetic linked root rejected")
            return original_reject(path)

        verifier = Mock(
            side_effect=lambda root, pin: {
                "text": (output_guard.private_output(root) / pin).read_text()
            }
        )
        # Model an alias without requiring Windows symlink creation privileges.
        with (
            patch.object(Path, "resolve", resolve),
            patch.object(output_guard, "reject_links", reject),
        ):
            with self.assertRaisesRegex(output_guard.DeliverableError, "linked root"):
                verified_source_read(self.intake, verifier, alias, "source.txt")
            verifier.reset_mock()
            with verified_selection_read(self.intake):
                self.assertEqual(
                    verified_source_read(
                        self.intake, verifier, self.root, "source.txt"
                    ),
                    {"text": "original"},
                )
                with self.assertRaisesRegex(
                    output_guard.DeliverableError, "linked root"
                ):
                    verified_source_read(self.intake, verifier, alias, "source.txt")
            self.assertEqual(verifier.call_count, 2)


if __name__ == "__main__":
    unittest.main()
