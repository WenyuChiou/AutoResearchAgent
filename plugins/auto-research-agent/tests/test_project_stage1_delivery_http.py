"""Real bounded HTTP/core package calls over authored offline source records."""

import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.project_host import ProjectHost
from stage1_deliverable.common import sha
import test_project_stage1_delivery as delivery_fixture


class ProjectStage1DeliveryHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        delivery_fixture.ProjectStage1DeliveryTests.setUpClass()

    def setUp(self):
        self.fixture = delivery_fixture.ProjectStage1DeliveryTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.token = "local-delivery-token-with-at-least-32-characters"
        self.fixture.intake.authenticate = lambda token: (
            "local-viewer" if token in (self.token, "alice-token") else None
        )
        self.saved = self.fixture.saved("http")
        self.host = ProjectHost(
            projects=self.fixture.intake,
            credential=self.token,
            stage1=self.fixture.stage1,
            files={},
            views=[],
            port=0,
        )
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.addCleanup(self.stop)
        self.worker.start()
        self.offer = self.host.project_stage1_delivery.register_records(
            self.saved["ref"],
            records_path=self.saved["path"],
            expected_records_sha256=sha(self.saved["path"].read_bytes()),
            expected_ledger_state_sha256=self.saved["ledger"].state_hash(),
        )
        self.body = self.fixture.body(self.saved, self.offer)
        self.base = "/api/projects/" + self.saved["ref"]

    def stop(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(3)
        self.assertFalse(self.worker.is_alive())

    def request(self, path, body=None, *, origin=None):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.host.server_port, timeout=30
        )
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers.update(
                {
                    "Origin": origin or self.host.expected_origin,
                    "Content-Type": "application/json",
                }
            )
        try:
            client.request(
                "POST" if body is not None else "GET",
                path,
                json.dumps(body).encode("utf-8") if body is not None else None,
                headers,
            )
            response = client.getresponse()
            return response.status, response.read()
        finally:
            client.close()

    def test_real_delivery_http_recovery_and_readonly_contract_have_same_hash(self):
        status, raw = self.request(self.base + "/stage1/deliver", self.body)
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertEqual(result["status"], "saved")
        self.assertFalse(result["stage1_complete"])
        with (
            patch(
                "research_workspace_native.project_stage1_delivery.package.build"
            ) as build,
            patch(
                "research_workspace_native.project_stage1_delivery.package.validate"
            ) as replay,
        ):
            status, raw = self.request(self.base + "/stage1/deliver", self.body)
            self.assertEqual(status, 200, raw)
            self.assertTrue(json.loads(raw)["replayed"])
            status, raw = self.request(self.base + "/overview")
            self.assertEqual(status, 200, raw)
            artifact = json.loads(raw)["stage1"]["delivery"]["canonical_package"]
            self.assertEqual(artifact["manifest_sha256"], result["manifest_sha256"])
            status, raw = self.request(self.base + "/contract")
            self.assertEqual(status, 200, raw)
            contract = json.loads(raw)
            self.assertEqual(
                contract["stages"]["1"]["artifacts"][0]["manifest_sha256"],
                result["manifest_sha256"],
            )
            self.assertFalse(contract["stages"]["1"]["accepted"])
            for stage in ("3", "4", "5", "6"):
                self.assertEqual(contract["stages"][stage]["status"], "planned")
                self.assertFalse(contract["stages"][stage]["connected"])
            build.assert_not_called()
            replay.assert_not_called()

    def test_client_path_cross_origin_and_stale_revision_reject_without_build(self):
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            for body, origin in (
                ({**self.body, "records_path": str(self.saved["path"])}, None),
                (self.body, "https://unrelated.example"),
                ({**self.body, "key": "stale", "revision": 999}, None),
            ):
                status, raw = self.request(
                    self.base + "/stage1/deliver", body, origin=origin
                )
                self.assertIn(status, (400, 403, 409), raw)
            build.assert_not_called()
        status, raw = self.request(self.base + "/history")
        self.assertEqual(status, 200, raw)
        action = next(
            row for row in json.loads(raw)["actions"] if row["key"] == "stale"
        )
        self.assertEqual(action["status"], "known-unsent")
        status, raw = self.request("/projects.html")
        self.assertEqual(status, 200, raw)
        self.assertIn(b'id="ledger-deliver"', raw)
        self.assertEqual(
            sha(raw), self.host.host_binding["served_files"]["/projects.html"]
        )


if __name__ == "__main__":
    unittest.main()
