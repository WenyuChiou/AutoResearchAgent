"""Real authenticated HTTP and saved automatic results; authored model output only."""

import http.client
import json
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_host import ProjectHost
from stage1_deliverable.common import sha
import test_project_stage1_execution as execution_fixture


class AutomaticStage1HttpTests(unittest.TestCase):
    fixture = execution_fixture.AutomaticStage1ProductionTests.fixture

    def setUp(self):
        case, saved, owners, execution, self.calls = self.fixture()
        self.case, self.ref = case, saved["ref"]
        # The existing saved fixture belongs to alice. A separate bootstrap
        # principal constructs the real host; every request still authenticates
        # against the actual intake owner, without changing saved identities.
        bootstrap = "synthetic-bootstrap-token-with-at-least-32-characters"
        authenticate = case.intake.authenticate
        case.intake.authenticate = lambda credential: (
            "local-viewer" if credential == bootstrap else authenticate(credential)
        )
        self.host = ProjectHost(
            projects=case.intake,
            credential=bootstrap,
            models=owners.project_models,
            stage1=case.stage1,
            files={},
            views=[],
            port=0,
        )
        self.host.authenticate = case.intake.authenticate
        for name in (
            "project_stage1_delivery",
            "project_stage1_records",
            "project_records_prepare",
        ):
            setattr(self.host, name, getattr(owners, name))
        owners.project_models.automatic_stage1 = None
        registered = self.host.register_stage1_execution(
            self.ref,
            permit_path=execution.path,
            permit_sha256=execution.permit_sha256,
            output_root=execution.root,
        )
        self.assertFalse(registered["model_or_source_started"])
        self.execution = self.host.project_stage1_execution
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.close_host)

    def close_host(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())

    def request(self, path, *, method="GET", headers=None, body=None):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_port, timeout=30
        )
        supplied = {"Authorization": "Bearer alice-token"}
        supplied.update(headers or {})
        if body is not None:
            supplied.update(
                {
                    "Origin": self.host.expected_origin,
                    "Content-Type": "application/json",
                }
            )
        try:
            client.request(method, path, body=body, headers=supplied)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_progress_and_full_note_reads_are_bound_and_passive(self):
        result = self.host.continue_stage1(
            "alice-token",
            self.ref,
            run_id="synthetic-http-delivery",
            deadline=time.monotonic() + 300,
            max_actions=64,
        )
        self.assertEqual(result["reason"], "saved-delivery", result)
        changes, count = self.case.intake.db.total_changes, len(self.calls)
        code, overview = self.request(f"/api/projects/{self.ref}/overview")
        self.assertEqual(code, 200, overview)
        progress = overview["stage1"]["automatic_production"]
        self.assertEqual(len(progress["automatically_recorded"]), 2)
        self.assertEqual(progress["automatic_pending"], [])
        self.assertEqual(progress["technical_blocked"], [])
        self.assertEqual(progress["researcher_questions"], [])
        self.assertEqual(len(progress["notes"]), 2)
        self.assertFalse(progress["stage1_complete"])
        self.assertFalse(progress["stage2_started"])
        self.assertNotIn(str(self.execution.root), json.dumps(progress))
        for row in progress["notes"]:
            code, note = self.request(row["url"])
            self.assertEqual(code, 200, note)
            self.assertEqual(note["sha256"], row["sha256"])
            self.assertEqual(sha(note["text"].encode("utf8")), row["sha256"])
            self.assertEqual(note["binding"], progress["binding"])
            self.assertEqual(note["run_ref"], progress["run_ref"])
            self.assertEqual(
                note["ledger_state_sha256"], progress["ledger_state_sha256"]
            )
            self.assertFalse(note["human_acceptance"])
            self.assertNotIn(str(self.execution.root), json.dumps(note))
        self.assertEqual(self.case.intake.db.total_changes, changes)
        self.assertEqual(len(self.calls), count)
        code, _ = self.request(
            f"/api/projects/{self.ref}/stage1/automatic-notes/" + "0" * 64
        )
        self.assertEqual(code, 404)
        row = progress["notes"][0]
        state = self.case.intake._load("alice", self.ref)
        applied = state["stage1_automatic_production"]["applied"][row["work_id"]]
        Path(applied["note_path"]).write_bytes(b"tampered synthetic note")
        code, error = self.request(row["url"])
        self.assertEqual(code, 409, error)
        self.assertEqual(error["error"], "automatic-stage1-note-bytes-differ")
        self.assertEqual(len(self.calls), count)

    def test_default_and_other_projects_do_not_adopt_the_registered_producer(self):
        other = self.case.intake.create(
            "alice-token",
            {"key": "other-http-project", "topic": "Another authored topic"},
        )["project_ref"]
        code, overview = self.request(f"/api/projects/{other}/overview")
        self.assertEqual(code, 200, overview)
        self.assertIsNone(overview["stage1"]["automatic_production"])
        code, _ = self.request(
            f"/api/projects/{other}/stage1/automatic-notes/" + "0" * 64
        )
        self.assertEqual(code, 409)
        self.host.project_stage1_execution = None
        code, stage1 = self.request(f"/api/projects/{self.ref}/stage1")
        self.assertEqual(code, 200, stage1)
        self.assertIsNone(stage1["automatic_production"])
        code, _ = self.request(
            f"/api/projects/{self.ref}/stage1/automatic-notes/" + "0" * 64
        )
        self.assertEqual(code, 409)
        self.assertEqual(self.calls, [])

    def test_note_route_retains_auth_origin_method_and_opaque_reference_guards(self):
        path = f"/api/projects/{self.ref}/stage1/automatic-notes/" + "0" * 64
        changes = self.case.intake.db.total_changes
        code, overview = self.request(f"/api/projects/{self.ref}/overview")
        self.assertEqual(code, 200, overview)
        progress = overview["stage1"]["automatic_production"]
        self.assertGreater(len(progress["automatic_pending"]), 0)
        self.assertEqual(progress["automatically_recorded"], [])
        self.assertEqual(progress["researcher_questions"], [])
        self.assertEqual(progress["model_calls_reserved"], 0)
        for headers, expected in (
            ({"Authorization": "Bearer invalid"}, 401),
            ({"Origin": "https://foreign.invalid"}, 403),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(path, headers=headers)[0], expected)
        self.assertEqual(self.request(path, method="POST", body=b"{}")[0], 400)
        self.assertEqual(self.request(path, body=b"{}")[0], 400)
        self.assertEqual(self.request(path + "?path=private.json")[0], 404)
        self.assertEqual(self.case.intake.db.total_changes, changes)
        self.assertEqual(self.calls, [])
        self.execution.path.write_bytes(self.execution.path.read_bytes() + b" ")
        code, error = self.request(f"/api/projects/{self.ref}/overview")
        self.assertEqual(code, 409, error)
        self.assertEqual(error["error"], "automatic-stage1-parent-changed")
        self.assertEqual(self.case.intake.db.total_changes, changes)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
