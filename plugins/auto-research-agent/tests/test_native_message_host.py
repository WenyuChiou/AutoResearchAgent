"""Real loopback HTTP/SQLite with injected channels, no native/model process."""

from copy import deepcopy
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
import test_native_message_api as fixture
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.http import SessionHttpServer
from research_workspace_native.host_config import HostRegistry, create_host
from research_workspace_native.session_api import SessionApi


class Runtime:
    """Synthetic ready registry, never a native ownership attestation."""

    def __init__(self, api, project):
        self.api, self.project, self.stops = api, project, []

    def bindings(self):
        p = self.project
        return {
            p.ref: dict(project_id=p.pid, index_sha256=p.hash, input_version=p.version)
        }

    def shutdown(self, timeout):
        self.stops.append(timeout)
        return {"status": "synthetic-closed"}


class MessageHostTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MessageApiTests("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.token = "x" * 32
        self.case.authenticate = lambda token: (
            "principal-a" if token == self.token else None
        )
        self.case.api = SessionApi(authenticate=self.case.authenticate)
        self.p = self.case.project()

    def start(self, atlas=False, **options):
        if atlas:
            self.runtime = Runtime(self.case.api, self.p)
            self.files = {
                "/views/case/atlas.html": b"<meta content=\"connect-src 'none'\"><body>Literal source text</body>"
            }
            self.views = [
                dict(
                    ref="case",
                    project_id=self.p.pid,
                    index_sha256=self.p.hash,
                    manifest_sha256="b" * 64,
                    fixture=True,
                    label="Same title",
                    url="/views/case/atlas.html",
                ),
                dict(
                    ref="unbound",
                    project_id="other",
                    index_sha256="c" * 64,
                    manifest_sha256="d" * 64,
                    fixture=True,
                    label="Same title",
                    url="/views/unbound/atlas.html",
                ),
            ]
            self.files["/views/unbound/atlas.html"] = self.files[
                "/views/case/atlas.html"
            ]
            server = AtlasHost(
                files=self.files,
                views=self.views,
                native_runtime=self.runtime,
                credential=self.token,
                native_script=b"/* fixture-only; no model */",
                **options,
            )
        else:
            server = SessionHttpServer(self.case.api, **options)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server

    def request(self, server, method, suffix="", body=None, **headers):
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            supplied = {"Authorization": "Bearer " + self.token, **headers}
            raw = None
            if body is not None:
                raw = json.dumps(body).encode()
                supplied.setdefault("Content-Type", "application/json")
            if method == "POST":
                supplied.setdefault("Origin", server.expected_origin)
            client.request(
                method, "/api/native/projects/" + self.p.ref + suffix, raw, supplied
            )
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def message(self, server, key="message-one"):
        status, offer = self.request(server, "GET", "/offer")
        self.assertEqual(status, 200)
        return dict(
            {name: offer[name] for name in ("offer_ref", "offer_sha256", "revision")},
            key=key,
            text="Read the saved source.",
        )

    def test_real_http_offer_message_same_key_and_recovery_are_single_write(self):
        server = self.start()
        body = self.message(server)
        self.assertEqual(self.p.channel.calls, [])
        status, receipt = self.request(server, "POST", "/messages", body)
        self.assertEqual((status, receipt["status"]), (200, "write-observed"))
        self.assertEqual(len(self.p.channel.messages()), 1)
        calls = list(self.p.channel.calls)
        for suffix in ("", "/offer", "/actions/" + receipt["action_ref"]):
            self.assertEqual(self.request(server, "GET", suffix)[0], 200)
        self.assertEqual(
            self.request(server, "POST", "/messages", body)[1]["replayed"], True
        )
        self.assertEqual(
            self.request(server, "POST", "/messages", dict(body, text="changed"))[0],
            409,
        )
        self.assertEqual(self.p.channel.calls, calls)
        self.assertTrue(0 < calls[0][1] <= 3)

    def test_first_offer_revision_and_typed_http_rejection_recover(self):
        server = self.start()
        initial = self.request(server, "GET")[1]
        status, offer = self.request(server, "GET", "/offer")
        self.assertEqual(status, 200)
        self.assertEqual(offer["max_text_bytes"], 128)
        current = self.request(server, "GET")[1]
        self.assertGreater(offer["revision"], initial["revision"])
        self.assertEqual(current["revision"], offer["revision"])
        body = {name: offer[name] for name in ("offer_ref", "offer_sha256", "revision")}
        body.update(key="known-unsent-http", text="x" * 129)
        before = self.p.store.snapshot(self.p.pid)
        status, rejected = self.request(server, "POST", "/messages", body)
        self.assertEqual(status, 400)
        self.assertEqual(
            rejected["receipt"],
            dict(
                schema_version="NativeKnownUnsent.v1",
                status="known-unsent",
                operation="message",
                project_ref=self.p.ref,
                index_sha256=self.p.hash,
                input_version=self.p.version,
                client_key=body["key"],
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            ),
        )
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.p.channel.calls, [])
        status, invalid = self.request(
            server, "POST", "/messages", body, Authorization="Bearer wrong"
        )
        self.assertEqual(status, 401)
        self.assertNotIn("receipt", invalid)
        body["text"] = "Corrected explicitly"
        self.assertEqual(self.request(server, "POST", "/messages", body)[0], 200)
        self.assertEqual(len(self.p.channel.messages()), 1)
        self.assertTrue(self.request(server, "POST", "/messages", body)[1]["replayed"])
        self.assertEqual(len(self.p.channel.messages()), 1)

    def test_semantic_registry_connects_only_existing_bound_runtime(self):
        self.start(atlas=True)
        config = dict(
            config_kind="semantic",
            files=self.files,
            views=self.views,
            presentation=dict(language="zh-Hant", density="compact"),
            server_object_requests=dict(
                native=dict(mode="registered", runtime_ref="saved"),
                maintenance=dict(mode="disabled"),
            ),
        )
        registry = HostRegistry(runtimes={"saved": self.runtime})
        before = self.p.store.snapshot(self.p.pid)
        with patch(
            "research_workspace_native.process_channel.OwnedProcessChannel.__init__",
            side_effect=AssertionError("no implicit owned process"),
        ):
            server = create_host(config, registry=registry, credential=self.token)
            try:
                self.assertEqual(server.native_cases["case"]["project_ref"], self.p.ref)
                self.assertEqual(server.capability_state["native"], "connected")
                self.assertEqual(server.presentation["language"], "zh-Hant")
                self.assertEqual(self.p.store.snapshot(self.p.pid), before)
                self.assertEqual(self.p.channel.calls, [])
            finally:
                server.server_close()
            missing = create_host(config, credential=self.token)
            try:
                self.assertEqual(missing.capability_state["native"], "unavailable")
                self.assertEqual(missing.native_cases, {})
            finally:
                missing.server_close()
        for value in (str(self.p.root), self.p.root, lambda: self.runtime, object()):
            with self.assertRaises(ValueError):
                HostRegistry(runtimes={"saved": value})
        with self.assertRaises(ValueError):
            create_host(
                config,
                registry=registry,
                credential=self.token,
                native_runtime=self.runtime,
            )

    def test_bad_http_authority_and_caller_model_have_zero_intent(self):
        server = self.start()
        body = self.message(server)
        before = self.p.store.snapshot(self.p.pid)
        for headers in (
            {"Authorization": "Bearer bad"},
            {"Origin": "http://other"},
            {"Host": "other"},
        ):
            self.assertIn(
                self.request(server, "POST", "/messages", body, **headers)[0],
                (401, 403),
            )
        self.assertEqual(
            self.request(server, "POST", "/messages", dict(body, model="caller"))[0],
            400,
        )
        self.assertEqual(self.request(server, "GET", "/offer/extra")[0], 400)
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.p.channel.calls, [])

    def test_response_loss_read_history_never_resends(self):
        server = self.start()
        body = self.message(server)
        path = "/api/native/projects/" + self.p.ref + "/messages"
        raw = json.dumps(body).encode()
        headers = (
            f"POST {path} HTTP/1.1\r\nHost: {server.expected_host}\r\n"
            f"Origin: {server.expected_origin}\r\nAuthorization: Bearer {self.token}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n"
        ).encode()
        with socket.create_connection(server.server_address, timeout=2) as client:
            client.sendall(headers + raw)
        end = time.monotonic() + 2
        while not self.p.channel.sent and time.monotonic() < end:
            time.sleep(0.005)
        self.assertEqual(len(self.p.channel.messages()), 1)
        status, view = self.request(server, "GET")
        self.assertEqual(status, 200)
        receipt = view["actions"][0]
        self.assertEqual(
            self.request(server, "GET", "/actions/" + receipt["action_ref"])[0], 200
        )
        self.assertEqual(len(self.p.channel.messages()), 1)

    def test_waiting_for_sqlite_lock_past_deadline_cannot_record_or_write(self):
        server = self.start(timeout=0.1)
        body = self.message(server)
        before = self.p.store.snapshot(self.p.pid)
        reached, done, errors = threading.Event(), threading.Event(), []
        original = self.case.api._authenticate

        def authenticate(token):
            reached.set()
            return original(token)

        self.case.api._authenticate = authenticate

        def submit():
            try:
                self.request(server, "POST", "/messages", body)
            except OSError as error:
                errors.append(type(error).__name__)
            finally:
                done.set()

        with self.p.store._lock:
            worker = threading.Thread(target=submit)
            worker.start()
            self.assertTrue(reached.wait(1))
            self.assertTrue(done.wait(1))  # Accept-time timer closes the socket.
        worker.join(2)
        limit = time.monotonic() + 1
        while server._deadlines and time.monotonic() < limit:
            time.sleep(0.005)
        self.assertFalse(server._deadlines)
        self.assertTrue(errors)
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.p.channel.calls, [])

    def test_slow_controller_admission_past_deadline_has_no_write(self):
        server = self.start(timeout=0.1)
        body = self.message(server)
        self.p.controller.admit_action = lambda _: time.sleep(0.15) or True
        try:
            self.request(server, "POST", "/messages", body)
        except OSError:
            pass
        deadline = time.monotonic() + 1
        while server._deadlines and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(server._deadlines)
        self.assertEqual(self.p.channel.sent, [])
        state = self.p.store.snapshot(self.p.pid)
        self.assertEqual(len(state["session_api_actions"]), 1)
        self.assertIsNotNone(
            next(iter(state["session_api_actions"].values()))["failure"]
        )

    def test_host_bootstrap_binds_case_and_default_or_foreign_case_is_disabled(self):
        server = self.start(atlas=True)

        def bootstrap(ref):
            client = http.client.HTTPConnection(*server.server_address, timeout=2)
            try:
                client.request("GET", "/host-bootstrap/" + ref + ".js")
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                rows = response.read().decode().splitlines()
                return [json.loads(row.split("=", 1)[1][:-1]) for row in rows]
            finally:
                client.close()

        host, native = bootstrap("case")
        self.assertEqual(host["current_case"], native["current_case"])
        self.assertEqual(
            native,
            dict(
                credential=self.token,
                current_case="case",
                enabled=True,
                project_ref=self.p.ref,
                index_sha256=self.p.hash,
                input_version=self.p.version,
            ),
        )
        self.assertFalse(bootstrap("unbound")[1]["enabled"])
        self.assertIsNone(bootstrap("unbound")[1]["input_version"])
        self.assertEqual(self.p.channel.calls, [])
        before = deepcopy(self.files)
        self.message(server)
        self.assertEqual(self.files, before)
        self.assertFalse(server.host_binding["execution_authority"])
        server.shutdown()
        server.server_close()
        self.assertEqual(self.runtime.stops, [10])
        server.server_close()
        self.assertEqual(self.runtime.stops, [10])

    def test_host_rejects_forged_binding_credential_and_view_before_socket(self):
        self.start(atlas=True)
        for mismatch in ("project_id", "index_sha256", "input_version"):
            declared = self.runtime.bindings()
            declared[self.p.ref][mismatch] = "different"
            with patch.object(self.runtime, "bindings", return_value=declared):
                with self.assertRaises(ValueError):
                    AtlasHost(
                        files=self.files,
                        views=self.views,
                        native_runtime=self.runtime,
                        credential=self.token,
                    )
        with self.assertRaises(Exception):
            AtlasHost(
                files=self.files,
                views=self.views,
                native_runtime=self.runtime,
                credential="z" * 32,
            )
        with self.assertRaises(ValueError):
            AtlasHost(
                files=self.files,
                views=self.views[1:],
                native_runtime=self.runtime,
                credential=self.token,
            )

    def test_failed_socket_construction_does_not_take_borrowed_runtime_ownership(self):
        server = self.start(atlas=True)
        before = self.p.store.snapshot(self.p.pid)
        for activate in (False, True):
            options = dict(
                files=self.files,
                views=self.views,
                native_runtime=self.runtime,
                credential=self.token,
            )
            if not activate:
                options["port"] = server.server_port
                with self.assertRaises(OSError):
                    AtlasHost(**options)
            else:
                with patch.object(
                    SessionHttpServer, "server_activate", side_effect=OSError("fixture")
                ):
                    with self.assertRaises(OSError):
                        AtlasHost(**options)
            self.assertEqual(self.runtime.stops, [])
            self.assertEqual(self.p.store.snapshot(self.p.pid), before)
            self.assertEqual(self.p.channel.calls, [])


if __name__ == "__main__":
    unittest.main()
