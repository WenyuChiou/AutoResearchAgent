"""Source-free Stage 2 content revisions bound to an authentic extraction unit."""

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

from stage1_eval.common import canonical
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_common.contract import _bound_path
from stage2_ideation import build_extraction_task, validate_extraction
from stage2_ideation.integration import build_next_packet
from stage2_workflow.store import _validate_impact, inspect_workflow

from .extraction import (
    _prompt,
    _request,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from .judges import _execution_policy
from .replay import replay_unit


VERSION = "1.0.0"
UPDATE_MODE = "replace-comparison-unresolved"
_LINES = re.compile(r"lines ([1-9][0-9]*)-([1-9][0-9]*)")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_json(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"content-revision-{label}-invalid") from error
    if not isinstance(value, dict):
        raise Stage2Error(f"content-revision-{label}-shape")
    return value


def _write_new(path, value):
    path = Path(path)
    if path.exists():
        raise Stage2Error("content-revision-output-already-exists")
    path.write_bytes(canonical(value) + b"\n")


def _source_map(packet):
    return {row["source_id"]: row for row in packet["sources"]}


def _source_bindings(packet, source_root):
    bindings = []
    for source in packet["sources"]:
        raw = _bound_path(source_root, source["path"]).read_bytes()
        observed = _sha(raw)
        if observed != source["sha256"]:
            raise Stage2Error("content-revision-source-bytes-changed")
        bindings.append(
            {
                "source_id": source["source_id"],
                "work_id": source["work_id"],
                "version_id": source["version_id"],
                "path": source["path"],
                "sha256": observed,
                "bytes": len(raw),
            }
        )
    return bindings


def _validate_evidence_additions(packet, source_root, additions):
    if not isinstance(additions, list):
        raise Stage2Error("content-revision-evidence-additions-shape")
    sources = _source_map(packet)
    known = {row["evidence_id"] for row in packet["evidence"]}
    validated = []
    for row in additions:
        allowed = {
            "evidence_id",
            "source_id",
            "work_id",
            "version_id",
            "locator",
            "quote",
        }
        if packet["schema_version"] != "1.0.0":
            allowed.add("origin")
        if not isinstance(row, dict) or set(row) != allowed:
            raise Stage2Error("content-revision-evidence-row-shape")
        if row["evidence_id"] in known:
            raise Stage2Error("content-revision-evidence-id-duplicate")
        source = sources.get(row["source_id"])
        if source is None:
            raise Stage2Error("content-revision-evidence-foreign-source")
        if (row["work_id"], row["version_id"]) != (
            source["work_id"],
            source["version_id"],
        ):
            raise Stage2Error("content-revision-evidence-source-identity-mismatch")
        match = _LINES.fullmatch(row["locator"])
        if match is None:
            raise Stage2Error("content-revision-evidence-locator-invalid")
        start, end = map(int, match.groups())
        lines = (
            _bound_path(source_root, source["path"])
            .read_bytes()
            .decode("utf-8")
            .splitlines(keepends=True)
        )
        if end < start or end > len(lines):
            raise Stage2Error("content-revision-evidence-locator-out-of-range")
        excerpt = "".join(lines[start - 1 : end])
        if excerpt.endswith("\r\n"):
            excerpt = excerpt[:-2]
        elif excerpt.endswith(("\r", "\n")):
            excerpt = excerpt[:-1]
        if row["quote"] != excerpt:
            raise Stage2Error("content-revision-evidence-quote-mismatch")
        known.add(row["evidence_id"])
        validated.append(copy.deepcopy(row))
    return validated


def prepare_content_revision_input(packet, source_root, additions, output_dir):
    """Append exact excerpts from existing frozen sources, or preserve zero additions."""

    validate_packet(packet, source_root)
    additions = _validate_evidence_additions(packet, source_root, additions)
    revised = copy.deepcopy(packet)
    revised["evidence"].extend(additions)
    revised["packet_id"] = (
        "content-revision-input-"
        + canonical_hash({"parent": canonical_hash(packet), "additions": additions})[
            :24
        ]
    )
    validate_packet(revised, source_root)
    output = Path(output_dir).resolve()
    if output.exists():
        raise Stage2Error("content-revision-input-output-already-exists")
    output.mkdir(parents=True)
    _write_new(output / "packet.json", revised)
    receipt = {
        "kind": "Stage2ContentRevisionInput",
        "schema_version": VERSION,
        "parent_packet_sha256": canonical_hash(packet),
        "packet_sha256": canonical_hash(revised),
        "evidence_additions": additions,
        "source_bindings": _source_bindings(packet, source_root),
        "sources_changed": False,
        "review_required": True,
    }
    _write_new(output / "content_revision_input.json", receipt)
    return receipt


def _external_receipt(value_or_path):
    value = (
        copy.deepcopy(value_or_path)
        if isinstance(value_or_path, dict)
        else _read_json(value_or_path, "external-replay-receipt")
    )
    if set(value) != {"result_sha256", "unit_receipts"} or set(
        value["unit_receipts"]
    ) != {"extraction"}:
        raise Stage2Error("content-revision-extraction-receipt-shape")
    for digest in (value["result_sha256"], value["unit_receipts"]["extraction"]):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Stage2Error("content-revision-extraction-receipt-sha256")
    return value


def _model_config(request):
    try:
        return {
            "codex": request["codex"],
            "codex_executable_sha256": request["codex_runtime_sha256"],
            "evaluator_home": request["evaluator_home"],
            "model": request["model"],
            "reasoning": request["reasoning"],
        }
    except (KeyError, TypeError) as error:
        raise Stage2Error("content-revision-extraction-config-missing") from error


def _authenticate_extraction(
    extraction_root,
    external_receipt_path,
    packet,
    source_root,
    snapshot_sha256,
):
    root = Path(extraction_root).resolve()
    receipt = _external_receipt(external_receipt_path)
    result_path = root / "result.json"
    unit_path = root / "extraction.unit.json"
    if (
        result_path.is_symlink()
        or unit_path.is_symlink()
        or not result_path.is_file()
        or not unit_path.is_file()
        or _sha(result_path.read_bytes()) != receipt["result_sha256"]
        or _sha(unit_path.read_bytes()) != receipt["unit_receipts"]["extraction"]
    ):
        raise Stage2Error("content-revision-extraction-artifact-changed")
    raw = (root / "raw-proposal.bin").read_bytes().decode("utf-8")
    if (root / "input-packet.json").read_bytes() != canonical(packet) + b"\n":
        raise Stage2Error("content-revision-extraction-input-packet-mismatch")
    request = _read_json(root / "request.json", "extraction-request")
    if (
        request.get("adapter_mode") != "native"
        or request.get("packet_update_mode") != UPDATE_MODE
    ):
        raise Stage2Error("content-revision-extraction-mode-mismatch")
    task = build_extraction_task(raw, packet, snapshot_sha256)
    spans = build_span_index(raw)
    schema = generation_schema(spans, packet)
    prompt = _prompt(task, packet, spans, schema, UPDATE_MODE)
    policy = _execution_policy(request.get("execution_policy", {}))
    expected_request = _request(
        task,
        packet,
        source_root,
        spans,
        schema,
        prompt,
        request.get("codex"),
        request.get("evaluator_home"),
        request.get("model"),
        request.get("reasoning"),
        policy,
        "native",
        UPDATE_MODE,
    )
    if request != expected_request:
        raise Stage2Error("content-revision-extraction-request-mismatch")

    def validate(value):
        expanded = expand_span_ids(value, raw, spans, packet)
        validate_extraction(raw, expanded, packet, snapshot_sha256)

    replay = replay_unit(
        root,
        "extraction",
        receipt["unit_receipts"]["extraction"],
        prompt=prompt,
        schema=schema,
        config=_model_config(request),
        policy=policy,
        validate=validate,
    )
    expanded = expand_span_ids(replay["value"], raw, spans, packet)
    validated = validate_extraction(raw, expanded, packet, snapshot_sha256)
    next_packet = build_next_packet(
        packet,
        source_root,
        raw,
        validated,
        snapshot_sha256,
        update_mode=UPDATE_MODE,
    )
    result = _read_json(result_path, "extraction-result")
    if (
        result.get("kind") != "Stage2LiveExtractionResult"
        or result.get("status") != "passed"
        or result.get("packet_update_mode") != UPDATE_MODE
        or result.get("request_sha256") != canonical_hash(expected_request)
        or result.get("extraction") != validated
        or result.get("next_packet") != next_packet
        or result.get("model_call_provenance") != replay["provenance"]
        or result.get("unit_receipts") != receipt["unit_receipts"]
        or result.get("native_execution_verified") is not True
    ):
        raise Stage2Error("content-revision-extraction-result-mismatch")
    return {
        "raw_repaired_prose_sha256": _sha(raw.encode("utf-8")),
        "request_sha256": canonical_hash(expected_request),
        "result_sha256": receipt["result_sha256"],
        "unit_receipt": receipt["unit_receipts"]["extraction"],
        "archive_sha256s": replay["archive_sha256s"],
        "actual_call_count": replay["actual_call_count"],
        "next_packet": next_packet["packet"],
    }


def _transition(parent, extraction_input, current, source_root, impact):
    for field in parent:
        if field in {"packet_id", "evidence"}:
            continue
        if extraction_input.get(field) != parent[field]:
            raise Stage2Error(f"content-revision-input-mutated-{field}")
    additions = extraction_input["evidence"][len(parent["evidence"]) :]
    if extraction_input["evidence"][: len(parent["evidence"])] != parent["evidence"]:
        raise Stage2Error("content-revision-evidence-history-changed")
    if _validate_evidence_additions(parent, source_root, additions) != additions:
        raise Stage2Error("content-revision-evidence-additions-changed")
    for field in ("brief", "resources", "sources", "evidence", "literature"):
        if field in extraction_input and current.get(field) != extraction_input[field]:
            raise Stage2Error(f"content-revision-mutated-{field}")
    normalized = _validate_impact(current, impact)
    affected = {
        row["candidate_id"]: row["reason"]
        for row in normalized
        if row["status"] == "affected"
    }
    old = {(row["candidate_id"], row["version"]): row for row in parent["candidates"]}
    new = {(row["candidate_id"], row["version"]): row for row in current["candidates"]}
    if any(new.get(key) != value for key, value in old.items()):
        raise Stage2Error("content-revision-candidate-history-changed")
    added = [row for key, row in new.items() if key not in old]
    if {row["candidate_id"] for row in added} != set(affected):
        raise Stage2Error("content-revision-affected-candidates-mismatch")
    rows = []
    candidate_changed = False
    for candidate in added:
        prior = old.get((candidate["candidate_id"], candidate["parent_version"]))
        if prior is None or candidate["version"] != prior["version"] + 1:
            raise Stage2Error("content-revision-candidate-version-invalid")
        if {
            key: value
            for key, value in candidate.items()
            if key not in {"version", "parent_version"}
        } == {
            key: value
            for key, value in prior.items()
            if key not in {"version", "parent_version"}
        }:
            raise Stage2Error("content-revision-candidate-no-op")
        candidate_changed = True
        if candidate["evidence_ids"] and not set(candidate["evidence_ids"]).issubset(
            {row["evidence_id"] for row in current["evidence"]}
        ):
            raise Stage2Error("content-revision-candidate-evidence-invalid")
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "from_version": prior["version"],
                "to_version": candidate["version"],
                "reason": affected[candidate["candidate_id"]],
                "evidence_ids": sorted(candidate["evidence_ids"]),
            }
        )
    if not (
        candidate_changed
        or current["comparison"] != parent["comparison"]
        or current["unresolved"] != parent["unresolved"]
    ):
        raise Stage2Error("content-revision-no-substantive-change")
    return normalized, sorted(rows, key=lambda row: row["candidate_id"]), additions


