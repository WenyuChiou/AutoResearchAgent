"""Authenticate source-update revision provenance for portable deliveries."""

import copy
import hashlib
import json
from pathlib import Path

from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval import validate_action_record
from stage2_workflow.store import _validate_append_only

VERSION = "1.0.0"
RECEIPT_FIELDS = {
    "kind",
    "schema_version",
    "parent_packet_sha256",
    "packet_sha256",
    "packet_path",
    "source_root",
    "impact",
    "acquisitions",
    "review_required",
    "scientific_quality_verified",
    "prior_reviews_carried_forward",
}


def _decode(raw, label):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage2Error(f"revision-provenance-json-invalid: {label}") from error
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _candidate_map(packet):
    return {(row["candidate_id"], row["version"]): row for row in packet["candidates"]}


def _revision_rows(parent, current, impact):
    _validate_append_only(parent, current)
    old = _candidate_map(parent)
    new = _candidate_map(current)
    added = [copy.deepcopy(row) for key, row in new.items() if key not in old]
    affected = {
        row["candidate_id"]: row["reason"]
        for row in impact
        if row["status"] == "affected"
    }
    if not added or set(affected) != {row["candidate_id"] for row in added}:
        raise Stage2Error("revision-provenance-affected-candidates-mismatch")
    valid_evidence = {row["evidence_id"] for row in current["evidence"]}
    rows = []
    for candidate in added:
        key = (candidate["candidate_id"], candidate["parent_version"])
        previous = old.get(key)
        if previous is None or candidate["version"] != candidate["parent_version"] + 1:
            raise Stage2Error("revision-provenance-parent-version-mismatch")
        evidence_ids = sorted(
            set(candidate["evidence_ids"]) - set(previous["evidence_ids"])
        )
        if not evidence_ids or not set(evidence_ids).issubset(valid_evidence):
            raise Stage2Error("revision-provenance-added-evidence-invalid")
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "from_version": previous["version"],
                "to_version": candidate["version"],
                "reason": affected[candidate["candidate_id"]],
                "evidence_ids": evidence_ids,
            }
        )
    return sorted(rows, key=lambda row: (row["candidate_id"], row["to_version"]))


def _validate_receipt(value):
    if not isinstance(value, dict) or set(value) != RECEIPT_FIELDS:
        raise Stage2Error("revision-provenance-source-update-shape")
    if value["kind"] != "Stage2SourceUpdate" or value["schema_version"] != "1.0.0":
        raise Stage2Error("revision-provenance-source-update-version")
    if (
        value["review_required"] is not True
        or value["scientific_quality_verified"] is not False
        or value["prior_reviews_carried_forward"] is not False
    ):
        raise Stage2Error("revision-provenance-source-update-claims-invalid")


