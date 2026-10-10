"""Build public synthetic Stage 1/2 review views; optionally serve on loopback.

This example reuses repository fixtures with injected source/judge behavior.
It never checks Codex, creates a native runtime, calls a model or searches.
"""

import argparse
import json
from pathlib import Path
import shutil
import secrets
import sys
import webbrowser

PLUGIN = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.stage2_import import prepare_stage2_bridge  # noqa: E402
from research_workspace.view import write_workspace  # noqa: E402
from research_workspace_native.atlas_host import AtlasHost, load_views  # noqa: E402
from research_workspace_native.harness_host import create_harness_operations  # noqa: E402
from research_workspace_native.http import token_authenticator  # noqa: E402
from research_workspace_native.stage_actions import StageActions  # noqa: E402
from research_workspace_native.stage_inputs import (  # noqa: E402
    snapshot_inputs,
    source_digest,
)
from stage1_brief.brief import validate_brief  # noqa: E402
from stage1_deliverable.common import canonical, private_output, sha  # noqa: E402
from test_stage1_ledger import fixture as ledger_fixture  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402
from test_stage2_completion import Stage2CompletionTests  # noqa: E402


def save(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value))


def ready_saved_case(destination):
    """Replay a public coverage fixture, then project that same saved ledger."""
    from test_coverage_gate import CoverageGateTests
    from stage1_ledger.journal import decode
    from stage1_ledger.validation import validate_run
    from stage1_deliverable.views import bibtex

    case = CoverageGateTests("runTest")
    try:
        case.setUp()
        case.prepare_review()
        case.finish_round(first=True)
        case.finish_round()
        case.finish_round()
        checkpoint = case.ledger.checkpoint()
        handoff = decode(
            case.ledger.read_ref(checkpoint["stage_result"]["outputs"][-1]),
            "saved coverage handoff",
        )
        report = validate_run(case.ledger.root)
        if not report["valid"] or not handoff["eligible_for_stage2"]:
            raise ValueError("repository coverage fixture did not pass its real gate")
        shutil.copytree(case.ledger.root, destination)
    finally:
        case.doCleanups()
    # Validate the copied input too; fixture cleanup must not remove a dependency.
    copied = validate_run(destination)
    if not copied["valid"]:
        raise ValueError("copied saved coverage input is not independently valid")
    from stage1_ledger.store import Ledger

    ledger = Ledger(destination)
    events = [row["payload"] for row in ledger.events()]
    candidates = ledger.candidates()
    index = fixture_index()
    index.update(
        project_id="saved-coverage-review-demo",
        topic=ledger.manifest["research_run"]["objective"],
        as_of=ledger.manifest["research_run"]["created_at"],
        papers=[],
        sources=[],
        claims=[],
    )
    bindings = []
    for included in handoff["papers"]:
        work, version = included["work_id"], included["reviewed_version_id"]
        discovery = next(
            row
            for row in reversed(candidates[work]["discoveries"])
            if row["version_id"] == version
        )
        record = discovery["record"]
        claims = [
            row
            for row in events
            if row["kind"] == "ClaimEvidence"
            and row["work_id"] == work
            and row["version_id"] == version
        ]
        review = next(
            row
            for row in reversed(events)
            if row["kind"] == "CoverageWorkReview" and row["work_id"] == work
        )
        source_refs = {
            row["source_ref"]["artifact_id"]: row["source_ref"] for row in claims
        }
        for source_id, ref in source_refs.items():
            raw = ledger.read_ref(ref)
            if sha(raw) != ref["sha256"]:
                raise ValueError("saved claim source binding differs")
            source_event = ledger.event(ref["producer"], "SourceImportStarted")
            index["sources"].append(
                {
                    "source_id": source_id,
                    "work_id": work,
                    "version_id": version,
                    "source_url": source_event["source_uri"],
                    "artifact_id": ref["artifact_id"],
                    "source_ref": ref,
                    "access_note": "Saved synthetic fixture text; no live acquisition.",
                }
            )
        index["claims"].extend(
            {
                "claim_id": row["event_id"],
                "work_id": work,
                "version_id": version,
                "text": row["claim_text"],
                "source_id": row["source_ref"]["artifact_id"],
                "relation": row["relation"],
                "evidence_level": row["evidence_level"],
                "locator": row["locator"],
            }
            for row in claims
        )
        relevance_ids = set(review["cluster_claims"].values())
        source_url = index["sources"][-1]["source_url"] if source_refs else None
        index["papers"].append(
            {
                "work_id": work,
                "version_id": version,
                "title": record["title"],
                "authors": record.get("authors", []),
                "year": record.get("year"),
                "venue": record.get("venue") or "Unknown",
                "doi": record.get("doi"),
                "url": source_url,
                "evidence_level": "full-text" if source_refs else "metadata",
                "classification": {"topic_cluster": list(review["cluster_claims"])},
                "roles": [],
                "source_ids": list(source_refs),
                "claim_ids": [row["event_id"] for row in claims],
                "findings": {
                    "relevance": "\n".join(
                        row["claim_text"]
                        for row in claims
                        if row["event_id"] in relevance_ids
                    )
                },
            }
        )
        bindings.append(
            {
                "work_id": work,
                "version_id": version,
                "candidate_event_id": included["candidate_event_id"],
                "decision_event_id": included["decision_event_id"],
                "source_refs": list(source_refs.values()),
                "claim_ids": [row["event_id"] for row in claims],
            }
        )
    records_sha256 = sha(
        canonical({"papers": index["papers"], "claims": index["claims"]})
    )
    index["provenance"]["records_sha256"] = records_sha256
    index["bibliography"] = {
        "records_sha256": records_sha256,
        "entries": [
            {
                "work_id": p["work_id"],
                "version_id": p["version_id"],
                "bibtex": bibtex({"papers": [p]}).decode(),
            }
            for p in index["papers"]
        ],
        "all_bibtex": bibtex(index).decode(),
        "producer": "stage1_deliverable.views.bibtex",
    }
    identities = [[p["work_id"], p["version_id"]] for p in index["papers"]]
    expected = [[p["work_id"], p["reviewed_version_id"]] for p in handoff["papers"]]
    if identities != expected:
        raise ValueError("display and saved Stage 1 handoff identities differ")
    proof = {
        "fixture": "test_coverage_gate.CoverageGateTests",
        "ledger_valid": True,
        "eligible_for_stage2": True,
        "readiness": checkpoint["stage_result"]["gate"]["outcome"],
        "next_allowed_action": checkpoint["stage_result"]["next_allowed_action"],
        "qualified_round_yields": [
            len(row["new_qualified_work_ids"]) for row in copied["coverage"]["rounds"]
        ],
        "display_and_saved_input_identities_match": True,
        "paper_bindings": bindings,
        "projection_kind": "saved-ledger-display; not a complete Stage1 delivery package",
    }
    return index, proof


