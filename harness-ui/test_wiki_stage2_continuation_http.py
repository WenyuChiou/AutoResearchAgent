"""Normal Wiki HTTP with original admission and a no-model engineering adapter."""

# ruff: noqa: E402 -- use the repository's own local fixtures.
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from test_v9_stage23_http import close_owned_fixture, launch_fixture_child

import test_project_stage2_host_controller as host_fixture
from stage2_common import canonical_hash
from stage2_workflow import inspect_workflow


REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "plugins/auto-research-agent/cli"
CHILD = r"""
import faulthandler
import json
import os
from pathlib import Path
import runpy
import socketserver
import subprocess
import sys
import threading
import time

entry = Path(sys.argv[1])
test_root = Path(sys.argv[2])
sys.path[:0] = [str(entry.parent), sys.argv[3]]
sys.argv = [str(entry), *sys.argv[4:]]

import run_v7
snapshot = run_v7.snapshot
run_v7.snapshot = lambda repo: snapshot(repo, package=test_root / "renderer-package")
serve = socketserver.BaseServer.serve_forever
if os.environ.get("WIKI_STAGE2_TEST_STACKS"):
    faulthandler.dump_traceback_later(7, repeat=True)

def serve_fixture(host, *args, **kwargs):
    # Call the exact production controller and workflow/verification stack.
    # Replace only the adapter that would otherwise call real models.
    from research_workspace_native import project_stage2_controller as driver
    from stage2_live import controller
    from test_stage2_controller import SyntheticAdapter

    class EngineeringAdapter(SyntheticAdapter):
        def research(self, context):
            command = (
                "import json, os, sys; "
                "print(json.dumps({'pid': os.getpid(), 'synthetic': True, "
                "'research_calls': 0, 'model_calls': 0, 'search_calls': 0}))"
            )
            worker_out = test_root / "worker.stdout"
            worker_err = test_root / "worker.stderr"
            # The Windows fixture owns a Job with its own standard handles.
            # Capture the engineering worker's output in files to avoid pipe
            # EOF depending on the parent fixture's handle inheritance.
            with worker_out.open("wb") as stdout, worker_err.open("wb") as stderr:
                worker = subprocess.Popen(
                    [sys._base_executable, "-B", "-I", "-S", "-c", command],
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                )
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
                    raise
            stdout = worker_out.read_text(encoding="utf-8")
            stderr = worker_err.read_text(encoding="utf-8")
            result = {"worker_pid": worker.pid, "exit_code": worker.returncode,
                      "stdout": json.loads(stdout), "stderr": stderr}
            with (test_root / "workers.jsonl").open("a", encoding="utf-8", newline="") as log:
                print(json.dumps(result), file=log)
            if worker.returncode != 0:
                raise RuntimeError("No-model engineering worker failed")
            deadline = time.monotonic() + 30
            while not (test_root / "release").exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Fixture did not release its worker")
                time.sleep(.02)
            return super().research(context)

        def extract(self, context):
            result = super().extract(context)
            packet = result["next_packet"]["packet"]
            packet["comparison"] = (
                "The fixture compares one repeatability question against the retained "
                "synthetic baseline. It has no independent assessment."
            )
            packet["candidates"] = [{
                "candidate_id": "candidate-1",
                "version": 1,
                "parent_version": None,
                "question": "Can the retained synthetic comparison be repeated?",
                "research_mode": "method-development",
                "opportunity": "Check whether the authored fixture reproduces.",
                "value": "An engineering contrast with the saved baseline.",
                "approach": "Compare against the retained synthetic baseline.",
                "requirements": ["Retained synthetic fixture"],
                "limitations": ["Synthetic engineering example only"],
                "evidence_ids": [packet["evidence"][0]["evidence_id"]],
            }]
            return result

        def review(self, context):
            result = super().review(context)
            for check in result["review"]["assessment"]["checks"].values():
                check["evidence_ids"] = [context["packet"]["evidence"][0]["evidence_id"]]
            return result

        def resolve(self, context):
            result = super().resolve(context)
            result["resolution"]["evidence_ids"] = [context["packet"]["evidence"][0]["evidence_id"]]
            return result

    def run(workflow, output, delivery, head, spec, *, prerequisite_handler):
        return controller._run_controller(
            workflow, output, delivery, head, spec, EngineeringAdapter()
        )

    driver.run_controller = run
    # Exercise expiry and loss after the loader verified the original pin.
    for binding in host.project_stage2_controllers.values():
        if os.environ["WIKI_STAGE2_TEST_ADMISSION"] == "expired":
            binding.handler.admission_context["deadline_unix"] = time.time() - 1
        elif os.environ["WIKI_STAGE2_TEST_ADMISSION"] == "missing":
            binding.handler.admission_context = None

    def stop():
        sys.stdin.readline()
        host.shutdown()

    watcher = threading.Thread(target=stop, daemon=True)
    watcher.start()
    try:
        return serve(host, *args, **kwargs)
    finally:
        watcher.join(5)

socketserver.BaseServer.serve_forever = serve_fixture
runpy.run_path(str(entry), run_name="__main__")
"""


