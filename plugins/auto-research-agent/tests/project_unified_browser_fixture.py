"""Lease-bound saved-result project host for same-page UI checks and preview.

The repository delivery case supplies real SQLite, Core ledger, source-parser
receipts and canonical delivery. Sources are authored HTTP responses; external
search, model/native execution and scientific quality are not attested.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def source_inventory(repo, loaded, host):
    rows = dict(loaded)
    plugin = repo / "plugins/auto-research-agent"
    for folder in (
        plugin / "cli/research_workspace_native/web",
        plugin / "references/research-workspace/atlas",
    ):
        for path in folder.rglob("*"):
            if path.is_file():
                rows.setdefault(str(path), digest(path.read_bytes()))
    for path in (
        Path(__file__).resolve(strict=True),
        plugin / "tests/browser/project-unified-test.cjs",
        plugin / "tests/test_project_unified_browser.py",
    ):
        rows.setdefault(str(path), digest(path.read_bytes()))
    result = []
    for name, expected in sorted(rows.items()):
        path = Path(name)
        if path.resolve(strict=True) != path or digest(path.read_bytes()) != expected:
            raise ValueError("owned source changed during browser check")
        result.append({"path": path.relative_to(repo).as_posix(), "sha256": expected})
    return {"owned_sources": result, "served_files": host.host_binding["served_files"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--lease-seconds", type=int, default=300)
    args = parser.parse_args()
    own = Path(__file__).resolve(strict=True)
    repo, plugin = own.parents[3], own.parents[1]
    stop = args.stop_file
    if not 30 <= args.lease_seconds <= 1800:
        raise ValueError("lease must be between 30 and 1800 seconds")
    if not stop.is_absolute() or stop.exists() or stop.is_symlink():
        raise ValueError("fresh absolute private stop file required")
    parent = stop.parent.resolve(strict=True)
    if parent != stop.parent or stop.is_relative_to(repo):
        raise ValueError("stop file must be outside checkout")
    if any((folder / ".git").exists() for folder in (parent, *parent.parents)):
        raise ValueError("stop file must be outside Git")
    helper = plugin / "tests/browser/project-intake-fixture.py"
    namespace = {"__name__": "unified_raw_loader", "__file__": str(helper)}
    raw = helper.read_bytes()
    exec(compile(raw, str(helper), "exec"), namespace)
    loaded = namespace["EXECUTED_SOURCES"]
    loaded[str(helper)] = digest(raw)
    roots = (plugin / "cli", plugin / "tests")
    sys.path[:0] = [str(path) for path in roots]
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, namespace["RawSources"](roots))
    from unittest.mock import patch
    import test_stage1_deliverable as package_fixture
    from test_project_stage1_delivery import ProjectStage1DeliveryTests
    from test_workspace_project_intake import bound_body, compile_body, submit_body
    from research_workspace.atlas import atlas_files
    from research_workspace_native.atlas_host import load_views
    from research_workspace_native.project_host import ProjectHost
    from stage1_ledger.journal import canonical
    from test_workspace_atlas import payload

    case = ProjectStage1DeliveryTests(methodName="runTest")
    host = worker = None
    class_ready = False
    failure = result = None
    guards = ExitStack()
    try:
        case.setUpClass()
        class_ready = True
        case.setUp()
        token = secrets.token_urlsafe(32)
        case.intake.authenticate = lambda value: (
            "local-viewer" if value in (token, "alice-token") else None
        )
        saved, projects = [], []
        original_records = package_fixture.ResearchDeliverableTests.make_records
        titles = [
            "Authored Alpha: sensor drift and aircraft diagnosis",
            "Authored Beta: traffic signal policy with a deliberately long title "
            + "for safety constraints, changing demand and transparent evidence " * 3,
        ]
        topics = [
            "Authored aircraft diagnosis project A",
            "Authored traffic signal project B · 城市路口与安全约束 " * 7,
        ]
        for index, (title, topic) in enumerate(zip(titles, topics)):

            def records(owner, *positional, _title=title, **kwargs):
                kwargs.update(
                    raw=package_fixture.HTML.replace(
                        b"Synthetic household research", _title.encode()
                    ),
                    title=_title,
                )
                return original_records(owner, *positional, **kwargs)

            with (
                patch.object(package_fixture, "TITLE", title),
                patch.object(
                    package_fixture.ResearchDeliverableTests, "make_records", records
                ),
            ):
                fixture = case.saved("saved-" + str(index), topic=topic)
            offer = case.register(fixture)
            delivery = case.delivery.deliver(
                "alice-token", fixture["ref"], case.body(fixture, offer)
            )
            case.assertEqual(delivery["status"], "saved")
            saved.append(fixture)
            view = case.intake.read(token, fixture["ref"])
            projects.append(
                {
                    "kind": "saved",
                    "project_ref": fixture["ref"],
                    "topic": topic,
                    "title": title,
                    "work_id": fixture["records"]["papers"][0]["work_id"],
                    "input_version": view["input_version"],
                    "revision": view["revision"],
                    "artifact_ref": delivery["artifact_ref"],
                    "manifest_sha256": delivery["manifest_sha256"],
                }
            )
        for key, topic, revise in (
            ("empty", "Authored empty project · no saved result", False),
            ("scope-v2", "Authored scope version two · no saved result", True),
        ):
            receipt = case.intake.create(token, {"key": key, "topic": topic})
            ref = receipt["project_ref"]
            if revise:
                case.intake.revise(
                    token,
                    ref,
                    {
                        **bound_body(case.intake.read(token, ref), "scope-two"),
                        "topic": topic,
                    },
                )
                case.intake.submit(
                    token, ref, submit_body(case.intake.read(token, ref))
                )
                case.intake.compile(
                    token, ref, compile_body(case.intake.read(token, ref))
                )
            view = case.intake.read(token, ref)
            projects.append(
                {
                    "kind": "scope-without-result" if revise else "empty",
                    "project_ref": ref,
                    "topic": topic,
                    "input_version": view["input_version"],
                    "revision": view["revision"],
                }
            )
        value = payload()
        value["index"]["topic"] = "Unrelated historical fixture must stay hidden"
        value["index_sha256"] = digest(canonical(value["index"]))
        files = atlas_files(value)
        files["workspace-index.json"] = canonical(value["index"])
        folder = case.root / "view"
        for name, raw in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        manifest = canonical(
            {
                "kind": "WorkspaceReadOnlyView",
                "index_sha256": value["index_sha256"],
                "files": {name: digest(raw) for name, raw in files.items()},
            }
        )
        manifest_path = folder / "view-manifest.json"
        manifest_path.write_bytes(manifest)
        config = canonical(
            {
                "views": [
                    {
                        "ref": "unified-v6",
                        "label": "Authored saved v6 shell",
                        "fixture": True,
                        "manifest": str(manifest_path),
                        "sha256": digest(manifest),
                    }
                ]
            }
        )
        config_path = folder / "views.json"
        config_path.write_bytes(config)
        assets, views = load_views(config_path, digest(config))
        host = ProjectHost(
            projects=case.intake,
            credential=token,
            stage1=case.stage1,
            files=assets,
            views=views,
            port=0,
            max_connections=16,
        )
        worker = threading.Thread(
            target=host.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        worker.start()
        baseline = {
            "sqlite_changes": case.intake.db.total_changes,
            "events": [
                digest(canonical(fixture["ledger"].events())) for fixture in saved
            ],
        }
        forbidden = [
            guards.enter_context(
                patch(target, side_effect=AssertionError("read dispatched producer"))
            )
            for target in (
                "stage1_deliverable.package.build",
                "stage1_deliverable.package.validate",
                "requests.Session.get",
            )
        ]
        started_inventory = source_inventory(repo, loaded, host)
        emit(
            {
                "kind": "UnifiedProjectBrowserFixture",
                "url": host.expected_origin + "/",
                "projects": projects,
                "lease_seconds": args.lease_seconds,
                "source_inventory": started_inventory,
                "scope": "authored-saved-result-engineering-only",
            }
        )
        deadline = time.monotonic() + args.lease_seconds
        while not stop.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        expired = not stop.exists()
        if not expired and (
            stop.is_symlink() or not stop.is_file() or stop.stat().st_size > 64
        ):
            raise ValueError("invalid private stop file")
        case.assertEqual(case.intake.db.total_changes, baseline["sqlite_changes"])
        case.assertEqual(
            [digest(canonical(fixture["ledger"].events())) for fixture in saved],
            baseline["events"],
        )
        case.runner.assert_not_called()
        for guard in forbidden:
            guard.assert_not_called()
        case.assertEqual(source_inventory(repo, loaded, host), started_inventory)
        result = {
            "readonly_sqlite_and_ledger": True,
            "model_calls": 0,
            "search_calls": case.runner.call_count,
            "native_calls": 0,
            "producer_rebuild_calls": 0,
            "lease_expired": expired,
            "source_inventory": started_inventory,
        }
        if expired:
            raise TimeoutError("fixture lease expired")
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    finally:
        guards.close()
        if host is not None:
            host.shutdown()
            host.server_close()
        if worker is not None:
            worker.join(3)
            case.assertFalse(worker.is_alive())
        case.assertTrue(case.doCleanups(), "fixture cleanup failed")
        if class_ready:
            case.tearDownClass()
        case.doClassCleanups()
    emit(
        {
            "kind": "UnifiedProjectBrowserFixtureStopped",
            **(result or {}),
            "cleanup_complete": True,
            "failure": failure,
        }
    )
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
