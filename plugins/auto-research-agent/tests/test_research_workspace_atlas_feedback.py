"""Real HTTP feedback persistence; no native processes or tasks are dispatched."""

import http.client
import json
from pathlib import Path
import subprocess
import threading
import unittest

import test_research_workspace_atlas_host as fixtures
from research_workspace_native.atlas_host import AtlasHost, load_views


class AtlasFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AtlasHostTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.root / "feedback.sqlite"
        self.files, self.views = load_views(self.fixture.config, self.fixture.pin)

    def start(self):
        server = AtlasHost(files=self.files, views=self.views, maintenance_db=self.db)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server, stop

    def request(self, server, method, path, body=None, headers=None):
        defaults = {"Authorization": "Bearer " + server.credential}
        if method == "POST":
            defaults.update(
                Origin=server.expected_origin, **{"Content-Type": "application/json"}
            )
        defaults.update(headers or {})
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            client.request(method, path, body=body, headers=defaults)
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def submit(
        self, server, key="feedback-1", text="保留 v6。 Stage 2 needs clearer routes."
    ):
        return self.request(
            server,
            "POST",
            "/api/maintenance/stage1",
            json.dumps(
                {
                    "stage": 2,
                    "message": text,
                    "key": key,
                }
            ),
        )

    def test_saved_receipt_reopen_and_lost_response_recovery_do_not_dispatch(self):
        server, stop = self.start()
        status, saved = self.submit(server)
        self.assertEqual(status, 200)
        self.assertEqual(saved["status"], "recorded-not-dispatched")
        self.assertEqual(saved["index_sha256"], self.views[0]["index_sha256"])
        for _ in range(2):
            self.assertEqual(self.submit(server)[1]["sequence"], saved["sequence"])
        self.assertEqual(server.api._projects, {})
        stop()
        restarted, _ = self.start()
        rows = self.request(restarted, "GET", "/api/maintenance/stage1")[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["message"], saved["message"])
        status, exact = self.request(
            restarted, "GET", "/api/maintenance/stage1/feedback-1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(exact["sequence"], saved["sequence"])
        self.assertEqual(self.submit(restarted)[1]["sequence"], saved["sequence"])
        self.assertEqual(restarted.api._projects, {})

    def test_changed_payload_and_caller_authority_fields_reject(self):
        server, _ = self.start()
        self.assertEqual(self.submit(server)[0], 200)
        self.assertEqual(self.submit(server, text="different")[0], 409)
        body = json.dumps(
            {"stage": 1, "message": "test", "key": "feedback-2", "root": "C:/"}
        )
        self.assertEqual(
            self.request(server, "POST", "/api/maintenance/stage1", body)[0], 400
        )
        rows = self.request(server, "GET", "/api/maintenance/stage1")[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.request(server, "GET", "/api/maintenance/stage2")[1], [])

    def test_auth_origin_duplicate_json_and_cross_case_guards(self):
        server, _ = self.start()
        body = '{"stage":1,"message":"hello","key":"x"}'
        for headers in (
            {"Origin": "https://elsewhere.invalid"},
            {"Host": "invalid"},
            {"Authorization": "Bearer wrong"},
        ):
            self.assertIn(
                self.request(server, "POST", "/api/maintenance/stage1", body, headers)[
                    0
                ],
                (401, 403),
            )
        duplicate = '{"stage":1,"stage":2,"message":"hello","key":"x"}'
        self.assertEqual(
            self.request(server, "POST", "/api/maintenance/stage1", duplicate)[0], 400
        )
        self.assertEqual(
            self.request(server, "POST", "/api/maintenance/missing", body)[0], 409
        )
        self.assertEqual(
            self.request(server, "POST", "/api/native/projects/stage1/answers", body)[
                0
            ],
            405,
        )
        self.assertEqual(self.request(server, "GET", "/api/maintenance/stage1")[1], [])

    def test_history_cursor_reaches_record_101_and_rejects_bad_queries(self):
        server, _ = self.start()
        for i in range(101):
            server.maintenance.submit("stage1", 1, f"Feedback {i}", f"page-{i}")
        status, first = self.request(server, "GET", "/api/maintenance/stage1")
        self.assertEqual(status, 200)
        self.assertEqual(len(first), 100)
        status, last = self.request(
            server,
            "GET",
            f"/api/maintenance/stage1?after_seq={first[-1]['sequence']}&limit=100",
        )
        self.assertEqual(status, 200)
        self.assertEqual([row["key"] for row in last], ["page-100"])
        for query in (
            "after_seq=-1",
            "after_seq=1&after_seq=2",
            "limit=101",
            "other=1",
            "after_seq=abc",
            "limit=",
        ):
            self.assertEqual(
                self.request(server, "GET", "/api/maintenance/stage1?" + query)[0], 400
            )
        self.assertEqual(
            self.request(server, "GET", "/api/maintenance/stage1/page-100?limit=1")[0],
            400,
        )

    def test_browser_history_pagination_retains_rows_on_invalid_page(self):
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).with_name("test-atlas-feedback-pagination.cjs")),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GET-only PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
