"""Authenticated HTTP behavior without any model or external service calls."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_studio.runtime import Engine  # noqa: E402
from research_studio.server import make_server  # noqa: E402
from research_studio.store import Store, StudioError  # noqa: E402

TOKEN = "synthetic-api-owner-token-1234567890"
ORIGIN = "https://owner.github.io"


class StudioHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / "data")
        self.engine = Engine(
            self.store,
            self.root / "missing-codex",
            self.root / "missing-profile",
            "0" * 40,
            TOKEN,
        )
        self.server = make_server(self.engine, TOKEN, {ORIGIN}, ("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.store.close()
        self.temp.cleanup()

    def call(self, path, *, method="GET", body=None, token=TOKEN, origin=ORIGIN):
        headers = {"Origin": origin, "Authorization": "Bearer " + token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.url + path,
            json.dumps(body).encode() if body is not None else None,
            headers,
            method=method,
        )
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, dict(response.headers), json.loads(raw)

    def test_auth_exact_cors_and_input_boundaries(self):
        self.assertEqual(self.call("/api/status", token="wrong")[0], 401)
        self.assertEqual(self.call("/api/status", origin=ORIGIN + ".evil")[0], 403)
        code, headers, body = self.call("/api/status")
        self.assertEqual(
            (code, headers["Access-Control-Allow-Origin"], body["available"]),
            (200, ORIGIN, False),
        )
        self.assertFalse(any(stage["enabled"] for stage in body["stages"]))
        self.assertEqual(self.call("/api/runs", method="OPTIONS", token="")[0], 200)
        self.assertEqual(
            self.call("/api/runs", method="POST", body={"command": "evil"})[0], 400
        )

    def test_json_escaped_tokens_are_rejected_before_any_use(self):
        for token in ("x" * 32 + '"', "x" * 32 + "\\", "x" * 32 + " ", "短" * 32):
            with self.subTest(token=repr(token)):
                with self.assertRaisesRegex(StudioError, "URL-safe"):
                    make_server(self.engine, token, {ORIGIN}, ("127.0.0.1", 0))
                # Direct Engine users cannot bypass the HTTP startup guard and
                # reach request, log-redaction or artifact paths with this token.
                with self.assertRaisesRegex(StudioError, "URL-safe"):
                    Engine(
                        self.store,
                        self.root / "codex",
                        self.root / "profile",
                        "0" * 40,
                        token,
                    )

    def test_blocked_request_persists_and_cursor_is_bounded(self):
        request = {
            "request_id": str(uuid.uuid4()),
            "topic": "Synthetic",
            "scope": "Unrestricted",
            "stage": 1,
            "scope_confirmed": True,
            "timeout_seconds": 60,
        }
        code, _, body = self.call("/api/runs", method="POST", body=request)
        self.assertEqual((code, body["run"]["status"]), (202, "blocked"))
        rid = body["run"]["id"]
        self.assertEqual(self.call("/api/runs", method="POST", body=request)[2], body)
        detail = self.call("/api/runs/" + rid)[2]
        self.assertEqual(detail["artifacts"], [])
        self.assertGreater(detail["cursor"], 0)
        self.assertEqual(
            self.call(f"/api/runs/{rid}?after=9999999999999999999999999")[0], 400
        )
        self.assertEqual(len(self.call("/api/runs")[2]["runs"]), 1)

    def test_dialogue_and_decisions_remain_authenticated_and_separate(self):
        decision = {
            "request_id": str(uuid.uuid4()),
            "stage": 2,
            "topic": "Synthetic",
            "action": "confirm_scope",
            "scope": "Compare supplied evidence",
            "run_id": None,
            "manifest_sha256": None,
            "note": "",
        }
        self.assertEqual(
            self.call("/api/decisions", method="POST", body=decision, token="wrong")[0],
            401,
        )
        self.assertEqual(
            self.call("/api/decisions", method="POST", body=decision)[0], 200
        )
        result = self.call(
            "/api/decisions/query",
            method="POST",
            body={"stage": 2, "topic": "Synthetic"},
        )
        self.assertEqual(result[2]["decisions"][0]["request"], decision)
        self.assertEqual(
            self.call(
                "/api/decisions/query",
                method="POST",
                body={"stage": True, "topic": "Synthetic"},
            )[0],
            400,
        )
        request = {
            "kind": "dialogue",
            "request_id": str(uuid.uuid4()),
            "thread_id": str(uuid.uuid4()),
            "parent_turn_id": None,
            "context_run_id": None,
            "artifact_ids": [],
            "stage": 2,
            "topic": "Synthetic",
            "message": "Which evidence is missing?",
            "timeout_seconds": 60,
        }
        self.assertEqual(self.call("/api/runs", method="POST", body=request)[0], 400)
        self.assertEqual(
            self.call("/api/dialogue/turns", method="POST", body=request)[2]["run"][
                "status"
            ],
            "blocked",
        )
        self.assertEqual(self.call("/api/runs")[2]["runs"], [])
        self.assertEqual(
            len(self.call("/api/dialogue/threads?stage=2")[2]["threads"]), 1
        )
        turn = self.call("/api/dialogue/threads/" + request["thread_id"])[2]["turns"][0]
        self.assertEqual(
            (turn["run"]["message"], turn["reply"]), (request["message"], None)
        )


if __name__ == "__main__":
    unittest.main()
