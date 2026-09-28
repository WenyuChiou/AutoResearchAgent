"""Build and inspect immutable local Stage 2 delivery packages."""

import copy
import hashlib
import json
import os
from html import escape
from pathlib import Path, PurePosixPath

from stage2_check import (
    apply_assessment,
    export_selection,
    initialize_run,
    inspect_run,
)
from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_workflow import inspect_workflow
from stage2_workflow.orchestration import reconcile_batch

from stage2_check.report_html import render_selection_html
from stage2_check.run import build_selection
from stage2_check.report import render_proposal, _quote_block

VERSION = "1.0.0"
MANIFEST = "delivery_manifest.json"
REVIEW_INPUT_FILES = {
    "batch": "review_batch.json",
    "reviews": "review_results.json",
    "resolutions": "review_resolutions.json",
    "reconciliation": "reconciliation.json",
    "audit": "review_audit.json",
}


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json(path):
    try:
        return decode_json(path.read_bytes(), str(path))
    except OSError as error:
        raise Stage2Error(f"delivery-read-failed: {path}: {error}") from error


def _write_new(path, value):
    data = value if isinstance(value, bytes) else _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise Stage2Error(f"delivery-exclusive-write-conflict: {path}") from error


def _file_sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise Stage2Error(f"delivery-file-read-failed: {path}: {error}") from error


