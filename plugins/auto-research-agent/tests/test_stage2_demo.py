"""Actual HTTP/SQLite/fixed SyntheticAdapter execution; no live research calls."""
# ruff: noqa: E402 -- load the installed repository CLI and example fixture.

import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

CANDIDATE = Path(__file__).resolve().parent
PLUGIN = Path(__file__).resolve().parents[1]
if not (PLUGIN / "cli").is_dir():
    PLUGIN = Path(os.environ["ATLAS_DEMO_TEST_REPO"]) / "plugins/auto-research-agent"
REPO = PLUGIN.parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace_native.atlas_local_source import inventory
from research_workspace_native.http import SessionHttpServer, token_authenticator
from research_workspace_native.session_api import SessionApi

script = CANDIDATE / "stage2-demo.py"
if not script.is_file():
    script = PLUGIN / "references/research-workspace/examples/stage2-demo.py"
spec = importlib.util.spec_from_file_location("stage2_demo", script)
demo_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_module)


class DemoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.token = "t" * 40
        self.authenticate = token_authenticator({self.token: "local-viewer"})
        self.pins = {"cli/" + k: v for k, v in inventory(PLUGIN / "cli").items()}
        self.pins.update(
            {
                "tests/" + p.name: demo_module.digest(p.read_bytes())
                for p in (PLUGIN / "tests").glob("*.py")
            }
        )
        self.demo = self.new_demo()
        self.addCleanup(self.demo.close)
        self.server = SessionHttpServer(
            SessionApi(authenticate=self.authenticate), timeout=30
        )
        self.server.authenticate = self.authenticate
        demo_module.install(self.server, self.demo)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)

    def new_demo(self, **extra):
        return demo_module.RepositoryStage2Demo(
            self.root / "stage2",
            repo=REPO,
            sources=self.pins,
            project_ref="stage2",
            index_sha256="a" * 64,
            authenticate=self.authenticate,
            **extra,
        )

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.demo.close()

    def request(self, method="GET", body=None, *, suffix="stage2", headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=60)
        supplied = {"Authorization": "Bearer " + self.token}
        if method == "POST":
            supplied.update(
                Origin=self.server.expected_origin,
                **{"Content-Type": "application/json"},
            )
        supplied.update(headers or {})
        raw = None if body is None else json.dumps(body).encode()
        try:
            connection.request(method, "/api/stage2-demo/" + suffix, raw, supplied)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def body(self):
        return dict(
            key=demo_module.KEY,
            case_sha256=self.demo.case_sha256,
            index_sha256="a" * 64,
            confirmed=True,
        )

    def test_changed_source_binding_auth_project_and_missing_confirmation_zero_child(
        self,
    ):
        invalid = self.body()
        invalid["case_sha256"] = "b" * 64
        with patch.object(
            demo_module.subprocess,
            "Popen",
            side_effect=AssertionError("no denied child"),
        ):
            self.assertEqual(self.request("POST", invalid)[0], 409)
            invalid = self.body()
            invalid["confirmed"] = False
            self.assertEqual(self.request("POST", invalid)[0], 409)
            self.assertEqual(self.request("POST", self.body(), suffix="other")[0], 404)
            self.assertEqual(
                self.request(
                    "POST", self.body(), headers={"Origin": "https://other.invalid"}
                )[0],
                403,
            )
            self.assertEqual(
                self.request(headers={"Authorization": "Bearer bad"})[0], 401
            )
            self.assertIsNone(self.request()[1]["action"])

    def test_worker_failure_is_retained_no_automatic_retry(self):
        popen = subprocess.Popen

        def failed_worker(command, **options):
            self.assertIn("--worker", command)
            return popen(
                [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"], **options
            )

        with patch.object(demo_module.subprocess, "Popen", side_effect=failed_worker):
            code, result = self.request("POST", self.body())
        self.assertEqual(code, 200)
        self.assertEqual(
            (result["action"]["status"], result["action"]["exit_code"]), ("failed", 7)
        )
        with patch.object(
            demo_module.subprocess, "Popen", side_effect=AssertionError("no retry")
        ):
            self.assertEqual(
                self.request("POST", self.body())[1]["action"], result["action"]
            )

    def test_timeout_kills_reaps_and_unknown_survives_new_owner(self):
        popen, children = subprocess.Popen, []

        def delayed_worker(command, **options):
            self.assertIn("--worker", command)
            child = popen(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(10)"],
                **options,
            )
            children.append(child)
            return child

        with (
            patch.object(demo_module, "MAX_SECONDS", 0.1),
            patch.object(demo_module.subprocess, "Popen", side_effect=delayed_worker),
        ):
            code, result = self.request("POST", self.body())
        self.assertEqual(code, 200)
        self.assertEqual(result["action"]["status"], "execution-unknown")
        self.assertTrue(result["action"]["worker_reaped"])
        self.assertIsNotNone(children[0].poll())
        self.demo.close()
        reopened = self.new_demo()
        try:
            with patch.object(
                demo_module.subprocess,
                "Popen",
                side_effect=AssertionError("no unknown retry"),
            ):
                actual = reopened.execute(
                    self.token, "stage2", self.body(), deadline=time.monotonic() + 60
                )
                self.assertEqual(actual["action"]["status"], "execution-unknown")
        finally:
            reopened.close()

    def test_preintent_expired_request_and_postintent_crash_fail_closed(self):
        with patch.object(
            demo_module.subprocess,
            "Popen",
            side_effect=AssertionError("no expired child"),
        ):
            with self.assertRaisesRegex(Exception, "demo-deadline-expired"):
                self.demo.execute(
                    self.token, "stage2", self.body(), deadline=time.monotonic() - 1
                )
            self.assertIsNone(self.request()[1]["action"])
        with self.demo.store._edit(
            demo_module.PID, self.demo.owner, None, "simulated-crash-after-intent", {}
        ) as state:
            state["intents"][demo_module.KEY] = dict(
                status="running", method="synthetic-stage2/run"
            )
        self.demo.close()
        reopened = self.new_demo()
        try:
            with patch.object(
                demo_module.subprocess,
                "Popen",
                side_effect=AssertionError("no crash resend"),
            ):
                actual = reopened.execute(
                    self.token, "stage2", self.body(), deadline=time.monotonic() + 60
                )
            self.assertEqual(actual["action"]["status"], "execution-unknown")
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
