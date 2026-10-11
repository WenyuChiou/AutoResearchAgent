"""180-second test-only project host; real SQLite/core, no model/search provider.

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
    parser.add_argument("--ui-overlay", action="store_true")
    parser.add_argument("--views-config", type=Path)
    parser.add_argument("--views-sha256")
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
    driver = plugin / (
        "tests/browser/project-operations-test.cjs"
        if args.ui_overlay
        else "tests/test_workspace_project_browser.cjs"
    )
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
    from research_workspace_native.project_stage1_library import (
        ProjectStage1LibraryService,
    )
    from stage1_ledger.journal import canonical
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
        files, views = {}, []
        if args.ui_overlay:
            from research_workspace_native.atlas_host import load_views

            if args.views_config is None:
                from research_workspace.atlas import atlas_files
                from test_workspace_atlas import payload

                value = payload()
                saved = atlas_files(value)
                saved["workspace-index.json"] = canonical(value["index"])
                folder = root / "view"
                for name, raw in saved.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                manifest = canonical(
                    dict(
                        kind="WorkspaceReadOnlyView",
                        index_sha256=value["index_sha256"],
                        files={name: digest(raw) for name, raw in saved.items()},
                    )
                )
                path = folder / "view-manifest.json"
                path.write_bytes(manifest)
                config = canonical(
                    dict(
                        views=[
                            dict(
                                ref="stage1-original-r3",
                                label="Offline synthetic saved fixture",
                                fixture=True,
                                manifest=str(path),
                                sha256=digest(manifest),
                            )
                        ]
                    )
                )
                args.views_config = root / "views.json"
                args.views_config.write_bytes(config)
                args.views_sha256 = digest(config)
            files, views = load_views(args.views_config, args.views_sha256)
        elif args.views_config is not None or args.views_sha256 is not None:
            raise ValueError("saved views require the explicit UI overlay fixture")
        server = ProjectHost(
            projects=service,
            credential=token,
            stage1=stage1,
            stage2=stage2,
            files=files,
            views=views,
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
                for name in (
                    "projects.html",
                    "projects.js",
                    "projects.css",
                    "projects-library.js",
                    "project-operations.js",
                    "project-operations.css",
                )
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

        def seed_screening(ref):
            with service._lock:
                state = service._load("local-viewer", ref)
                _, ledger, _ = stage1._ledger(state, service.binding(ref))
                if ledger.candidates():
                    raise ValueError("fixture screening is single-use")
                queries = list(ledger.coverage_state().queries)
                records = [
                    dict(
                        title=f"Authored screening fixture study {i:02d}"
                        + (" <img src=x>" if i == 0 else ""),
                        authors=["Fixture Author"],
                        year=2025,
                        version="v1",
                    )
                    for i in range(25)
                ]
                for i, batch in enumerate((records, [records[0]])):
                    query = ledger.start_planned(queries[i])
                    backend = ledger.start(
                        "backend",
                        {"input": ledger.coverage_state().arguments(queries[i])},
                        backend="openalex",
                        parent_id=query,
                    )
                    output = ledger.save_bytes(canonical(batch), producer=backend)
                    empty = ledger.save_bytes(b"", producer=backend)
                    ledger.finish(
                        backend,
                        outcome="success_nonempty",
                        http_status=200,
                        exit_code=0,
                        stdout=empty,
                        stderr=empty,
                        records=output,
                    )
                    ledger.complete_query(query)
                    ledger.extract()
                candidates = list(ledger.candidates().values())
                for candidate, status in zip(
                    candidates, ("include", "exclude", "pending")
                ):
                    ledger.decide(
                        candidate["work_id"],
                        status,
                        reason="fixture-screening",
                        rationale="Authored saved screening observation; no live research.",
                        evidence_refs=[candidate["discoveries"][-1]["source_ref"]],
                    )
                historical = candidates[1]
                version = historical["discoveries"][-1]["version_id"]
                source = ledger.start_source(
                    work_id=historical["work_id"],
                    version_id=version,
                    source_uri="https://example.org/historical-source-v1",
                    tool="authored-browser-fixture",
                    request={"public_only": True},
                    actor="fixture",
                    reason="Saved authored bytes; no source acquisition.",
                )
                text = ledger.save_bytes(
                    b"Authored historical claim, not a model output.", producer=source
                )
                ledger.finish_source(
                    attempt_id=source,
                    outcome="available",
                    observed_at=ledger.clock(),
                    http_status=200,
                    resolved_uri="https://example.org/historical-source-v1",
                    raw_ref=text,
                    text_ref=text,
                    extraction={"method": "identity", "version": "fixture"},
                    reason="Authored saved observation only.",
                )
                ledger.claim(
                    work_id=historical["work_id"],
                    version_id=version,
                    claim_text="Authored historical claim, not a model output.",
                    relation="supports",
                    evidence_level="full_text",
                    locator={
                        "section": "fixture",
                        "quote": "Authored historical claim, not a model output.",
                    },
                    source_ref=text,
                    verifier={
                        "actor": "fixture",
                        "actor_type": "agent",
                        "method": "saved-span",
                    },
                )
                imported = candidates[2]
                intent = ledger.start_source_import(
                    work_id=imported["work_id"],
                    version_id=imported["discoveries"][-1]["version_id"],
                    source_uri="https://example.org/authored-import",
                    actor="fixture",
                    reason="Authored saved import observation; no protected import.",
                )
                imported_ref = ledger.save_bytes(
                    b"Authored import bytes, not complete reading.", producer=intent
                )
                query = ledger.start_planned(queries[2])
                backend = ledger.start(
                    "backend",
                    {"input": ledger.coverage_state().arguments(queries[2])},
                    backend="openalex",
                    parent_id=query,
                )
                revised = dict(records[1], version="v2")
                output = ledger.save_bytes(canonical([revised]), producer=backend)
                empty = ledger.save_bytes(b"", producer=backend)
                ledger.finish(
                    backend,
                    outcome="success_nonempty",
                    http_status=200,
                    exit_code=0,
                    stdout=empty,
                    stderr=empty,
                    records=output,
                )
                ledger.complete_query(query)
                ledger.extract()
                latest_version = ledger.candidates()[historical["work_id"]][
                    "discoveries"
                ][-1]["version_id"]
                ledger.start_source(
                    work_id=historical["work_id"],
                    version_id=latest_version,
                    source_uri="https://example.org/current-pending-source-v2",
                    tool="authored-browser-fixture",
                    request={"public_only": True},
                    actor="fixture",
                    reason="Unfinished saved source intent, not acquired bytes.",
                )
                return dict(
                    project_ref=ref,
                    total_candidates=len(candidates),
                    mode="authored-saved-observations-only",
                    historical_source_version=version,
                    imported_sha256=imported_ref["sha256"],
                )

        emit(
            {
                "origin": server.expected_origin,
                "source_sha256": source_hashes,
                "served_sha256": server.host_binding["served_files"],
                "mode": "offline-real-core-with-synthetic-plan-proposal",
                "lease_seconds": 180,
            }
        )
        offset, deadline, stopped, pending = 0, time.monotonic() + 180, False, b""
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
                    elif op == "seed-screening":
                        value = seed_screening(command["project_ref"])
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
                        server.project_stage1_library = ProjectStage1LibraryService(
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
