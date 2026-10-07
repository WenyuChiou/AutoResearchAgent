"""Portable registered content history, without execution or authorship attestation.

The retained delivery manifest anchors these local records. Rehashing an entire
history cannot prove who authored it or whether a described native call ran.
"""

import copy
import hashlib
from pathlib import Path

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.revision_provenance import _candidate_map, _revision_rows
from stage2_workflow.store import _inside, inspect_workflow


VERSION = "2.0.0"
IMPORTED_VERSION = "2.1.0"
ARCHIVE = "registered_history/workflow"
SCOPE = "registered-content-history-only"
MEANING = "registered content history; execution, authorship and human approval are not attested"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _transition_revisions(parent, current, impact):
    old = _candidate_map(parent)
    added = [row for key, row in _candidate_map(current).items() if key not in old]
    revised = [row for row in added if row["parent_version"] is not None]
    if not revised:
        return []
    # New v1 introductions are registered, but are not candidate revisions.
    revision_packet = copy.deepcopy(current)
    revision_packet["candidates"] = list(old.values()) + revised
    ids = {row["candidate_id"] for row in revised}
    return _revision_rows(
        parent,
        revision_packet,
        [row for row in impact if row["candidate_id"] in ids],
        require_added_evidence=False,
    )


def _required_files(state):
    """List verified engine dependencies; never crawl an arbitrary workflow tree."""
    documents = {"workflow_manifest.json": state["manifest"]}
    hashes = {}
    for event in state["events"]:
        documents[f"events/{event['sequence']:06d}.json"] = event
    for snapshot in state["snapshots"]:
        sequence = snapshot["event"]["payload"]["snapshot_sequence"]
        prefix = f"snapshots/{sequence:06d}/checker/"
        checker = snapshot["checker"]
        manifest = checker["manifest"]
        documents[prefix + "run_manifest.json"] = manifest
        documents[prefix + manifest["packet_path"]] = checker["packet"]
        for row in manifest["source_snapshots"]:
            hashes[prefix + row["stored_path"]] = row["sha256"]
        stage_run = manifest.get("stage_run") or {}
        for row in stage_run.get("input_refs", []):
            hashes[prefix + row["path"]] = row["sha256"]
        original = _inside(
            state["root"], prefix + "input_packet.json", "registered-history"
        )
        if original.exists():
            documents[prefix + "input_packet.json"] = snapshot["packet"]
    for action_id, action in state["actions"].items():
        prefix = f"actions/{action_id}/"
        documents[prefix + "request.json"] = action["request"]
        if action["result"] is not None:
            result = action["result"]
            documents[prefix + "result.json"] = result
            for row in result["artifacts"].values():
                hashes[row["stored_path"]] = row["sha256"]
    return documents, hashes


