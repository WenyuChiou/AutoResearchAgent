"""Real temporary HTTP + durable broker; all model I/O is injected synthetic."""

import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace_native.atlas_host import load_views
from research_workspace_native.stage_run_http import StageRunHost
from research_workspace_native.http import token_authenticator
from research_workspace_native.stage_run_service import StageRunService
from stage1_deliverable.common import sha
from test_native_stage_run_case import load_builder
from test_stage_run_service import Model, Pipeline


class StageRunHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        case = load_builder().build(self.root / "case")
        files, views = load_views(case["host_config_path"], case["host_config_sha256"])
        permit = dict(
            kind="NativeStagePilotPermit",
            schema_version="1.0.0",
            project_id="http-pilot",
            source_sha256="b" * 64,
            case_sha256="c" * 64,
            output_root=str(self.root / "budget"),
            model="test-only",
            max_calls=8,
            max_seconds=900,
            execution_scope="repository-saved-content-only",
            external_search=False,
            frozen_subjects=False,
            permission_id="explicit-synthetic-test",
        )
        path = self.root / "permit.json"
        path.write_text(json.dumps(permit))
        self.token = "s" * 40
        self.service = StageRunService(
            path,
            sha(path.read_bytes()),
            pipeline=Pipeline(),
            authenticate=token_authenticator({self.token: "local-viewer"}),
        )
        self.model = Model(self.service)
        self.model.status = lambda: dict(active=False, native_view=None)
        self.service.attach_model(self.model)
        self.host = StageRunHost(
            files, views, service=self.service, credential=self.token
        )
        self.thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.thread.start()
        self.base = "/api/stage-run/projects/" + self.service.ref

    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(5)
        self.temp.cleanup()

    def request(self, method, path, body=None, **changes):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Origin": self.host.expected_origin,
        }
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        headers.update(changes)
        client = http.client.HTTPConnection(*self.host.server_address, timeout=5)
        try:
            client.request(method, path, body, headers)
            result = client.getresponse()
            return result.status, result.read()
        finally:
            client.close()

    def test_baseline_graph_and_execution_overlay_are_both_served(self):
        status, raw = self.request("GET", self.host.views[0]["url"])
        self.assertEqual(status, 200)
        self.assertIn(b"stage-run-panel.js", raw)
        self.assertIn(b"atlas-network.js", raw)
        for route in (
            "/stage-run-panel.js",
            "/stage-run-panel.css",
            "/stage-run-bootstrap.js",
        ):
            self.assertEqual(self.request("GET", route)[0], 200)
        status, binding_raw = self.request("GET", "/host-binding.json")
        self.assertEqual(status, 200)
        binding = json.loads(binding_raw)
        for route, expected in binding["served_files"].items():
            with self.subTest(route=route):
                status, served = self.request("GET", route)
                self.assertEqual(status, 200)
                self.assertEqual(sha(served), expected)
        self.assertIn(
            b"A bounded real model pilot is registered.", self.request("GET", "/")[1]
        )
        self.assertEqual(self.model.writes, 0)

    def test_explicit_action_and_get_recovery_dispatch_once(self):
        status, raw = self.request("GET", self.base)
        view = json.loads(raw)
        self.assertEqual(status, 200)
        body = dict(
            key="same-key",
            revision=view["revision"],
            task_sha256=view["next_task"]["task_sha256"],
            confirmed=True,
        )
        self.assertEqual(self.request("POST", self.base + "/actions", body)[0], 200)
        self.service.wait()
        self.assertEqual(self.request("POST", self.base + "/actions", body)[0], 200)
        for _ in range(3):
            self.assertEqual(self.request("GET", self.base)[0], 200)
        self.assertEqual(self.model.writes, 1)

    def test_cross_origin_wrong_project_and_unconfirmed_dispatch_zero(self):
        view = json.loads(self.request("GET", self.base)[1])
        body = dict(
            key="denied",
            revision=view["revision"],
            task_sha256=view["next_task"]["task_sha256"],
            confirmed=False,
        )
        self.assertEqual(self.request("POST", self.base + "/actions", body)[0], 400)
        self.assertEqual(
            self.request(
                "POST",
                self.base + "/actions",
                body,
                Origin="http://other-device.invalid",
            )[0],
            403,
        )
        self.assertEqual(
            self.request("GET", self.base.replace(self.service.ref, "other-project"))[
                0
            ],
            403,
        )
        self.assertEqual((self.model.writes, self.service._row()["calls"]), (0, 0))

    def test_get_native_does_not_pump_or_start_runtime(self):
        for _ in range(4):
            self.assertEqual(self.request("GET", self.base + "/native")[0], 200)
        self.assertEqual(self.model.writes, 0)


if __name__ == "__main__":
    unittest.main()
