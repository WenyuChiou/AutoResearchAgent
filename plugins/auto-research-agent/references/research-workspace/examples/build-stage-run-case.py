"""Prepare a controlled repository corpus for an explicitly admitted native run.

The source texts come from the existing Stage 2 fixture. This builder does not
call Codex, search, import private delivery packages, or grant execution rights.
Its Stage 1 saved ledger and Stage 2 seed share exact work/version/source bytes;
that correspondence is not an accepted canonical Stage 1 to Stage 2 handoff.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

PLUGIN = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.projection import validate_index  # noqa: E402
from research_workspace.view import write_workspace  # noqa: E402
from research_workspace_native.atlas_host import load_views  # noqa: E402
from research_workspace_native.stage_inputs import (  # noqa: E402
    snapshot_inputs,
    source_digest,
)
from stage1_brief.brief import validate_brief  # noqa: E402
from stage1_deliverable.common import canonical, private_output, sha  # noqa: E402
from stage1_deliverable.views import bibtex  # noqa: E402
from stage1_ledger.store import Ledger  # noqa: E402
from stage1_ledger.validation import validate_run  # noqa: E402
from stage2_common import validate_packet  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402


def save(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value))


def metadata(packet, sources):
    """Titles are literal source sentences; other fields are fixture metadata."""
    return [
        dict(
            title=(sources / row["path"])
            .read_text(encoding="utf-8")
            .strip()
            .split(".")[0]
            + ".",
            authors=["Repository synthetic fixture"],
            year=2026,
            version="repository-fixture-v1",
        )
        for row in packet["sources"]
    ]


def ledger_case(root, packet, sources):
    ledger = Ledger.create(
        root,
        run_id="repository-native-stage-pilot",
        objective=packet["brief"]["original_description"],
    )
    records = metadata(packet, sources)
    query = ledger.start(
        "search", {"query": "Saved repository corpus import; no online search"}
    )
    attempt = ledger.start(
        "backend",
        {"operation": "saved-fixture-import", "network_calls": 0},
        backend="repository-snapshot",
        parent_id=query,
    )
    raw = ledger.save_bytes(canonical(records), producer=attempt)
    empty = ledger.save_bytes(b"", producer=attempt)
    ledger.finish(
        attempt,
        outcome="partial_failure",
        http_status=None,
        exit_code=0,
        stdout=raw,
        stderr=empty,
        records=raw,
    )
    ledger.complete_query(query)
    extracted = ledger.extract()
    if extracted["extraction_failures"]:
        raise ValueError("controlled corpus metadata extraction failed")
    bindings = []
    candidates = ledger.candidates()
    for row, record in zip(packet["sources"], records):
        candidate = next(
            item
            for item in candidates.values()
            if item["discoveries"][0]["record"] == record
        )
        work, version = candidate["work_id"], candidate["version_ids"][0]
        imported = ledger.start_source_import(
            work_id=work,
            version_id=version,
            source_uri="repository:tests/stage2_fixture_helpers.py#" + row["path"],
            actor="repository-case-builder",
            reason="Copy the public controlled fixture text; not live acquisition.",
        )
        content = (sources / row["path"]).read_bytes()
        source_ref = ledger.save_bytes(content, producer=imported)
        evidence = next(
            item for item in packet["evidence"] if item["source_id"] == row["source_id"]
        )
        claim = ledger.claim(
            work_id=work,
            version_id=version,
            claim_text=evidence["quote"],
            relation="supports",
            evidence_level="full-text",
            locator={
                "section": "controlled fixture line 1",
                "quote": evidence["quote"],
            },
            source_ref=source_ref,
            verifier={
                "actor": "repository-case-builder",
                "method": "Literal controlled-fixture quote comparison; not scientific review",
                "actor_type": "agent",
            },
        )
        bindings.append(
            dict(
                source_id=row["source_id"],
                original_fixture_work_id=row["work_id"],
                original_fixture_version_id=row["version_id"],
                work_id=work,
                version_id=version,
                path=row["path"],
                sha256=sha(content),
                source_ref=source_ref,
                claim_event_id=claim,
                metadata=record,
            )
        )
        row.update(work_id=work, version_id=version)
        evidence.update(work_id=work, version_id=version)
    report = validate_run(root)
    if not report["valid"]:
        raise ValueError("generated ledger invalid: " + str(report["errors"]))
    checkpoint = ledger.checkpoint()["stage_result"]
    if checkpoint["next_allowed_action"] == "stop-sufficient":
        raise ValueError("fixture must not claim complete Stage 1 coverage")
    return bindings, report, checkpoint


def projection(packet, bindings):
    index = fixture_index()
    index.update(
        project_id="repository-native-stage-pilot",
        topic="Controlled Methods A/B · repository native Harness pilot",
        papers=[],
        sources=[],
        claims=[],
        edges=[],
        screening=[],
        coverage=[],
        search=[],
    )
    for row in bindings:
        record = row["metadata"]
        evidence = next(
            item for item in packet["evidence"] if item["source_id"] == row["source_id"]
        )
        index["papers"].append(
            dict(
                work_id=row["work_id"],
                version_id=row["version_id"],
                title=record["title"],
                authors=record["authors"],
                year=record["year"],
                venue="Controlled repository corpus; not a publication",
                doi=None,
                url=None,
                evidence_level="full-text",
                classification={"topic_cluster": "Controlled Methods A/B"},
                roles=[],
                source_ids=[row["source_id"]],
                claim_ids=[row["claim_event_id"]],
                findings={
                    "main_findings": evidence["quote"],
                    "limitations": "Synthetic fixture text; not a real paper or scientific finding.",
                    "relevance": "Exact local source for an explicitly authorized native Harness pilot.",
                },
            )
        )
        index["sources"].append(
            dict(
                source_id=row["source_id"],
                work_id=row["work_id"],
                version_id=row["version_id"],
                source_ref=row["source_ref"],
                access_note="Existing repository fixture copied locally; no network or private import.",
            )
        )
        index["claims"].append(
            dict(
                claim_id=row["claim_event_id"],
                work_id=row["work_id"],
                version_id=row["version_id"],
                text=evidence["quote"],
                source_id=row["source_id"],
                relation="supports",
                evidence_level="full-text",
                locator={
                    "section": "controlled fixture line 1",
                    "quote": evidence["quote"],
                },
            )
        )
    digest = sha(canonical({"papers": index["papers"], "claims": index["claims"]}))
    index["provenance"]["records_sha256"] = digest
    index["bibliography"] = dict(
        records_sha256=digest,
        entries=[
            dict(
                work_id=p["work_id"],
                version_id=p["version_id"],
                bibtex=bibtex({"papers": [p]}).decode(),
            )
            for p in index["papers"]
        ],
        all_bibtex=bibtex(index).decode(),
        producer="stage1_deliverable.views.bibtex",
    )
    validate_index(index)
    return index


def build(output):
    root = private_output(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    sources = root / "sources"
    packet = write_stage2_fixture(sources, candidate_count=0)
    bindings, report, checkpoint = ledger_case(root / "stage1-ledger", packet, sources)
    validate_packet(packet, sources)
    validate_brief(packet["brief"], require_confirmed=True)
    save(root / "packet.json", packet)
    save(root / "brief.json", packet["brief"])
    save(root / "stage1-report.json", report)
    save(root / "stage1-checkpoint.json", checkpoint)
    inputs = {"1": {"ledger_root": (root / "stage1-ledger").as_posix()}, "2": None}
    save(root / "stage-inputs.json", inputs)
    index = projection(packet, bindings)
    manifests = {}
    for stage in ("stage1", "stage2"):
        view = root / "views" / stage
        manifests[stage] = write_workspace(
            deepcopy(index), PLUGIN / "references/research-workspace", view, atlas=True
        )
        save(view / "brief.json", packet["brief"])
    host = {
        "views": [
            dict(
                ref=stage,
                label=stage.upper()
                + " · controlled corpus · native run requires separate permit",
                manifest=(root / "views" / stage / "view-manifest.json").as_posix(),
                sha256=sha(
                    (root / "views" / stage / "view-manifest.json").read_bytes()
                ),
                fixture=True,
            )
            for stage in ("stage1", "stage2")
        ]
    }
    save(root / "host-config.json", host)
    load_views(root / "host-config.json", sha((root / "host-config.json").read_bytes()))
    source_bindings = {row["path"]: row["sha256"] for row in bindings}
    case = dict(
        kind="RepositoryNativeStageRunCase",
        schema_version="1.0.0",
        project_id=index["project_id"],
        packet_path=(root / "packet.json").as_posix(),
        packet_sha256=sha((root / "packet.json").read_bytes()),
        source_root=sources.as_posix(),
        source_bindings=source_bindings,
        source_binding_sha256=sha(canonical(source_bindings)),
        content_provenance={
            "corpus": "synthetic-repository-fixture",
            "fixture_helper": "tests/stage2_fixture_helpers.py",
            "fixture_helper_sha256": sha(
                (PLUGIN / "tests/stage2_fixture_helpers.py").read_bytes()
            ),
            "builder_sha256": sha(Path(__file__).read_bytes()),
            "metadata": "Generated fixture titles are literal source sentences; author/year/version labels are synthetic.",
        },
        paper_bindings=bindings,
        stage1_ledger_root=(root / "stage1-ledger").as_posix(),
        stage1_gate=checkpoint["gate"],
        stage1_next_allowed_action=checkpoint["next_allowed_action"],
        brief_path=(root / "brief.json").as_posix(),
        brief_sha256=sha((root / "brief.json").read_bytes()),
        stage_inputs_path=(root / "stage-inputs.json").as_posix(),
        stage_inputs_sha256=sha((root / "stage-inputs.json").read_bytes()),
        stage_source_sha256=source_digest(snapshot_inputs(inputs)),
        host_config_path=(root / "host-config.json").as_posix(),
        host_config_sha256=sha((root / "host-config.json").read_bytes()),
        view_manifests={
            stage: host["views"][i] for i, stage in enumerate(("stage1", "stage2"))
        },
        index_sha256=manifests["stage1"]["index_sha256"],
        shared_work_version_source_identities=True,
        canonical_stage1_to_stage2_lineage=False,
        stage1_complete=False,
        stage2_complete=False,
        daily_v3_status="not-started; independently admitted evaluation required",
        execution_authorized=False,
        native_calls=0,
        model_calls=0,
        search_calls=0,
    )
    save(root / "case.json", case)
    return case


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    case = build(args.output)
    print(json.dumps(case, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
