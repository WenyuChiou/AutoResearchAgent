"""Physical copies, real SQLite and fake execution; no native/Hub/model calls."""

import os
from pathlib import Path
import threading
import time
from unittest.mock import patch

from planned_query_fixture import QueryCase
from research_workspace_native.planned_query_contract import tree_sha
from research_workspace_native.query_storage import LedgerOwners
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha


class QueryHardlinkStorageTests(QueryCase):
    def link(self, source, destination):
        os.link(source, destination)
        self.addCleanup(destination.unlink, missing_ok=True)
        self.assertEqual(source.stat().st_nlink, 2)

    def ledger_owner(self):
        return self.ledger_root.parent / (
            ".planned-query-owner-"
            + sha(os.path.normcase(str(self.ledger_root.resolve())).encode())
            + ".sqlite3"
        )

    def reject(self):
        with self.assertRaisesRegex(SessionApiError, "mutable-hardlink-refused"):
            self.service()
        self.assertEqual(self.children, [])

    def test_shared_parent_events_refuse_before_any_writer(self):
        original = tree_sha(self.parent_ledger)
        target = self.ledger_root / "stage_events.jsonl"
        target.unlink()
        self.link(self.parent_ledger / target.name, target)
        self.assertEqual(tree_sha(self.ledger_root), original)
        self.reject()
        self.assertEqual(tree_sha(self.parent_ledger), original)
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertFalse((self.root / "query.sqlite3.created").exists())
        self.assertFalse(self.ledger_owner().exists())

    def test_every_existing_mutable_ledger_file_requires_single_link(self):
        for number, path in enumerate(sorted(self.ledger_root.rglob("*"))):
            if path.is_file():
                alias = self.root / ("immutable-alias-" + str(number))
                before = sha(path.read_bytes())
                self.link(path, alias)
                with self.subTest(path=path.name):
                    self.reject()
                    self.assertEqual(sha(alias.read_bytes()), before)
                alias.unlink()
        self.assertFalse((self.root / "query.sqlite3.created").exists())

    def reject_paths(self, stem, suffixes):
        source = self.root / "protected-regular-file"
        source.write_bytes(b"protected synthetic bytes\n")
        before = source.read_bytes()
        for suffix in suffixes:
            target = Path(str(stem) + suffix)
            self.link(source, target)
            with self.subTest(suffix=suffix):
                self.reject()
                self.assertEqual(source.read_bytes(), before)
            target.unlink()

    def test_control_database_and_every_sidecar_reject_hardlinks(self):
        self.reject_paths(
            self.root / "query.sqlite3", ("", "-wal", "-shm", "-journal", ".created")
        )

    def test_ledger_owner_database_and_every_sidecar_reject_hardlinks(self):
        self.reject_paths(self.ledger_owner(), ("", "-wal", "-shm", "-journal"))

    def test_project_owner_database_and_every_sidecar_reject_hardlinks(self):
        pid = "planned-query-" + sha(b"case")[:32]
        owner = self.root / ("query.sqlite3.owner-" + sha(pid.encode()) + ".sqlite3")
        self.reject_paths(owner, ("", "-wal", "-shm", "-journal"))

    def test_nonregular_control_file_refuses_before_marker(self):
        target = self.root / "query.sqlite3"
        target.mkdir()
        with self.assertRaisesRegex(SessionApiError, "mutable-file-required"):
            self.service()
        self.assertFalse((self.root / "query.sqlite3.created").exists())
        self.assertEqual(self.children, [])

    def test_standalone_ledger_owner_never_opens_shared_database(self):
        source = self.root / "protected-owner"
        source.write_bytes(b"not SQLite; must remain untouched")
        self.link(source, self.ledger_owner())
        with self.assertRaisesRegex(SessionApiError, "mutable-hardlink-refused"):
            LedgerOwners([self.ledger_root])
        self.assertEqual(source.read_bytes(), b"not SQLite; must remain untouched")

    def execute_injected_link(self, phase):
        alias = self.root / "new-protected-alias"
        captured = {}

        def admit(event):
            matches = (
                event["phase"] == phase
                if isinstance(phase, str)
                else isinstance(event["phase"], dict)
            )
            if matches and not alias.exists():
                self.link(self.ledger_root / "stage_events.jsonl", alias)
                captured["sha256"] = sha(alias.read_bytes())
                captured["ledger_sha256"] = tree_sha(self.ledger_root)
            return True

        service = self.service(admit=admit)
        request = self.request(service)
        parent = tree_sha(self.parent_ledger)
        with self.no_probe(), self.fake_runner():
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            row = self.wait(service)
        self.assertEqual(sha(alias.read_bytes()), captured["sha256"])
        self.assertEqual(tree_sha(self.ledger_root), captured["ledger_sha256"])
        self.assertEqual(tree_sha(self.parent_ledger), parent)
        self.assertEqual(self.children, [])
        self.assertEqual(service.view("secret", "case")["budget"]["attempts"], 1)
        self.assertEqual(row["error"]["code"], "query-mutable-hardlink-refused")
        self.assertEqual(
            service.execute("secret", "case", request, deadline=time.monotonic() + 30),
            row,
        )
        return row

    def test_admission_added_link_without_byte_drift_refuses_before_ledger_write(self):
        row = self.execute_injected_link("before-runner")
        self.assertEqual(
            (row["status"], row["outcome"]), ("completed", "refused-known-unsent")
        )

    def test_spawn_admission_added_link_without_byte_drift_blocks_backend(self):
        row = self.execute_injected_link({})
        self.assertEqual(
            (row["status"], row["outcome"]), ("execution-unknown", "unknown")
        )

    def test_new_link_before_request_does_not_reserve_budget(self):
        service = self.service()
        request = self.request(service)
        marker = self.root / "query.sqlite3.created"
        self.link(marker, self.root / "protected-marker")
        with self.assertRaisesRegex(SessionApiError, "mutable-hardlink-refused"):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
        self.assertEqual(service.view("secret", "case")["budget"]["attempts"], 0)
        self.assertEqual(service.view("secret", "case")["history"], [])
        self.assertEqual(self.children, [])

    def test_new_link_after_intent_prevents_worker_journal_write(self):
        service = self.service()
        request = self.request(service)
        marker = self.root / "query.sqlite3.created"
        errors, observed = [], {}
        original = threading.Thread.start

        def linked_start(thread):
            if getattr(thread, "_target", None) == service._run:
                self.link(marker, self.root / "protected-marker")
                observed["changes"] = service.store.db.total_changes
            return original(thread)

        with (
            patch.object(threading.Thread, "start", linked_start),
            patch.object(threading, "excepthook", errors.append),
        ):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            row = self.wait(service)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0].exc_value, SessionApiError)
        self.assertEqual(errors[0].exc_value.code, "query-mutable-hardlink-refused")
        self.assertEqual(service.store.db.total_changes, observed["changes"])
        self.assertEqual(row["status"], "dispatch-unobserved")
        self.assertEqual(
            service.execute("secret", "case", request, deadline=time.monotonic() + 30),
            row,
        )
        self.assertEqual(self.children, [])

    def test_real_physical_copy_runs_fake_backend_and_preserves_parent(self):
        service = self.service()
        parent = tree_sha(self.parent_ledger)
        with self.no_probe(), self.fake_runner():
            service.execute(
                "secret", "case", self.request(service), deadline=time.monotonic() + 30
            )
            row = self.wait(service)
        self.assertEqual((row["status"], len(self.children)), ("completed", 1))
        self.assertEqual(tree_sha(self.parent_ledger), parent)
        self.assertFalse(row["result"]["stage_complete"])

    def test_worker_start_failure_with_linked_control_cannot_append_failure(self):
        service = self.service()
        request = self.request(service)
        marker = self.root / "query.sqlite3.created"
        changes = {}
        original = threading.Thread.start

        def refused(thread):
            if getattr(thread, "_target", None) == service._run:
                self.link(marker, self.root / "protected-marker")
                changes["total"] = service.store.db.total_changes
                raise RuntimeError("synthetic start refusal after link")
            return original(thread)

        with patch.object(threading.Thread, "start", refused):
            with self.assertRaisesRegex(SessionApiError, "mutable-hardlink-refused"):
                service.execute(
                    "secret", "case", request, deadline=time.monotonic() + 30
                )
        self.assertEqual(service.store.db.total_changes, changes["total"])
        row = service.get_action("secret", "case", request["key"])
        self.assertEqual(row["status"], "dispatch-unobserved")
        self.assertEqual(self.children, [])
        self.assertEqual(
            service.execute("secret", "case", request, deadline=time.monotonic() + 30),
            row,
        )
        worker = service._workers["case"]
        self.assertIsNone(worker.ident)
        self.assertFalse(worker.is_alive())
        (self.root / "protected-marker").unlink()
        service.close()
        self.assertTrue(service._closed)
        self.assertEqual(service.store._owners, {})
        self.assertEqual(service.ledger_owners.connections, [])
        reopened = self.service()
        recovered = reopened.get_action("secret", "case", request["key"])
        self.assertEqual(recovered["status"], "execution-unknown")
        self.assertEqual(
            {k: v for k, v in recovered.items() if k != "status"},
            {k: v for k, v in row.items() if k != "status"},
        )
        self.assertEqual(
            reopened.execute("secret", "case", request, deadline=time.monotonic() + 30),
            recovered,
        )
        self.assertEqual(self.children, [])

    def test_queued_ledger_link_records_safe_refusal_without_ledger_write(self):
        service = self.service()
        request = self.request(service)
        alias = self.root / "protected-ledger-events"
        before = {}
        original = threading.Thread.start

        def linked(thread):
            if getattr(thread, "_target", None) == service._run:
                self.link(self.ledger_root / "stage_events.jsonl", alias)
                before["sha"] = sha(alias.read_bytes())
            return original(thread)

        with patch.object(threading.Thread, "start", linked):
            service.execute("secret", "case", request, deadline=time.monotonic() + 30)
            row = self.wait(service)
        self.assertEqual(
            (row["status"], row["outcome"]), ("completed", "refused-known-unsent")
        )
        self.assertEqual(row["error"]["code"], "query-mutable-hardlink-refused")
        self.assertEqual(sha(alias.read_bytes()), before["sha"])
        self.assertEqual(self.children, [])

    def test_failed_start_closes_unstarted_worker_and_releases_real_owners(self):
        service = self.service()
        request = self.request(service)
        owner = service._projects["case"]["owner"]
        original = threading.Thread.start

        def refused(thread):
            if getattr(thread, "_target", None) == service._run:
                raise RuntimeError("synthetic worker start failure")
            return original(thread)

        with patch.object(threading.Thread, "start", refused):
            with self.assertRaisesRegex(RuntimeError, "synthetic worker start failure"):
                service.execute(
                    "secret", "case", request, deadline=time.monotonic() + 30
                )
        worker = service._workers["case"]
        self.assertIsNone(worker.ident)
        self.assertFalse(worker.is_alive())
        row = service.get_action("secret", "case", request["key"])
        self.assertEqual(row["status"], "execution-unknown")
        self.assertEqual(
            service.execute("secret", "case", request, deadline=time.monotonic() + 30),
            row,
        )
        self.assertEqual(self.children, [])
        service.close()
        self.assertTrue(service._closed)
        self.assertEqual(service.store._owners, {})
        self.assertEqual(service.ledger_owners.connections, [])
        reopened = self.service()
        self.assertNotEqual(reopened._projects["case"]["owner"], owner)
        self.assertEqual(reopened.get_action("secret", "case", request["key"]), row)
        self.assertEqual(
            reopened.execute("secret", "case", request, deadline=time.monotonic() + 30),
            row,
        )
        with self.assertRaisesRegex(SessionApiError, "query-unreconciled-action"):
            reopened.offer("secret", "case")
        self.assertEqual(self.children, [])