def synthetic_brief():
    """An unconfirmed display input, never a researcher-confirmed intake."""
    value = {
        "kind": "ResearchBrief",
        "schema_version": "1.0.0",
        "original_description": "Synthetic saved-case UI review only; do not search, execute research or infer scientific results.",
        "needs": [
            {
                "need_id": "ui-review",
                "question": "Can saved stage checks and explicit UI decisions be inspected?",
            }
        ],
        "scope_fields": [
            {
                "field": "geography",
                "material": True,
                "reason": "No research scope has been confirmed for this synthetic UI example.",
            }
        ],
        "suggestions": [],
        "decisions": [],
    }
    validate_brief(value)
    return value


def create_stage_actions(output, views, credential):
    """Bind generated saved inputs; no native runtime or execution permission."""
    root = private_output(output).resolve()
    receipt = json.loads((root / "fixture-receipt.json").read_bytes())
    raw = (root / "stage-inputs.json").read_bytes()
    brief = (root / "brief.json").read_bytes()
    if (
        sha(raw) != receipt["stage_inputs_sha256"]
        or sha(brief) != receipt["brief_sha256"]
    ):
        raise ValueError("generated saved-input/brief binding differs")
    inputs = json.loads(raw)
    digest = source_digest(snapshot_inputs(inputs))
    if digest != receipt["stage_source_sha256"]:
        raise ValueError("generated stage source bytes differ")
    return StageActions(
        root / "stage-actions.sqlite3",
        authenticate=token_authenticator({credential: "local-viewer"}),
        registrations={
            view["ref"]: dict(
                project_id=view["project_id"],
                index_sha256=view["index_sha256"],
                input_version=sha(brief),
                source_sha256=digest,
                inputs=inputs,
                output_root=(root / "stage-results" / view["ref"]).as_posix(),
                principals=["local-viewer"],
            )
            for view in views
        },
    )