def capture_revision_provenance(state, bindings):
    """Bind raw source-update receipts to authenticated consecutive snapshots."""
    if not bindings:
        return None, {}
    files = {}
    steps = []
    used_pairs = set()
    previous_sequence = 0
    for index, (receipt_path, expected_sha256) in enumerate(bindings, 1):
        path = Path(receipt_path)
        if path.is_symlink() or not path.is_file():
            raise Stage2Error("revision-provenance-receipt-not-regular-file")
        raw = path.read_bytes()
        if _sha(raw) != expected_sha256:
            raise Stage2Error("revision-provenance-receipt-hash-mismatch")
        receipt = _decode(raw, str(path))
        _validate_receipt(receipt)
        matches = []
        for parent, current in zip(state["snapshots"], state["snapshots"][1:]):
            if (
                canonical_hash(parent["packet"]) == receipt["parent_packet_sha256"]
                and canonical_hash(current["packet"]) == receipt["packet_sha256"]
            ):
                matches.append((parent, current))
        if len(matches) != 1:
            raise Stage2Error("revision-provenance-snapshot-match-not-unique")
        parent, current = matches[0]
        sequence = current["event"]["payload"]["snapshot_sequence"]
        if sequence <= previous_sequence:
            raise Stage2Error("revision-provenance-bindings-out-of-order")
        previous_sequence = sequence
        pair = (receipt["parent_packet_sha256"], receipt["packet_sha256"])
        if pair in used_pairs:
            raise Stage2Error("revision-provenance-duplicate-source-update")
        used_pairs.add(pair)
        event = current["event"]
        payload = event["payload"]
        if (
            payload["impact"] != receipt["impact"]
            or payload["original_packet_sha256"] != receipt["packet_sha256"]
            or payload["parent_snapshot_sha256"]
            != parent["event"]["payload"]["snapshot_sha256"]
            or payload["snapshot_sha256"]
            != current["checker"]["manifest"]["manifest_sha256"]
            or payload["checker_manifest_sha256"] != payload["snapshot_sha256"]
        ):
            raise Stage2Error("revision-provenance-workflow-snapshot-mismatch")
        adjacent = path.parent / "packet.json"
        if adjacent.is_symlink() or not adjacent.is_file():
            raise Stage2Error("revision-provenance-adjacent-packet-missing")
        adjacent_packet = _decode(adjacent.read_bytes(), str(adjacent))
        if adjacent_packet != current["packet"]:
            raise Stage2Error("revision-provenance-adjacent-packet-mismatch")
        receipt_name = f"revision_provenance/source_update_{index:06d}.json"
        parent_name = f"revision_provenance/parent_packet_{index:06d}.json"
        files[receipt_name] = raw
        files[parent_name] = json.dumps(
            parent["packet"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        steps.append(
            {
                "receipt_file": receipt_name,
                "receipt_sha256": expected_sha256,
                "parent_packet_file": parent_name,
                "parent_packet_sha256": receipt["parent_packet_sha256"],
                "packet_sha256": receipt["packet_sha256"],
                "snapshot_sequence": payload["snapshot_sequence"],
                "parent_snapshot_sha256": payload["parent_snapshot_sha256"],
                "snapshot_sha256": payload["snapshot_sha256"],
                "checker_manifest_sha256": current["checker"]["manifest"][
                    "manifest_sha256"
                ],
                "snapshot_reason": payload["reason"],
                "impact": copy.deepcopy(payload["impact"]),
                "revisions": _revision_rows(
                    parent["packet"], current["packet"], payload["impact"]
                ),
            }
        )
    provenance = {
        "kind": "Stage2DeliveryRevisionProvenance",
        "schema_version": VERSION,
        "workflow_manifest_sha256": state["manifest"]["manifest_sha256"],
        "workflow_head_sha256": state["head_sha256"],
        "steps": sorted(steps, key=lambda row: row["snapshot_sequence"]),
        "meaning": "local source-update provenance; not native execution attestation or human approval",
    }
    return provenance, files


def inspect_revision_provenance(root, provenance, packet, manifest):
    """Rebuild revision rows using only portable, manifest-bound files."""
    required = {
        "kind",
        "schema_version",
        "workflow_manifest_sha256",
        "workflow_head_sha256",
        "steps",
        "meaning",
    }
    if not isinstance(provenance, dict) or set(provenance) != required:
        raise Stage2Error("revision-provenance-shape")
    if (
        provenance["kind"] != "Stage2DeliveryRevisionProvenance"
        or provenance["schema_version"] != VERSION
        or provenance["workflow_manifest_sha256"]
        != manifest["workflow_manifest_sha256"]
        or provenance["workflow_head_sha256"] != manifest["workflow_head_sha256"]
    ):
        raise Stage2Error("revision-provenance-binding-mismatch")
    revisions = []
    prior_sequence = 0
    step_fields = {
        "receipt_file",
        "receipt_sha256",
        "parent_packet_file",
        "parent_packet_sha256",
        "packet_sha256",
        "snapshot_sequence",
        "parent_snapshot_sha256",
        "snapshot_sha256",
        "checker_manifest_sha256",
        "snapshot_reason",
        "impact",
        "revisions",
    }
    for index, step in enumerate(provenance["steps"], 1):
        if not isinstance(step, dict) or set(step) != step_fields:
            raise Stage2Error("revision-provenance-step-shape")
        expected_receipt = f"revision_provenance/source_update_{index:06d}.json"
        expected_parent = f"revision_provenance/parent_packet_{index:06d}.json"
        if (
            step["receipt_file"] != expected_receipt
            or step["parent_packet_file"] != expected_parent
        ):
            raise Stage2Error("revision-provenance-file-path-invalid")
        if step["snapshot_sequence"] <= prior_sequence:
            raise Stage2Error("revision-provenance-order-invalid")
        prior_sequence = step["snapshot_sequence"]
        receipt_raw = (root / step["receipt_file"]).read_bytes()
        if _sha(receipt_raw) != step["receipt_sha256"]:
            raise Stage2Error("revision-provenance-receipt-hash-mismatch")
        receipt = _decode(receipt_raw, step["receipt_file"])
        _validate_receipt(receipt)
        parent = _decode(
            (root / step["parent_packet_file"]).read_bytes(), step["parent_packet_file"]
        )
        if (
            canonical_hash(parent) != step["parent_packet_sha256"]
            or receipt["parent_packet_sha256"] != step["parent_packet_sha256"]
            or receipt["packet_sha256"] != step["packet_sha256"]
            or receipt["impact"] != step["impact"]
            or step["checker_manifest_sha256"] != step["snapshot_sha256"]
        ):
            raise Stage2Error("revision-provenance-portable-binding-mismatch")
        validate_packet(parent, root / "checker" / "sources")
        current = packet if step["packet_sha256"] == canonical_hash(packet) else None
        if current is None:
            for later in provenance["steps"]:
                if later["parent_packet_sha256"] == step["packet_sha256"]:
                    current = _decode(
                        (root / later["parent_packet_file"]).read_bytes(),
                        later["parent_packet_file"],
                    )
                    break
        if (
            current is None
            or _revision_rows(parent, current, step["impact"]) != step["revisions"]
        ):
            raise Stage2Error("revision-provenance-revision-mismatch")
        revisions.extend(copy.deepcopy(step["revisions"]))
    if provenance["steps"]:
        final = provenance["steps"][-1]
        if final["packet_sha256"] == canonical_hash(packet) and (
            final["snapshot_sequence"] != manifest["snapshot_sequence"]
            or final["snapshot_sha256"] != manifest["snapshot_sha256"]
        ):
            raise Stage2Error("revision-provenance-final-snapshot-mismatch")
    validate_packet(packet, root / "checker" / "sources")
    return revisions


def derive_selection(checker_selection, revisions):
    """Add a complete evaluator action record only when all blockers are covered."""
    selection = copy.deepcopy(checker_selection)
    covered = {
        f"{row['candidate_id']} v{row['to_version']}: imported revision has no recorded reason/evidence event"
        for row in revisions
    }
    remaining = [
        row for row in selection["action_record_blocking_items"] if row not in covered
    ]
    if remaining or not revisions:
        return selection
    history = []
    for event in selection["assessment_history"]:
        assessment = event["assessment"]
        evidence = sorted(
            {
                ref
                for finding in assessment["checks"].values()
                for ref in finding["evidence_ids"]
            }
            | set((assessment.get("revised_candidate") or {}).get("evidence_ids", []))
        )
        history.append(
            {
                "event_id": assessment["event_id"],
                "candidate_id": assessment["candidate_id"],
                "candidate_version": assessment["candidate_version"],
                "disposition": assessment["disposition"],
                "reason": assessment["reason"],
                "evidence_ids": evidence,
                "next_step": assessment["next_step"]
                or "Follow the recorded disposition and its documented evidence constraints.",
            }
        )
    latest = []
    for option in selection["current_options"]:
        assessment = option["assessment"]
        if assessment is None:
            return selection
        row = copy.deepcopy(
            next(
                item
                for item in reversed(history)
                if item["candidate_id"] == assessment["candidate_id"]
                and item["candidate_version"] == assessment["candidate_version"]
            )
        )
        row.pop("event_id")
        latest.append(row)
    selected = [row["candidate_id"] for row in selection["recommendations"]]
    if selected:
        rationale = (
            "Selected source-bound sufficient-for-design option(s): "
            + " ".join(
                row["reason"] for row in latest if row["candidate_id"] in selected
            )
        )
    elif selection["blocking_items"] or selection["pending_scope_questions"]:
        rationale = (
            "No candidate selected because blocking or pending scope items remain: "
            + "; ".join(
                selection["blocking_items"] + selection["pending_scope_questions"]
            )
        )
    elif latest:
        rationale = (
            "No candidate selected after the recorded source-bound dispositions: "
            + " ".join(row["reason"] for row in latest)
        )
    else:
        rationale = "No candidate was supplied, so no selection was made."
    action = {
        "kind": "Stage2ActionRecord",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(selection["evaluation_packet"]),
        "history": history,
        "latest_dispositions": latest,
        "selected_candidate_ids": selected,
        "choice_rationale": rationale,
        "revision_history": sorted(
            revisions, key=lambda row: (row["candidate_id"], row["to_version"])
        ),
    }
    validate_action_record(action, selection["evaluation_packet"])
    selection["action_record"] = action
    selection["action_record_status"] = "complete"
    selection["action_record_blocking_items"] = []
    return selection
