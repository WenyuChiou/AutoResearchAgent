"""Actual loopback HTTP over repository stage cases and durable SQLite."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from copy import deepcopy
import http.client
import io
import json
import threading
import time
import unittest

from stage1_deliverable.common import sha
from atlas_bootstrap_fixture import bootstrap_objects
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.stage_http import bind_stages, handle_stages
from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
from types import SimpleNamespace
import test_workspace_stage_actions as fixture


class StageHttpTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.StageActionTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.ledger = self.case.stage1()
        self.case.stage2()
        self.raw = b'{"project_id":"case-a"}\n'
        self.hash = sha(self.raw)
        registrations = self.case.registrations()
        registrations["case"]["index_sha256"] = self.hash
        self.service = self.case.start(registrations)
        self.credential = "test-token-" * 4
        self.service._authenticate = lambda token: (
            "principal-a" if token in ("a", self.credential) else None
        )
        self.files = {
            "/views/case/atlas.html": b"<meta content=\"connect-src 'none'\"><body><section id='atlas-stage-review'></section></body>",
            "/views/case/workspace-index.json": self.raw,
        }
        self.views = [
            dict(
                ref="case",
                label="Repository fixture",
                project_id="case-a",
                index_sha256=self.hash,
                manifest_sha256="a" * 64,
                fixture=True,
                url="/views/case/atlas.html",
            )
        ]
        self.host = AtlasHost(
            files=self.files,
            views=self.views,
            stage_actions=self.service,
            credential=self.credential,
        )
        self.worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.host.shutdown()
        self.host.server_close()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def call(self, suffix="", body=None, origin=None, path=None):
        connection = http.client.HTTPConnection(*self.host.server_address, timeout=3)
        headers = {"Authorization": "Bearer " + self.credential}
        if body is not None:
            headers.update(
                Origin=origin or self.host.expected_origin,
                **{"Content-Type": "application/json"},
            )
        try:
            connection.request(
                "GET" if body is None else "POST",
                path or "/api/stages/projects/case" + suffix,
                None if body is None else json.dumps(body),
                headers,
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def body(self, *args, **kwargs):
        body = self.case.body(*args, **kwargs)
        body["index_sha256"] = self.hash
        return body

    def test_stage1_checkpoint_completed_replay_preserves_original(self):
        original = source_digest(snapshot_inputs(self.case.inputs))
        body = self.body(1, "checkpoint-stage1", "check-1")
        status, raw = self.call("/actions", body)
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        self.assertTrue(result["result"]["ledger_valid"])
        self.assertEqual(source_digest(snapshot_inputs(self.case.inputs)), original)
        self.assertEqual(json.loads(self.call("/actions/check-1")[1]), result)
        self.assertEqual(json.loads(self.call("/actions", body)[1]), result)
        self.assertEqual(json.loads(self.call()[1])["history_count"], 1)

    def test_stage2_incomplete_retains_blockers_and_next_request_is_not_execution(self):
        status, raw = self.call("/actions", self.body(2, "inspect-stage2", "check-2"))
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["result"]["readiness"]["status"], "incomplete")
        body = self.body(
            2,
            "review-stage",
            "review-2",
            decision="request-next",
            note="Review saved case; do not launch research.",
            confirmed=True,
        )
        result = json.loads(self.call("/actions", body)[1])["result"]
        self.assertEqual(result["next_stage_request"], "blocked")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["native_user_message_attested"])

    def test_guarded_reads_posts_and_strict_duplicate_json(self):
        before = self.service.view("a", "case")
        self.assertEqual(self.call(path="/api/stages/projects/foreign")[0], 404)
        self.assertEqual(
            self.call(
                "/actions",
                self.body(1, "checkpoint-stage1", "deny"),
                "https://foreign.invalid",
            )[0],
            403,
        )
        self.assertEqual(self.call("/offers/1/inspect-stage2")[0], 400)
        connection = http.client.HTTPConnection(*self.host.server_address, timeout=3)
        try:
            connection.request(
                "POST",
                "/api/stages/projects/case/actions",
                '{"stage":1,"stage":2}',
                {
                    "Authorization": "Bearer " + self.credential,
                    "Content-Type": "application/json",
                    "Origin": self.host.expected_origin,
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.service.view("a", "case"), before)

    def test_changed_payload_stale_revision_and_source_binding_fail_closed(self):
        body = self.body(1, "checkpoint-stage1", "first")
        self.assertEqual(self.call("/actions", body)[0], 200)
        changed = deepcopy(body)
        changed["stage"], changed["action"] = 2, "inspect-stage2"
        self.assertEqual(self.call("/actions", changed)[0], 409)
        stale = self.body(1, "checkpoint-stage1", "stale")
        stale["revision"] = 0
        self.assertEqual(self.call("/actions", stale)[0], 409)
        invalid = self.body(1, "checkpoint-stage1", "invalid")
        invalid["input_version"] = "f" * 64
        self.assertEqual(self.call("/actions", invalid)[0], 409)
        self.assertEqual(json.loads(self.call()[1])["history_count"], 1)

    def test_binding_preflight_and_disabled_host_preserve_borrowed_service(self):
        bad = deepcopy(self.views)
        bad[0]["index_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "binding differs"):
            AtlasHost(
                files=self.files,
                views=bad,
                stage_actions=self.service,
                credential=self.credential,
            )
        self.assertFalse(self.service._closed)
        with self.assertRaisesRegex(ValueError, "snapshot binding differs"):
            bind_stages(self.service, {}, self.views, self.credential)
        disabled = AtlasHost(files=self.files, views=self.views)
        self.addCleanup(disabled.server_close)
        self.assertEqual(disabled.stage_cases, {})

    def test_fourth_bootstrap_domain_and_assets_do_not_change_original_index(self):
        raw = self.call(path="/host-bootstrap/case.js")[1]
        config = bootstrap_objects(raw, "WORKSPACE_STAGE_ACTIONS")[
            "WORKSPACE_STAGE_ACTIONS"
        ]
        self.assertTrue(config["enabled"])
        self.assertEqual(config["input_version"], "b" * 64)
        page = self.call(path="/views/case/atlas.html")[1]
        self.assertIn(b"stage-panel.js", page)
        self.assertEqual(
            self.call(path="/views/case/workspace-index.json")[1], self.raw
        )

    def test_route_passes_accept_time_deadline_without_extending_it(self):
        captured = []
        handler = SimpleNamespace(
            _headers=lambda _: (self.credential, 0),
            headers={},
            server=SimpleNamespace(
                authenticate=lambda _: "principal-a",
                stage_cases={"case": {}},
                stage_actions=self.service,
            ),
            path="/api/stages/projects/case",
            deadline=time.monotonic() - 1,
            _remaining=lambda: (_ for _ in ()).throw(TimeoutError()),
            _reply=lambda *args: captured.append(args),
            close_connection=False,
        )
        handle_stages(handler, "GET")
        self.assertTrue(handler.close_connection)
        self.assertFalse(captured)
        body = self.body(1, "checkpoint-stage1", "deadline")
        raw = json.dumps(body).encode()
        original_deadline = time.monotonic() + 3
        handler.deadline = original_deadline
        handler.path += "/actions"
        handler.headers = {"Content-Type": "application/json"}
        handler._headers = lambda _: (self.credential, len(raw))
        handler._remaining = lambda: 1
        handler.rfile = io.BytesIO(raw)
        handler.server.stage_actions = SimpleNamespace(
            execute=lambda token, ref, request, *, deadline: (
                captured.append((token, ref, request, deadline)) or {"saved": True}
            )
        )
        handle_stages(handler, "POST")
        self.assertEqual(
            captured[0], (self.credential, "case", body, original_deadline)
        )


if __name__ == "__main__":
    unittest.main()