def build(output, *, demonstrate_ready_saved_case=False):
    root = private_output(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    reference = PLUGIN / "references/research-workspace"
    inputs_root = root / "inputs"
    inputs_root.mkdir()
    positive_case = None
    if demonstrate_ready_saved_case:
        index, positive_case = ready_saved_case(inputs_root / "stage1-ledger")
    else:
        index = fixture_index()
        ledger_fixture(inputs_root / "stage1-ledger")
    write_workspace(index, reference, root / "stage1", atlas=True)
    fixture = Stage2CompletionTests("runTest")
    try:
        fixture.setUp()
        fixture.deliver(disposition="park")
        manifest = fixture.evaluated()
        delivery = inputs_root / "stage2-delivery"
        evaluation = inputs_root / "stage2-evaluation"
        shutil.copytree(fixture.delivery, delivery)
        shutil.copytree(fixture.root / "completion-evaluation", evaluation)
        bridge = prepare_stage2_bridge(
            index, evaluation, expected_manifest_sha256=manifest["manifest_sha256"]
        )
        save(root / "stage2-bridge.json", bridge)
        write_workspace(
            index,
            reference,
            root / "stage2",
            atlas=True,
            stage2_delivery=evaluation,
            stage2_bridge=bridge,
            expected_stage2_bridge_sha256=sha(canonical(bridge)),
        )
        selection = json.loads((evaluation / "core_selection.json").read_bytes())
        stage_inputs = {
            "1": {"ledger_root": (inputs_root / "stage1-ledger").as_posix()},
            "2": {
                "delivery_root": delivery.as_posix(),
                "delivery_manifest_sha256": fixture.manifest["manifest_sha256"],
                "evaluation_root": evaluation.as_posix(),
                "evaluation_manifest_sha256": manifest["manifest_sha256"],
            },
        }
    finally:
        fixture.doCleanups()
    config = {
        "views": [
            {
                "ref": stage,
                "label": stage.upper()
                + (
                    " saved coverage · synthetic"
                    if stage == "stage1" and positive_case
                    else " independent synthetic repository case"
                    if positive_case
                    else " synthetic repository case"
                ),
                "manifest": str(root / stage / "view-manifest.json"),
                "sha256": sha((root / stage / "view-manifest.json").read_bytes()),
                "fixture": True,
            }
            for stage in ("stage1", "stage2")
        ]
    }
    path = root / "host.json"
    save(path, config)
    pin = sha(path.read_bytes())
    files, views = load_views(path, pin)
    brief = synthetic_brief()
    save(root / "brief.json", brief)
    # Separate pins; adding an input does not rewrite the read-only view manifest.
    for view in views:
        save(root / view["ref"] / "brief.json", brief)
    save(root / "stage-inputs.json", stage_inputs)
    receipt = {
        "kind": "SyntheticAtlasReviewFixture",
        "config": str(path),
        "config_sha256": pin,
        "index_sha256": sha(canonical(index)),
        "builder_sha256": sha(Path(__file__).read_bytes()),
        "project_id": index["project_id"],
        "views": views,
        "retained_status": index["status"],
        "stage1_papers": len(index["papers"]),
        "stage2_literature": len(selection["evaluation_packet"].get("literature", [])),
        "classification": "synthetic-repository-fixture",
        "stage_cases": "Independent synthetic ledger and saved delivery examples; not an end-to-end research chain or paper-discovery provenance.",
        "stage_inputs": str(root / "stage-inputs.json"),
        "stage_inputs_sha256": sha(canonical(stage_inputs)),
        "stage_source_sha256": source_digest(snapshot_inputs(stage_inputs)),
        "brief": str(root / "brief.json"),
        "brief_sha256": sha(canonical(brief)),
        "researcher_confirmed_intake": False,
        "original_stage1_lineage_attested": False,
        "execution_authority": False,
        "scientific_quality_verified": False,
        "native_process_started": False,
        "model_call_started": False,
    }
    if positive_case is not None:
        receipt["saved_stage1_case"] = positive_case
        receipt["stage1_display_binding"] = (
            "same saved coverage ledger and handoff identities"
        )
        receipt["stage2_independent_saved_case"] = True
    save(root / "fixture-receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=True), flush=True)
    return files, views


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--harness-operations", action="store_true")
    parser.add_argument("--stage-actions", action="store_true")
    parser.add_argument(
        "--demonstrate-ready-saved-case",
        action="store_true",
        help="Display the same saved synthetic coverage ledger whose real gate passes; Stage2 remains independent, with no research execution.",
    )
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.open and not args.serve:
        parser.error("--open requires --serve")
    if (args.harness_operations or args.stage_actions) and not args.serve:
        parser.error("--harness-operations/--stage-actions requires --serve")
    files, views = build(
        args.output, demonstrate_ready_saved_case=args.demonstrate_ready_saved_case
    )
    if args.serve:
        credential = secrets.token_urlsafe(32)
        operations = stages = None
        try:
            if args.harness_operations:
                operations = create_harness_operations(
                    files,
                    views,
                    private_output(args.output) / "harness-operations",
                    credential,
                )
            if args.harness_operations or args.stage_actions:
                stages = create_stage_actions(args.output, views, credential)
            server = AtlasHost(
                files=files,
                views=views,
                port=args.port,
                credential=credential,
                harness_ops=operations,
                stage_actions=stages,
            )
        except BaseException:
            if operations is not None:
                operations.close()
            if stages is not None:
                stages.close()
            raise
        print(server.expected_origin + "/", flush=True)
        if args.open:
            webbrowser.open(server.expected_origin + "/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
