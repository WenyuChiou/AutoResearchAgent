"""Synthetic configured Wiki HTTP reads bind selection and planning to one project.

The child process only reads saved material; it never dispatches a planner.
"""


# ruff: noqa: E402 -- import the repository test fixtures after adding their paths.
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "plugins/auto-research-agent/cli"),
    str(REPO / "plugins/auto-research-agent/tests"),
]
import test_project_stage2_direct_cli as direct_fixture
from test_project_stage3_planning_config import settings
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.http import token_authenticator


class ConfiguredWikiHttpTests(unittest.TestCase):
    def test_same_project_selection_and_planning_reads(self):
        repo = REPO
        f = direct_fixture.DirectDeliveryCliTests()
        f.setUp()
        proc = None
        try:
            f.eligible_delivery()
            direct, pin = f.config()
            temporary = tempfile.TemporaryDirectory(prefix="w9-")
            self.addCleanup(temporary.cleanup)
            root = Path(temporary.name).resolve()
            incoming = root / "incoming"
            incoming.mkdir()
            token = "synthetic-prepare-token-000000000000000000"
            intake = ProjectIntakeService(
                root / "projects",
                authenticate=token_authenticator({token: "local-viewer"}),
            )
            try:
                service = ProjectStage2Service(intake)
                registered = service.import_direct_request_project(
                    token,
                    delivery_dir=f.delivery_root,
                    expected_manifest_sha256=f.manifest["manifest_sha256"],
                    expected_request_sha256=f.request_hash,
                    project_id="synthetic-cli-direct",
                    input_version=1,
                )
                ref = registered["project_ref"]
                project = intake.read(token, ref)
            finally:
                intake.close()
            cfg = settings(root, [project])
            cfg_path = root / "planning-config.json"
            raw = json.dumps(cfg).encode()
            cfg_path.write_bytes(raw)
            cfg_pin = hashlib.sha256(raw).hexdigest()
            helper = (
                repo
                / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
            )
            cmd = [
                sys.executable,
                "-X",
                "utf8",
                str(repo / "harness-ui/run_v9.py"),
                "--repo",
                str(repo),
                "--source-helper-sha256",
                hashlib.sha256(helper.read_bytes()).hexdigest(),
                "--projects-root",
                str(root / "projects"),
                "--ui-state-root",
                str(root / "state"),
                "--incoming-root",
                str(incoming),
                "--run-limits",
                str(repo / "harness-ui/zero-limits.json"),
                "--port",
                "0",
                "--stage2-direct-import-config",
                str(direct),
                "--stage2-direct-import-sha256",
                pin,
                "--stage3-planning-config",
                str(cfg_path),
                "--stage3-planning-sha256",
                cfg_pin,
            ]
            errors = (root / "child-stderr.log").open("w+", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=errors,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            out = queue.Queue()
            reader = threading.Thread(
                target=lambda: out.put(proc.stdout.readline()), daemon=True
            )
            reader.start()
            try:
                try:
                    line = out.get(timeout=90)
                except queue.Empty:
                    errors.flush()
                    errors.seek(0)
                    raise RuntimeError("startup timeout; stderr: " + errors.read())
                if not line:
                    errors.flush()
                    errors.seek(0)
                    raise RuntimeError("startup failed: " + errors.read())
                startup = json.loads(line)
                assert startup["model_calls"] == 0
                base = startup["url"].rstrip("/")

                def raw_get(path, headers=None):
                    with urllib.request.urlopen(
                        urllib.request.Request(base + path, headers=headers or {}),
                        timeout=60,
                    ) as resp:
                        return resp.status, resp.read()

                status, page = raw_get("/")
                assert status == 200 and b"project-stage3-research-diagram.js" in page
                assert b'id="v93-selection-template"' in page
                assert b'<template id="v93-selection-template"><main id="selection-layout">' in page
                assert b'id="preference-bar"' in page
                assert b"project-stage2-selection.js" in page
                _, raw_binding = raw_get("/host-binding.json")
                host_binding = json.loads(raw_binding)["v9"]
                assert host_binding["formal_selection"] is False
                assert host_binding["formal_selection_scope"] == "manual-packet-only"
                assert host_binding["current_delivery_selection_configured"] is True
                assert host_binding["stage3_planning_configured"] is True
                assert host_binding["configuration_is_not_selection"] is True
                _, app_bytes = raw_get("/app.js")
                for name in ("v9-research-guide-contract.js", "v9-research-guide-view.js", "v9-research-guide.js"):
                    module_bytes = (repo / "harness-ui" / name).read_bytes()
                    assert host_binding["modules"][name] == hashlib.sha256(module_bytes).hexdigest()
                    assert module_bytes in app_bytes
                _, css_bytes = raw_get("/runtime.css")
                assert (repo / "harness-ui/v9-research-guide.css").read_bytes() in css_bytes
                status, bootstrap = raw_get("/project-bootstrap.js")
                boot = json.loads(
                    bootstrap.decode().split("=", 1)[1].strip().removesuffix(";")
                )
                assert (
                    boot["wiki_v9"] is True
                    and ref in boot["stage2_selection_projects"]
                    and ref in boot["stage3_planning_projects"]
                )
                status, script = raw_get("/project-stage3-research-diagram.js")
                assert status == 200 and b"STAGE3_RESEARCH_DIAGRAM" in script
                auth = {"Origin": base, "Authorization": "Bearer " + boot["credential"]}
                path = "/api/projects/" + ref
                _, selection = raw_get(path + "/stage2/selection", auth)
                selection = json.loads(selection)
                _, planning = raw_get(path + "/stage3/planning", auth)
                planning = json.loads(planning)
                for v in (selection, planning):
                    assert (
                        v["project_ref"] == ref
                        and v["input_version"] == project["input_version"]
                        and v["brief_sha256"] == project["brief_sha256"]
                        and not v["execution_authorized"]
                    )
                assert not (root / "capture-0").exists()
                print(
                    json.dumps(
                        {
                            "passed": True,
                            "kind": "synthetic-configured-wiki-http-read",
                            "project_ref": ref,
                            "selection_eligible": len(selection["eligible"]),
                            "planning_configured": planning["planning_configured"],
                            "model_calls": 0,
                            "human_choice": False,
                            "browser_test": False,
                            "wiki_script_sha256": hashlib.sha256(script).hexdigest(),
                            "fixture_root": str(root),
                        }
                    ),
                    flush=True,
                )
            finally:
                proc.terminate()
                proc.wait(timeout=20)
                reader.join(timeout=3)
                proc.stdout.close()
                errors.close()
        finally:
            f.doCleanups()


if __name__ == "__main__":
    unittest.main()
