"""Synthetic configured Wiki HTTP reads bind selection and planning to one project.

The child process only reads saved material; it never dispatches a planner.
"""

# ruff: noqa: E402 -- import the repository test fixtures after adding their paths.
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
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
from research_workspace_native.source_worker_process import WindowsJobProcess


# The pinned launcher must still run in a fresh interpreter. This observer adds
# only a private fixture shutdown pipe; it delegates the original server loop.
WIKI_CHILD_OBSERVER = r"""
import json
import os
from pathlib import Path
import runpy
import socketserver
import sqlite3
import sys
import threading

entry = Path(sys.argv[1]).resolve()
receipt = Path(os.environ["WIKI_TEST_LIFECYCLE_RECEIPT"])
sys.argv = [str(entry), *sys.argv[2:]]
sys.path.insert(0, str(entry.parent))
original_serve = socketserver.BaseServer.serve_forever
observed = {}

def serve(host, *args, **kwargs):
    if observed:
        raise RuntimeError("fixture expected exactly one owned server")
    observed["host"] = host
    observed["databases"] = [host.projects.db]
    observed["journals"] = [
        binding["jobs"].journal
        for binding in host.project_stage3_http.service.bindings.values()
    ]
    observed["databases"].extend(journal.db for journal in observed["journals"])

    def stop_owned_server():
        try:
            command = sys.stdin.readline()
            if command not in ("wiki-test-shutdown\n", ""):
                raise RuntimeError("unexpected fixture shutdown command")
            host.shutdown()
        except BaseException as error:
            observed["shutdown_error"] = repr(error)

    waiter = threading.Thread(target=stop_owned_server, name="wiki-fixture-stop")
    observed["waiter"] = waiter
    waiter.start()
    try:
        return original_serve(host, *args, **kwargs)
    finally:
        waiter.join(timeout=5)

socketserver.BaseServer.serve_forever = serve
try:
    runpy.run_path(str(entry), run_name="__main__")
finally:
    host = observed.get("host")
    closed = []
    for database in observed.get("databases", []):
        try:
            database.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            closed.append(True)
        else:
            closed.append(False)
    value = dict(
        pid=os.getpid(),
        parent_pid=os.getppid(),
        python_executable=sys.executable,
        original_entrypoint=str(entry),
        listener_closed=host is not None and host.socket.fileno() == -1,
        shutdown_waiter_joined="waiter" in observed
        and not observed["waiter"].is_alive(),
        databases_closed=bool(closed) and all(closed),
        journal_owner_handles_released=bool(observed.get("journals"))
        and all(not journal._owners for journal in observed["journals"]),
        planning_shutdown=getattr(host, "planning_shutdown", None),
        shutdown_error=observed.get("shutdown_error"),
        wrapped_interpreter_entrypoint=True,
    )
    receipt.write_text(json.dumps(value), encoding="utf-8")
"""


