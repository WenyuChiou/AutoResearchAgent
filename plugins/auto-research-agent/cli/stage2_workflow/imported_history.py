"""Import retained legacy local revision evidence without reusing approvals."""

import copy
import hashlib
import os
from pathlib import Path

from stage1_deliverable.common import DeliverableError, reject_links
from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.delivery import inspect_delivery
from stage2_workflow.revision_provenance import (
    _candidate_map,
    inspect_revision_provenance,
)
from stage2_workflow.store import _inside


PREFIX = "registered_history/imported_delivery"
CLAIMS = {
    "kind": "Stage2ImportedDeliveryHistory",
    "schema_version": "1.0.0",
    "scope": "imported-local-content-history-only",
    "native_execution_attested": False,
    "human_approval": False,
    "authorship": "not-attested",
}
SOURCE_FIELDS = ("source_id", "work_id", "version_id", "evidence_level", "sha256")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(path):
    return decode_json(path.read_bytes(), str(path))


def _guard_inventory(root, manifest):
    """Reject links and undeclared files before the legacy inspector reads bytes."""
    reject_links(root)
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise Stage2Error("imported-history-inventory-invalid")
    expected = {"delivery_manifest.json"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size"}:
            raise Stage2Error("imported-history-inventory-invalid")
        path = _inside(root, row["path"], "imported-history")
        reject_links(path)
        if row["path"] in expected or not path.is_file():
            raise Stage2Error("imported-history-inventory-invalid")
        expected.add(row["path"])
    actual = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            reject_links(Path(directory) / name)
        actual.update(
            (Path(directory) / name).relative_to(root).as_posix() for name in files
        )
    if actual != expected:
        raise Stage2Error("imported-history-file-set-mismatch")


def _bind_revisions(root, provenance, delivery_packet, initial_packet):
    """Compare exact retained transition payloads, allowing only source relocation."""
    packets = {canonical_hash(delivery_packet): delivery_packet}
    for step in provenance["steps"]:
        path = _inside(root, step["parent_packet_file"], "imported-history")
        parent = _json(path)
        packets[canonical_hash(parent)] = parent
    initial_candidates = _candidate_map(initial_packet)
    initial_evidence = {row["evidence_id"]: row for row in initial_packet["evidence"]}
    initial_sources = {row["source_id"]: row for row in initial_packet["sources"]}
    if any(
        len(mapping) != len(initial_packet[field])
        for mapping, field in (
            (initial_candidates, "candidates"),
            (initial_evidence, "evidence"),
            (initial_sources, "sources"),
        )
    ):
        raise Stage2Error("imported-history-initial-identities-duplicate")
    rows = []
    for step in provenance["steps"]:
        parent = packets.get(step["parent_packet_sha256"])
        current = packets.get(step["packet_sha256"])
        if parent is None or current is None:
            raise Stage2Error("imported-history-transition-missing")
        old, new = _candidate_map(parent), _candidate_map(current)
        evidence = {row["evidence_id"]: row for row in current["evidence"]}
        sources = {row["source_id"]: row for row in current["sources"]}
        for revision in step["revisions"]:
            references = set(revision["evidence_ids"])
            for field, candidates in (("from_version", old), ("to_version", new)):
                key = (revision["candidate_id"], revision[field])
                candidate = candidates.get(key)
                if candidate is None or candidate != initial_candidates.get(key):
                    raise Stage2Error("imported-history-candidate-mismatch")
                references.update(candidate["evidence_ids"])
            for evidence_id in references:
                claim = evidence.get(evidence_id)
                if claim is None or claim != initial_evidence.get(evidence_id):
                    raise Stage2Error("imported-history-evidence-mismatch")
                source = sources.get(claim["source_id"])
                initial_source = initial_sources.get(claim["source_id"])
                if (
                    source is None
                    or initial_source is None
                    or any(
                        source.get(key) != initial_source.get(key)
                        for key in SOURCE_FIELDS
                    )
                ):
                    raise Stage2Error("imported-history-source-mismatch")
                stored_source = _inside(
                    root / "checker" / "sources", source["path"], "imported-history"
                )
                if _sha(stored_source.read_bytes()) != initial_source["sha256"]:
                    raise Stage2Error("imported-history-source-hash-mismatch")
            rows.append(copy.deepcopy(revision))
    if not rows:
        raise Stage2Error("imported-history-revisions-absent")
    return rows


def _capture_one(root, expected_manifest_sha256, initial_packet, index):
    reject_links(root)
    root = Path(root).resolve()
    manifest_path = _inside(root, "delivery_manifest.json", "imported-history")
    manifest = _json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.1.0":
        raise Stage2Error("imported-history-delivery-version-unsupported")
    _guard_inventory(root, manifest)
    state = inspect_delivery(root, expected_manifest_sha256)
    provenance = _json(
        _inside(root, manifest["revision_provenance_file"], "imported-history")
    )
    if provenance.get("schema_version") != "1.0.0":
        raise Stage2Error("imported-history-provenance-version-unsupported")
    actual_rows = inspect_revision_provenance(
        root, provenance, state["input_packet"], manifest
    )
    rows = _bind_revisions(root, provenance, state["input_packet"], initial_packet)
    if rows != actual_rows:
        raise Stage2Error("imported-history-revision-mismatch")
    prefix = f"{PREFIX}/{index:06d}"
    files = {}
    for row in manifest["files"]:
        raw = _inside(root, row["path"], "imported-history").read_bytes()
        if _sha(raw) != row["sha256"] or len(raw) != row["size"]:
            raise Stage2Error("imported-history-file-hash-mismatch")
        files[f"{prefix}/{row['path']}"] = raw
    raw_manifest = manifest_path.read_bytes()
    if decode_json(raw_manifest, str(manifest_path)) != manifest:
        raise Stage2Error("imported-history-manifest-changed")
    files[f"{prefix}/delivery_manifest.json"] = raw_manifest
    inspect_delivery(root, expected_manifest_sha256)
    record = {
        **CLAIMS,
        "delivery_root": prefix,
        "delivery_manifest_sha256": expected_manifest_sha256,
        "initial_packet_sha256": canonical_hash(initial_packet),
        "delivery_packet_sha256": canonical_hash(state["input_packet"]),
        "revisions": rows,
        "files": [
            {"path": name, "sha256": _sha(raw), "size": len(raw)}
            for name, raw in sorted(files.items())
        ],
    }
    return record, files, rows


def _add_rows(rows, additions, seen):
    for row in additions:
        key = (row["candidate_id"], row["to_version"])
        if key in seen:
            raise Stage2Error("imported-history-duplicate-transition")
        seen.add(key)
        rows.append(copy.deepcopy(row))


def capture_imported_history(bindings, initial_packet):
    """Copy only authenticated legacy inventories; never reuse prior judgments."""
    if not isinstance(bindings, list) or not isinstance(initial_packet, dict):
        raise Stage2Error("imported-history-input-shape")
    records, files, rows, seen = [], {}, [], set()
    try:
        for index, binding in enumerate(bindings, 1):
            if not isinstance(binding, (tuple, list)) or len(binding) != 2:
                raise Stage2Error("imported-history-binding-shape")
            root, receipt = binding
            record, copied, revisions = _capture_one(
                Path(root), receipt, initial_packet, index
            )
            _add_rows(rows, revisions, seen)
            records.append(record)
            files.update(copied)
        return records, files, rows
    except (OSError, KeyError, TypeError, DeliverableError) as error:
        raise Stage2Error("imported-history-capture-failed") from error


def inspect_imported_history(root, records, initial_packet):
    """Reconstruct imported rows from copied bytes and retained manifest receipts."""
    if not isinstance(records, list) or not isinstance(initial_packet, dict):
        raise Stage2Error("imported-history-input-shape")
    revisions, seen = [], set()
    expected_files = set()
    try:
        for index, record in enumerate(records, 1):
            if not isinstance(record, dict) or any(
                type(record.get(key)) is not type(value) or record.get(key) != value
                for key, value in CLAIMS.items()
            ):
                raise Stage2Error("imported-history-claims-invalid")
            prefix = f"{PREFIX}/{index:06d}"
            if record.get("delivery_root") != prefix:
                raise Stage2Error("imported-history-delivery-path-invalid")
            package = _inside(Path(root), prefix, "imported-history")
            actual, _, additions = _capture_one(
                package, record["delivery_manifest_sha256"], initial_packet, index
            )
            if actual != record:
                raise Stage2Error("imported-history-record-mismatch")
            _add_rows(revisions, additions, seen)
            expected_files.update(row["path"] for row in actual["files"])
        imported_root = _inside(Path(root), PREFIX, "imported-history")
        actual_files = set()
        if imported_root.exists():
            reject_links(imported_root)
            if {path.name for path in imported_root.iterdir()} != {
                f"{index:06d}" for index in range(1, len(records) + 1)
            }:
                raise Stage2Error("imported-history-package-set-mismatch")
            for directory, dirs, files in os.walk(imported_root, followlinks=False):
                for name in dirs + files:
                    reject_links(Path(directory) / name)
                actual_files.update(
                    (Path(directory) / name).relative_to(Path(root)).as_posix()
                    for name in files
                )
        if actual_files != expected_files:
            raise Stage2Error("imported-history-file-set-mismatch")
        return revisions
    except (OSError, KeyError, TypeError, DeliverableError) as error:
        raise Stage2Error("imported-history-replay-failed") from error
