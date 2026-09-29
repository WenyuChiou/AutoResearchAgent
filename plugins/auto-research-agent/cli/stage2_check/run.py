"""Immutable run initialization, assessment application, and export."""

from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

from stage1_deliverable.common import DeliverableError, private_output
from stage2_common import Stage2Error, canonical_hash, validate_packet

from .contracts import decode_json, latest_candidates, validate_assessment
from .report import render_proposal


VERSION = "1.0.0"
ZERO_HASH = "0" * 64


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path, label=None):
    try:
        return decode_json(path.read_bytes(), label or str(path))
    except OSError as error:
        raise Stage2Error(f"read-failed: {path}: {error}") from error


def _write_new(path, value):
    data = value if isinstance(value, bytes) else _canonical_bytes(value)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise Stage2Error(f"exclusive-write-conflict: {path}") from error


def _write_projection(path, data):
    payload = data if isinstance(data, bytes) else _canonical_bytes(data)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _source_path(root, relative):
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or PurePosixPath(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise Stage2Error(f"unsafe-source-path: {relative!r}")
    path = root.joinpath(*relative.split("/"))
    if not path.resolve().is_relative_to(root.resolve()):
        raise Stage2Error(f"escaping-source-path: {relative}")
    return path


def _manifest_hash(manifest):
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    return canonical_hash(unsigned)


def _timestamp(value, label):
    try:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("timestamp must be UTC")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Stage2Error(f"invalid-timestamp: {label}") from error


def _validate_manifest(manifest):
    required = {
        "kind",
        "schema_version",
        "run_id",
        "created_at",
        "packet_path",
        "packet_sha256",
        "stored_packet_sha256",
        "source_snapshots",
        "stage_run",
        "manifest_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise Stage2Error("run-manifest-shape")
    if manifest["kind"] != "Stage2CheckRun" or manifest["schema_version"] != VERSION:
        raise Stage2Error("run-manifest-version")
    if manifest["packet_path"] != "packet.json":
        raise Stage2Error("run-manifest-packet-path")
    if manifest["manifest_sha256"] != _manifest_hash(manifest):
        raise Stage2Error("run-manifest-hash-mismatch")
    _timestamp(manifest["created_at"], "run manifest")
    stage = manifest["stage_run"]
    if (
        not isinstance(stage, dict)
        or stage.get("stage") != 2
        or stage.get("status") != "running"
    ):
        raise Stage2Error("run-manifest-stage")


def _validate_stage_input_refs(packet, manifest):
    refs = manifest["stage_run"]["input_refs"]
    if packet["schema_version"] == "1.0.0":
        if refs:
            raise Stage2Error("legacy-stage-run-input-refs-must-be-empty")
        return
    expected = [
        {
            "kind": "ArtifactRef",
            "schema_version": VERSION,
            "artifact_id": f"stage1-stage2-source-{manifest['packet_sha256'][:16]}",
            "artifact_type": "stage1-stage2-source-packet",
            "path": "input_packet.json",
            "sha256": manifest["packet_sha256"],
            "producer": "stage1-stage2-handoff",
            "created_at": manifest["created_at"],
        },
        {
            "kind": "ArtifactRef",
            "schema_version": VERSION,
            "artifact_id": f"stage1-stage2-stored-{manifest['stored_packet_sha256'][:16]}",
            "artifact_type": "stage1-stage2-stored-packet",
            "path": "packet.json",
            "sha256": manifest["stored_packet_sha256"],
            "producer": "stage1-stage2-handoff",
            "created_at": manifest["created_at"],
        },
    ]
    if refs != expected:
        raise Stage2Error("stage1-stage2-input-ref-binding-mismatch")


def _load_events(root):
    events_dir = root / "events"
    try:
        paths = sorted(events_dir.glob("*.json"))
    except OSError as error:
        raise Stage2Error(f"event-list-failed: {error}") from error
    events = []
    previous = ZERO_HASH
    previous_time = None
    event_ids = {}
    expected_names = []
    for sequence, path in enumerate(paths, 1):
        expected_names.append(f"{sequence:06d}.json")
        if path.name != expected_names[-1]:
            raise Stage2Error(f"event-sequence-gap: {path.name}")
        event = _read_json(path)
        required = {
            "kind",
            "schema_version",
            "sequence",
            "previous_sha256",
            "event_sha256",
            "event_id",
            "applied_at",
            "packet_sha256",
            "assessment_sha256",
            "reason",
            "evidence_ids",
            "assessment",
        }
        if not isinstance(event, dict) or set(event) != required:
            raise Stage2Error(f"event-shape: {path.name}")
        unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
        if (
            event["kind"] != "Stage2CheckEvent"
            or event["schema_version"] != VERSION
            or event["sequence"] != sequence
            or event["previous_sha256"] != previous
            or event["event_sha256"] != canonical_hash(unsigned)
            or event["assessment_sha256"] != canonical_hash(event["assessment"])
            or event["event_id"] != event["assessment"].get("event_id")
            or event["reason"] != event["assessment"].get("reason")
        ):
            raise Stage2Error(f"event-chain-invalid: {path.name}")
        expected_evidence = _assessment_evidence_ids(event["assessment"])
        if event["evidence_ids"] != expected_evidence:
            raise Stage2Error(f"event-evidence-summary-invalid: {path.name}")
        event_time = _timestamp(event["applied_at"], path.name)
        if previous_time is not None and event_time < previous_time:
            raise Stage2Error(f"event-time-regression: {path.name}")
        event_id = event["assessment"].get("event_id")
        if event_id in event_ids:
            raise Stage2Error(f"duplicate-event-id: {event_id}")
        event_ids[event_id] = event
        previous = event["event_sha256"]
        previous_time = event_time
        events.append(event)
    return events, event_ids


def _original_packet(packet, manifest, histories=None):
    restored = copy.deepcopy(packet)
    original_paths = {
        row["source_id"]: row["original_path"] for row in manifest["source_snapshots"]
    }
    if set(original_paths) != {row["source_id"] for row in restored["sources"]}:
        raise Stage2Error("source-snapshot-set-mismatch")
    for source in restored["sources"]:
        source["path"] = original_paths[source["source_id"]]
    if histories is not None:
        restored["candidates"] = [
            copy.deepcopy(candidate)
            for history in histories.values()
            for candidate in history
        ]
    return restored


def inspect_run(run_dir, *, expected_event_head=None):
    """Validate an initialized run and its complete immutable history."""

    root = Path(run_dir).absolute()
    manifest = _read_json(root / "run_manifest.json")
    _validate_manifest(manifest)
    packet_path = root / manifest["packet_path"]
    packet = _read_json(packet_path)
    if packet.get("schema_version") == "2.0.0":
        try:
            root = private_output(root)
        except DeliverableError as error:
            raise Stage2Error(f"stage2-private-output-invalid: {error}") from error
    else:
        root = root.resolve()
    if canonical_hash(packet) != manifest["stored_packet_sha256"]:
        raise Stage2Error("stored-packet-hash-mismatch")
    if packet.get("schema_version") == "2.0.0":
        input_packet_path = root / "input_packet.json"
        try:
            input_packet_bytes = input_packet_path.read_bytes()
        except OSError as error:
            raise Stage2Error(f"source-packet-read-failed: {error}") from error
        if hashlib.sha256(input_packet_bytes).hexdigest() != manifest["packet_sha256"]:
            raise Stage2Error("source-packet-byte-hash-mismatch")
        if canonical_hash(_read_json(input_packet_path)) != manifest["packet_sha256"]:
            raise Stage2Error("source-packet-canonical-hash-mismatch")
    validate_packet(packet, root)
    _validate_stage_input_refs(packet, manifest)
    actual_sources = {source["source_id"]: source for source in packet["sources"]}
    snapshot_ids = [row.get("source_id") for row in manifest["source_snapshots"]]
    if len(snapshot_ids) != len(set(snapshot_ids)) or set(snapshot_ids) != set(
        actual_sources
    ):
        raise Stage2Error("source-snapshot-set-mismatch")
    for snapshot in manifest["source_snapshots"]:
        source = actual_sources.get(snapshot.get("source_id"))
        if source is None or snapshot.get("stored_path") != source["path"]:
            raise Stage2Error("source-snapshot-binding-mismatch")
        path = _source_path(root, snapshot["stored_path"])
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise Stage2Error(
                f"source-snapshot-read-failed: {path}: {error}"
            ) from error
        if digest != source["sha256"] or digest != snapshot.get("sha256"):
            raise Stage2Error(
                f"source-snapshot-hash-mismatch: {snapshot['stored_path']}"
            )
    if canonical_hash(_original_packet(packet, manifest)) != manifest["packet_sha256"]:
        raise Stage2Error("original-packet-hash-mismatch")
    events, event_ids = _load_events(root)
    if events and _timestamp(events[0]["applied_at"], "first event") < _timestamp(
        manifest["created_at"], "run manifest"
    ):
        raise Stage2Error("event-time-regression: first event")
    event_head = events[-1]["event_sha256"] if events else ZERO_HASH
    if expected_event_head is not None and expected_event_head != event_head:
        raise Stage2Error("event-head-receipt-mismatch")
    if any(event["packet_sha256"] != manifest["packet_sha256"] for event in events):
        raise Stage2Error("event-packet-binding-mismatch")
    histories, latest = latest_candidates(packet, [])
    for event in events:
        assessment = event["assessment"]
        if assessment.get("packet_sha256") != manifest["packet_sha256"]:
            raise Stage2Error("assessment-packet-binding-mismatch")
        validate_assessment(assessment, packet, latest)
        revised = assessment.get("revised_candidate")
        if revised is not None:
            histories[revised["candidate_id"]].append(revised)
            latest[revised["candidate_id"]] = revised
    return {
        "root": root,
        "manifest": manifest,
        "packet": packet,
        "events": events,
        "event_ids": event_ids,
        "histories": histories,
        "latest": latest,
        "event_head_sha256": event_head,
    }


def initialize_run(
    packet_path,
    source_root,
    output_dir,
    expected_packet_sha256=None,
    *,
    clock=_utc_now,
):
    """Create or inspect an exclusive source-bound Stage 2 checker run."""

    packet_file = Path(packet_path).resolve()
    source_root = Path(source_root).resolve()
    source_packet = _read_json(packet_file)
    packet_sha256 = canonical_hash(source_packet)
    if source_packet.get("schema_version") == "2.0.0":
        if expected_packet_sha256 is None:
            raise Stage2Error("stage2-v2-expected-packet-sha256-required")
        if expected_packet_sha256 != packet_sha256:
            raise Stage2Error("stage2-v2-external-packet-hash-mismatch")
    elif expected_packet_sha256 is not None and expected_packet_sha256 != packet_sha256:
        raise Stage2Error("stage2-external-packet-hash-mismatch")
    try:
        output = (
            private_output(Path(output_dir).absolute())
            if source_packet.get("schema_version") == "2.0.0"
            else Path(output_dir).resolve()
        )
    except DeliverableError as error:
        raise Stage2Error(f"stage2-private-output-invalid: {error}") from error
    validate_packet(source_packet, source_root)
    if output.exists():
        state = inspect_run(output)
        if state["manifest"]["packet_sha256"] != packet_sha256:
            raise Stage2Error("existing-run-packet-mismatch")
        return state["manifest"]

    try:
        output.mkdir(parents=False)
    except FileExistsError:
        state = inspect_run(output)
        if state["manifest"]["packet_sha256"] != packet_sha256:
            raise Stage2Error("existing-run-packet-mismatch")
        return state["manifest"]
    except OSError as error:
        raise Stage2Error(f"run-directory-create-failed: {output}: {error}") from error

    try:
        (output / "events").mkdir()
        snapshots = []
        stored_packet = copy.deepcopy(source_packet)
        stored_sources = {row["source_id"]: row for row in stored_packet["sources"]}
        for source in source_packet["sources"]:
            relative = source["path"]
            stored_relative = f"sources/{relative}"
            original = _source_path(source_root, relative)
            destination = _source_path(output, stored_relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with original.open("rb") as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                    writer.flush()
                    os.fsync(writer.fileno())
            except OSError as error:
                raise Stage2Error(f"source-copy-failed: {relative}: {error}") from error
            snapshots.append(
                {
                    "source_id": source["source_id"],
                    "original_path": relative,
                    "stored_path": stored_relative,
                    "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
            )
            stored_sources[source["source_id"]]["path"] = stored_relative
        _write_new(output / "packet.json", _canonical_bytes(stored_packet))
        created_at = clock()
        input_refs = []
        if source_packet["schema_version"] == "2.0.0":
            _write_new(output / "input_packet.json", _canonical_bytes(source_packet))
            stored_packet_sha256 = canonical_hash(stored_packet)
            input_refs = [
                {
                    "kind": "ArtifactRef",
                    "schema_version": VERSION,
                    "artifact_id": f"stage1-stage2-source-{packet_sha256[:16]}",
                    "artifact_type": "stage1-stage2-source-packet",
                    "path": "input_packet.json",
                    "sha256": packet_sha256,
                    "producer": "stage1-stage2-handoff",
                    "created_at": created_at,
                },
                {
                    "kind": "ArtifactRef",
                    "schema_version": VERSION,
                    "artifact_id": f"stage1-stage2-stored-{stored_packet_sha256[:16]}",
                    "artifact_type": "stage1-stage2-stored-packet",
                    "path": "packet.json",
                    "sha256": stored_packet_sha256,
                    "producer": "stage1-stage2-handoff",
                    "created_at": created_at,
                },
            ]
        manifest = {
            "kind": "Stage2CheckRun",
            "schema_version": VERSION,
            "run_id": f"stage2-{packet_sha256[:16]}",
            "created_at": created_at,
            "packet_path": "packet.json",
            "packet_sha256": packet_sha256,
            "stored_packet_sha256": canonical_hash(stored_packet),
            "source_snapshots": snapshots,
            "stage_run": {
                "kind": "StageRun",
                "schema_version": VERSION,
                "stage_run_id": f"stage2-{packet_sha256[:16]}",
                "run_id": source_packet["packet_id"],
                "stage": 2,
                "phase": "gate",
                "status": "running",
                "attempt": 1,
                "started_at": created_at,
                "ended_at": None,
                "input_refs": input_refs,
            },
        }
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        _write_new(output / "run_manifest.json", manifest)
        inspect_run(output)
        return manifest
    except Exception:
        # Only this call's newly-created directory is removed; no pre-existing run is touched.
        shutil.rmtree(output)
        raise


@contextmanager
def _apply_lock(root):
    lock = root / ".apply-lock"
    try:
        _write_new(lock, _canonical_bytes({"pid": os.getpid()}))
    except Stage2Error as error:
        raise Stage2Error(
            "apply-locked: inspect the existing writer before retrying"
        ) from error
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def apply_assessment(run_dir, assessment_path, *, clock=_utc_now):
    """Validate and append one external assessment, idempotently by event ID."""

    root = Path(run_dir).resolve()
    assessment = _read_json(Path(assessment_path).resolve())
    with _apply_lock(root):
        state = inspect_run(root)
        if assessment.get("packet_sha256") != state["manifest"]["packet_sha256"]:
            raise Stage2Error("assessment-packet-hash-mismatch")
        assessment_sha256 = canonical_hash(assessment)
        existing = state["event_ids"].get(assessment.get("event_id"))
        if existing is not None:
            if existing["assessment_sha256"] != assessment_sha256:
                raise Stage2Error("event-id-content-conflict")
            return existing
        validate_assessment(assessment, state["packet"], state["latest"])
        revised = assessment.get("revised_candidate")
        if revised is not None:
            candidate_histories = copy.deepcopy(state["histories"])
            candidate_histories[revised["candidate_id"]].append(revised)
            revised_packet = copy.deepcopy(state["packet"])
            revised_packet["candidates"] = [
                candidate
                for history in candidate_histories.values()
                for candidate in history
            ]
            validate_packet(revised_packet, root)
        sequence = len(state["events"]) + 1
        applied_at = clock()
        applied_time = _timestamp(applied_at, "new event")
        previous_time = _timestamp(
            state["events"][-1]["applied_at"]
            if state["events"]
            else state["manifest"]["created_at"],
            "previous event",
        )
        if applied_time < previous_time:
            raise Stage2Error("event-time-regression: new event")
        event = {
            "kind": "Stage2CheckEvent",
            "schema_version": VERSION,
            "sequence": sequence,
            "previous_sha256": (
                state["events"][-1]["event_sha256"] if state["events"] else ZERO_HASH
            ),
            "event_id": assessment["event_id"],
            "applied_at": applied_at,
            "packet_sha256": state["manifest"]["packet_sha256"],
            "assessment_sha256": assessment_sha256,
            "reason": assessment["reason"],
            "evidence_ids": _assessment_evidence_ids(assessment),
            "assessment": assessment,
        }
        event["event_sha256"] = canonical_hash(event)
        _write_new(root / "events" / f"{sequence:06d}.json", event)
        inspect_run(root)
        return event


def _artifact(path, artifact_id, artifact_type, producer, created_at):
    return {
        "kind": "ArtifactRef",
        "schema_version": VERSION,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "path": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "producer": producer,
        "created_at": created_at,
    }


def _assessment_evidence_ids(assessment):
    evidence_ids = {
        evidence_id
        for finding in assessment.get("checks", {}).values()
        for evidence_id in finding.get("evidence_ids", [])
    }
    revised = assessment.get("revised_candidate")
    if revised is not None:
        evidence_ids.update(revised["evidence_ids"])
    return sorted(evidence_ids)


def _action_next_step(assessment):
    if assessment["next_step"]:
        return assessment["next_step"]
    if assessment["disposition"] == "recommend":
        return "Obtain human review before authorizing Stage 3."
    return (
        "Retain the rejection unless new source-bound evidence supports reassessment."
    )


def _evaluation_packet(state):
    return _original_packet(state["packet"], state["manifest"], state["histories"])


def _action_record_limitations(state, current_assessments):
    """Identify missing provenance without inventing an evaluator handoff."""
    limitations = []
    event_revisions = {
        (
            event["assessment"]["candidate_id"],
            event["assessment"]["revised_candidate"]["version"],
        )
        for event in state["events"]
        if event["assessment"].get("revised_candidate") is not None
    }
    for candidate_id, history in state["histories"].items():
        for candidate in history:
            if (
                candidate["version"] > 1
                and (candidate_id, candidate["version"]) not in event_revisions
            ):
                limitations.append(
                    f"{candidate_id} v{candidate['version']}: imported revision has no recorded reason/evidence event"
                )
        current = state["latest"][candidate_id]
        if (candidate_id, current["version"]) not in current_assessments:
            limitations.append(
                f"{candidate_id} v{current['version']}: pending assessment"
            )
    for event in state["events"]:
        if not _assessment_evidence_ids(event["assessment"]):
            limitations.append(
                f"{event['event_id']}: action has no source evidence for evaluator handoff"
            )
    return limitations


def _action_record(
    state,
    evaluation_packet,
    current_assessments,
    recommendations,
    blockers,
    pending_scope,
):
    latest_dispositions = []
    for candidate_id in sorted(state["latest"]):
        candidate = state["latest"][candidate_id]
        assessment = current_assessments.get((candidate_id, candidate["version"]))
        if assessment is None:
            return None
        latest_dispositions.append(
            {
                "candidate_id": candidate_id,
                "candidate_version": candidate["version"],
                "disposition": assessment["disposition"],
                "reason": assessment["reason"],
                "evidence_ids": _assessment_evidence_ids(assessment),
                "next_step": _action_next_step(assessment),
            }
        )
    history = [
        {
            "event_id": event["event_id"],
            "candidate_id": event["assessment"]["candidate_id"],
            "candidate_version": event["assessment"]["candidate_version"],
            "disposition": event["assessment"]["disposition"],
            "reason": event["reason"],
            "evidence_ids": event["evidence_ids"],
            "next_step": _action_next_step(event["assessment"]),
        }
        for event in state["events"]
    ]
    revision_history = [
        {
            "candidate_id": event["assessment"]["candidate_id"],
            "from_version": event["assessment"]["candidate_version"],
            "to_version": event["assessment"]["revised_candidate"]["version"],
            "reason": event["reason"],
            "evidence_ids": event["evidence_ids"],
        }
        for event in state["events"]
        if event["assessment"].get("revised_candidate") is not None
    ]
    selected_ids = [candidate["candidate_id"] for candidate in recommendations]
    if selected_ids:
        reasons = [
            row["reason"]
            for row in latest_dispositions
            if row["candidate_id"] in selected_ids
        ]
        choice_rationale = (
            "Selected source-bound sufficient-for-design option(s): "
            + " ".join(reasons)
        )
    elif blockers or pending_scope:
        choice_rationale = (
            "No candidate selected because blocking or pending scope items remain: "
            + "; ".join(blockers + pending_scope)
        )
    elif latest_dispositions:
        choice_rationale = (
            "No candidate selected after the recorded source-bound dispositions: "
            + " ".join(row["reason"] for row in latest_dispositions)
        )
    else:
        choice_rationale = "No candidate was supplied, so no selection was made."
    return {
        "kind": "Stage2ActionRecord",
        "schema_version": VERSION,
        "packet_sha256": canonical_hash(evaluation_packet),
        "history": history,
        "latest_dispositions": latest_dispositions,
        "selected_candidate_ids": selected_ids,
        "choice_rationale": choice_rationale,
        "revision_history": revision_history,
    }


def build_selection(state):
    """Reconstruct the selection from an already inspected checker state, without writes."""
    current_assessments = {}
    all_assessments = []
    for event in state["events"]:
        assessment = event["assessment"]
        key = (assessment["candidate_id"], assessment["candidate_version"])
        current_assessments[key] = assessment
        all_assessments.append(
            {
                "sequence": event["sequence"],
                "event_sha256": event["event_sha256"],
                "assessment": assessment,
            }
        )
    current_options = []
    recommendations = []
    parked = []
    rejected = []
    pending_scope = []
    blockers = []
    for candidate_id in sorted(state["latest"]):
        candidate = state["latest"][candidate_id]
        assessment = current_assessments.get((candidate_id, candidate["version"]))
        current_options.append({"candidate": candidate, "assessment": assessment})
        if assessment is None:
            blockers.append(
                f"{candidate_id} v{candidate['version']}: pending assessment"
            )
            continue
        disposition = assessment["disposition"]
        if assessment["scope_change_requested"]:
            pending_scope.append(
                f"{candidate_id} v{candidate['version']}: {assessment['next_step'] or assessment['reason']}"
            )
        if disposition == "recommend":
            recommendations.append(candidate)
        elif disposition == "park":
            parked.append(candidate)
        elif disposition == "reject":
            rejected.append(candidate)
        elif disposition == "revise":
            blockers.append(f"{candidate_id} v{candidate['version']}: revision pending")
        blockers.extend(
            f"{candidate_id} v{candidate['version']} {axis}: {finding['rationale']}"
            for axis, finding in assessment["checks"].items()
            if finding["blocking"] or finding["status"] == "unknown"
        )
    evaluation_packet = _evaluation_packet(state)
    action_limitations = _action_record_limitations(state, current_assessments)
    action_record = (
        None
        if action_limitations
        else _action_record(
            state,
            evaluation_packet,
            current_assessments,
            recommendations,
            blockers,
            pending_scope,
        )
    )

    selection = {
        "kind": "Stage2Selection",
        "schema_version": VERSION,
        "status": "prehuman",
        "packet_sha256": state["manifest"]["packet_sha256"],
        "evaluation_packet": evaluation_packet,
        "candidate_histories": state["histories"],
        "assessment_history": all_assessments,
        "current_options": current_options,
        "recommendations": recommendations,
        "parked_options": parked,
        "rejected_options": rejected,
        "blocking_items": blockers,
        "pending_scope_questions": pending_scope,
        "unresolved": state["packet"]["unresolved"],
        "action_record": action_record,
        "action_record_status": "complete"
        if action_record is not None
        else "unavailable",
        "action_record_blocking_items": action_limitations,
        "scientific_truth_validated": False,
        "stage3": {"status": "not-started", "execution_authorized": False},
    }
    return selection


def export_selection(run_dir, *, expected_event_head=None):
    """Rebuild deterministic JSON, Markdown, validator, and StageResult views."""

    state = inspect_run(run_dir, expected_event_head=expected_event_head)
    selection = build_selection(state)
    recommendations = selection["recommendations"]
    blockers = selection["blocking_items"]
    pending_scope = selection["pending_scope_questions"]
    root = state["root"]
    selection_path = root / "selection.json"
    markdown_path = root / "selection.md"
    _write_projection(selection_path, selection)
    _write_projection(
        markdown_path,
        render_proposal(
            selection,
            state["packet"]["sources"],
            event_head=state["event_head_sha256"],
            stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
        ),
    )

    timestamp = (
        state["events"][-1]["applied_at"]
        if state["events"]
        else state["manifest"]["created_at"]
    )
    report = {
        "kind": "Stage2CheckValidation",
        "schema_version": VERSION,
        "status": "passed",
        "packet_sha256": state["manifest"]["packet_sha256"],
        "history_head_sha256": (state["event_head_sha256"]),
        "event_count": len(state["events"]),
        "candidate_count": len(state["latest"]),
        "recommendation_count": len(recommendations),
        "blocking_count": len(blockers) + len(pending_scope),
        "meaning": "structural and source-binding validation only",
    }
    report_path = root / "validator_report.json"
    _write_projection(report_path, report)
    decisions = []
    previous_by_candidate = {}
    for event in state["events"]:
        assessment = event["assessment"]
        candidate_id = assessment["candidate_id"]
        previous = previous_by_candidate.get(candidate_id)
        event_path = root / "events" / f"{event['sequence']:06d}.json"
        evidence_ref = _artifact(
            event_path,
            event["event_id"],
            "stage2-assessment",
            "stage2-check",
            event["applied_at"],
        )
        evidence_ref["path"] = event_path.relative_to(root).as_posix()
        decision = {
            "kind": "DecisionEvent",
            "schema_version": VERSION,
            "event_id": event["event_id"],
            "run_id": state["manifest"]["stage_run"]["run_id"],
            "stage_run_id": state["manifest"]["stage_run"]["stage_run_id"],
            "sequence": event["sequence"],
            "created_at": event["applied_at"],
            "actor": "stage2-check",
            "actor_type": "system",
            "subject_id": candidate_id,
            "prior_decision": previous["new_decision"] if previous else None,
            "new_decision": assessment["disposition"],
            "reason_code": assessment["disposition"],
            "rationale": assessment["reason"],
            "evidence_refs": [evidence_ref],
            "reverses_event_id": previous["event_id"]
            if previous and previous["new_decision"] != assessment["disposition"]
            else None,
            "authorization": None,
        }
        decisions.append(decision)
        previous_by_candidate[candidate_id] = decision
    decisions_path = root / "decision_events.jsonl"
    _write_projection(
        decisions_path, b"".join(_canonical_bytes(row) + b"\n" for row in decisions)
    )
    output_refs = [
        _artifact(
            selection_path,
            "stage2-selection-json",
            "stage2-selection",
            "stage2-check",
            timestamp,
        ),
        _artifact(
            markdown_path,
            "stage2-selection-markdown",
            "stage2-selection-markdown",
            "stage2-check",
            timestamp,
        ),
        _artifact(
            decisions_path,
            "stage2-decisions",
            "decision-events",
            "stage2-check",
            timestamp,
        ),
    ]
    report_ref = _artifact(
        report_path,
        "stage2-validator-report",
        "validator-report",
        "stage2-check",
        timestamp,
    )
    reasons = (
        ["prehuman selection requires human review"]
        if not blockers and not pending_scope
        else ["blocking or pending scope items remain"]
    )
    stage_result = {
        "kind": "StageResult",
        "schema_version": VERSION,
        "stage_run_id": state["manifest"]["stage_run"]["stage_run_id"],
        "status": "human-review",
        "outputs": output_refs,
        "validator_report": report_ref,
        "metrics": {
            "candidate_count": len(state["latest"]),
            "recommendation_count": len(recommendations),
            "blocking_count": len(blockers) + len(pending_scope),
        },
        "gate": {
            "kind": "GateResult",
            "schema_version": VERSION,
            "gate_name": "stage2-prehuman-selection",
            "outcome": "review-required",
            "reasons": reasons,
            "blocking_items": blockers + pending_scope,
            "evidence_refs": output_refs,
        },
        "next_allowed_action": "human-review",
    }
    _write_projection(root / "stage_result.json", stage_result)
    return selection