def prepare_content_revision(
    run_dir,
    expected_head,
    extraction_root,
    extraction_receipt,
    source_root,
    impact,
    output_dir,
):
    """Authenticate a source-free v2 snapshot and write its portable receipt."""

    state = inspect_workflow(run_dir, expected_head=expected_head)
    if len(state["snapshots"]) < 2:
        raise Stage2Error("content-revision-snapshot-pair-required")
    parent, current = state["snapshots"][-2:]
    parent_packet, current_packet = parent["packet"], current["packet"]
    validate_packet(parent_packet, source_root)
    validate_packet(current_packet, source_root)
    extraction_input = _read_json(
        Path(extraction_root) / "input-packet.json", "extraction-input-packet"
    )
    normalized, revisions, additions = _transition(
        parent_packet, extraction_input, current_packet, source_root, impact
    )
    if current["event"]["payload"]["impact"] != normalized:
        raise Stage2Error("content-revision-workflow-impact-mismatch")
    proof = _authenticate_extraction(
        extraction_root,
        extraction_receipt,
        extraction_input,
        source_root,
        parent["event"]["payload"]["snapshot_sha256"],
    )
    if proof["next_packet"] != current_packet:
        raise Stage2Error("content-revision-extracted-packet-mismatch")
    output = Path(output_dir).resolve()
    if output.exists():
        raise Stage2Error("content-revision-output-already-exists")
    output.mkdir(parents=True)
    sources = output / "sources"
    sources.mkdir()
    for source in current_packet["sources"]:
        source_path = _bound_path(source_root, source["path"])
        target = (sources / source["path"]).resolve()
        try:
            target.relative_to(sources)
        except ValueError as error:
            raise Stage2Error("content-revision-source-path-escapes") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
    _write_new(output / "packet.json", current_packet)
    external = _external_receipt(extraction_receipt)
    receipt = {
        "kind": "Stage2ContentRevision",
        "schema_version": VERSION,
        "parent_packet_sha256": canonical_hash(parent_packet),
        "extraction_input_packet_sha256": canonical_hash(extraction_input),
        "extraction_input_packet_id": extraction_input["packet_id"],
        "packet_sha256": canonical_hash(current_packet),
        "packet_path": str(output / "packet.json"),
        "source_root": str(sources),
        "source_bindings": _source_bindings(current_packet, sources),
        "evidence_additions": additions,
        "impact": normalized,
        "revisions": revisions,
        "raw_repaired_prose_sha256": proof["raw_repaired_prose_sha256"],
        "extraction_root": str(Path(extraction_root).resolve()),
        "extraction_replay_receipt": external,
        "extraction_request_sha256": proof["request_sha256"],
        "extraction_archive_sha256s": proof["archive_sha256s"],
        "extraction_actual_call_count": proof["actual_call_count"],
        "packet_update_mode": UPDATE_MODE,
        "parent_snapshot_sha256": parent["event"]["payload"]["snapshot_sha256"],
        "snapshot_sha256": current["event"]["payload"]["snapshot_sha256"],
        "workflow_event_sha256": current["event"]["event_sha256"],
        "affected_candidate_ids": sorted(row["candidate_id"] for row in revisions),
        "review_required": True,
        "prior_reviews_carried_forward": False,
        "scientific_quality_verified": False,
    }
    _write_new(output / "content_revision.json", receipt)
    return receipt


