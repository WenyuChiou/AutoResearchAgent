"""Existing repository case composition, real HTTP/SQLite; no Codex/model calls."""

import atlas_test_paths  # noqa: F401 -- standalone discovery needs the local CLI.

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import http.client
import json
import re
import subprocess
import threading
import unittest

from atlas_bootstrap_fixture import bootstrap_objects
from research_workspace_native.atlas_host import AtlasHost, AtlasHandler
from research_workspace_native.scope_api import ScopeApi
from research_workspace_native.session_api import SessionApi, SessionApiError
import test_research_workspace_native_scope_api as scope_fixture
import test_research_workspace_native_session_api as api_fixture


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.case = api_fixture.SessionApiTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.p = self.case.project()
        self.api = self.case.api

    def policy(self, callback):
        api = SessionApi(authenticate=self.case.authenticate)
        api.register(self.p.ref, **self.p.registration, approval_policy=callback)
        self.api = api

    def pending(self):
        self.case.request(self.p, method="item/commandExecution/requestApproval")
        return self.api.view("token-a", self.p.ref)["requests"][-1]

    def body(self, request, decision="accept"):
        return self.case.body(self.p, request, result={"decision": decision})

    def test_default_accept_disabled_and_refuses_without_intent_or_io(self):
        request = self.pending()
        before = self.p.store.snapshot(self.p.pid)
        self.assertFalse(request["can_accept"])
        with self.assertRaisesRegex(SessionApiError, "approval-not-admitted"):
            self.api.answer("token-a", self.p.ref, self.body(request))
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.p.channel.messages(), [])

    def test_exact_admitted_approval_replay_has_one_write(self):
        checks = []

        def policy(context):
            checks.append(context)
            return (
                context["principal"] == self.p.principal
                and context["binding"]["input_version"] == self.p.version
            )

        self.policy(policy)
        request = self.pending()
        self.assertTrue(request["can_accept"])
        body = self.body(request)
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(
                pool.map(
                    lambda _: self.api.answer("token-a", self.p.ref, body), range(2)
                )
            )
        self.assertEqual(sum(not row["replayed"] for row in rows), 1)
        self.assertEqual(
            self.p.channel.messages(), [{"id": 83, "result": {"decision": "accept"}}]
        )
        self.assertGreaterEqual(len(checks), 3)
        before = list(self.p.channel.calls)
        self.api.view("token-a", self.p.ref)
        self.assertEqual(self.p.channel.calls, before)

    def test_revoked_policy_after_view_and_nonliteral_admission_refuse(self):
        allowed = [True]
        self.policy(lambda _: allowed[0])
        request = self.pending()
        self.assertTrue(request["can_accept"])
        allowed[0] = 1
        with self.assertRaisesRegex(SessionApiError, "approval-not-admitted"):
            self.api.answer("token-a", self.p.ref, self.body(request))
        self.assertEqual(self.p.channel.messages(), [])

    def test_accept_still_obeys_controller_dispatch_gate(self):
        self.policy(lambda _: True)  # Explicit synthetic approval policy only.
        self.p.controller.admit_action = lambda _: False
        request = self.pending()
        receipt = self.api.answer("token-a", self.p.ref, self.body(request))
        self.assertEqual(receipt["status"], "refused")
        self.assertEqual(self.p.channel.messages(), [])
        self.assertTrue(self.api.view("token-a", self.p.ref)["actions"])

    def test_last_policy_check_cannot_extend_expired_transport_deadline(self):
        calls, expired = [], [False]

        def policy(_):
            calls.append(True)
            if len(calls) == 3:  # View, initial POST admission, final pre-dispatch.
                expired[0] = True
            return True

        def deadline():
            if expired[0]:
                raise TimeoutError("synthetic absolute deadline expired")
            return 1

        self.policy(policy)
        request = self.pending()
        with self.api.admission_guard(deadline):
            with self.assertRaises(SessionApiError):
                self.api.answer("token-a", self.p.ref, self.body(request))
        self.assertEqual(self.p.channel.messages(), [])
        actions = self.api.view("token-a", self.p.ref)["actions"]
        self.assertTrue(actions)
        self.assertIsNotNone(actions[-1]["failure"])


