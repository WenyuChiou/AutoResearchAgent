"""Production owner guard over real SQLite/Core; bootstrap probe is mocked."""

from copy import deepcopy
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from project_stage1_query_cases import ProjectQueryCases
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.project_stage1_records import ProjectStage1RecordsService
from research_workspace_native.session_api import SessionApiError
from test_workspace_project_intake import authenticate, bound_body


class SavedRecordOwnerCases(ProjectQueryCases):
    def ready(self):
        self.authorize()
        self.bootstrap()
        state = self.intake._load("alice", self.ref)
        return self.stage1._ledger(state, self.intake.binding(self.ref))

    def test_guard_and_factory_use_saved_owner_after_expiry_without_any_dispatch(self):
        run, ledger, report = self.ready()
        before = self.queries.saved_frontier(self.ref)
        budget = deepcopy(self.intake._load("alice", self.ref)["stage1_query_budget"])
        expiry = self.intake._load("alice", self.ref)["stage1_query_authorization"][
            "permit"
        ]["expires_at_unix"]
        materials = self.root / "materials"
        materials.mkdir()
        with self.assertRaisesRegex(SessionApiError, "storage-overlap"):
            self.queries.create_records_service(
                ProjectStage1DeliveryService(self.stage1),
                materials_root=self.intake.root,
            )
        for value in (
            self.queries.config["execution_source_root"],
            self.queries.config["execution_source_root"] + "/..",
        ):
            with self.assertRaisesRegex(SessionApiError, "storage-overlap"):
                self.queries.create_records_service(
                    ProjectStage1DeliveryService(self.stage1), materials_root=value
                )
        with self.assertRaisesRegex(SessionApiError, "delivery-differs"):
            self.queries.create_records_service(
                ProjectStage1DeliveryService(ProjectStage1Service(self.intake)),
                materials_root=materials,
            )
        with (
            self.no_probe(),
            patch.object(self.queries, "admit", side_effect=AssertionError("admit")),
            patch.object(
                self.queries, "verify_source", side_effect=AssertionError("source")
            ),
            patch(
                "research_workspace_native.project_query_permit.time.time",
                return_value=expiry + 1,
            ),
        ):
            records = self.queries.create_records_service(
                ProjectStage1DeliveryService(self.stage1), materials_root=materials
            )
            self.assertIsInstance(records, ProjectStage1RecordsService)
            with records.guard(run, ledger, report) as check:
                check()
        self.assertEqual(self.queries.saved_frontier(self.ref), before)
        self.assertEqual(
            self.intake._load("alice", self.ref)["stage1_query_budget"], budget
        )

    def test_offline_missing_and_ambiguous_owners_refuse_before_frontier_read(self):
        run, ledger, report = self.ready()
        service = self.queries.services.pop(self.ref)
        try:
            with patch.object(
                service, "_saved_frontier", side_effect=AssertionError("read")
            ):
                for value in (dict(run, query_owned=False), run):
                    with self.assertRaises(SessionApiError):
                        with self.queries.saved_records_guard(value, ledger, report):
                            self.fail("unowned guard admitted")
                self.queries.services[self.ref] = service
                service._projects["duplicate"] = service._projects[self.ref]
                self.queries.services["duplicate"] = service
                with self.assertRaisesRegex(SessionApiError, "ambiguous"):
                    with self.queries.saved_records_guard(run, ledger, report):
                        self.fail("ambiguous guard admitted")
        finally:
            self.queries.services.pop("duplicate", None)
            service._projects.pop("duplicate", None)
            self.queries.services[self.ref] = service

    def test_true_sqlite_reopen_requires_explicit_owner_restore_without_reprobe(self):
        run, ledger, report = self.ready()
        before = self.queries.saved_frontier(self.ref)
        self.queries.close()
        self.stage1.query_service = None
        self.intake.close()
        self.intake = ProjectIntakeService(self.root / "p", authenticate=authenticate)
        self.addCleanup(self.intake.close)
        self.stage1 = ProjectStage1Service(self.intake, limit=3)
        self.queries = self.bridge()
        with self.no_probe():
            with self.assertRaisesRegex(SessionApiError, "owner-ambiguous"):
                with self.queries.saved_records_guard(run, ledger, report):
                    self.fail("guard implicitly restored owner")
            self.assertEqual(self.queries.services, {})
            self.queries.restore_owner(
                "alice-token", self.ref, self.body("owner_offer", "restore-saved")
            )
            with self.queries.saved_records_guard(run, ledger, report) as check:
                check()
            self.assertEqual(self.queries.saved_frontier(self.ref), before)

    def test_crossed_root_manifest_report_and_registration_are_rejected(self):
        run, ledger, report = self.ready()
        service = self.queries.services[self.ref]
        for value, owned, replay in (
            (run, SimpleNamespace(root=self.root / "foreign"), report),
            (dict(run, manifest_sha256="0" * 64), ledger, report),
            (run, ledger, dict(report, state_sha256="0" * 64)),
            (run, ledger, dict(report, valid=False)),
        ):
            with self.assertRaises(SessionApiError):
                with self.queries.saved_records_guard(value, owned, replay):
                    self.fail("crossed saved records admitted")
        original = service._projects[self.ref]["item"]
        service._projects[self.ref]["item"] = dict(original, project_id="foreign")
        try:
            with self.assertRaisesRegex(SessionApiError, "binding-differs"):
                with self.queries.saved_records_guard(run, ledger, report):
                    self.fail("crossed registration admitted")
        finally:
            service._projects[self.ref]["item"] = original

    def test_guard_reloads_current_settings_before_saved_action_commit(self):
        run, ledger, report = self.ready()
        with self.assertRaises(SessionApiError):
            with self.queries.saved_records_guard(run, ledger, report) as check:
                state = self.intake._load("alice", self.ref)
                state["settings"]["resource_envelope"] += " changed"
                self.intake._save(state, "test-drift", {})
                check()

    def test_guard_rejects_owner_replacement_and_releases_both_locks(self):
        run, ledger, report = self.ready()
        service = self.queries.services[self.ref]
        try:
            with self.assertRaisesRegex(SessionApiError, "owner-unavailable"):
                with self.queries.saved_records_guard(run, ledger, report) as check:
                    self.queries.services.pop(self.ref)
                    check()
        finally:
            self.queries.services[self.ref] = service
        acquired = threading.Event()

        def lock_again():
            with self.intake._lock, service._lock:
                acquired.set()

        worker = threading.Thread(target=lock_again)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(acquired.is_set())

    def test_guard_rechecks_full_frontier_and_rejects_pending_inner_action(self):
        run, ledger, report = self.ready()
        extra = ledger.root / "unexpected-output.txt"
        try:
            with self.assertRaisesRegex(SessionApiError, "ledger-changed"):
                with self.queries.saved_records_guard(run, ledger, report) as check:
                    extra.write_bytes(b"unregistered write")
                    check()
        finally:
            extra.unlink(missing_ok=True)
        service = self.queries.services[self.ref]
        project = service._projects[self.ref]
        with service.store._edit(
            project["pid"],
            project["owner"],
            service.store.snapshot(project["pid"])["revision"],
            "test-unknown",
            {},
        ) as saved:
            saved["intents"]["lost"] = {"status": "execution-unknown"}
        with self.assertRaisesRegex(SessionApiError, "unreconciled-action"):
            with self.queries.saved_records_guard(run, ledger, report):
                self.fail("unknown writer admitted")

    def test_physical_owner_transaction_loss_refuses_without_reacquisition(self):
        run, ledger, report = self.ready()
        service = self.queries.services[self.ref]
        project = service._projects[self.ref]
        connection = service.store._owners[project["pid"]][1]
        with self.assertRaisesRegex(SessionApiError, "ledger-owner-lost"):
            with self.queries.saved_records_guard(run, ledger, report) as check:
                connection.rollback()
                check()
        self.assertFalse(connection.in_transaction)

    def test_query_lock_and_close_transition_wait_for_saved_guard(self):
        run, ledger, report = self.ready()
        service = self.queries.services[self.ref]
        entered, closing, done = threading.Event(), threading.Event(), threading.Event()

        def query_lock():
            entered.set()
            with service._lock:
                done.set()

        def close():
            closing.set()
            self.queries.close()

        first = threading.Thread(target=query_lock)
        second = threading.Thread(target=close)
        with self.queries.saved_records_guard(run, ledger, report) as check:
            first.start()
            self.assertTrue(entered.wait(5))
            self.assertFalse(done.wait(0.05))
            second.start()
            self.assertTrue(closing.wait(5))
            self.assertFalse(self.queries.closing)
            check()
        first.join(5)
        second.join(5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(done.is_set())
        self.assertTrue(self.queries.closing)

    def test_lost_owner_after_saved_sql_rolls_back_and_history_never_reexecutes(self):
        run, ledger, report = self.ready()
        service = self.queries.services[self.ref]
        body = bound_body(self.intake.read("alice-token", self.ref), "guarded-registry")
        original_save = self.intake._save
        calls = []

        def late_loss(state, kind, payload):
            result = original_save(state, kind, payload)
            if kind == "test-guarded-registry-saved":
                service._closing = True
            return result

        def produce(current, *unused):
            calls.append(True)
            current["guarded_output"] = "must roll back"
            return {"output": "retained observation"}

        try:
            with (
                patch.object(self.intake, "_save", side_effect=late_loss),
                self.assertRaisesRegex(SessionApiError, "owner-unavailable"),
            ):
                with self.queries.saved_records_guard(run, ledger, report) as check:
                    result = self.intake._perform(
                        "alice",
                        self.ref,
                        "test-guarded-registry",
                        body,
                        produce,
                        check_deadline=check,
                    )
                    self.assertEqual(result["status"], "execution-unknown")
        finally:
            service._closing = False
        self.assertNotIn("guarded_output", self.intake._load("alice", self.ref))
        replay = self.intake._perform(
            "alice",
            self.ref,
            "test-guarded-registry",
            body,
            lambda *args: self.fail("repeat producer"),
        )
        self.assertEqual(replay["status"], "execution-unknown")
        self.assertTrue(replay["replayed"])
        self.assertEqual(calls, [True])


def load_tests(loader, tests, pattern):
    # Parent supplies neutral setup helpers; don't rerun its distinct scenarios.
    return unittest.TestSuite(
        SavedRecordOwnerCases(name)
        for name in SavedRecordOwnerCases.__dict__
        if name.startswith("test_")
    )