CONTENT_REVISION_FIELDS = {
    "kind",
    "schema_version",
    "parent_packet_sha256",
    "extraction_input_packet_sha256",
    "extraction_input_packet_id",
    "packet_sha256",
    "packet_path",
    "source_root",
    "source_bindings",
    "evidence_additions",
    "impact",
    "revisions",
    "raw_repaired_prose_sha256",
    "extraction_root",
    "extraction_replay_receipt",
    "extraction_request_sha256",
    "extraction_archive_sha256s",
    "extraction_actual_call_count",
    "packet_update_mode",
    "parent_snapshot_sha256",
    "snapshot_sha256",
    "workflow_event_sha256",
    "affected_candidate_ids",
    "review_required",
    "prior_reviews_carried_forward",
    "scientific_quality_verified",
}


def validate_content_revision_receipt(
    receipt_path,
    parent,
    current,
    source_root,
    *,
    authenticate_extraction,
    require_adjacent_packet,
):
    """Validate a ContentRevision against an authenticated snapshot pair."""

    receipt_path = Path(receipt_path)
    receipt = _read_json(receipt_path, "receipt")
    if set(receipt) != CONTENT_REVISION_FIELDS:
        raise Stage2Error("content-revision-receipt-shape")
    if (
        receipt["kind"] != "Stage2ContentRevision"
        or receipt["schema_version"] != VERSION
        or receipt["packet_update_mode"] != UPDATE_MODE
        or receipt["review_required"] is not True
        or receipt["prior_reviews_carried_forward"] is not False
        or receipt["scientific_quality_verified"] is not False
    ):
        raise Stage2Error("content-revision-receipt-claims-invalid")
    parent_packet, current_packet = parent["packet"], current["packet"]
    if (
        receipt["parent_packet_sha256"] != canonical_hash(parent_packet)
        or receipt["packet_sha256"] != canonical_hash(current_packet)
        or receipt["parent_snapshot_sha256"]
        != parent["event"]["payload"]["snapshot_sha256"]
        or receipt["snapshot_sha256"] != current["event"]["payload"]["snapshot_sha256"]
        or receipt["workflow_event_sha256"] != current["event"]["event_sha256"]
    ):
        raise Stage2Error("content-revision-snapshot-binding-mismatch")
    if require_adjacent_packet:
        adjacent = receipt_path.parent / "packet.json"
        if adjacent.is_symlink() or not adjacent.is_file():
            raise Stage2Error("content-revision-adjacent-packet-missing")
        if _read_json(adjacent, "adjacent-packet") != current_packet:
            raise Stage2Error("content-revision-adjacent-packet-mismatch")
    extraction_input = copy.deepcopy(parent_packet)
    extraction_input["packet_id"] = receipt["extraction_input_packet_id"]
    extraction_input["evidence"].extend(copy.deepcopy(receipt["evidence_additions"]))
    if canonical_hash(extraction_input) != receipt["extraction_input_packet_sha256"]:
        raise Stage2Error("content-revision-extraction-input-hash-mismatch")
    normalized, revisions, additions = _transition(
        parent_packet,
        extraction_input,
        current_packet,
        source_root,
        receipt["impact"],
    )
    if (
        normalized != current["event"]["payload"]["impact"]
        or normalized != receipt["impact"]
        or revisions != receipt["revisions"]
        or additions != receipt["evidence_additions"]
        or receipt["affected_candidate_ids"]
        != sorted(row["candidate_id"] for row in revisions)
        or receipt["source_bindings"] != _source_bindings(current_packet, source_root)
    ):
        raise Stage2Error("content-revision-semantic-binding-mismatch")
    _external_receipt(receipt["extraction_replay_receipt"])
    if authenticate_extraction:
        proof = _authenticate_extraction(
            receipt["extraction_root"],
            receipt["extraction_replay_receipt"],
            extraction_input,
            source_root,
            receipt["parent_snapshot_sha256"],
        )
        expected = {
            "raw_repaired_prose_sha256": proof["raw_repaired_prose_sha256"],
            "extraction_request_sha256": proof["request_sha256"],
            "extraction_archive_sha256s": proof["archive_sha256s"],
            "extraction_actual_call_count": proof["actual_call_count"],
        }
        if any(receipt[key] != value for key, value in expected.items()):
            raise Stage2Error("content-revision-producer-proof-mismatch")
        if proof["next_packet"] != current_packet:
            raise Stage2Error("content-revision-extracted-packet-mismatch")
    return revisions


__all__ = [
    "UPDATE_MODE",
    "prepare_content_revision",
    "prepare_content_revision_input",
    "validate_content_revision_receipt",
]
