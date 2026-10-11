"""Temporary real HTTP/Core/SQLite recovery, with authored saved sources only."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
from types import ModuleType
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--lease-seconds", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.lease_seconds <= 600:
        parser.error("fixture lease must be 1-600 seconds")
    tests = Path(__file__).resolve().parent
    plugin = tests.parent
    stop_path = args.stop_file
    if (
        not stop_path.is_absolute()
        or not stop_path.parent.is_dir()
        or stop_path.exists()
        or stop_path.parent.resolve().is_relative_to(plugin.parents[1])
    ):
        raise ValueError("fresh private stop file outside checkout required")
    loader_path = tests / "browser/project-intake-fixture.py"
    loader = ModuleType("_recovery_browser_raw_loader")
    exec(compile(loader_path.read_bytes(), str(loader_path), "exec"), loader.__dict__)
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, loader.RawSources([plugin / "cli", tests]))
    sys.path[:0] = [str(plugin / "cli"), str(tests)]

    from test_project_stage1_records import saved_stage1_case
    from test_project_records_prepare import body
    from research_workspace_native.project_records_prepare import (
        ProjectRecordsPrepareService,
    )
    from research_workspace_native.project_host import ProjectHost

    credential = secrets.token_urlsafe(32)
    with (
        patch(
            "test_project_stage1_delivery.authenticate",
            lambda token: (
                "local-viewer" if token in (credential, "alice-token") else None
            ),
        ),
        saved_stage1_case() as (case, fixture),
    ):
        service = ProjectRecordsPrepareService(case.producer)
        with patch.object(
            case.delivery,
            "register_records",
            side_effect=TimeoutError("authored registration interruption"),
        ):
            try:
                service.prepare("alice-token", fixture["ref"], body(case, fixture))
            except TimeoutError:
                pass
            else:
                raise AssertionError("fixture must retain the registration failure")
        producer = next(
            row
            for row in case.intake.history("alice-token", fixture["ref"])["actions"]
            if row["kind"] == "stage1-produce-records"
        )
        original = Path(producer["records_path"]).read_bytes()
        events = fixture["ledger"].events()
        host = ProjectHost(
            projects=case.intake,
            credential=credential,
            stage1=case.stage1,
            files={},
            views=[],
            port=0,
        )
        host.project_records_prepare = (
            service  # authored fixture only; production owner guards stay intact
        )
        worker = threading.Thread(
            target=host.serve_forever, kwargs=dict(poll_interval=0.1), daemon=True
        )
        worker.start()
        try:
            print(
                json.dumps(
                    dict(
                        kind="SyntheticSavedRecordsRecoveryBrowserFixture",
                        url=host.expected_origin + "/",
                        project_ref=fixture["ref"],
                        lease_seconds=args.lease_seconds,
                        executed_sources=loader.EXECUTED_SOURCES,
                        ui_sources={
                            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (
                                plugin / "cli/research_workspace_native/web"
                            ).glob("projects*")
                            if p.is_file()
                        },
                        native_calls=0,
                        model_calls=0,
                        search_calls=0,
                        source_acquisitions=0,
                    )
                ),
                flush=True,
            )
            stop = threading.Event()
            for _ in range(args.lease_seconds * 10):
                if stop_path.exists():
                    break
                stop.wait(0.1)
            history = case.intake.history("alice-token", fixture["ref"])["actions"]
            artifact = case.delivery.read("alice-token", fixture["ref"])[
                "canonical_package"
            ]
            print(
                json.dumps(
                    dict(
                        kind="SyntheticSavedRecordsRecoveryBrowserFixtureStopped",
                        actions=[
                            {
                                name: row[name]
                                for name in ("kind", "key", "status", "request_sha256")
                            }
                            for row in history
                        ],
                        canonical_package=artifact,
                        original_records_unchanged=Path(
                            producer["records_path"]
                        ).read_bytes()
                        == original,
                        core_events_unchanged=fixture["ledger"].events() == events,
                        native_calls=0,
                        model_calls=0,
                        search_calls=0,
                        source_acquisitions=0,
                    )
                ),
                flush=True,
            )
            case.runner.assert_not_called()
        finally:
            host.shutdown()
            host.server_close()
            worker.join(5)
            if worker.is_alive():
                raise RuntimeError("fixture cleanup unobserved")


if __name__ == "__main__":
    main()
