"""Build a source-bound Stage 2 seed from accepted Stage 1 artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

from stage1_brief.brief import validate_brief
from stage1_deliverable import package as deliverable_package
from stage1_deliverable import sources as deliverable_sources
from stage1_deliverable.common import (
    DeliverableError,
    private_output,
    read_json,
    reject_links,
    safe_path,
)
from stage1_ledger.contracts import check as check_stage1_contract
from stage1_ledger.handoff import DIMENSIONS
from stage1_ledger.journal import LedgerError
from stage2_common import (
    Stage2Error,
    canonical_hash,
    stage1_projection_hash,
    validate_packet,
)


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_bound_json(path, expected_sha256, label):
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Stage2Error(f"{label}-read-failed: {error}") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise Stage2Error(f"{label}-sha256-mismatch")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise Stage2Error(f"{label}-duplicate-json-key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"{label}-invalid-json: {error}") from error
    return value


def _metadata_snapshot(paper, source, result):
    value = {
        "kind": "Stage1MetadataSnapshot",
        "work_id": paper["work_id"],
        "version_id": paper["version_id"],
        "source_id": source["source_id"],
        "title": paper["title"],
        "authors": paper["authors"],
        "year": paper["year"],
        "venue": paper["venue"],
        "doi": paper["doi"],
        "url": paper["url"],
        "access_note": source["access_note"],
        "access_status": result["status"],
        "evidence_level": "metadata",
    }
    return _canonical_bytes(value) + b"\n"


def _source_bytes(root, source, paper):
    archive = safe_path(root, "sources/" + source["source_id"])
    result, mapping, replay = deliverable_sources.validate_archive(archive)
    deliverable_sources.validate_observation(archive, result, mapping, replay)
    extracted = result.get("extracted_text_path")
    if result["status"] == "available" and extracted:
        relative = mapping.get(extracted)
        if relative is None:
            raise Stage2Error(
                f"stage1-source-extracted-text-unmapped: {source['source_id']}"
            )
        raw = safe_path(archive, relative).read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Stage2Error(
                f"stage1-source-text-not-utf8: {source['source_id']}"
            ) from error
        return raw, result
    metadata_result = copy.deepcopy(result)
    metadata_result["evidence_level"] = "metadata"
    return _metadata_snapshot(paper, source, result), metadata_result


def _literature_projection(papers, included):
    return [
        {"origin": "stage1", **copy.deepcopy(papers[work_id])}
        for work_id in sorted(included)
    ]


def _comparison_text(handoff):
    return _comparison_for_papers(handoff["papers"])


def _comparison_for_papers(papers):
    titles = "; ".join(paper["title"] for paper in papers)
    dimensions = ", ".join(DIMENSIONS)
    return (
        f"Stage 1 supplied {len(papers)} included works ({titles}) for "
        f"comparison across: {dimensions}. Stage 2 has not yet compared these works, "
        "generated research directions, or selected a direction."
    )


def _unresolved(records, unavailable, included):
    rows = [
        (
            f"Coverage need {row['need_id']}: {row['unresolved']} "
            f"(Stage 1 decision={row['stop_decision']}; reason={row['reason']})"
        )
        for row in records["coverage"]
    ]
    rows.extend(
        f"Source {source_id} remained {status}; Stage 2 only receives metadata."
        for source_id, status in sorted(unavailable.items())
    )
    rows.extend(
        (
            f"Claim {claim['claim_id']} for {claim['work_id']} "
            f"version {claim['version_id']} remains {claim['relation']}: "
            f"{claim['text']} (source={claim['source_id']}; "
            f"evidence={claim['evidence_level']}; locator={claim['locator']}). "
            "Verify the unresolved assertion before using it as a confirmed premise."
        )
        for claim in records["claims"]
        if claim["work_id"] in included
        and claim["relation"] in {"unverified", "partial", "contradicts"}
    )
    return rows


def _project_stage1(deliverable_root, output, records, included):
    """Copy the selected immutable Stage 1 projection into a Stage 2 seed."""

    papers = {row["work_id"]: row for row in records["papers"]}
    sources_dir = output / "sources"
    sources_dir.mkdir()
    stage2_sources = []
    unavailable = {}
    source_by_id = {row["source_id"]: row for row in records["sources"]}
    for work_id in sorted(included):
        paper = papers[work_id]
        for source_id in paper["source_ids"]:
            source = source_by_id[source_id]
            raw, result = _source_bytes(deliverable_root, source, paper)
            relative = f"sources/{source_id}.txt"
            (output / relative).write_bytes(raw)
            stage2_sources.append(
                {
                    "origin": "stage1",
                    "source_id": source_id,
                    "work_id": work_id,
                    "version_id": paper["version_id"],
                    "path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "evidence_level": result["evidence_level"],
                    "access_status": result["status"],
                    "retrieved_at": result["retrieved_at"],
                    "source_url": result["source_url"] or None,
                    "final_url": result["final_url"] or None,
                    "access_note": source["access_note"],
                }
            )
            if result["status"] != "available":
                unavailable[source_id] = result["status"]

    literature = _literature_projection(papers, included)
    evidence = [
        {
            "origin": "stage1",
            "evidence_id": row["claim_id"],
            "source_id": row["source_id"],
            "work_id": row["work_id"],
            "version_id": row["version_id"],
            "claim_text": row["text"],
            "relation": row["relation"],
            "evidence_level": row["evidence_level"],
            "locator": row["locator"],
            "quote": row["quote"],
        }
        for row in records["claims"]
        if row["work_id"] in included
    ]
    return literature, stage2_sources, evidence, unavailable


def _revalidate_deliverable(deliverable_root, deliverable_manifest_sha256, manifest):
    """Reject a deliverable that changed while source bytes were projected."""

    deliverable_package.validate(deliverable_root, deliverable_manifest_sha256)
    final_manifest = _read_bound_json(
        deliverable_root / "provenance_manifest.json",
        deliverable_manifest_sha256,
        "stage1-deliverable-manifest",
    )
    if final_manifest != manifest:
        raise Stage2Error("stage1-deliverable-changed-during-import")


def build_stage2_seed(
    deliverable_dir,
    deliverable_manifest_sha256,
    handoff_path,
    handoff_sha256,
    brief_path,
    resources_path,
    output_dir,
):
    """Validate Stage 1, then create an unstarted Stage 2 v2 packet."""

    deliverable_root = Path(deliverable_dir).resolve()
    output = Path(output_dir).absolute()
    owned_output = False
    try:
        output = private_output(output)
        if output.exists():
            raise Stage2Error(f"stage1-stage2-output-exists: {output}")
        deliverable_package.validate(deliverable_root, deliverable_manifest_sha256)
        manifest = _read_bound_json(
            deliverable_root / "provenance_manifest.json",
            deliverable_manifest_sha256,
            "stage1-deliverable-manifest",
        )
        records = manifest["canonical_records"]
        handoff = _read_bound_json(handoff_path, handoff_sha256, "stage1-handoff")
        check_stage1_contract(handoff, "Stage1Handoff")
        if not handoff["eligible_for_stage2"]:
            raise Stage2Error("stage1-handoff-not-eligible-for-stage2")
        if handoff["stage2"] != {
            "status": "not-started",
            "execution_authorized": False,
        }:
            raise Stage2Error("stage1-handoff-stage2-boundary-invalid")
        brief = read_json(Path(brief_path).resolve())
        validate_brief(brief, require_confirmed=True)
        resources = Path(resources_path).resolve().read_text(encoding="utf-8").strip()
        if not resources:
            raise Stage2Error("stage1-stage2-resources-empty")

        papers = {row["work_id"]: row for row in records["papers"]}
        handoff_papers = {row["work_id"]: row for row in handoff["papers"]}
        if not handoff_papers or len(handoff_papers) != len(handoff["papers"]):
            raise Stage2Error("stage1-handoff-paper-set-invalid")
        for work_id, row in handoff_papers.items():
            paper = papers.get(work_id)
            expected_version = row["reviewed_version_id"] or row["listed_version_id"]
            if (
                paper is None
                or paper["version_id"] != expected_version
                or paper["title"] != row["title"]
            ):
                raise Stage2Error(f"stage1-handoff-paper-binding-mismatch: {work_id}")

        output.mkdir(parents=False)
        owned_output = True
        reject_links(output)
        included = set(handoff_papers)
        literature, stage2_sources, evidence, unavailable = _project_stage1(
            deliverable_root, output, records, included
        )
        upstream = {
            "kind": "Stage1Stage2Binding",
            "schema_version": "1.0.0",
            "source_run_id": handoff["source_run_id"],
            "source_state_sha256": handoff["source_state_sha256"],
            "stage1_handoff_sha256": handoff_sha256,
            "stage1_deliverable_manifest_sha256": deliverable_manifest_sha256,
            "stage1_records_sha256": manifest["original_input_sha256"],
            "research_brief_sha256": canonical_hash(brief),
            "resources_sha256": canonical_hash(resources),
            "stage1_literature_sha256": stage1_projection_hash(literature),
            "stage1_sources_sha256": stage1_projection_hash(
                stage2_sources, omit={"path"}
            ),
            "stage1_evidence_sha256": stage1_projection_hash(evidence),
            "included_work_ids": sorted(included),
            "eligible_for_stage2": True,
            "stage2": copy.deepcopy(handoff["stage2"]),
        }
        upstream["binding_sha256"] = canonical_hash(upstream)
        packet = {
            "kind": "Stage2Packet",
            "schema_version": "2.0.0",
            "packet_id": f"stage2-seed-{upstream['binding_sha256'][:16]}",
            "brief": brief,
            "resources": resources,
            "comparison": _comparison_text(handoff),
            "literature": literature,
            "evidence": evidence,
            "sources": stage2_sources,
            "candidates": [],
            "unresolved": _unresolved(records, unavailable, included),
            "upstream": upstream,
        }
        # Revalidate after source reads so the imported projection cannot mix
        # bytes from two deliverable states changed during this operation.
        _revalidate_deliverable(deliverable_root, deliverable_manifest_sha256, manifest)
        validate_packet(packet, output)
        (output / "packet.json").write_bytes(_canonical_bytes(packet))
        return {
            "kind": "Stage1Stage2ImportReceipt",
            "schema_version": "1.0.0",
            "status": "ready-for-explicit-stage2-start",
            "packet_path": "packet.json",
            "packet_sha256": canonical_hash(packet),
            "binding_sha256": upstream["binding_sha256"],
            "source_count": len(stage2_sources),
            "evidence_count": len(evidence),
            "candidate_count": 0,
            "stage2_execution_authorized": False,
        }
    except (DeliverableError, LedgerError, OSError, ValueError) as error:
        if owned_output and output.exists():
            reject_links(output)
            shutil.rmtree(output)
        if isinstance(error, Stage2Error):
            raise
        raise Stage2Error(f"stage1-stage2-import-failed: {error}") from error
    except Exception:
        if owned_output and output.exists():
            reject_links(output)
            shutil.rmtree(output)
        raise
