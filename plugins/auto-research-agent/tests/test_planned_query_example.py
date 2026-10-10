"""Public download example: actual loopback API/ledger with a fake Hub boundary."""

import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


PLUGIN = Path(__file__).resolve().parents[1]


class PlannedQueryExampleTests(unittest.TestCase):
    def test_complete_checkout_explicit_query_saved_stage2_and_no_repeat(self):
        with tempfile.TemporaryDirectory(prefix="query-example-") as folder:
            fixture_lifetime, cleanup_allowance = 60, 15
            root = Path(folder).resolve()
            repo = root / "repo"
            plugin = repo / "plugins/auto-research-agent"
            plugin.mkdir(parents=True)
            for name in (
                "cli",
                "schemas",
                "tests",
                "evals",
                "references/research-workspace",
            ):
                shutil.copytree(
                    PLUGIN / name,
                    plugin / name,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc", ".ruff_cache"
                    ),
                )
            prefix = [
                "git",
                "-c",
                "core.longpaths=true",
                "-c",
                "core.autocrlf=false",
                "-c",
                "user.name=Synthetic fixture",
                "-c",
                "user.email=fixture@invalid",
                "-c",
                "commit.gpgsign=false",
            ]
            for command in (
                ["init", "-q"],
                ["add", "--", "plugins/auto-research-agent"],
                ["commit", "-qm", "Synthetic test-owned source snapshot"],
            ):
                result = subprocess.run(
                    prefix + command,
                    cwd=repo,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                    shell=False,
                )
                self.assertEqual(
                    result.returncode, 0, result.stderr.decode("utf8", "replace")
                )
            output = root / "output"
            example = (
                plugin
                / "references/research-workspace/examples/build-planned-query-fixture.py"
            )
            log = root / "example.log"
            process = None
            with log.open("wb") as stream:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-X",
                        "utf8",
                        str(example),
                        "--output",
                        str(output),
                        "--serve",
                        "--port",
                        "0",
                        "--lifetime",
                        str(fixture_lifetime),
                    ],
                    cwd=repo,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    shell=False,
                )
                try:
                    ready = output / "serving-receipt.json"
                    until = time.monotonic() + 120
                    while (
                        not ready.exists()
                        and process.poll() is None
                        and time.monotonic() < until
                    ):
                        time.sleep(0.05)
                    self.assertTrue(
                        ready.is_file(),
                        log.read_text(encoding="utf8", errors="replace"),
                    )
                    receipt = json.loads(ready.read_bytes())
                    self.assertEqual(
                        receipt["classification"], "synthetic-repository-fixture"
                    )
                    self.assertFalse(receipt["researcher_confirmed_intake"])
                    self.assertFalse(receipt["native_process_started"])
                    self.assertFalse(receipt["model_call_started"])
                    self.assertFalse(receipt["real_search_started"])
                    self.assertEqual(
                        receipt["native_script_role"], "fixture-notice-only"
                    )
                    origin = receipt["origin"]
                    self.assertRegex(origin, r"^http://127\.0\.0\.1:[0-9]+$")
                    port = int(origin.rsplit(":", 1)[1])

                    def call(path, body=None, *, token=None, request_origin=None):
                        connection = http.client.HTTPConnection(
                            "127.0.0.1", port, timeout=15
                        )
                        headers = {"Authorization": "Bearer " + token} if token else {}
                        if body is not None:
                            headers.update(
                                Origin=request_origin or origin,
                                **{"Content-Type": "application/json"},
                            )
                        try:
                            connection.request(
                                "POST" if body is not None else "GET",
                                path,
                                json.dumps(body) if body is not None else None,
                                headers,
                            )
                            response = connection.getresponse()
                            return response.status, response.read()
                        finally:
                            connection.close()

                    status, bootstrap = call("/host-bootstrap/case.js")
                    self.assertEqual(status, 200)
                    match = re.search(rb"window\.WORKSPACE_HOST=(.+?);\n", bootstrap)
                    self.assertIsNotNone(match)
                    token = json.loads(match.group(1))["credential"]
                    self.assertNotIn(token, json.dumps(receipt))
                    self.assertIn(
                        b"stage-query-panel.js", call("/views/case/atlas.html")[1]
                    )
                    notice = call("/native-atlas-chat.js")[1]
                    self.assertIn("模拟后端工程案例".encode(), notice)
                    self.assertIn("模擬後端工程案例".encode(), notice)
                    base = "/api/stages/projects/case/queries"
                    status, raw = call(base, token=token)
                    self.assertEqual(status, 200, raw)
                    initial = json.loads(raw)
                    self.assertEqual(initial["history"], [])
                    self.assertEqual(initial["budget"], {"attempts": 0, "seconds": 0})
                    self.assertFalse(initial["automatic_retry"])
                    status, raw = call(base + "/offer", token=token)
                    self.assertEqual(status, 200, raw)
                    offer = json.loads(raw)
                    body = dict(
                        key="offline-example-first",
                        revision=offer["revision"],
                        index_sha256=offer["document"]["index_sha256"],
                        input_version=offer["document"]["input_version"],
                        offer_ref=offer["offer_ref"],
                        offer_sha256=offer["offer_sha256"],
                        confirmed=True,
                    )
                    self.assertEqual(
                        call(
                            base + "/actions",
                            body,
                            token=token,
                            request_origin="https://foreign.invalid",
                        )[0],
                        403,
                    )
                    self.assertEqual(
                        call(base + "/actions", dict(body, permit=True), token=token)[
                            0
                        ],
                        400,
                    )
                    self.assertEqual(
                        json.loads(call(base, token=token)[1])["history"], []
                    )
                    status, raw = call(base + "/actions", body, token=token)
                    self.assertEqual(status, 200, raw)
                    until = time.monotonic() + 40
                    row = None
                    while time.monotonic() < until:
                        status, raw = call(
                            base + "/actions/" + body["key"], token=token
                        )
                        self.assertEqual(status, 200, raw)
                        row = json.loads(raw)
                        if row["status"] == "completed":
                            break
                        time.sleep(0.05)
                    self.assertEqual(row["status"], "completed", row)
                    self.assertEqual(
                        row["result"]["backend_outcome"], "success_nonempty"
                    )
                    self.assertFalse(row["result"]["stage_complete"])
                    self.assertFalse(row["model_execution"])
                    self.assertEqual(
                        json.loads(
                            call(base + "/actions/" + body["key"], token=token)[1]
                        ),
                        row,
                    )
                    self.assertEqual(
                        json.loads(call(base + "/actions", body, token=token)[1]), row
                    )
                    view = json.loads(call(base, token=token)[1])
                    self.assertEqual(view["budget"], {"attempts": 1, "seconds": 32})
                    stage_base = "/api/stages/projects/stage2"
                    status, raw = call(
                        stage_base + "/offers/2/inspect-stage2", token=token
                    )
                    self.assertEqual(status, 200, raw)
                    stage_offer = json.loads(raw)
                    stage_body = dict(
                        stage=2,
                        action="inspect-stage2",
                        key="saved-stage2",
                        revision=stage_offer["revision"],
                        index_sha256=stage_offer["document"]["index_sha256"],
                        input_version=stage_offer["document"]["input_version"],
                        offer_ref=stage_offer["offer_ref"],
                        offer_sha256=stage_offer["offer_sha256"],
                        decision=None,
                        note="",
                        confirmed=False,
                    )
                    status, raw = call(stage_base + "/actions", stage_body, token=token)
                    self.assertEqual(status, 200, raw)
                    self.assertEqual(json.loads(raw)["status"], "completed", raw)
                    self.assertFalse(json.loads(raw)["execution_authorized"])
                    self.assertEqual(
                        process.wait(timeout=fixture_lifetime + cleanup_allowance),
                        0,
                        log.read_text(encoding="utf8", errors="replace"),
                    )
                    completion = json.loads(
                        (output / "completion-receipt.json").read_bytes()
                    )
                    self.assertEqual(len(completion["injected_children"]), 1)
                    self.assertTrue(completion["source_manifest_unchanged"])
                    self.assertTrue(completion["head_unchanged"])
                    self.assertEqual(completion["cleanup_errors"], [])
                finally:
                    if process.poll() is None:
                        try:
                            process.wait(
                                timeout=fixture_lifetime + cleanup_allowance
                            )  # Prefer normal bounded lease cleanup.
                        except subprocess.TimeoutExpired:
                            if sys.platform == "win32":
                                subprocess.run(
                                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    shell=False,
                                    timeout=10,
                                )  # Captured live fixture parent and its own children only.
                            else:
                                process.terminate()
                            process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
