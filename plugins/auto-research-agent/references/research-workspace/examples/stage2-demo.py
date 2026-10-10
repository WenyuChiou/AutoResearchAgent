"""Fixed, synthetic repository Stage2 UI demo; never a production execution API.

The only runner is the public SyntheticAdapter. A durable single intent owns a
new delivery; reads/reconnects never run it. No source index or gate is changed.
"""

from copy import deepcopy
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
import types

KEY = "run-repository-stage2-v1"
PID = "independent-stage2-repository-demo"
MAX_SECONDS = 20
MAX_JSON = 1024 * 1024
ROUTE = "/api/stage2-demo"
BOOTSTRAP = """import hashlib,pathlib,stat,sys
p=pathlib.Path(sys.argv[1])
if not p.is_absolute(): raise SystemExit('absolute demo source required')
for q in (p,*p.parents):
 s=q.lstat()
 if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
  raise SystemExit('linked source refused')
if p.stat().st_nlink!=1: raise SystemExit('hardlinked source refused')
with p.open('rb') as f: raw=f.read(262145)
if len(raw)>262144 or hashlib.sha256(raw).hexdigest()!=sys.argv[2]:
 raise SystemExit('demo source hash differs before execution')
sys.argv=[str(p),*sys.argv[3:]]
exec(compile(raw,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
"""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, maximum=MAX_JSON):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("absolute path required")
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("linked/reparse input refused")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("single-link regular input required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("file bound exceeded")
    return raw


def save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def verify_sources(config):
    plugin = Path(config["repo"]) / "plugins/auto-research-agent"
    for relative, expected in config["sources"].items():
        if not relative.startswith(("cli/", "tests/")) or ".." in relative.split("/"):
            raise ValueError("source allowlist invalid")
        if digest(read(plugin / relative, 32 * MAX_JSON)) != expected:
            raise ValueError("fixed source bytes differ: " + relative)
    if digest(read(Path(config["script"]), 256 * 1024)) != config["script_sha256"]:
        raise ValueError("fixed worker source differs")


class RawTests(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, plugin, files):
        self.plugin, self.files = plugin, files

    def find_spec(self, name, path=None, target=None):
        relative = "tests/" + name + ".py"
        if "." not in name and relative in self.files:
            return importlib.util.spec_from_file_location(
                name, self.plugin / relative, loader=self
            )
        if "." not in name and (self.plugin / relative).is_file():
            raise ValueError("unlisted repository fixture import refused")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        relative = "tests/" + module.__name__ + ".py"
        path = self.plugin / relative
        raw = read(path, 32 * MAX_JSON)
        if digest(raw) != self.files[relative]:
            raise ValueError("fixture bytes changed")
        exec(compile(raw, str(path), "exec"), module.__dict__)


def worker(binding_path, expected):
    """An isolated Python child only: fixed public source, fixed synthetic adapter."""
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("isolated raw source worker required")
    raw = read(binding_path)
    if digest(raw) != expected:
        raise ValueError("worker binding differs")
    config = json.loads(raw)
    verify_sources(config)
    plugin = Path(config["repo"]) / "plugins/auto-research-agent"
    helper_path = plugin / "cli/research_workspace_native/atlas_local_source.py"
    helper = types.ModuleType("demo_raw_helper")
    helper_raw = read(helper_path)
    if (
        digest(helper_raw)
        != config["sources"]["cli/research_workspace_native/atlas_local_source.py"]
    ):
        raise ValueError("bootstrap helper bytes differ before execution")
    exec(compile(helper_raw, str(helper_path), "exec"), helper.__dict__)
    cli_pins = {k: v for k, v in config["sources"].items() if k.startswith("cli/")}
    sys.meta_path[:0] = [
        helper.PinnedLoader(Path(config["repo"]), cli_pins),
        RawTests(plugin, config["sources"]),
    ]
    sys.path[:0] = [str(plugin / "cli"), str(plugin / "tests")]
    # Importing the fixture does not call its production adapter. The sole
    # constructor and runner below are fixed; no caller adapter is accepted.
    from test_stage2_controller import Stage2ControllerTests, SyntheticAdapter
    from stage2_fixture_helpers import write_stage2_fixture
    from stage2_live.controller import _run_controller, verify_controller
    from stage2_workflow import initialize_workflow, inspect_workflow

    root = Path(config["output"]) / "run-once"
    root.mkdir(exist_ok=False)
    case = Stage2ControllerTests("runTest")
    case.root, case.sources = root, root / "sources"
    case.packet = write_stage2_fixture(case.sources, candidate_count=1)
    case.packet_path = root / "packet.json"
    save(case.packet_path, case.packet)
    case.run = root / "workflow"
    initialize_workflow(
        case.packet_path,
        case.sources,
        case.run,
        {"model": "synthetic-model", "reasoning": "medium"},
        {"path": "policy.json", "sha256": "a" * 64},
    )
    initial = inspect_workflow(case.run)
    case.base = initial["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
    case.controller, case.delivery = root / "controller", root / "delivery"
    spec = case._spec()  # Public fixture's exact, synthetic test-only role spec.
    adapter = SyntheticAdapter()
    started = time.monotonic()
    result = _run_controller(
        case.run, case.controller, case.delivery, initial["head_sha256"], spec, adapter
    )
    verified = verify_controller(case.controller, result["controller_manifest_sha256"])
    if not result["synthetic_test_only"] or verified["authentic_native_execution"]:
        raise ValueError("synthetic boundary violated")
    report = case.delivery / "selection.html"
    receipt = dict(
        kind="SyntheticRepositoryStage2Run",
        schema_version="1.0.0",
        case_sha256=expected,
        classification="synthetic-repository-fixture",
        lineage="independent Stage2 seed; not derived from the displayed Stage1",
        packet_sha256=digest(read(case.packet_path)),
        source_work_ids=["work-1", "work-2"],
        initial_workflow_head_sha256=initial["head_sha256"],
        spec_sha256=digest(canonical(spec)),
        elapsed_seconds=time.monotonic() - started,
        adapter_calls=adapter.calls,
        adapter_identity=adapter.identity,
        fixture_packet_version="1.0.0 (legacy controller regression fixture)",
        ordinary_route="stage2-general-v3/daily_v3; not exercised by this fixture",
        rubric_executed=None,
        scoring_denominator_applied=False,
        evaluation_class="fixed synthetic review records; no external judge calls or scores",
        result=result,
        native_execution=False,
        model_execution=False,
        real_search_execution=False,
        formal_ready=False,
        actual_stage2_complete=False,
        scientific_acceptance=False,
        source_index_modified=False,
        report_sha256=digest(read(report)) if report.is_file() else None,
        controller_verified={
            k: verified[k]
            for k in (
                "synthetic_test_only",
                "authentic_native_execution",
                "model_call_verification",
                "selection_ready",
                "stage2_complete",
                "formal_ready",
                "human_selection",
            )
        },
    )
    save(root / "result.json", receipt)


class RepositoryStage2Demo:
    """Single server-owned case with immutable bindings and process-held ownership."""

    def __init__(
        self, output, *, repo, sources, project_ref, index_sha256, authenticate
    ):
        from research_workspace_native.store import ProjectStore
        from stage1_deliverable.common import private_output

        self.root = private_output(Path(output)).resolve()
        repo = Path(repo).resolve()
        if (
            not {
                "tests/test_stage2_controller.py",
                "tests/stage2_fixture_helpers.py",
                "cli/research_workspace_native/atlas_local_source.py",
            }
            <= sources.keys()
            or len(sources) > 4096
        ):
            raise ValueError("fixed repository source inventory required")
        if self.root.is_relative_to(repo) or repo.is_relative_to(self.root):
            raise ValueError("source/output overlap refused")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_ref) or not re.fullmatch(
            r"[0-9a-f]{64}", index_sha256
        ):
            raise ValueError("fixed view binding required")
        self.root.mkdir(parents=True, exist_ok=True)
        self._authenticate, self._lock = authenticate, threading.RLock()
        self.project_ref, self._closed = project_ref, False
        self.config = dict(
            repo=str(repo),
            sources=deepcopy(sources),
            output=str(self.root),
            script=str(Path(__file__).resolve()),
            script_sha256=digest(read(Path(__file__).resolve(), 256 * 1024)),
            project_ref=project_ref,
            index_sha256=index_sha256,
            fixture="test_stage2_controller.Stage2ControllerTests",
            adapter="strict-controller-test-adapter-v1",
            candidate_count=1,
        )
        verify_sources(self.config)
        binding = self.root / "binding.json"
        if binding.exists():
            if read(binding) != canonical(self.config):
                raise ValueError("saved demo binding differs")
        else:
            save(binding, self.config)
        self.case_sha256 = digest(canonical(self.config))
        self.store = ProjectStore(self.root / "actions.sqlite3")
        try:
            self.store.bind_project(PID, self.case_sha256)
            self.owner = self.store.acquire_owner(PID, "repository-demo-host")
        except BaseException:
            self.store.close()
            raise

    def _access(self, token, project_ref):
        from research_workspace_native.session_api import SessionApiError

        if self._closed or project_ref != self.project_ref:
            raise SessionApiError("demo-project-unavailable", 404)
        if self._authenticate(token) != "local-viewer":
            raise SessionApiError("credential-rejected", 401)
        verify_sources(self.config)
        if digest(read(self.root / "binding.json")) != self.case_sha256:
            raise SessionApiError("demo-binding-differs", 409)

    def view(self, token, project_ref):
        with self._lock:
            self._access(token, project_ref)
            state = self.store.snapshot(PID)
            row = deepcopy(state["intents"].get(KEY))
            if row and row.get("outcome") == "failed":
                row["status"] = "failed"
            return dict(
                kind="SyntheticStage2DemoView",
                project_ref=self.project_ref,
                case_sha256=self.case_sha256,
                index_sha256=self.config["index_sha256"],
                key=KEY,
                revision=state["revision"],
                action=row,
                classification="synthetic-repository-fixture",
                lineage="independent Stage2 seed; not a continuous Stage1 handoff",
                native_execution=False,
                model_execution=False,
                real_search_execution=False,
            )

    def execute(self, token, project_ref, request, *, deadline):
        from research_workspace_native.session_api import SessionApiError

        with self._lock:
            self._access(token, project_ref)
            if time.monotonic() >= deadline:
                raise SessionApiError("demo-deadline-expired", 408)
            if not isinstance(request, dict) or set(request) != {
                "key",
                "case_sha256",
                "index_sha256",
                "confirmed",
            }:
                raise SessionApiError("demo-fields-rejected", 400)
            expected = dict(
                key=KEY,
                case_sha256=self.case_sha256,
                index_sha256=self.config["index_sha256"],
                confirmed=True,
            )
            if request != expected or request["confirmed"] is not True:
                raise SessionApiError("demo-confirmation-or-binding-differs", 409)
            state = self.store.snapshot(PID)
            if KEY in state["intents"]:
                return self.view(token, project_ref)  # Never dispatch on replay.
            row = dict(
                status="running",
                method="synthetic-stage2/run",
                key=KEY,
                request_sha256=digest(canonical(request)),
                request=deepcopy(request),
                native_execution=False,
                model_execution=False,
                started_at_unix=time.time(),
            )
            with self.store._edit(
                PID, self.owner, state["revision"], "demo-intent", row
            ) as s:
                s["intents"][KEY] = deepcopy(row)
            stderr = self.root / "worker-stderr.log"
            child = None
            try:
                remaining = min(MAX_SECONDS, deadline - time.monotonic())
                if remaining <= 0:
                    raise TimeoutError("demo expired before worker start")
                command = [
                    sys.executable,
                    "-I",
                    "-B",
                    "-X",
                    "utf8",
                    "-c",
                    BOOTSTRAP,
                    self.config["script"],
                    self.config["script_sha256"],
                    "--worker",
                    str(self.root / "binding.json"),
                    self.case_sha256,
                ]
                with stderr.open("xb") as errors:
                    verify_sources(self.config)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("demo expired before dispatch")
                    child = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=errors,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    remaining = min(remaining, deadline - time.monotonic())
                    if remaining <= 0:
                        raise TimeoutError("demo expired after dispatch")
                    code = child.wait(timeout=remaining)
                if code:
                    row.update(
                        status="completed",
                        outcome="failed",
                        exit_code=code,
                        error="synthetic-worker-failed",
                    )
                else:
                    result_path = self.root / "run-once/result.json"
                    raw = read(result_path)
                    result = json.loads(raw)
                    if (
                        result["case_sha256"] != self.case_sha256
                        or result["native_execution"] is not False
                    ):
                        raise ValueError("worker receipt binding differs")
                    row.update(
                        status="completed",
                        outcome="succeeded",
                        result=result,
                        result_sha256=digest(raw),
                        report_url=ROUTE + "/" + project_ref + "/report",
                    )
            except (subprocess.TimeoutExpired, TimeoutError):
                if child is not None:
                    child.kill()
                    child.wait(timeout=5)
                row.update(
                    status="execution-unknown" if child is not None else "completed",
                    outcome="timeout-unknown" if child is not None else "failed",
                    error="worker-time-bound-exceeded"
                    if child is not None
                    else "deadline-before-dispatch",
                    worker_reaped=child is None or child.poll() is not None,
                )
            except Exception as error:
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                row.update(
                    status="completed", outcome="failed", error=type(error).__name__
                )
            row["finished_at_unix"] = time.time()
            with self.store._edit(PID, self.owner, None, "demo-outcome", row) as s:
                s["intents"][KEY] = deepcopy(row)
            return self.view(token, project_ref)

    def report(self, token, project_ref):
        view = self.view(token, project_ref)
        row = view["action"]
        if not row or row.get("outcome") != "succeeded":
            raise ValueError("successful saved report required")
        raw = read(self.root / "run-once/delivery/selection.html")
        if digest(raw) != row["result"]["report_sha256"]:
            raise ValueError("saved report differs")
        return dict(html=raw.decode("utf8"), sha256=digest(raw))

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self.store.close()


def install(server, demo):
    """Example-only composition; normal AtlasHost and StageActions are unchanged."""
    from research_workspace_native.atlas_host import AtlasHandler
    from research_workspace_native.session_api import SessionApiError
    from research_workspace_native.transport import _decode

    class DemoHandler(AtlasHandler):
        def _demo(self, method):
            try:
                token, length = self._headers(method)
                if self.headers.get("Sec-Fetch-Site") not in (
                    None,
                    "none",
                    "same-origin",
                ):
                    raise SessionApiError("cross-site-rejected", 403)
                base = ROUTE + "/" + demo.project_ref
                if self.path not in {base, base + "/report"}:
                    raise SessionApiError("demo-route-rejected", 404)
                self._remaining()
                if method == "GET":
                    if length:
                        raise SessionApiError("demo-read-body-rejected", 400)
                    result = (
                        demo.report(token, demo.project_ref)
                        if self.path.endswith("/report")
                        else demo.view(token, demo.project_ref)
                    )
                else:
                    if self.path != base or not 0 < length <= 2048:
                        raise SessionApiError("demo-write-rejected", 400)
                    if (
                        self.headers.get("Content-Type", "").lower()
                        != "application/json"
                    ):
                        raise SessionApiError("json-content-type-required", 415)
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise SessionApiError("partial-body", 400)
                    request = _decode(raw.decode("utf8"))
                    self._remaining()
                    result = demo.execute(
                        token, demo.project_ref, request, deadline=self.deadline
                    )
                self._reply(200, result)
            except SessionApiError as error:
                self._reply(error.status, {"error": error.code})
            except (TimeoutError, OSError):
                self.close_connection = True
            except (ValueError, UnicodeError, RecursionError):
                self._reply(409, {"error": "demo-source-or-result-rejected"})
            except Exception:
                self._reply(500, {"error": "demo-service-failure"})

        def do_GET(self):
            return (
                self._demo("GET") if self.path.startswith(ROUTE) else super().do_GET()
            )

        def do_POST(self):
            return (
                self._demo("POST") if self.path.startswith(ROUTE) else super().do_POST()
            )

    server.RequestHandlerClass = DemoHandler


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Only the fixed synthetic demo worker mode is supported.")
    worker(Path(sys.argv[2]), sys.argv[3])