class ContainedWikiChild:
    """Use the existing suspended-launch Job to own the Windows venv child tree."""

    def __init__(self, command, *, errors, env):
        # This finite synthetic fixture lease does not change any native budget.
        self.end = time.monotonic() + 900
        self.child = WindowsJobProcess.launch(
            command[0], command[1:], os.getcwd(), env, absolute_end=self.end
        )
        self.args, self.pid = command, self.child.pid
        self.returncode = self.cleanup_report = self.stderr_error = None
        self.stderr_reader = None
        try:
            self.stdin = io.TextIOWrapper(
                self.child.stdin, encoding="utf-8", write_through=True
            )
            self.stdout = io.TextIOWrapper(self.child.stdout, encoding="utf-8")

            def drain_stderr():
                try:
                    with open(errors.name, "ab", buffering=0) as sink:
                        while block := self.child.stderr.read(65536):
                            sink.write(block)
                except BaseException as error:
                    self.stderr_error = error

            self.stderr_reader = threading.Thread(target=drain_stderr, daemon=True)
            self.stderr_reader.start()
            self.child.resume()
        except BaseException as primary:
            try:
                self.terminate_tree()
                if self.stderr_reader is not None:
                    self.stderr_reader.join(timeout=3)
                for stream in (self.child.stdin, self.child.stdout):
                    stream.close()
                if self.stderr_reader is None or not self.stderr_reader.is_alive():
                    self.child.stderr.close()
            except BaseException as error:
                primary.add_note("Owned fixture launch cleanup failure: " + repr(error))
            raise

    def poll(self):
        if self.cleanup_report is None:
            self.returncode = self.child.poll()
        return self.returncode

    def wait(self, timeout):
        if self.poll() is None:
            result = self.child.kernel.WaitForSingleObject(
                self.child.process, min(0xFFFFFFFE, int(max(0, timeout) * 1000))
            )
            if result == 0x102:
                raise subprocess.TimeoutExpired(self.args, timeout)
            if result != 0:
                raise ctypes.WinError()
        return self.poll()

    def terminate_tree(self):
        if self.cleanup_report is None:
            self.cleanup_report = self.child.cleanup(
                min(self.end, time.monotonic() + 5)
            )
            self.returncode = self.cleanup_report["exit_code"]
        if (
            self.cleanup_report["errors"]
            or not self.cleanup_report["tree_empty_observed"]
            or not self.cleanup_report["leader_reaped"]
        ):
            raise AssertionError(self.cleanup_report)

    def release(self):
        if self.cleanup_report is None:
            # A signalled process handle may precede the Job's exit accounting.
            # Observe bounded graceful tree exit before invoking any termination.
            grace_end = min(self.end, time.monotonic() + 5)
            while True:
                counts = self.child.Accounting()
                if not self.child.kernel.QueryInformationJobObject(
                    self.child.job, 1, ctypes.byref(counts), ctypes.sizeof(counts), None
                ):
                    raise ctypes.WinError()
                if counts.active == 0:
                    break
                if time.monotonic() >= grace_end:
                    raise AssertionError("Graceful Wiki shutdown left live descendants")
                time.sleep(min(0.01, max(0, grace_end - time.monotonic())))
        self.terminate_tree()
        self.stderr_reader.join(timeout=3)
        if self.stderr_reader.is_alive():
            raise AssertionError("Owned fixture stderr reader did not stop")
        self.child.stderr.close()
        if self.stderr_error is not None:
            raise AssertionError(
                "Owned fixture stderr capture failed"
            ) from self.stderr_error


def launch_fixture_child(command, *, errors, env):
    if sys.platform == "win32":
        return ContainedWikiChild(command, errors=errors, env=env)
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=errors,
        text=True,
        encoding="utf-8",
        env=env,
    )


def close_owned_fixture(proc, reader, *, wait_seconds=20):
    """Graceful success is required; a bounded reap never turns failure into pass."""
    try:
        if proc.poll() is None:
            proc.stdin.write("wiki-test-shutdown\n")
            proc.stdin.flush()
        proc.stdin.close()
        if proc.wait(timeout=wait_seconds) != 0:
            raise AssertionError("Wiki fixture child did not exit successfully")
        if isinstance(proc, ContainedWikiChild):
            proc.release()
    except BaseException as primary:
        if isinstance(proc, ContainedWikiChild):
            try:
                # Reap the owned Job even when its redirector has already exited.
                proc.terminate_tree()
                proc.release()
            except BaseException as error:
                primary.add_note("Owned fixture tree reap failure: " + repr(error))
        else:
            for stop in (proc.terminate, proc.kill):
                if proc.poll() is None:
                    try:
                        stop()
                        proc.wait(timeout=5)
                    except BaseException as error:
                        primary.add_note("Owned fixture reap failure: " + repr(error))
        try:
            proc.stdin.close()
        except BaseException as error:
            primary.add_note("Owned fixture stdin cleanup failure: " + repr(error))
        reader.join(timeout=3)
        if reader.is_alive():
            primary.add_note("Owned fixture reader did not stop; stdout left open")
        else:
            proc.stdout.close()
        raise
    reader.join(timeout=3)
    if reader.is_alive():
        raise AssertionError("Owned fixture reader did not stop; stdout left open")
    proc.stdout.close()


