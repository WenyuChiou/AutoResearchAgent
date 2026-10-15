"""Temporary synthetic coverage UI host; no model, search or source execution.

Run with --temp-root pointing outside the checkout. The first stdout line is
JSON metadata (URL and synthetic IDs, never the credential). Send ``stop`` on
stdin to shut down; EOF or the five-minute lease also ends the fixture.
"""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from types import ModuleType


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-root", type=Path, required=True)
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    repo, plugin = tests.parents[2], tests.parent
    if not args.temp_root.is_absolute() or not args.temp_root.is_dir():
        raise ValueError("existing absolute private temp root required")
    temp_root = args.temp_root.resolve(strict=True)
    if temp_root.is_relative_to(repo) or repo.is_relative_to(temp_root):
        raise ValueError("temp root must be separate from the checkout")

    # Reuse the existing fixture's raw loader so this candidate's actual source
    # bytes execute without adopting owned cached bytecode.
    loader_path = tests / "browser/project-intake-fixture.py"
    raw_loader = ModuleType("_coverage_browser_raw_loader")
    exec(
        compile(loader_path.read_bytes(), str(loader_path), "exec"), raw_loader.__dict__
    )
    roots = [plugin / "cli", tests]
    sys.dont_write_bytecode = True
    sys.meta_path.insert(0, raw_loader.RawSources(roots))
    sys.path[:0] = [str(root) for root in roots]
    from research_workspace_native.http import token_authenticator
    from research_workspace_native.project_host import ProjectHost
    from research_workspace_native.project_intake import ProjectIntakeService
    from research_workspace_native.project_stage1 import ProjectStage1Service
    from stage1_coverage.run import CoverageLedger
    from stage1_ledger.journal import canonical
    from stage1_ledger.validation import validate_run
    from test_project_stage1 import bound_body, compile_body, submit_body
    from test_stage1_ledger import SYNTHETIC

    credential = secrets.token_urlsafe(32)
    temporary = tempfile.TemporaryDirectory(prefix="pcv-", dir=temp_root)
    projects = ProjectIntakeService(
        Path(temporary.name).resolve(),
        authenticate=token_authenticator({credential: "local-viewer"}),
    )
    stage1 = ProjectStage1Service(projects, backends=("synthetic",))
    host = worker = None
    try:
        ref = projects.create(
            credential,
            {
                "key": "synthetic-create",
                "topic": "Synthetic coverage UI review — authored test evidence",
            },
        )["project_ref"]
        scope = submit_body(projects.read(credential, ref))
        scope["budgets"]["rounds"] = 3
        scope["resource_envelope"] = (
            "Synthetic UI fixture only; no execution, network, model or source permission."
        )
        scope["user_input"] = (
            "Confirm three synthetic coverage rounds; every external execution budget stays zero."
        )
        projects.submit(credential, ref, scope)
        projects.compile(credential, ref, compile_body(projects.read(credential, ref)))
        offer = stage1.offers(credential, ref)["initialization_offer"]
        stage1.initialize(
            credential,
            ref,
            dict(
                bound_body(projects.read(credential, ref), "synthetic-initialize"),
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            ),
        )
        state = projects._load("local-viewer", ref)
        run = state["stage1_runs"][state["stage1_active"]]
        ledger = CoverageLedger(projects._path(ref, run["path"]))
        planned = next(iter(ledger.coverage_state().queries))
        query = ledger.start_planned(planned)
        attempt = ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        records = ledger.save_bytes(canonical([SYNTHETIC]), producer=attempt)
        empty = ledger.save_bytes(b"", producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=records,
            stderr=empty,
            records=records,
        )
        completed = ledger.complete_query(query)
        ledger.extract()
        ledger.receipt(
            completed,
            truncated=False,
            note="Authored synthetic complete query receipt; no backend executed.",
        )
        candidate = next(iter(ledger.candidates().values()))
        work, version = candidate["work_id"], candidate["version_ids"][0]
        source_id = ledger.start_source_import(
            work_id=work,
            version_id=version,
            source_uri="https://example.invalid/synthetic",
            actor="synthetic-reviewer",
            reason="Caller-attested import of authored test text; no source acquisition.",
        )
        source = ledger.save_bytes(
            b"Synthetic household record. Synthetic Author. 2024. 10.5555/stage1-synthetic. record-v1. Synthetic households differ.",
            producer=source_id,
        )
        ledger.decide(
            work,
            "include",
            reason="scope-match",
            rationale="Synthetic UI relevance only.",
            evidence_refs=[source],
            actor="synthetic-reviewer",
        )
        claims = {}
        for field in ("title", "authors", "year", "identifier", "version", "relevance"):
            claims[field] = ledger.claim(
                work_id=work,
                version_id=version,
                claim_text="Synthetic review of " + field,
                relation="supports",
                evidence_level="full_text",
                locator={
                    "section": "synthetic source",
                    "quote": "Synthetic household record",
                },
                source_ref=source,
                verifier={
                    "actor": "synthetic-reviewer",
                    "method": "saved-text-review",
                    "actor_type": "agent",
                },
            )
        report = validate_run(ledger.root)
        if not report["valid"]:
            raise ValueError("synthetic coverage seed failed Core validation")
        host = ProjectHost(
            projects=projects,
            stage1=stage1,
            credential=credential,
            files={},
            views=[],
            port=0,
        )
        worker = threading.Thread(
            target=host.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        worker.start()
        emit(
            {
                "kind": "SyntheticCoverageBrowserFixture",
                "url": host.expected_origin + "/",
                "project_ref": ref,
                "work_ref": work,
                "version_id": version,
                "query_event_id": completed,
                "claim_refs": claims,
                "cluster_ids": [
                    row["cluster_id"]
                    for row in ledger.coverage_state().plan["proposal"]["clusters"]
                ],
                "synthetic": True,
                "lease_seconds": 300,
                "model_calls": 0,
                "search_calls": 0,
                "source_acquisitions": 0,
                "rounds_budget": 3,
                "fixture_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "executed_sources": raw_loader.EXECUTED_SOURCES,
                "ui_sources": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (plugin / "cli/research_workspace_native/web").glob(
                        "projects*"
                    )
                    if path.is_file()
                },
            }
        )
        stop = threading.Event()

        def read_stop():
            for line in sys.stdin:
                if line.strip().casefold() == "stop":
                    break
            stop.set()

        threading.Thread(target=read_stop, daemon=True).start()
        stop.wait(300)
        emit(
            {
                "kind": "SyntheticCoverageBrowserFixtureStopped",
                "project_ref": ref,
                "stage1": stage1.read(credential, ref),
                "history": projects.history(credential, ref),
                "synthetic": True,
                "model_calls": 0,
                "search_calls": 0,
                "source_acquisitions": 0,
            }
        )
    finally:
        if host is not None:
            if worker is not None and worker.is_alive():
                host.shutdown()
            host.server_close()
        if worker is not None:
            worker.join(5)
        projects.close()
        temporary.cleanup()


if __name__ == "__main__":
    main()
