"""Append captured sources to a private packet; never attest their scientific truth."""

import copy
import hashlib
import json
from pathlib import Path

from stage1_deliverable.common import private_output, safe_path
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_common.contract import _bound_path
from stage2_workflow.store import _validate_append_only, _validate_impact


def prepare_source_update(
    packet,
    source_root,
    additions,
    revisions,
    impact,
    output_dir,
    *,
    expected_packet_sha256,
    unresolved=None,
):
    """Build a new immutable, review-required packet from externally captured text.

    Each addition has a packet ``source``, exact ``evidence`` rows, an optional
    ``literature`` row, a local ``raw_path`` and an ``acquisition`` receipt.
    Failed acquisition receipts have no source/evidence and remain visible.
    Receipt identity/level assertions are recorded, not silently upgraded to
    independent verification. Applying this output still requires the existing
    snapshot/review interfaces.
    """
    validate_packet(packet, source_root)
    if canonical_hash(packet) != expected_packet_sha256:
        raise Stage2Error("source-update-parent-hash-mismatch")
    if not isinstance(additions, list) or not additions:
        raise Stage2Error("source-update-additions-required")
    if not isinstance(revisions, list):
        raise Stage2Error("source-update-revised-candidate-required")
    next_packet = copy.deepcopy(packet)
    raw_files = {}
    receipts = []
    for addition in additions:
        if not isinstance(addition, dict):
            raise Stage2Error("source-update-addition-shape")
        receipt = addition.get("acquisition")
        if not isinstance(receipt, dict) or set(receipt) != {
            "status",
            "url",
            "retrieved_at",
            "raw_sha256",
            "identity_status",
            "evidence_level",
            "reason",
            "action_ref",
        }:
            raise Stage2Error("source-update-acquisition-receipt-shape")
        if receipt["status"] not in {
            "obtained",
            "unavailable",
            "rate-limit",
            "parse-failure",
            "identity-mismatch",
            "empty-result",
            "credential-failure",
        }:
            raise Stage2Error("source-update-acquisition-status")
        for field in ("url", "retrieved_at", "identity_status", "reason", "action_ref"):
            if not isinstance(receipt[field], str) or not receipt[field].strip():
                raise Stage2Error(f"source-update-missing-{field}")
        if not receipt["url"].startswith(("https://", "http://")):
            raise Stage2Error("source-update-public-url-required")
        receipts.append(copy.deepcopy(receipt))
        if receipt["status"] != "obtained":
            if set(addition) != {"acquisition"}:
                raise Stage2Error("source-update-failure-cannot-produce-evidence")
            continue
        if not {"source", "evidence", "raw_path", "acquisition"}.issubset(addition):
            raise Stage2Error("source-update-obtained-source-required")
        if set(addition) - {
            "source",
            "evidence",
            "raw_path",
            "acquisition",
            "literature",
        }:
            raise Stage2Error("source-update-unknown-field")
        raw_path = Path(addition["raw_path"])
        if raw_path.is_symlink() or not raw_path.is_file():
            raise Stage2Error("source-update-raw-file-missing")
        raw = raw_path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Stage2Error("source-update-needs-extracted-utf8-text") from error
        source = copy.deepcopy(addition["source"])
        actual = hashlib.sha256(raw).hexdigest()
        if actual != receipt["raw_sha256"] or actual != source.get("sha256"):
            raise Stage2Error("source-update-raw-hash-mismatch")
        if source.get("evidence_level") != receipt["evidence_level"]:
            raise Stage2Error("source-update-evidence-level-mismatch")
        if receipt["identity_status"] not in {"matched", "unverified"}:
            raise Stage2Error("source-update-identity-not-usable")
        if (
            source["evidence_level"] == "full-text"
            and receipt["identity_status"] != "matched"
        ):
            raise Stage2Error("source-update-full-text-identity-unverified")
        if packet["schema_version"] != "1.0.0":
            if source.get("origin") != "stage2":
                raise Stage2Error("source-update-origin-must-be-stage2")
            for row in addition["evidence"]:
                if row.get("origin") != "stage2":
                    raise Stage2Error("source-update-evidence-origin-must-be-stage2")
        next_packet["sources"].append(source)
        next_packet["evidence"].extend(copy.deepcopy(addition["evidence"]))
        if "literature" in addition:
            row = copy.deepcopy(addition["literature"])
            if row.get("origin") != "stage2":
                raise Stage2Error("source-update-literature-origin-must-be-stage2")
            primary_work_ids = {
                item["work_id"] for item in next_packet.get("literature", [])
            }
            target = (
                "supplemental_literature"
                if packet["schema_version"] in {"2.3.0", "2.4.0"}
                and row.get("work_id") in primary_work_ids
                else "literature"
            )
            next_packet.setdefault(target, []).append(row)
        raw_files[source["path"]] = raw
    next_packet["candidates"].extend(copy.deepcopy(revisions))
    if packet["schema_version"] == "2.4.0":
        # Every added source/evidence row changes the complete source-set hash.
        # The immutable parent retains its reviews; the new packet requires fresh ones.
        next_packet["prior_work_reviews"] = []
    if unresolved is not None:
        if not isinstance(unresolved, list) or any(
            not isinstance(row, str) or not row.strip() for row in unresolved
        ):
            raise Stage2Error("source-update-unresolved-shape")
        for row in unresolved:
            if row not in next_packet["unresolved"]:
                next_packet["unresolved"].append(row)
    next_packet["packet_id"] = (
        "source-update-"
        + canonical_hash(
            {
                "parent": expected_packet_sha256,
                "receipts": receipts,
                "revisions": revisions,
            }
        )[:24]
    )
    _validate_append_only(packet, next_packet)
    normalized = _validate_impact(next_packet, impact)
    affected = {
        row["candidate_id"] for row in normalized if row["status"] == "affected"
    }
    if any(row["candidate_id"] not in affected for row in revisions):
        raise Stage2Error("source-update-revised-candidate-must-be-affected")
    for field, identity in (("sources", "source_id"), ("evidence", "evidence_id")):
        values = [row[identity] for row in next_packet[field]]
        if len(values) != len(set(values)):
            raise Stage2Error(f"source-update-duplicate-{identity}")
    paths = [row["path"].casefold() for row in next_packet["sources"]]
    if len(paths) != len(set(paths)):
        raise Stage2Error("source-update-duplicate-source-path")
    destination = private_output(output_dir)
    if destination.exists():
        raise Stage2Error("source-update-output-already-exists")
    for source in next_packet["sources"]:
        safe_path(destination, source["path"])
        if Path(source["path"]).name.casefold() in {
            "packet.json",
            "source_update.json",
        }:
            raise Stage2Error("source-update-control-path-collision")
    destination.mkdir(parents=True)
    # Only bound UTF-8 snapshots are copied. No credential/profile inventory.
    for source in packet["sources"]:
        raw_files[source["path"]] = _bound_path(
            source_root, source["path"]
        ).read_bytes()
    for relative, raw in raw_files.items():
        path = safe_path(destination, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    validate_packet(next_packet, destination)
    packet_path = destination / "packet.json"
    packet_path.write_text(
        json.dumps(next_packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = {
        "kind": "Stage2SourceUpdate",
        "schema_version": "1.0.0",
        "parent_packet_sha256": expected_packet_sha256,
        "packet_sha256": canonical_hash(next_packet),
        "packet_path": str(packet_path),
        "source_root": str(destination),
        "impact": normalized,
        "acquisitions": receipts,
        "review_required": True,
        "scientific_quality_verified": False,
        "prior_reviews_carried_forward": False,
    }
    (destination / "source_update.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
