"""HTTP/SQLite feedback recovery and failure bounds; no task dispatch occurs."""

import http.client
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

import test_research_workspace_atlas_feedback as fixtures
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.maintenance_inbox import MaintenanceInbox


class AtlasFeedbackSafetyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AtlasFeedbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.files, self.views = self.fixture.files, self.fixture.views
        self.db = self.fixture.db

    def start(self, **options):
        server = AtlasHost(
            files=self.files, views=self.views, maintenance_db=self.db, **options
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server

    def request(self, server, method, path, body=None):
        return self.fixture.request(server, method, path, body)

    @staticmethod
    def body(key):
        return json.dumps({"stage": 1, "message": "Keep the v6 graph.", "key": key})

    def test_actual_response_loss_then_keyed_get_has_one_save_and_no_dispatch(self):
        server = self.start()
        committed = threading.Event()
        original = server.maintenance.submit

        def observed(*args, **kwargs):
            result = original(*args, **kwargs)
            committed.set()
            return result

        with patch.object(server.maintenance, "submit", side_effect=observed) as submit:
            client = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=3
            )
            try:
                client.request(
                    "POST",
                    "/api/maintenance/stage1",
                    self.body("lost-response"),
                    {
                        "Origin": server.expected_origin,
                        "Authorization": "Bearer " + server.credential,
                        "Content-Type": "application/json",
                    },
                )
            finally:
                client.close()  # Never read the response; recover only through GET.
            self.assertTrue(committed.wait(2), "POST did not reach durable commit")
            writes = server.maintenance.db.total_changes
            status, saved = self.request(
                server, "GET", "/api/maintenance/stage1/lost-response"
            )
            self.assertEqual(status, 200)
            self.assertEqual(saved["status"], "recorded-not-dispatched")
            self.assertEqual(saved["manifest_sha256"], self.views[0]["manifest_sha256"])
            again = self.request(server, "GET", "/api/maintenance/stage1/lost-response")
            self.assertEqual(again[1]["sequence"], saved["sequence"])
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(server.maintenance.db.total_changes, writes)
            self.assertEqual(len(server.maintenance.history("stage1")), 1)
            self.assertEqual(server.api._projects, {})

    def test_accepted_colon_and_dot_key_round_trips_through_http_get(self):
        server = self.start()
        status, saved = self.request(
            server, "POST", "/api/maintenance/stage1", self.body("ui:colon.1")
        )
        self.assertEqual(status, 200)
        status, recovered = self.request(
            server, "GET", "/api/maintenance/stage1/ui:colon.1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(recovered["record_sha256"], saved["record_sha256"])
        self.assertEqual(recovered["sequence"], saved["sequence"])

    def test_real_occupied_port_failure_closes_created_sqlite_handle(self):
        occupied = self.start()
        failed_db = self.fixture.fixture.root / "bind-failed.sqlite"
        captured = []

        def capture(*args, **kwargs):
            inbox = MaintenanceInbox(*args, **kwargs)
            captured.append(inbox)
            return inbox

        with patch(
            "research_workspace_native.maintenance_inbox.MaintenanceInbox",
            side_effect=capture,
        ):
            with self.assertRaises(OSError):
                AtlasHost(
                    files=self.files,
                    views=self.views,
                    maintenance_db=failed_db,
                    port=occupied.server_port,
                )
        self.assertEqual(len(captured), 1)
        self.addCleanup(captured[0].close)
        with self.assertRaises(sqlite3.ProgrammingError):
            captured[0].db.execute("SELECT 1")

    def test_invalid_template_does_not_create_maintenance_database(self):
        broken = dict(self.files)
        broken[self.views[0]["url"]] = b"<html><body>invalid template</body></html>"
        failed_db = self.fixture.fixture.root / "template-failed.sqlite"
        with patch(
            "research_workspace_native.maintenance_inbox.MaintenanceInbox"
        ) as make:
            with self.assertRaisesRegex(ValueError, "template contract"):
                AtlasHost(files=broken, views=self.views, maintenance_db=failed_db)
            make.assert_not_called()
        self.assertFalse(failed_db.exists())

    def test_http_request_waiting_for_inbox_lock_expires_before_insert(self):
        server = self.start(timeout=0.25)
        entered, finished, response_lost = (threading.Event() for _ in range(3))
        original, outcomes = server.maintenance.submit, []

        def waiting(*args, **kwargs):
            entered.set()
            try:
                return original(*args, **kwargs)
            finally:
                finished.set()

        def request():
            try:
                outcomes.append(
                    self.request(
                        server, "POST", "/api/maintenance/stage1", self.body("expired")
                    )
                )
            except OSError as error:
                outcomes.append(error)
            finally:
                response_lost.set()

        with patch.object(server.maintenance, "submit", side_effect=waiting) as submit:
            with server.maintenance._lock:
                worker = threading.Thread(target=request, daemon=True)
                worker.start()
                self.assertTrue(
                    entered.wait(2), "POST did not queue for the inbox lock"
                )
                self.assertTrue(response_lost.wait(2), "accepted socket did not expire")
                self.assertIsInstance(outcomes[0], OSError)
            self.assertTrue(finished.wait(2), "queued operation did not finish")
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(server.maintenance.history("stage1"), [])
            self.assertEqual(server.api._projects, {})
        bindings = {
            row["ref"]: {
                field: row[field]
                for field in ("project_id", "index_sha256", "manifest_sha256")
            }
            for row in self.views
        }
        reopened = MaintenanceInbox(self.db, bindings)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.history("stage1"), [])


if __name__ == "__main__":
    unittest.main()