def _capture_verified(state):
    documents, hashes = _required_files(state)
    files = {}
    for relative in sorted(documents.keys() | hashes.keys()):
        path = _inside(state["root"], relative, "registered-history")
        if not path.is_file():
            raise Stage2Error("registered-history-file-not-regular")
        raw = path.read_bytes()
        if relative in hashes and _sha(raw) != hashes[relative]:
            raise Stage2Error("registered-history-file-hash-mismatch")
        if relative in documents and decode_json(raw, relative) != documents[relative]:
            raise Stage2Error("registered-history-file-document-mismatch")
        files[f"{ARCHIVE}/{relative}"] = raw
    steps = []
    previous = None
    for snapshot in state["snapshots"]:
        event = snapshot["event"]
        payload = event["payload"]
        packet = snapshot["packet"]
        steps.append(
            {
                "snapshot_sequence": payload["snapshot_sequence"],
                "event_sequence": event["sequence"],
                "event_sha256": event["event_sha256"],
                "parent_packet_sha256": canonical_hash(previous["packet"])
                if previous
                else None,
                "packet_sha256": canonical_hash(packet),
                "parent_snapshot_sha256": payload["parent_snapshot_sha256"],
                "snapshot_sha256": payload["snapshot_sha256"],
                "checker_manifest_sha256": payload["checker_manifest_sha256"],
                "snapshot_reason": payload["reason"],
                "impact": copy.deepcopy(payload["impact"]),
                "source_versions": copy.deepcopy(payload["source_versions"]),
                "evidence_sha256": canonical_hash(packet["evidence"]),
                "candidates_sha256": canonical_hash(packet["candidates"]),
                "revisions": _transition_revisions(
                    previous["packet"], packet, payload["impact"]
                )
                if previous
                else [],
            }
        )
        previous = snapshot
    latest = state["latest_snapshot"]
    provenance = {
        "kind": "Stage2DeliveryRevisionProvenance",
        "schema_version": VERSION,
        "scope": SCOPE,
        "native_execution_attested": False,
        "human_approval": False,
        "authorship": "not-attested",
        "workflow_root": ARCHIVE,
        "workflow_manifest_sha256": state["manifest"]["manifest_sha256"],
        "workflow_head_sha256": state["head_sha256"],
        "snapshot_sequence": latest["event"]["payload"]["snapshot_sequence"],
        "snapshot_sha256": latest["event"]["payload"]["snapshot_sha256"],
        "packet_sha256": canonical_hash(latest["packet"]),
        "steps": steps,
        "files": [
            {"path": name, "sha256": _sha(raw), "size_bytes": len(raw)}
            for name, raw in sorted(files.items())
        ],
        "meaning": MEANING,
    }
    return provenance, files


def _with_imported_history(provenance, records):
    if not records:
        return provenance
    result = copy.deepcopy(provenance)
    result["schema_version"] = IMPORTED_VERSION
    result["imported_history"] = records
    history_revisions(result)  # Reject duplicate/conflicting transition claims.
    return result


def history_revisions(provenance):
    """Return imported and registered transitions without inventing missing rows."""
    rows = [
        copy.deepcopy(row)
        for record in provenance.get("imported_history", [])
        for row in record["revisions"]
    ] + [
        copy.deepcopy(row) for step in provenance["steps"] for row in step["revisions"]
    ]
    seen = set()
    for row in rows:
        key = (row["candidate_id"], row["to_version"])
        if key in seen:
            raise Stage2Error("registered-history-duplicate-transition")
        seen.add(key)
    return rows


def capture_registered_history(state, imported_delivery_bindings=None):
    """Capture actual registered events and all consecutive immutable snapshots.

    The caller writes returned bytes without rewriting paths inside those bytes,
    and creates the archive's actions directory even when it has no actions.
    """
    if not isinstance(state, dict) or not {"root", "head_sha256"}.issubset(state):
        raise Stage2Error("registered-history-state-shape")
    try:
        verified = inspect_workflow(state["root"], expected_head=state["head_sha256"])
        for key in ("manifest", "events", "actions", "pending_candidate_ids"):
            if state.get(key) != verified[key]:
                raise Stage2Error("registered-history-state-mismatch")
        supplied_snapshots = [
            (row["event"], row["packet"]) for row in state["snapshots"]
        ]
        actual_snapshots = [
            (row["event"], row["packet"]) for row in verified["snapshots"]
        ]
        if supplied_snapshots != actual_snapshots:
            raise Stage2Error("registered-history-state-mismatch")
        provenance, files = _capture_verified(verified)
        if imported_delivery_bindings:
            from .imported_history import capture_imported_history

            records, imported_files, _ = capture_imported_history(
                imported_delivery_bindings, verified["snapshots"][0]["packet"]
            )
            provenance = _with_imported_history(provenance, records)
            files.update(imported_files)
        # Detect concurrent append/edit rather than silently capture a moving head.
        inspect_workflow(verified["root"], expected_head=verified["head_sha256"])
        return provenance, files
    except (OSError, KeyError, TypeError) as error:
        raise Stage2Error("registered-history-capture-failed") from error