class ConfiguredWikiHttpTests(unittest.TestCase):
    def test_startup_stall_is_reaped_and_retains_shutdown_failure(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki-child-stall-")
        self.addCleanup(temporary.cleanup)
        errors = (Path(temporary.name) / "stderr.log").open("w+", encoding="utf-8")
        self.addCleanup(errors.close)
        proc = launch_fixture_child(
            [
                sys.executable,
                "-c",
                "import json,os,sys,time; "
                "print(json.dumps(dict(pid=os.getpid(),parent_pid=os.getppid())),flush=True); "
                "sys.stdin.readline(); time.sleep(60)",
            ],
            errors=errors,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        started = queue.Queue()

        def observe():
            started.put(proc.stdout.readline())
            proc.stdout.read()

        reader = threading.Thread(target=observe, daemon=True)
        reader.start()
        try:
            identity = json.loads(started.get(timeout=10))
            self.assertTrue(
                identity["pid"] == proc.pid
                or (sys.platform == "win32" and identity["parent_pid"] == proc.pid),
                identity,
            )
            with self.assertRaises(subprocess.TimeoutExpired) as failure:
                close_owned_fixture(proc, reader, wait_seconds=0.05)
            self.assertFalse(getattr(failure.exception, "__notes__", []))
        finally:
            if not proc.stdin.closed or not proc.stdout.closed:
                try:
                    close_owned_fixture(proc, reader, wait_seconds=0.05)
                except subprocess.TimeoutExpired:
                    pass
        self.assertIsNotNone(proc.poll())
        self.assertFalse(reader.is_alive())
        self.assertTrue(proc.stdout.closed)
        self.assertTrue(proc.stdin.closed)
        if isinstance(proc, ContainedWikiChild):
            self.assertTrue(proc.cleanup_report["tree_empty_observed"])
            self.assertEqual(proc.cleanup_report["active_processes"], 0)
            self.assertEqual(proc.cleanup_report["errors"], [])
            self.assertTrue(proc.cleanup_report["leader_reaped"])
            self.assertIsNone(proc.stderr_error)
            self.assertFalse(proc.stderr_reader.is_alive())
            print(
                json.dumps(
                    dict(
                        kind="synthetic-wiki-started-stall-tree-reap",
                        interpreter=identity,
                        owner=proc.cleanup_report,
                    )
                ),
                flush=True,
            )

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
            lifecycle = root / "child-lifecycle.json"
            proc = launch_fixture_child(
                [*cmd[:3], "-c", WIKI_CHILD_OBSERVER, *cmd[3:]],
                errors=errors,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "WIKI_TEST_LIFECYCLE_RECEIPT": str(lifecycle),
                },
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
                assert (
                    b'<template id="v93-selection-template"><main id="selection-layout">'
                    in page
                )
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
                for name in (
                    "v9-research-guide-contract.js",
                    "v9-research-guide-view.js",
                    "v9-research-guide.js",
                ):
                    module_bytes = (repo / "harness-ui" / name).read_bytes()
                    assert (
                        host_binding["modules"][name]
                        == hashlib.sha256(module_bytes).hexdigest()
                    )
                    assert module_bytes in app_bytes
                _, css_bytes = raw_get("/runtime.css")
                assert (
                    repo / "harness-ui/v9-research-guide.css"
                ).read_bytes() in css_bytes
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
                primary = sys.exc_info()[1]
                try:
                    close_owned_fixture(proc, reader)
                    stopped = json.loads(lifecycle.read_text(encoding="utf-8"))
                    print(
                        json.dumps(
                            {"kind": "synthetic-wiki-stop-observation", **stopped}
                        ),
                        flush=True,
                    )
                    # Windows venv launchers may retain the Popen PID while the
                    # interpreter serving this fixture is their direct child.
                    self.assertTrue(
                        stopped["pid"] == proc.pid
                        or (
                            sys.platform == "win32"
                            and stopped["parent_pid"] == proc.pid
                            and stopped["python_executable"] == sys.executable
                        ),
                        stopped,
                    )
                    self.assertEqual(stopped["original_entrypoint"], cmd[3])
                    for field in (
                        "listener_closed",
                        "shutdown_waiter_joined",
                        "databases_closed",
                        "journal_owner_handles_released",
                    ):
                        self.assertIs(stopped[field], True, stopped)
                    self.assertIsNone(stopped["shutdown_error"])
                    self.assertEqual(
                        stopped["planning_shutdown"],
                        dict(
                            closed=True,
                            active_request_threads=0,
                            threads_joined=True,
                            automatic_retry=False,
                        ),
                    )
                    print(
                        json.dumps(
                            {
                                "kind": "synthetic-wiki-graceful-shutdown",
                                **stopped,
                                "owned_tree_cleanup": getattr(
                                    proc, "cleanup_report", None
                                ),
                            }
                        ),
                        flush=True,
                    )
                except BaseException as error:
                    if primary is None:
                        raise
                    primary.add_note(
                        "Additional fixture cleanup failure: " + repr(error)
                    )
                finally:
                    if primary is not None:
                        errors.flush()
                        errors.seek(0)
                        primary.add_note("Owned Wiki child stderr: " + errors.read())
                    errors.close()
        finally:
            f.doCleanups()


if __name__ == "__main__":
    unittest.main()