def write_config(path, value):
    payload = json.dumps(value).encode("utf-8")
    path.write_bytes(payload)
    return str(path), hashlib.sha256(payload).hexdigest()


def controller_config(case):
    spec, spec_pin = write_config(case.root / "spec.json", case.spec)
    prep, prep_pin = write_config(
        case.root / "prep.json",
        {
            "kind": "Stage2NativePrerequisiteConfiguration",
            "schema_version": "1.0.0",
            "native_sha256": canonical_hash(case.spec["native"]),
            "admission_context": case.handler.admission_context,
            "output_root": str(case.root / "original-preparation"),
            "workspace_templates": {},
        },
    )
    return write_config(
        case.root / "controller-config.json",
        {
            "kind": "ProjectStage2ControllerConfiguration",
            "schema_version": "1.0.0",
            "bindings": [
                {
                    "project_ref": case.ref,
                    "spec_path": spec,
                    "spec_sha256": spec_pin,
                    "controller_root": str(case.output),
                    "delivery_root": str(case.delivery),
                    "preparation_path": prep,
                    "preparation_sha256": prep_pin,
                }
            ],
        },
    )


def request(base, path, *, credential=None, body=None):
    headers = {"Sec-Fetch-Site": "same-origin"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    wire = json.dumps(body).encode() if body is not None else None
    start = time.monotonic()
    try:
        with urlopen(
            Request(base + path, data=wire, headers=headers), timeout=15
        ) as response:
            status, raw = response.status, response.read()
    except HTTPError as response:
        status, raw = response.code, response.read()
    print(
        json.dumps(
            {
                "event": "http",
                "method": "GET" if body is None else "POST",
                "path": path,
                "status": status,
                "elapsed": round(time.monotonic() - start, 3),
                "response": json.loads(raw) if path.startswith("/api/") else None,
            }
        ),
        flush=True,
    )
    return status, raw


@contextmanager
def wiki(case, root, *params, admission="valid"):
    helper = CLI / "research_workspace_native/atlas_local_source.py"
    arguments = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        "-c",
        CHILD,
        str(REPO / "harness-ui/run_v9.py"),
        str(root),
        str(REPO / "plugins/auto-research-agent/tests"),
        "--repo",
        str(REPO),
        "--port",
        "0",
        "--source-helper-sha256",
        hashlib.sha256(helper.read_bytes()).hexdigest(),
        "--projects-root",
        str(case.store_root),
        "--run-limits",
        str(REPO / "harness-ui/zero-limits.json"),
        "--ui-state-root",
        str(root / "state"),
        "--incoming-root",
        str(root / "incoming"),
        *params,
    ]
    with (root / "wiki-stderr.log").open("w+", encoding="utf-8") as errors:
        host = launch_fixture_child(
            arguments,
            errors=errors,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "WIKI_STAGE2_TEST_ADMISSION": admission,
            },
        )
        stdout = queue.Queue()
        reader = threading.Thread(
            target=lambda: stdout.put(host.stdout.readline()), daemon=True
        )
        reader.start()
        try:
            line = stdout.get(timeout=40)
            if not line:
                errors.seek(0)
                raise AssertionError(errors.read())
            info = json.loads(line)
            print(
                json.dumps({"event": "wiki-start", "pid": host.pid, "startup": info}),
                flush=True,
            )
            base = info["url"].rstrip("/")
            assert request(base, "/")[0] == 200
            status, payload = request(base, "/project-bootstrap.js")
            assert status == 200
            token = json.loads(payload.decode().split("=", 1)[1].strip()[:-1])[
                "credential"
            ]
            yield base, token
        finally:
            (root / "release").touch()
            try:
                close_owned_fixture(host, reader)
            finally:
                errors.seek(0)
                traces = errors.read()
                print(
                    json.dumps(
                        {
                            "event": "wiki-exit",
                            "pid": host.pid,
                            "exit_code": host.returncode,
                            "stderr": traces,
                        }
                    ),
                    flush=True,
                )


