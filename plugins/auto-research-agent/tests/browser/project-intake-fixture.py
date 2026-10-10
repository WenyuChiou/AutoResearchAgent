"""120-second test-only project host; real SQLite/core, no model/search provider.

The private file queue compiles an explicitly synthetic proposal through the
real brief compiler. It is not an HTTP endpoint or research execution permit.
"""

import argparse
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import traceback

EXECUTED_SOURCES = {}


class RawSources(importlib.abc.MetaPathFinder):
    """Load this candidate's owned Python sources directly, never cached pyc."""

    def __init__(self, roots):
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        for root in self.roots:
            stem = root.joinpath(*fullname.split("."))
            for source, package in (
                (stem / "__init__.py", True),
                (stem.with_suffix(".py"), False),
            ):
                if source.is_file():
                    if source.resolve(strict=True) != source:
                        raise RuntimeError("linked candidate source")
                    loader = RawLoader(fullname, str(source))
                    return importlib.util.spec_from_file_location(
                        fullname,
                        source,
                        loader=loader,
                        submodule_search_locations=[str(stem)] if package else None,
                    )
        return None


class RawLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        raw = Path(self.path).read_bytes()
        EXECUTED_SOURCES[self.path] = digest(raw)
        return compile(raw, self.path, "exec")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "temp-root", "control-file"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if not all(
        path.is_absolute() for path in (args.repo, args.temp_root, args.control_file)
    ):
        raise ValueError("absolute paths required")
    repo = args.repo.resolve(strict=True)
    if (
        not args.control_file.is_relative_to(args.temp_root)
        or args.control_file.resolve(strict=True) != args.control_file
    ):
        raise ValueError("private regular control file required")
    plugin = repo / "plugins/auto-research-agent"
    own = plugin / "tests/browser/project-intake-fixture.py"
    driver = plugin / "tests/test_workspace_project_browser.cjs"
    if Path(__file__).resolve(strict=True) != own or own.resolve() != own:
        raise ValueError("fixture must belong to the sole candidate")
    roots = (plugin / "cli", plugin / "tests")
    sys.path[:0] = [str(path) for path in roots]
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, RawSources(roots))
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.project_host import ProjectHost
    from research_workspace_native.project_intake import ProjectIntakeService
    from research_workspace_native.project_stage1 import ProjectStage1Service
    from research_workspace_native.project_stage1_delivery import (
        ProjectStage1DeliveryService,
    )
    from research_workspace_native.project_stage2 import ProjectStage2Service
    from test_workspace_project_intake import compile_body

    token = secrets.token_urlsafe(32)
    authenticate = token_authenticator({token: "local-viewer"})
    args.temp_root.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="pb-", dir=args.temp_root)
    root = Path(temporary.name)
    service = ProjectIntakeService(root, authenticate=authenticate)
    stage1, stage2 = ProjectStage1Service(service), ProjectStage2Service(service)
    server = worker = None
    diagnostics = []
    source_hashes = {}
    try:
        server = ProjectHost(
            projects=service,
            credential=token,
            stage1=stage1,
            stage2=stage2,
            files={},
            views=[],
            port=0,
            timeout=5,
            max_connections=8,
        )
        server.handle_error = lambda request, address: diagnostics.append(
            "HTTP handler failure"
        )
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        worker.start()
        for module in list(sys.modules.values()):
            filename = getattr(module, "__file__", None)
            if filename:
                path = Path(filename).absolute()
                if any(path.is_relative_to(owned) for owned in roots):
                    if path.resolve(strict=True) != path or path.suffix != ".py":
                        raise RuntimeError("candidate module origin differs")
                    source_hashes[str(path.relative_to(repo)).replace("\\", "/")] = (
                        digest(path.read_bytes())
                    )
                    if path != own and EXECUTED_SOURCES.get(str(path)) != digest(
                        path.read_bytes()
                    ):
                        raise RuntimeError("executed module bytes differ from snapshot")
        for path in (
            own,
            driver,
            *(
                plugin / "cli/research_workspace_native/web" / name
                for name in ("projects.html", "projects.js", "projects.css")
            ),
        ):
            source_hashes[str(path.relative_to(repo)).replace("\\", "/")] = digest(
                path.read_bytes()
            )

        def verify():
            for relative, expected in source_hashes.items():
                path = repo / relative
                if (
                    path.resolve(strict=True) != path
                    or digest(path.read_bytes()) != expected
                ):
                    raise RuntimeError("candidate source changed: " + relative)

        def snapshot():
            projects = service.list(token)
            return {
                "projects": [
                    dict(
                        project=service.read(token, item["project_ref"]),
                        history=service.history(token, item["project_ref"]),
                        stage1=stage1.read(token, item["project_ref"]),
                        stage2=stage2.read(token, item["project_ref"]),
                    )
                    for item in projects
                ],
                "model_provider": "unconnected",
                "search_provider": "unconnected",
                "actual_model_calls": 0,
                "actual_search_calls": 0,
            }

        emit(
            {
                "origin": server.expected_origin,
                "source_sha256": source_hashes,
                "served_sha256": server.host_binding["served_files"],
                "mode": "offline-real-core-with-synthetic-plan-proposal",
                "lease_seconds": 120,
            }
        )
        offset, deadline, stopped, pending = 0, time.monotonic() + 120, False, b""
        while time.monotonic() < deadline:
            with args.control_file.open("rb") as stream:
                stream.seek(offset)
                pending += stream.read()
                offset = stream.tell()
            if len(pending) > 65536:
                raise ValueError("fixture control record bound exceeded")
            lines = pending.split(b"\n")
            pending = lines.pop()
            for raw in lines:
                command = json.loads(raw)
                try:
                    op = command["op"]
                    if op == "stop":
                        stopped = True
                        break
                    verify()
                    if op == "snapshot":
                        value = snapshot()
                    elif op == "compile":
                        ref = command["project_ref"]
                        view = service.read(token, ref)
                        body = compile_body(view)
                        body["key"] = "fixture-compile-" + secrets.token_hex(8)
                        for binding in body["request"]["query_bindings"]:
                            binding["need_ids"] = [
                                row["need_id"] for row in view["brief"]["needs"]
                            ]
                        value = service.compile(token, ref, body)
                    elif op == "reopen":
                        service.close()
                        service = ProjectIntakeService(root, authenticate=authenticate)
                        stage1, stage2 = (
                            ProjectStage1Service(service),
                            ProjectStage2Service(service),
                        )
                        (
                            server.projects,
                            server.project_stage1,
                            server.project_stage2,
                        ) = service, stage1, stage2
                        server.project_stage1_delivery = ProjectStage1DeliveryService(
                            stage1
                        )
                        value = snapshot()
                    else:
                        raise ValueError("unsupported fixture command")
                    emit({"ok": value})
                except Exception:
                    emit({"error": traceback.format_exc()})
            if stopped:
                break
            time.sleep(0.01)
        if not stopped:
            raise TimeoutError("120-second fixture lease expired")
        verify()
        if diagnostics:
            raise RuntimeError("; ".join(diagnostics))
    finally:
        failures = []
        for name, operation in (
            (
                "HTTP shutdown",
                lambda: server.shutdown() if worker and worker.is_alive() else None,
            ),
            ("HTTP close", lambda: server.server_close() if server else None),
            ("HTTP join", lambda: worker.join(2) if worker else None),
            ("SQLite close", service.close),
            ("private cleanup", temporary.cleanup),
        ):
            try:
                operation()
            except BaseException as error:
                failures.append(name + ": " + repr(error))
        if worker and worker.is_alive():
            failures.append("HTTP worker still alive")
        if failures:
            raise RuntimeError("; ".join(failures))


if __name__ == "__main__":
    main()