def _relative_files(root, *, include_manifest=False):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Stage2Error(f"delivery-symlink-forbidden: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST and not include_manifest:
            continue
        rows.append(
            {
                "path": relative,
                "sha256": _file_sha(path),
                "size": path.stat().st_size,
            }
        )
    return rows


def _manifest_hash(manifest):
    return canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def _safe_package_path(root, relative):
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise Stage2Error(f"unsafe-delivery-path: {relative!r}")
    path = root.joinpath(*relative.split("/"))
    if not path.resolve().is_relative_to(root.resolve()):
        raise Stage2Error(f"escaping-delivery-path: {relative}")
    return path


def _verify_source_map(snapshot, packet):
    checker = snapshot["checker"]
    source_root = checker["root"] / "sources"
    packet_sources = {row["source_id"]: row for row in packet["sources"]}
    manifest_sources = {
        row["source_id"]: row for row in checker["manifest"]["source_snapshots"]
    }
    if set(packet_sources) != set(manifest_sources):
        raise Stage2Error("delivery-source-map-set-mismatch")
    for source_id, source in packet_sources.items():
        record = manifest_sources[source_id]
        if (
            record["original_path"] != source["path"]
            or record["stored_path"] != f"sources/{source['path']}"
            or record["sha256"] != source["sha256"]
        ):
            raise Stage2Error(f"delivery-source-map-mismatch: {source_id}")
        path = source_root.joinpath(*source["path"].split("/"))
        if not path.is_file() or _file_sha(path) != source["sha256"]:
            raise Stage2Error(f"delivery-source-hash-mismatch: {source_id}")
    validate_packet(packet, source_root)
    return source_root


def _current_snapshot(state, batch):
    snapshot = state["latest_snapshot"]
    snapshot_hash = snapshot["event"]["payload"]["snapshot_sha256"]
    packet = copy.deepcopy(snapshot["packet"])
    if batch.get("snapshot_sha256") != snapshot_hash:
        raise Stage2Error("delivery-review-batch-current-snapshot-mismatch")
    if batch.get("packet_sha256") != canonical_hash(packet):
        raise Stage2Error("delivery-review-batch-packet-mismatch")
    return snapshot, snapshot_hash, packet


def _review_audit(state, snapshot, batch, reviews, resolutions, reconciliation):
    return {
        "kind": "Stage2DeliveryReviewAudit",
        "schema_version": VERSION,
        "workflow_manifest_sha256": state["manifest"]["manifest_sha256"],
        "workflow_head_sha256": state["head_sha256"],
        "snapshot_sequence": snapshot["event"]["payload"]["snapshot_sequence"],
        "snapshot_sha256": batch["snapshot_sha256"],
        "batch": copy.deepcopy(batch),
        "reviews": copy.deepcopy(reviews),
        "resolutions": copy.deepcopy(resolutions),
        "reconciliation": copy.deepcopy(reconciliation),
        "actual_execution_attested": False,
        "meaning": "local review records and reconciliation only; not native execution attestation or human approval",
    }


def _resolved_assessments(reconciliation):
    rows = []
    for candidate in sorted(
        reconciliation["candidates"], key=lambda row: row["candidate_id"]
    ):
        reconciled = candidate["reconciliation"]
        if reconciled["status"] == "resolved":
            rows.append(copy.deepcopy(reconciled["assessment"]))
    return rows


def _root_markdown(checker, selection, reconciliation):
    data = render_proposal(
        selection,
        checker["packet"]["sources"],
        event_head=checker["event_head_sha256"],
        stored_packet_sha256=checker["manifest"]["stored_packet_sha256"],
        audit_prefix="checker",
    )
    next_step = (
        reconciliation["next_step"]
        or "No additional portfolio-level step was recorded."
    )
    appendix = (
        "\n\n## Independent checks and next steps\n\n"
        + "\n".join(_quote_block(next_step))
        + "\n"
    )
    return data + appendix.encode("utf-8")


def _root_html(checker, selection, reconciliation):
    document = render_selection_html(selection, checker["packet"]["sources"])
    next_step = (
        reconciliation["next_step"]
        or "No additional portfolio-level step was recorded."
    )
    appendix = (
        '<section id="review-next-step"><h2>Independent checks and next steps</h2><pre>'
        + escape(next_step)
        + "</pre></section>"
    )
    return document.replace(b"</main>", appendix.encode("utf-8") + b"</main>")


def build_delivery(run_dir, batch, reviews, resolutions, output_dir, expected_head):
    """Build a separate source-bound checker and prehuman delivery package."""
    state = inspect_workflow(run_dir, expected_head=expected_head)
    snapshot, snapshot_hash, packet = _current_snapshot(state, batch)
    source_root = _verify_source_map(snapshot, packet)
    reconciliation = reconcile_batch(packet, batch, reviews, resolutions)

    output = Path(output_dir).resolve()
    if output.exists():
        raise Stage2Error(f"delivery-output-exists: {output}")
    try:
        output.mkdir(parents=False)
    except FileExistsError as error:
        raise Stage2Error(f"delivery-output-exists: {output}") from error
    except OSError as error:
        raise Stage2Error(
            f"delivery-output-create-failed: {output}: {error}"
        ) from error

    packet_path = output / "input_packet.json"
    _write_new(packet_path, packet)
    _write_new(output / "review_batch.json", batch)
    _write_new(output / "review_results.json", reviews)
    _write_new(output / "review_resolutions.json", resolutions)
    _write_new(output / "reconciliation.json", reconciliation)
    audit = _review_audit(state, snapshot, batch, reviews, resolutions, reconciliation)
    _write_new(output / "review_audit.json", audit)

    checker_root = output / "checker"
    initialize_run(packet_path, source_root, checker_root)
    for index, assessment in enumerate(_resolved_assessments(reconciliation), 1):
        assessment_path = output / "resolved_assessments" / f"{index:06d}.json"
        _write_new(assessment_path, assessment)
        apply_assessment(checker_root, assessment_path)
    selection = export_selection(checker_root)
    checker = inspect_run(checker_root)

    # Root reports intentionally use the same validated ``sources/...`` links as
    # the checker report, so publish byte-identical snapshot copies at that path.
    for source in checker["packet"]["sources"]:
        source_path = _safe_package_path(checker_root, source["path"])
        delivery_source = _safe_package_path(output, source["path"])
        _write_new(delivery_source, source_path.read_bytes())

    _write_new(output / "selection.json", selection)
    _write_new(
        output / "selection.md", _root_markdown(checker, selection, reconciliation)
    )
    html = _root_html(checker, selection, reconciliation)
    _write_new(output / "selection.html", html)

    # Unreviewed screened-out ideas and honestly parked options remain visible.
    # They do not veto the independently checked selectable directions.
    local_ready = reconciliation["local_reconciliation_ready"]
    recommendation_refs = [
        {
            "candidate_id": candidate["candidate_id"],
            "candidate_version": candidate["version"],
        }
        for candidate in selection["recommendations"]
    ]
    pending_revisions = [
        {
            "candidate_id": option["candidate"]["candidate_id"],
            "candidate_version": option["candidate"]["version"],
            "parent_version": option["candidate"]["parent_version"],
        }
        for option in selection["current_options"]
        if option["assessment"] is None
        and option["candidate"]["parent_version"] is not None
    ]
    manifest = {
        "kind": "Stage2DeliveryManifest",
        "schema_version": VERSION,
        "delivery_status": ("local-report-ready" if local_ready else "draft-not-ready"),
        "workflow_manifest_sha256": state["manifest"]["manifest_sha256"],
        "workflow_head_sha256": state["head_sha256"],
        "snapshot_sequence": snapshot["event"]["payload"]["snapshot_sequence"],
        "snapshot_sha256": snapshot_hash,
        "snapshot_checker_manifest_sha256": snapshot["checker"]["manifest"][
            "manifest_sha256"
        ],
        "batch_sha256": batch["batch_sha256"],
        "reconciliation_sha256": canonical_hash(reconciliation),
        "delivery_checker_manifest_sha256": checker["manifest"]["manifest_sha256"],
        "delivery_checker_event_head_sha256": checker["event_head_sha256"],
        "selection_sha256": canonical_hash(selection),
        "local_reconciliation_ready": reconciliation["local_reconciliation_ready"],
        "recommendation_candidate_versions": recommendation_refs,
        "pending_revision_candidate_versions": pending_revisions,
        "review_input_files": dict(REVIEW_INPUT_FILES),
        "human_selection": "pending",
        "stage3_execution_authorized": False,
        "actual_execution_attested": False,
        "readiness_meaning": "local report completeness only; not native execution attestation, human approval, or scientific truth",
        "files": _relative_files(output),
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    _write_new(output / MANIFEST, manifest)
    inspect_delivery(output, manifest["manifest_sha256"])
    return manifest


def inspect_delivery(directory, expected_manifest_sha256):
    """Revalidate a package against an externally retained manifest receipt.

    Returns ``root`` (resolved ``Path``), the validated ``manifest``, the exact
    ``selection`` and ``reconciliation`` dictionaries, and the separate
    checker's validated ``inspect_run`` state.
    """
    root = Path(directory).resolve()
    manifest = _read_json(root / MANIFEST)
    required = {
        "kind",
        "schema_version",
        "delivery_status",
        "workflow_manifest_sha256",
        "workflow_head_sha256",
        "snapshot_sequence",
        "snapshot_sha256",
        "snapshot_checker_manifest_sha256",
        "batch_sha256",
        "reconciliation_sha256",
        "delivery_checker_manifest_sha256",
        "delivery_checker_event_head_sha256",
        "selection_sha256",
        "local_reconciliation_ready",
        "recommendation_candidate_versions",
        "pending_revision_candidate_versions",
        "review_input_files",
        "human_selection",
        "stage3_execution_authorized",
        "actual_execution_attested",
        "readiness_meaning",
        "files",
        "manifest_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise Stage2Error("delivery-manifest-shape")
    if (
        manifest["kind"] != "Stage2DeliveryManifest"
        or manifest["schema_version"] != VERSION
        or manifest["manifest_sha256"] != _manifest_hash(manifest)
    ):
        raise Stage2Error("delivery-manifest-invalid")
    if expected_manifest_sha256 != manifest["manifest_sha256"]:
        raise Stage2Error("delivery-manifest-receipt-mismatch")
    if manifest["review_input_files"] != REVIEW_INPUT_FILES:
        raise Stage2Error("delivery-review-input-paths-invalid")
    if (
        manifest["human_selection"] != "pending"
        or manifest["stage3_execution_authorized"] is not False
        or manifest["actual_execution_attested"] is not False
    ):
        raise Stage2Error("delivery-authorization-state-invalid")

    actual_files = _relative_files(root)
    if actual_files != manifest["files"]:
        raise Stage2Error("delivery-file-inventory-mismatch")
    for row in manifest["files"]:
        path = _safe_package_path(root, row["path"])
        if _file_sha(path) != row["sha256"] or path.stat().st_size != row["size"]:
            raise Stage2Error(f"delivery-file-hash-mismatch: {row['path']}")

    checker = inspect_run(
        root / "checker",
        expected_event_head=manifest["delivery_checker_event_head_sha256"],
    )
    if (
        checker["manifest"]["manifest_sha256"]
        != manifest["delivery_checker_manifest_sha256"]
    ):
        raise Stage2Error("delivery-checker-manifest-mismatch")
    for source in checker["packet"]["sources"]:
        checker_source = _safe_package_path(root / "checker", source["path"])
        delivery_source = _safe_package_path(root, source["path"])
        if (
            _file_sha(checker_source) != source["sha256"]
            or _file_sha(delivery_source) != source["sha256"]
        ):
            raise Stage2Error(
                f"delivery-published-source-mismatch: {source['source_id']}"
            )
    packet = _read_json(root / "input_packet.json")
    validate_packet(packet, root / "checker" / "sources")
    if checker["manifest"]["packet_sha256"] != canonical_hash(packet):
        raise Stage2Error("delivery-checker-input-packet-mismatch")
    batch = _read_json(root / manifest["review_input_files"]["batch"])
    if (
        batch.get("snapshot_sha256") != manifest["snapshot_sha256"]
        or batch.get("batch_sha256") != manifest["batch_sha256"]
    ):
        raise Stage2Error("delivery-batch-snapshot-mismatch")
    reviews = _read_json(root / manifest["review_input_files"]["reviews"])
    resolutions = _read_json(root / manifest["review_input_files"]["resolutions"])
    reconciliation = reconcile_batch(packet, batch, reviews, resolutions)
    saved_reconciliation = _read_json(
        root / manifest["review_input_files"]["reconciliation"]
    )
    if (
        reconciliation != saved_reconciliation
        or canonical_hash(reconciliation) != manifest["reconciliation_sha256"]
    ):
        raise Stage2Error("delivery-reconciliation-mismatch")
    audit = _read_json(root / manifest["review_input_files"]["audit"])
    if (
        audit.get("batch") != batch
        or audit.get("reviews") != reviews
        or audit.get("resolutions") != resolutions
        or audit.get("reconciliation") != reconciliation
        or audit.get("snapshot_sha256") != manifest["snapshot_sha256"]
        or audit.get("snapshot_sequence") != manifest["snapshot_sequence"]
        or audit.get("workflow_manifest_sha256") != manifest["workflow_manifest_sha256"]
        or audit.get("workflow_head_sha256") != manifest["workflow_head_sha256"]
        or audit.get("actual_execution_attested") is not False
    ):
        raise Stage2Error("delivery-review-audit-mismatch")

    selection = _read_json(root / "selection.json")
    checker_selection = _read_json(root / "checker" / "selection.json")
    if (
        selection != build_selection(checker)
        or selection != checker_selection
        or canonical_hash(selection) != manifest["selection_sha256"]
    ):
        raise Stage2Error("delivery-selection-mismatch")
    recommendation_refs = [
        {
            "candidate_id": candidate["candidate_id"],
            "candidate_version": candidate["version"],
        }
        for candidate in selection["recommendations"]
    ]
    pending_revisions = [
        {
            "candidate_id": option["candidate"]["candidate_id"],
            "candidate_version": option["candidate"]["version"],
            "parent_version": option["candidate"]["parent_version"],
        }
        for option in selection["current_options"]
        if option["assessment"] is None
        and option["candidate"]["parent_version"] is not None
    ]
    expected_status = (
        "local-report-ready"
        if reconciliation["local_reconciliation_ready"]
        else "draft-not-ready"
    )
    if manifest["delivery_status"] != expected_status:
        raise Stage2Error("delivery-status-mismatch")
    if [row["assessment"] for row in checker["events"]] != _resolved_assessments(
        reconciliation
    ):
        raise Stage2Error("delivery-checker-review-mismatch")
    if (
        manifest["recommendation_candidate_versions"] != recommendation_refs
        or manifest["pending_revision_candidate_versions"] != pending_revisions
        or manifest["local_reconciliation_ready"]
        is not reconciliation["local_reconciliation_ready"]
    ):
        raise Stage2Error("delivery-readiness-summary-mismatch")
    if (root / "selection.md").read_bytes() != _root_markdown(
        checker, selection, reconciliation
    ):
        raise Stage2Error("delivery-markdown-mismatch")
    expected_html = _root_html(checker, selection, reconciliation)
    if (root / "selection.html").read_bytes() != expected_html:
        raise Stage2Error("delivery-html-mismatch")
    return {
        "root": root,
        "manifest": manifest,
        "selection": selection,
        "reconciliation": reconciliation,
        "checker": checker,
        "input_packet": packet,
    }