def inspect_registered_history(root, provenance, packet, manifest):
    """Replay solely portable bytes bound by the retained delivery manifest."""
    if not isinstance(provenance, dict) or not isinstance(manifest, dict):
        raise Stage2Error("registered-history-shape")
    version = provenance.get("schema_version")
    if version not in {VERSION, IMPORTED_VERSION}:
        raise Stage2Error("registered-history-claims-invalid")
    if (version, manifest.get("schema_version")) not in {
        (VERSION, "1.3.0"),
        (VERSION, None),  # Preserve the legacy helper's binding-only receipt.
        (IMPORTED_VERSION, "1.4.0"),
    }:
        raise Stage2Error("registered-history-version-mismatch")
    claims = {
        "kind": "Stage2DeliveryRevisionProvenance",
        "schema_version": version,
        "scope": SCOPE,
        "native_execution_attested": False,
        "human_approval": False,
        "authorship": "not-attested",
        "workflow_root": ARCHIVE,
        "meaning": MEANING,
    }
    if any(
        type(provenance.get(key)) is not type(value) or provenance.get(key) != value
        for key, value in claims.items()
    ):
        raise Stage2Error("registered-history-claims-invalid")
    bindings = (
        "workflow_manifest_sha256",
        "workflow_head_sha256",
        "snapshot_sequence",
        "snapshot_sha256",
    )
    if (
        manifest.get("revision_provenance_scope") != SCOPE
        or manifest.get("revision_provenance_sha256") != canonical_hash(provenance)
        or any(provenance.get(key) != manifest.get(key) for key in bindings)
        or provenance.get("packet_sha256") != canonical_hash(packet)
    ):
        raise Stage2Error("registered-history-delivery-binding-mismatch")
    try:
        inventory = provenance.get("files")
        if not isinstance(inventory, list) or not inventory:
            raise Stage2Error("registered-history-file-inventory-invalid")
        seen = set()
        for row in inventory:
            if not isinstance(row, dict) or set(row) != {
                "path",
                "sha256",
                "size_bytes",
            }:
                raise Stage2Error("registered-history-file-inventory-invalid")
            name = row["path"]
            if (
                not isinstance(name, str)
                or not name.startswith(ARCHIVE + "/")
                or name in seen
                or type(row["size_bytes"]) is not int
            ):
                raise Stage2Error("registered-history-file-inventory-invalid")
            seen.add(name)
            path = _inside(Path(root), name, "registered-history")
            if not path.is_file():
                raise Stage2Error("registered-history-file-not-regular")
            raw = path.read_bytes()
            if _sha(raw) != row["sha256"] or len(raw) != row["size_bytes"]:
                raise Stage2Error("registered-history-file-hash-mismatch")
        archive_root = _inside(Path(root), ARCHIVE, "registered-history")
        actual_paths = set()
        for path in archive_root.rglob("*"):
            if path.is_symlink():
                raise Stage2Error("registered-history-symlink-invalid")
            if path.is_file():
                actual_paths.add(path.relative_to(Path(root)).as_posix())
        if actual_paths != seen:
            raise Stage2Error("registered-history-file-set-mismatch")
        state = inspect_workflow(
            archive_root, expected_head=manifest["workflow_head_sha256"]
        )
        actual, _ = _capture_verified(state)
        from .imported_history import inspect_imported_history

        records = provenance.get("imported_history", [])
        if version == IMPORTED_VERSION and (
            not isinstance(records, list) or not records
        ):
            raise Stage2Error("registered-history-import-records-required")
        inspect_imported_history(root, records, state["snapshots"][0]["packet"])
        if version == IMPORTED_VERSION:
            actual = _with_imported_history(actual, records)
        if actual != provenance or state["latest_snapshot"]["packet"] != packet:
            raise Stage2Error("registered-history-replay-mismatch")
        if (
            manifest.get("snapshot_checker_manifest_sha256")
            != state["latest_snapshot"]["checker"]["manifest"]["manifest_sha256"]
        ):
            raise Stage2Error("registered-history-final-checker-mismatch")
        return history_revisions(actual)
    except (OSError, KeyError, TypeError) as error:
        raise Stage2Error("registered-history-replay-failed") from error