class WikiStage2ContinuationHttpTests(unittest.TestCase):
    def test_request_concurrency_and_reopen_real_wiki(self):
        root_dir = tempfile.TemporaryDirectory(prefix="w508-")
        self.addCleanup(root_dir.cleanup)
        root = Path(root_dir.name).resolve()
        (root / "incoming").mkdir()
        renderer = root / "renderer-package/renderer"
        shutil.copytree(REPO / "harness-ui/renderer", renderer)
        if not (renderer / "vendor/three.core.js").exists():
            source = Path(os.environ["WIKI_STAGE2_TEST_THREE_CORE"])
            shutil.copyfile(source, renderer / "vendor/three.core.js")
        fixture_type = host_fixture.HostStage2ControllerTests
        fixture_type.setUpClass()
        self.addCleanup(fixture_type.doClassCleanups)
        case = fixture_type()
        self.addCleanup(case.doCleanups)
        case.setUp()
        print(
            json.dumps(
                {
                    "event": "fixture",
                    "packet_schema": case.packet["schema_version"],
                    "project_ref": case.ref,
                    "input_version": case.binding["input_version"],
                    "adapter": "test_stage2_controller.SyntheticAdapter with one local worker",
                    "grant": "synthetic pinned zero model/search admission",
                }
            ),
            flush=True,
        )
        other = case.intake.create(
            case.token,
            {
                "key": "other-project",
                "topic": "Other synthetic project",
            },
        )["project_ref"]
        route = "/api/projects/" + case.ref + "/stage2/continuation"
        body = {
            "key": "user-request-1",
            "input_version": case.binding["input_version"],
            "brief_sha256": case.binding["brief_sha256"],
            "confirmed": True,
        }
        path, digest = controller_config(case)
        params = [
            "--stage2-controller-config",
            path,
            "--stage2-controller-sha256",
            digest,
        ]
        workers = root / "workers.jsonl"
        with wiki(case, root) as (base, token):
            status, payload = request(base, route, credential=token, body=body)
            self.assertEqual(
                (status, json.loads(payload)),
                (409, {"error": "stage2-controller-not-connected"}),
            )
            self.assertFalse(workers.exists())
        for admission in ("missing", "expired"):
            (root / "release").unlink()
            with (
                self.subTest(admission=admission),
                wiki(case, root, *params, admission=admission) as (base, token),
            ):
                status, payload = request(base, route, credential=token, body=body)
                self.assertEqual(
                    (status, json.loads(payload)),
                    (
                        409,
                        {"error": "stage2-continuation-original-admission-unavailable"},
                    ),
                )
                self.assertFalse(
                    (case.output / "project_stage2_driver/wiki-request.json").exists()
                )
                self.assertFalse(workers.exists())
        (root / "release").unlink()
        with wiki(case, root, *params) as (base, token):

            def read():
                return request(base, route, credential=token)

            def post(data):
                return request(base, route, credential=token, body=data)

            self.assertEqual(json.loads(read()[1])["status"], "ready")
            self.assertEqual(
                post({**body, "input_version": str(body["input_version"])})[0], 409
            )
            self.assertEqual(
                post({**body, "controller_key": "browser-cannot-pass"})[0], 400
            )
            self.assertEqual(
                request(
                    base, route.replace(case.ref, other), credential=token, body=body
                )[0],
                409,
            )
            self.assertFalse(workers.exists())
            with ThreadPoolExecutor(2) as pool:
                requests = [pool.submit(post, body) for _ in range(2)]
                self.assertEqual(
                    sorted(result.result()[0] for result in requests), [200, 202]
                )
            limit = time.monotonic() + 15
            while not workers.exists() and time.monotonic() < limit:
                time.sleep(0.04)
            if not workers.exists():
                failure = case.output / "project_stage2_driver/failure.json"
                print(
                    json.dumps(
                        {
                            "event": "missing-worker-evidence",
                            "retained_failure": json.loads(failure.read_bytes())
                            if failure.exists()
                            else None,
                            "controller_records": [
                                path.name
                                for path in (
                                    case.output / "project_stage2_driver"
                                ).glob("*")
                            ],
                        }
                    ),
                    flush=True,
                )
                read()
                self.fail("No local engineering worker receipt was saved")
            self.assertEqual(json.loads(read()[1])["status"], "running")
            self.assertEqual(post({**body, "key": "second-user-request"})[0], 409)
            (root / "release").touch()
            limit = time.monotonic() + 25
            while True:
                status, payload = read()
                self.assertEqual(status, 200)
                result = json.loads(payload)
                if result["status"] != "running" or time.monotonic() >= limit:
                    break
                time.sleep(0.2)
            self.assertEqual(result["status"], "candidate-ready")
            self.assertTrue(result["synthetic_test_only"])
            self.assertFalse(result["execution_authorized"])
            self.assertEqual(result["assessment_status"], "missing")
            self.assertEqual(result["human_selection"], "pending")
            self.assertIn("retained synthetic baseline", result["comparison"])
            self.assertFalse(result["comparison_is_input_baseline"])
            self.assertEqual(
                [card["candidate_id"] for card in result["cards"]], ["candidate-1"]
            )
            self.assertEqual(read(), (200, payload))
            self.assertEqual(post(body), (200, payload))
        with wiki(case, root, *params) as (base, token):
            self.assertEqual(request(base, route, credential=token), (200, payload))
            self.assertEqual(
                request(base, route, credential=token, body=body), (200, payload)
            )
            selection = case.delivery / "selection.json"
            original = selection.read_bytes()
            selection.write_bytes(original + b" ")
            status, stale = request(base, route, credential=token)
            self.assertEqual(
                (status, json.loads(stale)),
                (409, {"error": "stage2-continuation-result-not-current"}),
            )
        try:
            with wiki(case, root, *params) as (base, token):
                status, stale = request(base, route, credential=token)
                self.assertEqual(
                    (status, json.loads(stale)),
                    (409, {"error": "stage2-continuation-result-not-current"}),
                )
        finally:
            selection.write_bytes(original)
        [worker] = (
            json.loads(line)
            for line in workers.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual(worker["exit_code"], 0)
        self.assertEqual(worker["worker_pid"], worker["stdout"]["pid"])
        journal = inspect_workflow(case.workflow)
        native = [
            a
            for a in journal["actions"].values()
            if a["request"]["action_kind"] == "stage2-ideation-native"
        ]
        self.assertEqual(len(native), 1)
        print(
            json.dumps(
                {
                    "event": "engineering-dispatch",
                    "real_os_worker": worker,
                    "stage2_ideation_actions": len(native),
                    "workflow_action_count": len(journal["actions"]),
                    "same_candidate_after_restart": True,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    unittest.main()
