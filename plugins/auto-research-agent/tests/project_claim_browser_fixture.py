"""Temporary saved-draft UI fixture: authored sources and a synthetic provider.

The actual HTTP, SQLite and Core claim producer execute. No native process,
external search, source acquisition, model or scientific evaluation executes.
Send stop on stdin; EOF or a three-minute lease also performs cleanup.
"""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
from types import ModuleType
from unittest.mock import patch


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    plugin = tests.parent
    if args.stop_file is not None:
        stop_path = args.stop_file
        if (
            not stop_path.is_absolute()
            or not stop_path.parent.is_dir()
            or stop_path.exists()
            or stop_path.parent.resolve().is_relative_to(plugin.parents[1])
        ):
            raise ValueError("fresh private stop file outside checkout required")
    loader = tests / "browser/project-intake-fixture.py"
    raw_loader = ModuleType("_claim_browser_raw_loader")
    exec(compile(loader.read_bytes(), str(loader), "exec"), raw_loader.__dict__)
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, raw_loader.RawSources([plugin / "cli", tests]))
    sys.path[:0] = [str(plugin / "cli"), str(tests)]

    from research_workspace_native.project_host import ProjectHost
    from research_workspace_native.project_saved_claims import ProjectSavedClaimService
    from research_workspace_native.project_reading_review import (
        ProjectReadingReviewService,
    )
    from research_workspace_native.project_records_prepare import (
        ProjectRecordsPrepareService,
    )
    from test_project_stage1_claims import reading_case
    import test_project_stage1_delivery as delivery_fixture

    host = worker = None
    credential = secrets.token_urlsafe(32)
    # Only fixture authentication changes; every production host principal check
    # still executes. The literal test credential is never emitted in a receipt.
    with (
        patch.object(
            delivery_fixture,
            "authenticate",
            lambda token: (
                "local-viewer" if token in {"alice-token", credential} else None
            ),
        ),
        reading_case(pending=True) as context,
    ):
        case, ref = context["case"], context["ref"]
        try:
            host = ProjectHost(
                projects=case.intake,
                stage1=case.stage1,
                models=context["models"],
                credential=credential,
                files={},
                views=[],
                port=0,
            )
            # This offline saved-Core case has no live query owner. Inject the
            # already composed service only in the fixture, rather than weakening
            # production materials-root/query-owner construction checks.
            host.project_stage1_claims = context["claims"]
            host.project_saved_claims = ProjectSavedClaimService(
                case.stage1, case.producer, context["models"]
            )
            host.project_reading_review = ProjectReadingReviewService(
                context["claims"], saved_claims=host.project_saved_claims
            )
            host.project_stage1_delivery = case.delivery
            host.project_stage1_records = case.producer
            host.project_records_prepare = ProjectRecordsPrepareService(case.producer)
            host.host_binding["project_stage1_claim_review"] = True
            host.host_binding["project_stage1_reading_review"] = True
            host.host_binding["project_stage1_saved_records"] = True
            worker = threading.Thread(
                target=host.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
            )
            worker.start()
            baseline = len(context["ledger"].coverage_state().evidence.claims)
            emit(
                dict(
                    kind="SyntheticSavedDraftBrowserFixture",
                    url=host.expected_origin + "/",
                    project_ref=ref,
                    output_ref=context["output_ref"],
                    synthetic=True,
                    baseline_claims=baseline,
                    synthetic_provider_units=len(context["called"]),
                    native_calls=0,
                    model_calls=0,
                    search_calls=0,
                    source_acquisitions=0,
                    lease_seconds=180,
                    executed_sources=raw_loader.EXECUTED_SOURCES,
                    ui_sources={
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (plugin / "cli/research_workspace_native/web").glob(
                            "projects*"
                        )
                        if p.is_file()
                    },
                )
            )
            stop = threading.Event()

            def read_stop():
                if args.stop_file is not None:
                    while not stop.wait(0.1):
                        if args.stop_file.exists():
                            break
                    stop.set()
                    return
                for line in sys.stdin:
                    if line.strip().casefold() == "stop":
                        break
                stop.set()

            threading.Thread(target=read_stop, daemon=True).start()
            stop.wait(180)
            emit(
                dict(
                    kind="SyntheticSavedDraftBrowserFixtureStopped",
                    project_ref=ref,
                    claims=len(context["ledger"].coverage_state().evidence.claims),
                    baseline_claims=baseline,
                    history=case.intake.history("alice-token", ref),
                    delivery=case.delivery.read("alice-token", ref),
                    executed_sources=raw_loader.EXECUTED_SOURCES,
                    synthetic_provider_units=len(context["called"]),
                    synthetic=True,
                    native_calls=0,
                    model_calls=0,
                    search_calls=0,
                    source_acquisitions=0,
                )
            )
        finally:
            if host is not None:
                if worker is not None and worker.is_alive():
                    host.shutdown()
                host.server_close()
            if worker is not None:
                worker.join(5)
                if worker.is_alive():
                    raise RuntimeError("fixture HTTP cleanup unobserved")


if __name__ == "__main__":
    main()
