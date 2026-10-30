"""Trusted receiving of sealed direct-request Stage2 packages; never execute research."""

from copy import deepcopy
import hashlib
import io
import os
from pathlib import Path

from stage1_deliverable.common import (
    canonical,
    identifier,
    private_output,
    safe_path,
    sha,
)
from stage1_ledger.journal import decode
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.delivery import inspect_delivery
from stage2_workflow.store import inspect_workflow
from stage2_workflow.ui_submission import valid_input_version
from .project_intake_contract import MAX_PROJECTS, MAX_REQUEST
from .session_api import SessionApiError, _check, _hash

PREFIX = "registered_history/workflow/"
KIND = "Stage2DirectProjectContext"


def _verified(delivery_dir, manifest_sha256, request_sha256):
    _check(
        _hash(manifest_sha256) and _hash(request_sha256),
        "direct-import-external-pins-required",
        400,
    )
    root = private_output(Path(delivery_dir).absolute())
    try:
        delivery = inspect_delivery(root, manifest_sha256)
        manifest = delivery["manifest"]
        packet = decode(
            safe_path(root, "input_packet.json").read_bytes(), "direct Stage2 packet"
        )
        workflow = inspect_workflow(
            root / "registered_history" / "workflow", manifest["workflow_head_sha256"]
        )
        entry = packet.get("entry", {})
        _check(
            entry.get("kind") == "Stage2DirectRequestOrigin"
            and entry.get("stage1_lineage") is False
            and "upstream" not in packet,
            "direct-import-origin-required",
        )
        _check(
            entry.get("request_sha256") == request_sha256
            and sha(entry["request_text"].encode("utf-8")) == request_sha256
            and packet["brief"]["original_description"] == entry["request_text"],
            "direct-import-request-differs",
        )
        _check(
            workflow["manifest"]["manifest_sha256"]
            == manifest["workflow_manifest_sha256"]
            and workflow["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
            == manifest["snapshot_sha256"]
            and canonical_hash(workflow["latest_snapshot"]["packet"])
            == canonical_hash(packet),
            "direct-import-workflow-differs",
        )
        _check(
            not manifest["stage3_execution_authorized"],
            "direct-import-authority-invalid",
        )
    except (OSError, ValueError, KeyError, TypeError, Stage2Error) as error:
        raise SessionApiError("direct-import-source-invalid", 409) from error
    return root, delivery, packet


def _copy(path, reader, size, expected_hash, staging):
    """Resume verified private prefixes; final files are published only when complete."""
    staging.mkdir(parents=True, exist_ok=True)
    partial = safe_path(staging, sha(str(path).encode("utf-8")))
    committed = path.exists()
    retained = path if committed else partial
    count, digest = 0, hashlib.sha256()
    if retained.exists():
        with retained.open("rb") as saved:
            while chunk := saved.read(65536):
                count += len(chunk)
                _check(
                    count <= size and reader.read(len(chunk)) == chunk,
                    "direct-import-partial-bytes-differ",
                )
                digest.update(chunk)
    if not committed:
        with partial.open("ab" if partial.exists() else "xb") as writer:
            while chunk := reader.read(65536):
                count += len(chunk)
                _check(count <= size, "direct-import-copy-size-differs")
                _check(writer.write(chunk) == len(chunk), "direct-import-short-write")
                digest.update(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    _check(
        count == size and digest.hexdigest() == expected_hash and not reader.read(1),
        "direct-import-copy-bytes-differ",
    )
    if not committed:
        os.link(partial, path)


def _retained(path, content):
    with io.BytesIO(content) as reader:
        _copy(
            path,
            reader,
            len(content),
            sha(content),
            safe_path(path.parent, "receiving-staging"),
        )


def _history(source, manifest, target):
    """Copy only externally pinned files; retain bounded private recovery bytes."""
    target.mkdir(parents=True, exist_ok=True)
    for name in ("actions", "events", "snapshots"):
        safe_path(target, name).mkdir(exist_ok=True)
    rows = [row for row in manifest["files"] if row["path"].startswith(PREFIX)]
    _check(bool(rows), "direct-import-registered-history-required")
    staging = safe_path(target.parent, "receiving-staging")
    for row in rows:
        original = safe_path(source, row["path"])
        output = safe_path(target, row["path"][len(PREFIX) :])
        output.parent.mkdir(parents=True, exist_ok=True)
        with original.open("rb") as reader:
            _copy(output, reader, row["size"], row["sha256"], staging)


def _parts(origin, origin_hash):
    source = origin["source"]
    current = dict(
        project_id=origin["project_id"],
        input_version=origin["input_version"],
        brief_sha256=origin["brief_sha256"],
        plan_manifest_sha256=None,
        settings=deepcopy(origin["settings"]),
        imported_input_sha256=origin_hash,
        direct_request_input=True,
        receiving_only=True,
        execution_authorized=False,
    )
    offer = dict(
        current,
        offer_ref="stage2-direct-" + origin_hash[:32],
        settings_sha256=canonical_hash(current["settings"]),
        delivery_manifest_sha256=source["delivery_manifest_sha256"],
        request_sha256=source["request_sha256"],
    )
    offer["offer_sha256"] = canonical_hash(offer)
    activation = dict(
        kind="Stage2DirectDeliveryActivation",
        schema_version="1.0.0",
        artifact_ref="stage2-direct-" + origin_hash,
        offer_ref=offer["offer_ref"],
        offer_sha256=offer["offer_sha256"],
        packet_sha256=source["packet_sha256"],
        binding_sha256=origin_hash,
        workflow_manifest_sha256=source["workflow_manifest_sha256"],
        workflow_head_sha256=source["workflow_head_sha256"],
        input_origin="stage2-direct-request",
        stage1_lineage=False,
        receiving_only=True,
        execution_authorized=False,
    )
    return current, activation, offer


def import_direct_request_project(
    service,
    credential,
    *,
    delivery_dir,
    expected_manifest_sha256,
    expected_request_sha256,
    project_id,
    input_version,
    existing_only=False,
):
    """Trusted bootstrap only. Browser fields cannot choose paths or import results."""
    intake = service.intake
    principal = intake._principal(credential)
    identifier(project_id)
    _check(
        valid_input_version(input_version, allow_string=True),
        "direct-import-input-version-invalid",
        400,
    )
    source, delivery, packet = _verified(
        delivery_dir, expected_manifest_sha256, expected_request_sha256
    )
    manifest = delivery["manifest"]
    brief_raw = canonical(packet["brief"])
    _check(len(brief_raw) <= MAX_REQUEST, "direct-import-brief-too-large", 400)
    origin = dict(
        kind=KIND,
        schema_version="1.0.0",
        project_id=project_id,
        input_version=input_version,
        brief_sha256=sha(brief_raw),
        settings={"resource_envelope": packet["resources"]},
        source=dict(
            delivery_root=str(source),
            delivery_manifest_sha256=expected_manifest_sha256,
            request_sha256=expected_request_sha256,
            workflow_manifest_sha256=manifest["workflow_manifest_sha256"],
            workflow_head_sha256=manifest["workflow_head_sha256"],
            packet_sha256=canonical_hash(packet),
        ),
        stage1_lineage=False,
        receiving_only=True,
        execution_authorized=False,
    )
    origin_raw = canonical(origin)
    _check(len(origin_raw) <= MAX_REQUEST, "direct-import-context-too-large", 400)
    origin_hash = sha(origin_raw)
    ref = (
        "project-" + sha(canonical(dict(principal=principal, origin=origin_hash)))[:32]
    )
    current, activation, _ = _parts(origin, origin_hash)
    with intake._lock:
        intake.db.execute("BEGIN IMMEDIATE")
        try:
            exists = intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (ref,)
            ).fetchone()
            if exists is not None:
                _check(exists[0] == principal, "project-unavailable", 404)
                state = intake._load(principal, ref)
                _check(
                    state.get("stage2_direct_import", {}).get("sha256") == origin_hash,
                    "direct-import-origin-differs",
                )
                direct_binding(intake, state)
            else:
                _check(not existing_only, "direct-import-existing-project-required")
                count = intake.db.execute(
                    "SELECT COUNT(*) FROM intake_projects WHERE principal=?",
                    (principal,),
                ).fetchone()[0]
                _check(count < MAX_PROJECTS, "intake-project-bound-exceeded")
                folder = intake._path(ref, "import")
                folder.mkdir(parents=True, exist_ok=True)
                for name, raw in (
                    ("brief.json", brief_raw),
                    ("origin.json", origin_raw),
                ):
                    _retained(intake._path(ref, "import/" + name), raw)
                target = intake._path(ref, activation["artifact_ref"] + "/workflow")
                _history(source, manifest, target)
                inspect_workflow(target, manifest["workflow_head_sha256"])
                state = dict(
                    project_ref=ref,
                    project_id=project_id,
                    input_version=input_version,
                    revision=0,
                    briefs=[
                        dict(
                            input_version=input_version,
                            path="import/brief.json",
                            sha256=sha(brief_raw),
                            raw_utf8=brief_raw.decode("utf-8"),
                        )
                    ],
                    settings=current["settings"],
                    plan=None,
                    stage2_direct_import=dict(
                        path="import/origin.json", sha256=origin_hash
                    ),
                    stage2_activation=activation,
                )
                intake.db.execute(
                    "INSERT INTO intake_projects VALUES(?,?,?)",
                    (ref, principal, canonical(state).decode()),
                )
                intake._save(
                    state,
                    "stage2-direct-input-imported",
                    dict(
                        origin_sha256=origin_hash,
                        activation_sha256=canonical_hash(activation),
                    ),
                )
            intake.db.commit()
        except BaseException:
            intake.db.rollback()
            raise
        verified = direct_binding(intake, state)
        workflow_root = intake._path(ref, activation["artifact_ref"] + "/workflow")
        selection_binding = dict(
            input_version=input_version,
            brief_sha256=verified["brief_sha256"],
            workflow_root=str(workflow_root),
            delivery_root=str(source),
            delivery_manifest_sha256=expected_manifest_sha256,
        )
        return dict(
            project_ref=ref,
            selection_binding=selection_binding,
            stage1_lineage=False,
            execution_authorized=False,
        )


def direct_binding(intake, state):
    saved = state["stage2_direct_import"]
    path = intake._path(state["project_ref"], saved["path"])
    with path.open("rb") as stream:
        raw = stream.read(MAX_REQUEST + 1)
    _check(
        len(raw) <= MAX_REQUEST and sha(raw) == saved["sha256"],
        "direct-import-origin-bytes-differ",
    )
    origin = decode(raw, "direct project origin")
    _check(
        origin.get("kind") == KIND
        and origin.get("schema_version") == "1.0.0"
        and origin.get("stage1_lineage") is False
        and origin.get("receiving_only") is True
        and origin.get("execution_authorized") is False
        and "stage1_import" not in state,
        "direct-import-context-invalid",
    )
    _check(
        type(origin["input_version"]) is type(state["input_version"])
        and origin["input_version"] == state["input_version"]
        and origin["project_id"] == state["project_id"]
        and origin["settings"] == state["settings"]
        and state["plan"] is None,
        "direct-import-context-differs",
    )
    source = origin["source"]
    _, _, packet = _verified(
        source["delivery_root"],
        source["delivery_manifest_sha256"],
        source["request_sha256"],
    )
    row, _, brief = intake._brief(state)
    _check(
        row["sha256"] == origin["brief_sha256"] == canonical_hash(brief)
        and canonical_hash(brief) == canonical_hash(packet["brief"]),
        "direct-import-brief-differs",
    )
    current, activation, _ = _parts(origin, saved["sha256"])
    _check(
        state.get("stage2_activation") == activation, "direct-import-activation-differs"
    )
    events = [
        decode(row[0].encode("utf-8"), "direct import event")
        for row in intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage2-direct-input-imported'",
            (state["project_ref"],),
        )
    ]
    _check(
        events
        == [
            dict(
                origin_sha256=saved["sha256"],
                activation_sha256=canonical_hash(activation),
            )
        ],
        "direct-import-origin-journal-differs",
    )
    return current


