"""Synthetic assets + real temporary HTTP/journals; no browser/native/model."""

import base64
import hashlib
import http.client
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
import test_research_workspace_native_session_api as fixtures
from research_workspace_native import wiki_http
from research_workspace_native.http import token_authenticator
from research_workspace_native.session_api import SessionApi


class WikiHttpTests(unittest.TestCase):
    project = fixtures.SessionApiTests.project
    push = fixtures.SessionApiTests.push

    def request(self, p):
        self.push(
            p,
            {
                "id": 83,
                "method": "item/tool/requestUserInput",
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
            result={"answers": {"q": {"answers": ["reply"]}}},
        )
        body.update(changes)
        return body

    def setUp(self):
        fixtures.SessionApiTests.setUp(self)
        self.token = "a" * 40
        self.api = SessionApi(
            authenticate=token_authenticator({self.token: "principal-a"})
        )
        self.assets = {
            "prototype.html": b"<html><head></head><body><script>window.test=true;</script></body></html>",
            "workspace.css": b"body{}",
            "workspace-i18n.js": b"/* synthetic translation */",
            "literature-reference.js": b"/* synthetic literature */",
        }
        pins = {
            name: hashlib.sha256(raw).hexdigest() for name, raw in self.assets.items()
        }
        self.pins = patch.object(wiki_http, "REFERENCE_HASHES", pins)
        self.pins.start()
        self.addCleanup(self.pins.stop)
        self.readme = b"# Synthetic public documentation"
        readme_pin = patch.object(
            wiki_http, "PUBLIC_README_SHA256", hashlib.sha256(self.readme).hexdigest()
        )
        readme_pin.start()
        self.addCleanup(readme_pin.stop)
        self.server = wiki_http.WikiSessionServer(
            self.api, reference_assets=self.assets, public_readme=self.readme
        )
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()

        def stop():
            self.server.shutdown()
            self.server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)

    def call(self, path, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_reference_hashes_checked_before_listener_and_assets_are_exact(self):
        for assets in (
            dict(self.assets, **{"workspace.css": b"changed"}),
            {},
            dict(self.assets, private=b"private payload"),
        ):
            with patch.object(wiki_http.SessionHttpServer, "__init__") as listener:
                with self.assertRaises(ValueError):
                    wiki_http.WikiSessionServer(
                        self.api, reference_assets=assets, public_readme=self.readme
                    )
                listener.assert_not_called()
        self.assertEqual(self.call("/README.md")[:2], (200, self.readme))
        with self.assertRaises(ValueError):
            wiki_http.WikiSessionServer(
                self.api, reference_assets=self.assets, public_readme=b"changed"
            )
        for name in ("workspace.css", "workspace-i18n.js", "literature-reference.js"):
            status, raw, _ = self.call("/" + name)
            self.assertEqual((status, raw), (200, self.assets[name]))

    def test_public_static_display_never_grants_private_api_access(self):
        p = self.project()
        before = list(p.channel.calls)
        status, raw, headers = self.call("/")
        self.assertEqual(status, 200)
        text = raw.decode()
        self.assertIn("/session-panel.js", text)
        self.assertIn("/session-panel.css", text)
        for value in (p.pid, p.thread, p.epoch, p.root.as_posix(), self.token):
            self.assertNotIn(value, text)
        expected = base64.b64encode(
            hashlib.sha256(b"window.test=true;").digest()
        ).decode()
        self.assertIn("'sha256-" + expected + "'", headers["Content-Security-Policy"])
        self.assertNotIn(
            "script-src 'self' 'unsafe-inline'", headers["Content-Security-Policy"]
        )
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.call("/api/native/projects/" + p.ref)[0], 401)
        self.assertEqual(p.channel.calls, before)

    def test_static_allowlist_and_origin_reject_before_any_private_read(self):
        p = self.project()
        before = len(p.source_checks)
        for path in (
            "/../index.json",
            "/index.json",
            "/?token=secret",
            "/web/session-panel.js",
            "/prototype.html",
        ):
            self.assertEqual(self.call(path)[0], 404)
        for headers in (
            {"Host": "evil.example"},
            {"Origin": "null"},
            {"Origin": "https://evil.example"},
            {"Content-Length": "1"},
            {"Transfer-Encoding": "chunked"},
        ):
            self.assertIn(self.call("/", headers)[0], (400, 403))
        self.assertEqual(len(p.source_checks), before)
        self.assertEqual(p.channel.calls, [])

    def test_saved_action_exposes_only_client_key_and_opaque_target_for_recovery(self):
        p = self.project()
        request = self.request(p)
        body = self.body(p, request, key="browser-key")
        receipt = self.api.answer(self.token, p.ref, body)
        self.assertEqual(receipt["client_key"], "browser-key")
        self.assertEqual(receipt["target_ref"], request["request_ref"])
        before = list(p.channel.calls)
        history = self.api.view(self.token, p.ref)["actions"]
        self.assertEqual(history[0]["client_key"], receipt["client_key"])
        self.assertEqual(history[0]["target_ref"], receipt["target_ref"])
        self.assertNotIn("result", receipt)
        self.assertNotIn("request_identity", receipt)
        self.assertEqual(p.channel.calls, before)


if __name__ == "__main__":
    unittest.main()