class AtlasScopeTests(unittest.TestCase):
    def setUp(self):
        self.case = scope_fixture.ScopeApiTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.api._authenticate = lambda credential: (
            "principal-a" if credential in {"token-a", "x" * 32} else None
        )
        self.p = self.case.brief()
        self.runtime = SimpleNamespace(
            api=self.case.api,
            bindings=lambda: {
                self.p.ref: dict(
                    project_id=self.p.pid,
                    index_sha256=self.p.hash,
                    input_version=self.p.version,
                )
            },
            shutdown=lambda timeout: {"status": "synthetic-closed"},
        )
        self.files = {
            "/views/case/atlas.html": b"<meta content=\"connect-src 'none'\"><body>Original source</body>"
        }
        self.views = [
            dict(
                ref="case",
                label="Repository fixture",
                project_id=self.p.pid,
                index_sha256=self.p.hash,
                manifest_sha256="a" * 64,
                fixture=True,
                url="/views/case/atlas.html",
            )
        ]
        self.host = AtlasHost(
            files=self.files,
            views=self.views,
            native_runtime=self.runtime,
            credential="x" * 32,
            scope_api=self.case.scope,
        )
        worker = threading.Thread(target=self.host.serve_forever, daemon=True)
        worker.start()

        def stop():
            self.host.shutdown()
            self.host.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)

    def call(self, path, body=None, origin=None):
        connection = http.client.HTTPConnection(*self.host.server_address, timeout=3)
        headers = {"Authorization": "Bearer " + "x" * 32}
        if body is not None:
            headers.update(
                Origin=origin or self.host.expected_origin,
                **{"Content-Type": "application/json"},
            )
        try:
            connection.request(
                "GET" if body is None else "POST",
                path,
                None if body is None else json.dumps(body),
                headers,
            )
            response = connection.getresponse()
            raw = response.read()
            return response.status, raw
        finally:
            connection.close()

    def test_scope_append_review_and_history_share_atlas_without_turn(self):
        route = "/api/native/projects/" + self.p.ref + "/scope"
        status, page = self.call("/views/case/atlas.html")
        self.assertEqual(status, 200)
        self.assertLess(
            page.index(b"/session-panel.js"), page.index(b"/session-scope.js")
        )
        _, bootstrap = self.call("/host-bootstrap/case.js")
        self.assertTrue(
            bootstrap_objects(bootstrap, "WORKSPACE_NATIVE_ATLAS")[
                "WORKSPACE_NATIVE_ATLAS"
            ]["enabled"]
        )
        original = self.p.brief_path.read_bytes()
        body = self.case.body(self.p)
        status, raw = self.call(route + "/versions", body)
        self.assertEqual(status, 200, raw)
        result = json.loads(raw)
        history = json.loads(self.call(route)[1])
        review = dict(
            key="review",
            revision=history["revision"],
            index_sha256=self.p.hash,
            input_version=self.p.version,
            confirmed=True,
            version_ref=result["version_ref"],
            version_sha256=result["version_sha256"],
            decision="reviewed",
            note="Keep original scope.",
        )
        self.assertEqual(self.call(route + "/reviews", review)[0], 200)
        self.assertTrue(
            json.loads(self.call(route + "/reviews", review)[1])["replayed"]
        )
        self.assertEqual(self.p.brief_path.read_bytes(), original)
        self.assertEqual(self.p.channel.calls, [])
        self.assertFalse(json.loads(self.call(route)[1])["execution_authorized"])

    def test_cross_origin_foreign_project_and_wrong_api_cannot_change_scope(self):
        route = "/api/native/projects/" + self.p.ref + "/scope/versions"
        before = self.p.store.snapshot(self.p.pid)
        self.assertEqual(
            self.call(route, self.case.body(self.p), "https://foreign.invalid")[0], 403
        )
        self.assertEqual(self.call("/api/native/projects/foreign/scope")[0], 404)
        with self.assertRaisesRegex(ValueError, "same explicit native runtime"):
            AtlasHost(
                files=self.files,
                views=self.views,
                native_runtime=self.runtime,
                credential="x" * 32,
                scope_api=ScopeApi(SessionApi(authenticate=lambda _: "principal-a")),
            )
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.p.channel.calls, [])

    def test_mixed_views_execute_passive_scripts_without_scope_or_native_io(self):
        files = dict(self.files)
        files["/views/passive/atlas.html"] = self.files["/views/case/atlas.html"]
        passive = dict(self.views[0], ref="passive", url="/views/passive/atlas.html")
        passive["index_sha256"] = "b" * 64
        mixed = AtlasHost(
            files=files,
            views=self.views + [passive],
            native_runtime=self.runtime,
            credential="x" * 32,
            scope_api=self.case.scope,
        )
        worker = threading.Thread(target=mixed.serve_forever, daemon=True)
        worker.start()

        def get(path):
            connection = http.client.HTTPConnection(*mixed.server_address, timeout=3)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                return response.read().decode("utf-8")
            finally:
                connection.close()

        before = self.p.store.snapshot(self.p.pid)
        try:
            bound_page = get("/views/case/atlas.html")
            page = get("/views/passive/atlas.html")
            bootstrap = bootstrap_objects(
                get("/host-bootstrap/passive.js").encode("utf-8"),
                "WORKSPACE_NATIVE_ATLAS",
            )["WORKSPACE_NATIVE_ATLAS"]
            self.assertFalse(bootstrap["enabled"])
            routes = re.findall(r'<script src="([^"]+)"></script>', page)
            scripts = [
                get(route)
                for route in routes
                if route
                in {"/session-panel.js", "/native-atlas-chat.js", "/session-scope.js"}
            ]
            result = subprocess.run(
                [
                    "node",
                    "-e",
                    "const vm=require('node:vm');"
                    "const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
                    "const context={window:{WORKSPACE_NATIVE_ATLAS:input.bootstrap},"
                    "fetch:()=>{throw Error('passive view attempted API access')}};"
                    "vm.createContext(context); for(const source of input.scripts)"
                    "vm.runInContext(source,context);"
                    "if(context.window.NativePanel) throw Error('passive native panel created');",
                ],
                input=json.dumps(dict(bootstrap=bootstrap, scripts=scripts)),
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("/session-scope.js", bound_page)
            self.assertNotIn("/session-scope.js", routes)
            self.assertEqual(self.p.store.snapshot(self.p.pid), before)
            self.assertEqual(self.p.channel.calls, [])
        finally:
            mixed.shutdown()
            mixed.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_scope_prefix_project_does_not_route_normal_actions_as_scope(self):
        calls = []
        handler = SimpleNamespace(
            server=SimpleNamespace(
                native_cases={"case": {"project_ref": "scope-a"}}, scope_api=None
            ),
            _handle=lambda method: calls.append(("native", method)),
            _reply=lambda status, body: calls.append((status, body)),
        )
        for route, method in (("", "GET"), ("/messages", "POST"), ("/answers", "POST")):
            handler.path = "/api/native/projects/scope-a" + route
            AtlasHandler._native(handler, method)
            self.assertEqual(calls[-1], ("native", method))
        handler.path = "/api/native/projects/scope-a/scope"
        AtlasHandler._native(handler, "GET")
        self.assertEqual(calls[-1], (404, {"error": "scope-unavailable"}))


if __name__ == "__main__":
    unittest.main()