def direct_context(service, project_ref, state):
    current = direct_binding(service.intake, state)
    saved = state["stage2_direct_import"]
    origin = decode(
        service.intake._path(project_ref, saved["path"]).read_bytes(), "direct origin"
    )
    _, activation, offer = _parts(origin, saved["sha256"])
    root = service.intake._path(project_ref, activation["artifact_ref"])
    return current, activation, offer, root


def direct_frontier(project_ref, current, offer, activation):
    return dict(
        kind="Stage2WorkflowFrontier",
        schema_version="1.1.0",
        project_ref=project_ref,
        project_id=current["project_id"],
        input_version=current["input_version"],
        brief_sha256=current["brief_sha256"],
        plan_manifest_sha256=None,
        offer_ref=offer["offer_ref"],
        offer_sha256=offer["offer_sha256"],
        settings_sha256=offer["settings_sha256"],
        activation_sha256=canonical_hash(activation),
        artifact_ref=activation["artifact_ref"],
        packet_sha256=activation["packet_sha256"],
        binding_sha256=activation["binding_sha256"],
        workflow_manifest_sha256=activation["workflow_manifest_sha256"],
        initial_workflow_head_sha256=activation["workflow_head_sha256"],
        workflow_head_sha256=activation["workflow_head_sha256"],
        sequence=0,
        input_origin="stage2-direct-request",
        stage1_lineage=False,
        delivery_manifest_sha256=offer["delivery_manifest_sha256"],
        request_sha256=offer["request_sha256"],
    )
