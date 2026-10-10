"""Real temporary HTTP + durable broker; all model I/O is injected synthetic."""

import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import time
from unittest.mock import patch
from stage_model_fixtures import StageModelFixture, FakeRuntime
from research_workspace_native.stage_model import StageModel
from research_workspace_native.stage_run_http import StageRunHandler
from stage1_deliverable.common import canonical

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


class StageRunActiveHttpTests(StageModelFixture):
    """Actual HTTP/API/controller/journal; injected bytes, no Codex process."""

    def setUp(self):
        super().setUp()
        self.token = "s" * 40
        self.auth = token_authenticator({self.token: "local-viewer"})
        case = load_builder().build(self.root / "case")
        files, views = load_views(case["host_config_path"], case["host_config_sha256"])
        permit = dict(
            kind="NativeStagePilotPermit",
            schema_version="1.0.0",
            project_id=self.checked["project_id"],
            source_sha256="b" * 64,
            case_sha256="c" * 64,
            output_root=str(self.root / "budget"),
            model="synthetic-model",
            max_calls=8,
            max_seconds=900,
            execution_scope="repository-saved-content-only",
            external_search=False,
            frozen_subjects=False,
            permission_id="explicit-synthetic-test",
        )
        path = self.root / "permit.json"
        path.write_bytes(canonical(permit))
        self.service = StageRunService(
            path, sha(path.read_bytes()), pipeline=Pipeline(), authenticate=self.auth
        )
        self.addCleanup(self.service.close)

        def factory(registrations, **kwargs):
            self.runtime = FakeRuntime(
                registrations[0], kwargs["authenticate"], kwargs["gates"], self.mode
            )
            return self.runtime

        self.stage_model = StageModel(
            self.checked,
            model=permit["model"],
            permit_sha256=self.service.permit_sha,
            source_sha256=permit["source_sha256"],
            executable_sha256=sha(self.executable.read_bytes()),
            user_config_sha256=sha(self.user.read_bytes()),
            config_sha256=sha(self.config.read_bytes()),
            authenticate=self.auth,
            credential=self.token,
            admit=self.service.admit,
            output_root=self.root / "models",
            runtime_factory=factory,
        )
        self.service.attach_model(self.stage_model)
        self.host = StageRunHost(
            files, views, service=self.service, credential=self.token, timeout=30
        )
        self.thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_host)
        self.base = "/api/stage-run/projects/" + self.service.ref

    def stop_host(self):
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(5)

    def request(self, method, suffix="", body=None):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Origin": self.host.expected_origin,
        }
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        client = http.client.HTTPConnection(*self.host.server_address, timeout=5)
        try:
            client.request(method, self.base + suffix, body, headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def active(self, mode):
        self.mode = mode
        status, view = self.request("GET")
        self.assertEqual(status, 200)
        status, _ = self.request(
            "POST",
            "/actions",
            dict(
                key="one-unit",
                revision=view["revision"],
                task_sha256=view["next_task"]["task_sha256"],
                confirmed=True,
            ),
        )
        self.assertEqual(status, 200)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            status, result = self.request("GET", "/native")
            view = result["native_view"]
            if (
                status == 200
                and view
                and (view["requests"] if mode == "question" else view["operations"])
            ):
                return view
            time.sleep(0.01)
        self.fail("injected native question/operation not observed")

    def answer_body(self, view):
        target = view["requests"][0]
        return dict(
            key="reply-once",
            revision=view["revision"],
            index_sha256=view["index_sha256"],
            input_version=view["input_version"],
            request_ref=target["request_ref"],
            request_sha256=target["request_sha256"],
            result=dict(answers=dict(q=dict(answers=["controlled source scope"]))),
        )

    def test_actual_http_question_answer_has_numeric_deadline_and_one_response(self):
        view = self.active("question")
        body = self.answer_body(view)
        status, result = self.request("POST", "/answers", body)
        self.assertEqual((status, result.get("status")), (200, "dispatched"), result)
        self.service.wait(5)
        self.assertFalse(self.service._worker_active())
        self.assertEqual(self.service._row()["jobs"]["one-unit"]["status"], "validated")
        messages = self.runtime.channel.messages()
        self.assertEqual(sum("result" in m and m.get("id") == 8 for m in messages), 1)
        before = len(messages)
        for _ in range(2):
            self.assertEqual(self.request("GET")[0], 200)
        self.assertEqual(len(self.runtime.channel.messages()), before)
        self.assertEqual(self.service._row()["calls"], 1)

    def test_actual_http_interrupt_has_numeric_deadline_and_one_write(self):
        view = self.active("timeout")
        op = view["operations"][0]
        body = dict(
            key="interrupt-once",
            revision=view["revision"],
            index_sha256=view["index_sha256"],
            input_version=view["input_version"],
            action_ref=op["action_ref"],
            action_sha256=op["action_sha256"],
        )
        status, result = self.request("POST", "/interrupts", body)
        self.assertEqual(
            (status, result.get("status")), (200, "write-observed"), result
        )
        self.service.wait(5)
        self.assertFalse(self.service._worker_active())
        messages = self.runtime.channel.messages()
        self.assertEqual(sum(m.get("method") == "turn/interrupt" for m in messages), 1)
        self.assertEqual(sum(m.get("method") == "turn/start" for m in messages), 1)
        self.assertEqual(self.service._row()["calls"], 1)
        self.assertEqual(
            self.service._row()["jobs"]["one-unit"]["status"], "failed-or-unknown"
        )

    def test_expiry_inside_native_admission_has_zero_extra_io(self):
        view = self.active("question")
        body = self.answer_body(view)
        before = len(self.runtime.channel.sent)
        original = StageRunHandler._remaining

        def expire_at_api(handler):
            if getattr(self.stage_model.active_api()._guards, "check", None):
                raise TimeoutError("expired accepted HTTP deadline")
            return original(handler)

        with patch.object(StageRunHandler, "_remaining", expire_at_api):
            with self.assertRaises((http.client.RemoteDisconnected, OSError)):
                self.request("POST", "/answers", body)
        self.assertEqual(len(self.runtime.channel.sent), before)
        self.assertEqual(self.service._row()["calls"], 1)
        self.assertTrue(self.service._worker_active())
        status, result = self.request("POST", "/answers", body)
        self.assertEqual((status, result.get("status")), (200, "dispatched"), result)
        self.service.wait(5)
        self.assertFalse(self.service._worker_active())


if __name__ == "__main__":
    unittest.main()
