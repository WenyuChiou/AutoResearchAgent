"""Exercise the installed Codex public plugin API in a disposable home."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]


class PluginLoadingTests(unittest.TestCase):
    def test_discovery_and_skill_loading_through_public_api(self):
        codex = shutil.which(os.environ.get("CODEX_TEST_BIN", "codex"))
        self.assertIsNotNone(codex, "Install the pinned Codex test CLI first")
        with tempfile.TemporaryDirectory(prefix="stage1-plugin-") as directory:
            isolated = Path(directory)
            checkout = isolated / "repo"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            shutil.copytree(REPO / ".agents", checkout / ".agents")
            shutil.copytree(PLUGIN, checkout / "plugins" / PLUGIN.name)
            config_home = isolated / "codex"
            config_home.mkdir()
            (config_home / "config.toml").write_text(
                "[features]\nplugins = true\n", encoding="utf-8"
            )
            env = {
                **os.environ,
                "CODEX_HOME": str(config_home),
                "HOME": str(isolated),
                "USERPROFILE": str(isolated),
            }
            with tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    [codex, "app-server", "--stdio"],
                    cwd=checkout,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                )
                messages = queue.Queue()

                def read_messages():
                    for line in process.stdout:
                        messages.put(json.loads(line))

                reader = threading.Thread(target=read_messages, daemon=True)
                reader.start()
                transcript = []

                def request(number, method, params):
                    payload = {"id": number, "method": method, "params": params}
                    transcript.append({"request": payload})
                    process.stdin.write(json.dumps(payload) + "\n")
                    process.stdin.flush()
                    while True:
                        response = messages.get(timeout=30)
                        if response.get("id") == number:
                            transcript.append({"response": response})
                            self.assertNotIn("error", response, response)
                            return response["result"]

                try:
                    request(
                        1,
                        "initialize",
                        {
                            "clientInfo": {
                                "name": "stage1-contract-test",
                                "version": "1.0",
                            },
                            "capabilities": {"experimentalApi": True},
                        },
                    )
                    process.stdin.write('{"method":"initialized"}\n')
                    process.stdin.flush()
                    discovered = request(
                        2,
                        "plugin/list",
                        {
                            "cwds": [str(checkout)],
                            "marketplaceKinds": ["local"],
                        },
                    )
                    matching = [
                        p
                        for m in discovered["marketplaces"]
                        for p in m["plugins"]
                        if p["name"] == PLUGIN.name
                    ]
                    self.assertEqual(len(matching), 1, discovered)
                    detail = request(
                        3,
                        "plugin/read",
                        {
                            "marketplacePath": str(
                                checkout / ".agents/plugins/marketplace.json"
                            ),
                            "pluginName": PLUGIN.name,
                        },
                    )["plugin"]
                    self.assertEqual(detail["summary"]["name"], PLUGIN.name)
                    self.assertEqual(
                        [s["name"] for s in detail["skills"]],
                        ["auto-research-agent:stage1-literature"],
                    )
                    self.assertEqual(detail["mcpServers"], [])
                    self.assertTrue(detail["skills"][0]["description"])
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=10)
                    reader.join(timeout=5)
                    process.stdout.close()
                    evidence = os.environ.get("STAGE1_TEST_EVIDENCE_DIR")
                    if evidence:
                        output = Path(evidence)
                        output.mkdir(parents=True, exist_ok=True)
                        (output / "plugin-rpc.json").write_text(
                            json.dumps(transcript, indent=2), encoding="utf-8"
                        )
                        stderr.seek(0)
                        (output / "plugin-stderr.txt").write_bytes(stderr.read())
