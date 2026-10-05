"""Temporary loopback HTTP + real journals + fake channel; no browser/native/model."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
import test_research_workspace_native_session_api as fixtures
from research_workspace_native.http import (
    SessionHandler,
    SessionHttpServer,
    token_authenticator,
)
from research_workspace_native.session_api import SessionApi


class SessionHttpTests(unittest.TestCase):
    project = fixtures.SessionApiTests.project
    push = fixtures.SessionApiTests.push

    def setUp(self):
        fixtures.SessionApiTests.setUp(self)
        self.token, self.other = "a" * 40, "b" * 40
        authenticate = token_authenticator(
            {self.token: "principal-a", self.other: "principal-b"}
        )

        def record(credential):
            self.auth.append(credential)
            return authenticate(credential)

        self.api = SessionApi(authenticate=record)
        self.server = SessionHttpServer(self.api)
        self.server_errors = []
        self.server.handle_error = lambda request, address: self.server_errors.append(
            address
        )
        self.worker = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def request(self, p, method="item/tool/requestUserInput"):
        self.push(
            p,
            {
                "id": 83,
                "method": method,
                "params": {
                    "threadId": p.thread,
                    "turnId": "private-turn",
                    "itemId": "private-item",
                    "questions": [{"id": "q", "question": "Choose?"}],
                },
            },
        )
        return self.api.view(self.token, p.ref)["requests"][-1]

    def body(self, p, request, **changes):
        body = dict(
            key="answer",
            revision=self.api.view(self.token, p.ref)["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            request_ref=request["request_ref"],
            request_sha256=request["request_sha256"],
            result=fixtures.ANSWER,
        )
        body.update(changes)
        return body

    def call(
        self, method, path, body=None, headers=None, token=None, omit_origin=False
    ):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        supplied = {
            "Host": self.server.expected_host,
            "Origin": self.server.expected_origin,
            "Authorization": "Bearer " + (token or self.token),
        }
        if body is not None:
            supplied["Content-Type"] = "application/json"
            body = json.dumps(body).encode() if isinstance(body, dict) else body
        supplied.update(headers or {})
        if omit_origin:
            supplied.pop("Origin", None)
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            return (
                response.status,
                json.loads(response.read()),
                dict(response.getheaders()),
            )
        finally:
            connection.close()

    def test_reads_auth_project_isolation_and_no_native_identity(self):
        a, b = self.project(), self.project("b", "principal-b")
        self.request(a)
        before = list(a.channel.calls)
        status, view, headers = self.call("GET", f"/api/native/projects/{a.ref}")
        self.assertEqual(status, 200)
        self.assertEqual(a.channel.calls, before)
        encoded = json.dumps(view)
        for private in (a.thread, a.epoch, a.owner, str(a.root), a.pid):
            self.assertNotIn(private, encoded)
        self.assertEqual(headers["Cache-Control"], "no-store")
        baseline = len(b.source_checks)
        for path, options in (
            (f"/api/native/projects/{b.ref}", {}),
            (f"/api/native/projects/{a.ref}", {"token": "wrong"}),
            (f"/api/native/projects/{a.ref}", {"headers": {"Host": "evil.example"}}),
            (
                f"/api/native/projects/{a.ref}",
                {"headers": {"Origin": "https://evil.example"}},
            ),
        ):
            self.assertIn(self.call("GET", path, **options)[0], (401, 403, 404))
        self.assertEqual(len(b.source_checks), baseline)
        self.assertEqual(b.channel.calls, [])

    def test_concurrent_posts_and_history_recovery_write_once(self):
        p = self.project()
        body = self.body(p, self.request(p))
        path = f"/api/native/projects/{p.ref}/answers"
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(
                pool.map(lambda _: self.call("POST", path, body), range(4))
            )
        self.assertTrue(all(r[0] == 200 for r in responses))
        self.assertEqual(sum(c == "write" for c in p.channel.calls), 1)
        ref = responses[0][1]["action_ref"]
        before = list(p.channel.calls)
        # Recover the saved receipt with GET; this case keeps the HTTP response.
        recovered = self.call("GET", f"/api/native/projects/{p.ref}/actions/{ref}")
        self.assertEqual(recovered[0], 200)
        self.assertEqual(recovered[1]["status"], responses[0][1]["status"])
        self.call("GET", f"/api/native/projects/{p.ref}")
        changed = dict(body, result={"answers": {"q": {"answers": ["other"]}}})
        self.assertEqual(self.call("POST", path, changed)[0], 409)
        self.assertEqual(p.channel.calls, before)

    def test_same_origin_get_without_origin_and_mutations_stay_guarded(self):
        p = self.project()
        body = self.body(p, self.request(p))
        path = f"/api/native/projects/{p.ref}"
        before = list(p.channel.calls)
        self.assertEqual(self.call("GET", path, omit_origin=True)[0], 200)
        self.assertEqual(
            self.call("POST", path + "/answers", body, omit_origin=True)[0], 403
        )
        for origin in ("null", "https://evil.example"):
            self.assertEqual(self.call("GET", path, headers={"Origin": origin})[0], 403)
        self.assertEqual(p.channel.calls, before)
        status, receipt, _ = self.call("POST", path + "/answers", body)
        self.assertEqual(status, 200)
        before = list(p.channel.calls)
        history = self.call(
            "GET", path + "/actions/" + receipt["action_ref"], omit_origin=True
        )
        self.assertEqual(history[0], 200)
        self.assertEqual(history[1]["action_ref"], receipt["action_ref"])
        self.assertEqual(p.channel.calls, before)

    def test_stale_and_untrusted_fields_reject_without_dispatch(self):
        p = self.project()
        body = self.body(p, self.request(p))
        before = list(p.channel.calls)
        path = f"/api/native/projects/{p.ref}/answers"
        for changes in (
            {"owner": p.owner},
            {"root": str(p.root)},
            {"threadId": p.thread},
            {"revision": True},
            {"revision": body["revision"] - 1},
            {"request_sha256": "f" * 64},
            {"input_version": "f" * 64},
        ):
            self.assertIn(self.call("POST", path, dict(body, **changes))[0], (400, 409))
        self.assertEqual(p.channel.calls, before)
        self.assertFalse(p.store.snapshot(p.pid).get("session_api_actions"))

    def test_strict_http_and_json_reject_before_dispatch(self):
        p = self.project()
        path = f"/api/native/projects/{p.ref}/answers"
        before = list(p.channel.calls)
        for raw in (
            b'{"key":"x","key":"y"}',
            b'{"x":NaN}',
            b'{"x":1e1000}',
            b"[]",
            b"\xff",
        ):
            self.assertEqual(self.call("POST", path, raw)[0], 400)
        self.assertEqual(
            self.call("POST", path, b"{}", {"Content-Type": "text/plain"})[0], 415
        )
        self.assertEqual(
            self.call("GET", f"/api/native/projects/{p.ref}?token=x")[0], 404
        )
        self.assertEqual(self.call("POST", path, b"x" * (256 * 1024 + 1))[0], 413)
        for field in ("Host", "Authorization", "Origin", "Content-Length"):
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.server.server_port, timeout=3
            )
            connection.putrequest("POST", path, skip_host=True)
            for name, value in (
                ("Host", self.server.expected_host),
                ("Authorization", "Bearer " + self.token),
                ("Origin", self.server.expected_origin),
                ("Content-Length", "2"),
                ("Content-Type", "application/json"),
            ):
                connection.putheader(name, value)
                if field == name:
                    connection.putheader(name, value)
            connection.endheaders(b"{}")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.close()
        self.assertEqual(
            self.call("POST", path, b"{}", {"Transfer-Encoding": "chunked"})[0], 400
        )
        self.assertEqual(p.channel.calls, before)

    def test_decline_and_interrupt_use_saved_native_targets(self):
        p = self.project()
        request = self.request(p, "item/commandExecution/requestApproval")
        status, _, _ = self.call(
            "POST",
            f"/api/native/projects/{p.ref}/answers",
            self.body(p, request, result={"decision": "decline"}),
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            p.channel.messages()[0], {"id": 83, "result": {"decision": "decline"}}
        )
        p.controller.client_action(
            "server-start",
            "turn/start",
            {"threadId": p.thread},
            p.controller.view()["revision"],
        )
        wire = p.channel.messages()[-1]
        self.push(p, {"id": wire["id"], "result": {"turn": {"id": "saved-turn"}}})
        view = self.api.view(self.token, p.ref)
        operation = view["operations"][0]
        body = dict(
            key="interrupt",
            revision=view["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            action_ref=operation["action_ref"],
            action_sha256=operation["action_sha256"],
        )
        self.assertEqual(
            self.call("POST", f"/api/native/projects/{p.ref}/interrupts", body)[0], 200
        )
        self.assertEqual(
            p.channel.messages()[-1]["params"],
            {"threadId": p.thread, "turnId": "saved-turn"},
        )
        before = list(p.channel.calls)
        self.call("POST", f"/api/native/projects/{p.ref}/interrupts", body)
        self.assertEqual(p.channel.calls, before)

    def test_partial_native_write_is_unknown_and_get_does_not_retry(self):
        p = self.project()
        body = self.body(p, self.request(p))
        p.channel.writes.extend([3, OSError("partial write")])
        status, result, _ = self.call(
            "POST", f"/api/native/projects/{p.ref}/answers", body
        )
        self.assertEqual(status, 409)
        self.assertEqual(result, {"error": "controller-action-failed"})
        result = self.call("GET", f"/api/native/projects/{p.ref}")[1]["actions"][-1]
        self.assertEqual(result["status"], "execution-unknown")
        before = list(p.channel.calls)
        self.call("GET", f"/api/native/projects/{p.ref}/actions/{result['action_ref']}")
        self.call("GET", f"/api/native/projects/{p.ref}")
        self.call("POST", f"/api/native/projects/{p.ref}/answers", body)
        self.assertEqual(p.channel.calls, before)
        self.assertEqual(len(p.store.snapshot(p.pid)["intents"]), 1)

    def test_closed_client_response_recovers_with_get_without_resend(self):
        p = self.project()
        body = self.body(p, self.request(p))
        raw = json.dumps(body).encode()
        path = f"/api/native/projects/{p.ref}/answers"
        with socket.create_connection(
            ("127.0.0.1", self.server.server_port), 3
        ) as client:
            headers = (
                f"POST {path} HTTP/1.1\r\nHost: {self.server.expected_host}\r\n"
                f"Origin: {self.server.expected_origin}\r\n"
                f"Authorization: Bearer {self.token}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n"
            ).encode()
            client.sendall(headers + raw)
            client.shutdown(socket.SHUT_WR)
            # Close without reading any response; recover only from GET history.
        deadline = time.monotonic() + 3
        view = self.call("GET", f"/api/native/projects/{p.ref}")[1]
        while not view["actions"] and time.monotonic() < deadline:
            time.sleep(0.01)
            view = self.call("GET", f"/api/native/projects/{p.ref}")[1]
        self.assertEqual(len(view["actions"]), 1)
        self.assertEqual(sum(c == "write" for c in p.channel.calls), 1)
        before = list(p.channel.calls)
        ref = view["actions"][0]["action_ref"]
        recovered = self.call("GET", f"/api/native/projects/{p.ref}/actions/{ref}")
        self.assertEqual(recovered[0], 200)
        self.assertEqual(recovered[1]["status"], "dispatched")
        self.assertEqual(p.channel.calls, before)
        self.assertEqual(self.server_errors, [])

    def test_listener_bounds_and_token_factory_do_not_launch(self):
        for args in ({"host": "0.0.0.0"}, {"port": True}, {"timeout": float("nan")}):
            with self.assertRaises(ValueError):
                SessionHttpServer(self.api, **args)
        for tokens in ({}, {"short": "p"}, {"x" * 32: ""}):
            with self.assertRaises(ValueError):
                token_authenticator(tokens)
        check = token_authenticator({"x" * 40: "p"})
        self.assertEqual(check("x" * 40), "p")
        self.assertIsNone(check("y" * 40))
        self.assertIsNone(check(None))
        with (
            patch.object(SessionHttpServer, "server_bind"),
            patch.object(SessionHttpServer, "server_activate"),
        ):
            server = SessionHttpServer(self.api, port=80)
            try:
                self.assertEqual(server.expected_host, "127.0.0.1")
                self.assertEqual(server.expected_origin, "http://127.0.0.1")
            finally:
                server.server_close()

    def test_response_timeout_does_not_issue_a_second_response(self):
        # Inject a response writer fault; no socket/process/native lifecycle.
        handler = SessionHandler.__new__(SessionHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=TimeoutError("slow client"))
        handler.wfile = Mock()
        handler._reply(200, {"status": "saved"})
        handler.send_response.assert_called_once_with(200)
        handler.wfile.write.assert_not_called()
        self.assertTrue(handler.close_connection)


if __name__ == "__main__":
    unittest.main()
