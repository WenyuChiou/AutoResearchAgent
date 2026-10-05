"""Real loopback HTTP/SQLite with synthetic assets, briefs and injected channels."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
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
import test_research_workspace_native_scope_api as fixtures
from research_workspace_native import scope_http, wiki_http
from research_workspace_native.http import token_authenticator
from research_workspace_native.scope_api import ScopeApi
from research_workspace_native.session_api import SessionApi


class ScopeHttpTests(unittest.TestCase):
    project = fixtures.ScopeApiTests.project
    brief = fixtures.ScopeApiTests.brief

    def setUp(self):
        fixtures.ScopeApiTests.setUp(self)
        self.token = "a" * 40
        self.api = SessionApi(
            authenticate=token_authenticator({self.token: "principal-a"})
        )
        self.scope = ScopeApi(self.api)
        self.assets = {
            "prototype.html": b"<html><head></head><body></body></html>",
            "workspace.css": b"body{}",
            "workspace-i18n.js": b"/* synthetic translation */",
            "literature-reference.js": b"/* synthetic literature */",
        }
        pins = {
            name: hashlib.sha256(raw).hexdigest() for name, raw in self.assets.items()
        }
        patcher = patch.object(wiki_http, "REFERENCE_HASHES", pins)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.readme = b"# Synthetic accepted README\n"
        readme_pin = patch.object(
            wiki_http, "PUBLIC_README_SHA256", hashlib.sha256(self.readme).hexdigest()
        )
        readme_pin.start()
        self.addCleanup(readme_pin.stop)
        self.server = scope_http.ScopeWikiSessionServer(
            self.api,
            scope_api=self.scope,
            reference_assets=self.assets,
            public_readme=self.readme,
        )
        self.errors = []
        self.server.handle_error = lambda *_: self.errors.append("handler error")
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()

        def close():
            self.server.shutdown()
            self.server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.errors, [])

        self.addCleanup(close)

    def call(self, path, *, method="GET", body=None, headers=None):
        merged = {"Authorization": "Bearer " + self.token}
        if method == "POST":
            merged.update(
                Origin=self.server.expected_origin,
                **{"Content-Type": "application/json"},
            )
        merged.update(headers or {})
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        try:
            connection.request(method, path, raw, merged)
            response = connection.getresponse()
            data = response.read()
            value = (
                json.loads(data)
                if response.getheader("Content-Type", "").startswith("application/json")
                else data
            )
            return response.status, value, dict(response.getheaders())
        finally:
            connection.close()

    def path(self, p, suffix=""):
        return "/api/native/projects/" + p.ref + "/scope" + suffix

    def body(self, p):
        _, view, _ = self.call(self.path(p))
        parent = view["versions"][-1]
        return dict(
            key="browser-choice",
            revision=view["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            confirmed=True,
            parent_ref=parent["version_ref"],
            parent_sha256=parent["sha256"],
            choices=[
                dict(
                    field="geography",
                    status="specified",
                    value="Region A",
                    reason="Synthetic choice.",
                    user_input="Use Region A.",
                )
            ],
        )

    def test_constructor_binding_static_assets_and_native_read_route(self):
        other = ScopeApi(SessionApi(authenticate=lambda _: "principal-a"))
        with patch.object(wiki_http.SessionHttpServer, "__init__") as listener:
            with self.assertRaises(ValueError):
                scope_http.ScopeWikiSessionServer(
                    self.api, scope_api=other, reference_assets=self.assets
                )
            listener.assert_not_called()
        p = self.brief()
        status, raw, headers = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"/session-scope.js", raw)
        self.assertIn(b"/session-scope.css", raw)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        for name in ("session-scope.js", "session-scope.css"):
            self.assertEqual(self.call("/" + name)[0], 200)
        self.assertEqual(self.call("/api/native/projects/" + p.ref)[0], 200)
        self.assertEqual(p.channel.calls, [])

    def test_http_append_old_version_review_and_private_identity_redaction(self):
        p = self.brief()
        body = self.body(p)
        status, saved, _ = self.call(
            self.path(p, "/versions"), method="POST", body=body
        )
        self.assertEqual((status, saved["status"]), (200, "version-saved"))
        _, view, _ = self.call(self.path(p))
        old = view["versions"][0]
        status, original, _ = self.call(self.path(p, "/versions/" + old["version_ref"]))
        self.assertEqual((status, original["pending_fields"]), (200, ["geography"]))
        review = dict(
            key="review",
            revision=view["revision"],
            index_sha256=p.hash,
            input_version=p.version,
            confirmed=True,
            version_ref=old["version_ref"],
            version_sha256=old["sha256"],
            decision="changes-requested",
            note="Pending geography.",
        )
        status, receipt, _ = self.call(
            self.path(p, "/reviews"), method="POST", body=review
        )
        self.assertEqual((status, receipt["status"]), (200, "review-recorded"))
        self.assertFalse(receipt["execution_authorized"])
        public = json.dumps([view, original, receipt])
        for private in (
            p.pid,
            p.thread,
            p.epoch,
            p.root.as_posix(),
            self.token,
            "private-source-marker",
        ):
            self.assertNotIn(private, public)
        self.assertEqual(p.channel.calls, [])

    def test_host_origin_auth_crossproject_and_strict_fields_reject_before_mutation(
        self,
    ):
        p, other = self.brief(), self.brief("b", "principal-b")
        body = self.body(p)
        before = p.store.snapshot(p.pid)
        checks = len(p.source_checks)
        for headers in (
            {"Host": "evil.example"},
            {"Origin": "null"},
            {"Authorization": "Bearer wrong"},
        ):
            self.assertIn(self.call(self.path(p), headers=headers)[0], (401, 403))
        self.assertEqual(len(p.source_checks), checks)
        self.assertEqual(self.call(self.path(other))[0], 404)
        self.assertEqual(
            self.call(
                self.path(p, "/versions"),
                method="POST",
                body=body,
                headers={"Origin": ""},
            )[0],
            403,
        )
        for raw in (
            dict(body, source_root="/private"),
            b'{"key":"x","key":"y"}',
            b'{"value":NaN}',
            b"[]",
        ):
            self.assertEqual(
                self.call(self.path(p, "/versions"), method="POST", body=raw)[0], 400
            )
        for suffix in ("/start", "/versions/../../secret", "/versions?root=x"):
            self.assertEqual(self.call(self.path(p, suffix))[0], 404)
        self.assertEqual(p.store.snapshot(p.pid), before)
        self.assertEqual(p.channel.calls + other.channel.calls, [])

    def test_concurrent_http_replay_and_changed_payload_preserve_one_version(self):
        p = self.brief()
        body = self.body(p)

        def submit(_):
            return self.call(self.path(p, "/versions"), method="POST", body=body)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual([row[0] for row in results], [200] * 4)
        self.assertEqual(sum(not row[1]["replayed"] for row in results), 1)
        changed = dict(body, choices=[dict(body["choices"][0], value="Region B")])
        self.assertEqual(
            self.call(self.path(p, "/versions"), method="POST", body=changed)[0], 409
        )
        self.assertEqual(
            self.call(
                self.path(p, "/versions"),
                method="POST",
                body=dict(body, confirmed=False),
            )[0],
            400,
        )
        _, history, _ = self.call(self.path(p))
        self.assertEqual(len(history["versions"]), 2)
        self.assertEqual(history["actions"][0]["client_key"], body["key"])
        self.assertEqual(p.channel.calls, [])

    def test_closed_response_client_recovers_saved_action_without_second_append(self):
        p = self.brief()
        body = self.body(p)
        raw = json.dumps(body).encode()
        headers = (
            f"POST {self.path(p, '/versions')} HTTP/1.1\r\nHost: {self.server.expected_host}\r\n"
            f"Origin: {self.server.expected_origin}\r\nAuthorization: Bearer {self.token}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
        ).encode()
        with socket.create_connection(
            self.server.server_address, timeout=3
        ) as connection:
            connection.sendall(headers + raw)
            connection.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + 3
        while True:
            _, history, _ = self.call(self.path(p))
            if history["actions"] or time.monotonic() > deadline:
                break
            time.sleep(0.01)
        self.assertEqual(len(history["actions"]), 1)
        status, replay, _ = self.call(
            self.path(p, "/versions"), method="POST", body=body
        )
        self.assertEqual((status, replay["replayed"]), (200, True))
        self.assertEqual(len(p.store.snapshot(p.pid)["scope_overlay"]["order"]), 2)
        p.brief_path.write_bytes(p.brief_raw + b" ")
        self.assertEqual(self.call(self.path(p))[0], 409)
        self.assertEqual(p.channel.calls, [])


if __name__ == "__main__":
    unittest.main()
