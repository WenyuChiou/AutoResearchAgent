"""Local append-only records for a Stage 2 workflow.

The hashes in this module detect local record edits when callers retain an
expected head.  They are not cryptographic attestation that an external action
executed as described.
"""

from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys

from stage2_check import initialize_run, inspect_run
from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash, source_set_hash


VERSION = "1.0.0"
ZERO_HASH = "0" * 64
TERMINAL_STATUSES = {"complete", "failed", "unavailable", "empty", "interrupted"}
EVENT_TYPES = {"snapshot_added", "action_started", "action_finished"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        data = path.read_bytes()
    except OSError as error:
        raise Stage2Error(f"workflow-read-failed: {path}: {error}") from error
    return decode_json(data, str(path))


def _write_new(path, value):
    """Atomically publish a new file without replacing an existing path."""

    data = value if isinstance(value, bytes) else _canonical_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise Stage2Error(f"workflow-exclusive-write-conflict: {path}") from error
        except OSError as error:
            raise Stage2Error(f"workflow-write-failed: {path}: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _safe_relative(value, label):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise Stage2Error(f"unsafe-{label}-path: {value!r}")
    return value


def _inside(root, relative, label, *, reject_symlinks=True):
    relative = _safe_relative(relative, label)
    path = root.joinpath(*relative.split("/"))
    resolved_root = root.resolve()
    if not path.resolve().is_relative_to(resolved_root):
        raise Stage2Error(f"escaping-{label}-path: {relative}")
    if reject_symlinks:
        current = resolved_root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                raise Stage2Error(f"symlink-{label}-path: {relative}")
    return path


def _manifest_hash(manifest):
    return canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def _event_hash(event):
    return canonical_hash(
        {key: value for key, value in event.items() if key != "event_sha256"}
    )


@contextmanager
def _exclusive_lock(root):
    lock = root / ".workflow-write.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise Stage2Error("workflow-write-lock-conflict") from error
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError as error:
            raise Stage2Error(f"workflow-lock-release-failed: {error}") from error


def _restore_packet(checker):
    packet = copy.deepcopy(checker["packet"])
    paths = {
        row["source_id"]: row["original_path"]
        for row in checker["manifest"]["source_snapshots"]
    }
    if set(paths) != {row["source_id"] for row in packet["sources"]}:
        raise Stage2Error("workflow-source-snapshot-set-mismatch")
    for source in packet["sources"]:
        source["path"] = paths[source["source_id"]]
    receipt_paths = {
        (row["candidate_id"], row["search_id"]): row["original_path"]
        for row in checker["manifest"].get("prior_work_receipts", [])
    }
    expected_receipts = {
        (review["candidate_id"], search["search_id"])
        for review in packet.get("prior_work_reviews", [])
        for search in review["searches"]
        if search["raw_path"] is not None
    }
    if set(receipt_paths) != expected_receipts:
        raise Stage2Error("workflow-prior-work-receipt-snapshot-set-mismatch")
    for review in packet.get("prior_work_reviews", []):
        for search in review["searches"]:
            key = (review["candidate_id"], search["search_id"])
            if search["raw_path"] is not None:
                if key not in receipt_paths:
                    raise Stage2Error("workflow-prior-work-receipt-snapshot-missing")
                search["raw_path"] = receipt_paths[key]
        review["source_set_sha256"] = source_set_hash(packet)
    return packet


def _source_versions(packet):
    return [
        {
            "source_id": row["source_id"],
            "work_id": row["work_id"],
            "version_id": row["version_id"],
            "sha256": row["sha256"],
        }
        for row in packet["sources"]
    ]


def _candidate_ids(packet):
    return sorted({row["candidate_id"] for row in packet["candidates"]})


def _validate_append_only(previous, current, *, parent_snapshot_sha256=None):
    if canonical_hash(previous["brief"]) != canonical_hash(current["brief"]):
        raise Stage2Error("workflow-brief-change-requires-explicit-decision")
    if canonical_hash(previous["resources"]) != canonical_hash(current["resources"]):
        raise Stage2Error("workflow-resources-change-requires-explicit-decision")
    if previous["schema_version"] != current["schema_version"]:
        raise Stage2Error("workflow-packet-version-change-requires-new-run")
    if previous["schema_version"] in {
        "2.0.0",
        "2.1.0",
        "2.2.0",
        "2.3.0",
        "2.4.0",
    } and canonical_hash(previous["upstream"]) != canonical_hash(current["upstream"]):
        raise Stage2Error("workflow-upstream-stage1-binding-rewritten")
    old_tables = previous.get("research_tables")
    tables = current.get("research_tables")
    if old_tables is not None and tables is None:
        raise Stage2Error("workflow-research-tables-cannot-be-discarded")
    if tables is not None and tables != old_tables:
        if tables["input_packet_sha256"] != canonical_hash(previous):
            raise Stage2Error("workflow-research-tables-parent-packet-mismatch")
        if (
            parent_snapshot_sha256 is not None
            and tables["input_snapshot_sha256"] != parent_snapshot_sha256
        ):
            raise Stage2Error("workflow-research-tables-parent-snapshot-mismatch")
    for field, keys in (
        ("literature", ("work_id", "version_id")),
        ("supplemental_literature", ("work_id", "version_id")),
        ("sources", ("source_id",)),
        ("evidence", ("evidence_id",)),
        ("candidates", ("candidate_id", "version")),
    ):
        if field not in previous:
            continue
        old_rows = {tuple(row[key] for key in keys): row for row in previous[field]}
        new_rows = {tuple(row[key] for key in keys): row for row in current[field]}
        for identity, row in old_rows.items():
            if new_rows.get(identity) != row:
                raise Stage2Error(f"workflow-{field}-history-rewritten: {identity}")


def _validate_impact(packet, impact):
    if isinstance(impact, dict):
        impact = [
            {"candidate_id": candidate_id, **copy.deepcopy(details)}
            if isinstance(details, dict)
            else details
            for candidate_id, details in impact.items()
        ]
    if not isinstance(impact, list):
        raise Stage2Error("workflow-impact-must-be-object")
    expected = set(_candidate_ids(packet))
    seen = set()
    normalized = []
    for row in impact:
        if not isinstance(row, dict) or set(row) != {
            "candidate_id",
            "status",
            "reason",
        }:
            raise Stage2Error("workflow-impact-row-shape")
        candidate_id = row["candidate_id"]
        if (
            candidate_id in seen
            or candidate_id not in expected
            or row["status"] not in {"affected", "unaffected", "unknown"}
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise Stage2Error(f"workflow-invalid-impact-row: {candidate_id!r}")
        seen.add(candidate_id)
        normalized.append(copy.deepcopy(row))
    if seen != expected:
        raise Stage2Error("workflow-impact-candidate-set-mismatch")
    return sorted(normalized, key=lambda row: row["candidate_id"])


def _load_events(root, manifest_sha256):
    events_dir = _inside(root, "events", "event")
    try:
        paths = sorted(events_dir.glob("*.json"))
    except OSError as error:
        raise Stage2Error(f"workflow-event-list-failed: {error}") from error
    events = []
    previous = ZERO_HASH
    for sequence, path in enumerate(paths, 1):
        if path.is_symlink() or path.name != f"{sequence:06d}.json":
            raise Stage2Error(f"workflow-event-sequence-invalid: {path.name}")
        event = _read_json(path)
        required = {
            "kind",
            "schema_version",
            "workflow_manifest_sha256",
            "sequence",
            "previous_sha256",
            "event_sha256",
            "recorded_at",
            "event_type",
            "payload",
        }
        if not isinstance(event, dict) or set(event) != required:
            raise Stage2Error(f"workflow-event-shape: {path.name}")
        if (
            event["kind"] != "Stage2WorkflowEvent"
            or event["schema_version"] != VERSION
            or event["workflow_manifest_sha256"] != manifest_sha256
            or event["event_type"] not in EVENT_TYPES
            or event["sequence"] != sequence
            or event["previous_sha256"] != previous
            or event["event_sha256"] != _event_hash(event)
        ):
            raise Stage2Error(f"workflow-event-chain-invalid: {path.name}")
        previous = event["event_sha256"]
        events.append(event)
    return events, previous


def _append_event(root, events, event_type, payload, *, clock):
    if event_type not in EVENT_TYPES:
        raise Stage2Error(f"workflow-unknown-event-type: {event_type!r}")
    manifest = _read_json(root / "workflow_manifest.json")
    event = {
        "kind": "Stage2WorkflowEvent",
        "schema_version": VERSION,
        "workflow_manifest_sha256": manifest.get("manifest_sha256"),
        "sequence": len(events) + 1,
        "previous_sha256": events[-1]["event_sha256"] if events else ZERO_HASH,
        "recorded_at": clock(),
        "event_type": event_type,
        "payload": payload,
    }
    event["event_sha256"] = _event_hash(event)
    path = root / "events" / f"{event['sequence']:06d}.json"
    _write_new(path, event)
    return event


def _snapshot_state(root, sequence):
    checker_root = _inside(root, f"snapshots/{sequence:06d}/checker", "snapshot")
    checker = inspect_run(checker_root)
    if checker["event_head_sha256"] != ZERO_HASH or checker["events"]:
        raise Stage2Error("workflow-snapshot-checker-history-not-immutable")
    return checker_root, checker, _restore_packet(checker)


def _runtime_identity(settings):
    module_path = Path(__file__).resolve()
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "store_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
        "executable": str(Path(sys.executable).resolve()),
        "declared_action_settings_sha256": canonical_hash(settings),
        "attests_model_bytes": False,
    }


def _request_identity(action_id, action_kind, inputs, settings, snapshot_event):
    request = {
        "action_id": action_id,
        "action_kind": action_kind,
        "inputs": copy.deepcopy(inputs),
        "inputs_sha256": canonical_hash(inputs),
        "settings": copy.deepcopy(settings),
        "settings_sha256": canonical_hash(settings),
        "snapshot_sequence": snapshot_event["payload"]["snapshot_sequence"],
        "snapshot_sha256": snapshot_event["payload"]["snapshot_sha256"],
        "runtime": _runtime_identity(settings),
    }
    request["request_sha256"] = canonical_hash(request)
    return request


def _same_request(existing, proposed):
    ignored = {"request_sha256", "started_at"}
    return {key: value for key, value in existing.items() if key not in ignored} == {
        key: value for key, value in proposed.items() if key not in ignored
    }


def _action_directory(root, action_id):
    _safe_relative(action_id, "action-id")
    if "/" in action_id:
        raise Stage2Error(f"unsafe-action-id-path: {action_id!r}")
    return _inside(root, f"actions/{action_id}", "action")


def _verify_result_artifacts(root, action_id, result):
    for name, row in result["artifacts"].items():
        _safe_relative(name, "artifact-name")
        path = _inside(root, row["stored_path"], "artifact")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise Stage2Error(
                f"workflow-artifact-read-failed: {name}: {error}"
            ) from error
        if actual != row["sha256"]:
            raise Stage2Error(f"workflow-artifact-hash-mismatch: {action_id}/{name}")


def _validate_cost(value, label="cost"):
    if value is None:
        return
    if isinstance(value, bool):
        raise Stage2Error(f"workflow-invalid-{label}-value")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            raise Stage2Error(f"workflow-invalid-{label}-value")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise Stage2Error(f"workflow-invalid-{label}-key")
            _validate_cost(item, f"{label}-{key}")
        return
    raise Stage2Error(f"workflow-invalid-{label}-value")


def _validate_terminal_result(status, artifacts, cost, error):
    if status not in TERMINAL_STATUSES or not isinstance(artifacts, dict):
        raise Stage2Error("workflow-invalid-action-result-shape")
    _validate_cost(cost)
    if status == "complete":
        if not artifacts or error is not None:
            raise Stage2Error("workflow-complete-requires-artifact-without-error")
    elif status in {"failed", "unavailable", "interrupted"}:
        if not isinstance(error, str) or not error.strip():
            raise Stage2Error(f"workflow-{status}-requires-error")
    elif artifacts or error is not None:
        raise Stage2Error("workflow-empty-must-have-no-artifacts-or-error")


def initialize_workflow(
    packet_path,
    source_root,
    output_dir,
    settings: dict,
    policy_ref: dict,
    expected_packet_sha256=None,
    *,
    clock=_now,
):
    """Create a workflow containing its first immutable checker snapshot."""

    if not isinstance(settings, dict) or not isinstance(policy_ref, dict):
        raise Stage2Error("workflow-settings-policy-must-be-objects")
    initial_packet = _read_json(Path(packet_path).resolve())
    initial_packet_sha256 = canonical_hash(initial_packet)
    if initial_packet.get("schema_version") in {
        "2.0.0",
        "2.1.0",
        "2.2.0",
        "2.3.0",
        "2.4.0",
    }:
        if expected_packet_sha256 is None:
            raise Stage2Error("stage2-v2-expected-packet-sha256-required")
        if expected_packet_sha256 != initial_packet_sha256:
            raise Stage2Error("stage2-v2-external-packet-hash-mismatch")
    elif (
        expected_packet_sha256 is not None
        and expected_packet_sha256 != initial_packet_sha256
    ):
        raise Stage2Error("stage2-external-packet-hash-mismatch")
    root = Path(output_dir).resolve()
    if root.exists():
        state = inspect_workflow(root)
        if (
            state["manifest"]["initial_packet_sha256"] != initial_packet_sha256
            or state["manifest"]["settings_sha256"] != canonical_hash(settings)
            or state["manifest"]["policy_ref_sha256"] != canonical_hash(policy_ref)
        ):
            raise Stage2Error("existing-workflow-input-mismatch")
        return state["manifest"]
    try:
        root.mkdir(parents=False)
    except FileExistsError:
        return initialize_workflow(
            packet_path,
            source_root,
            output_dir,
            settings,
            policy_ref,
            expected_packet_sha256,
            clock=clock,
        )
    try:
        (root / "events").mkdir()
        (root / "snapshots").mkdir()
        (root / "actions").mkdir()
        snapshot_dir = root / "snapshots" / "000001"
        snapshot_dir.mkdir()
        checker_manifest = initialize_run(
            packet_path,
            source_root,
            snapshot_dir / "checker",
            expected_packet_sha256,
            clock=clock,
        )
        checker = inspect_run(snapshot_dir / "checker")
        packet = _restore_packet(checker)
        created_at = clock()
        manifest = {
            "kind": "Stage2WorkflowRun",
            "schema_version": VERSION,
            "workflow_id": f"stage2-workflow-{canonical_hash(packet)[:16]}",
            "created_at": created_at,
            "initial_packet_sha256": canonical_hash(packet),
            "settings": copy.deepcopy(settings),
            "settings_sha256": canonical_hash(settings),
            "policy_ref": copy.deepcopy(policy_ref),
            "policy_ref_sha256": canonical_hash(policy_ref),
            "brief_sha256": canonical_hash(packet["brief"]),
            "resources_sha256": canonical_hash(packet["resources"]),
            "stage_run": copy.deepcopy(checker_manifest["stage_run"]),
        }
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        _write_new(root / "workflow_manifest.json", manifest)
        payload = {
            "snapshot_sequence": 1,
            "snapshot_sha256": checker_manifest["manifest_sha256"],
            "parent_snapshot_sha256": None,
            "original_packet_sha256": checker_manifest["packet_sha256"],
            "checker_manifest_sha256": checker_manifest["manifest_sha256"],
            "source_versions": _source_versions(packet),
            "reason": "initial workflow snapshot",
            "impact": [
                {
                    "candidate_id": candidate_id,
                    "status": "unknown",
                    "reason": "Initial snapshot requires an independent check.",
                }
                for candidate_id in _candidate_ids(packet)
            ],
            "pending_candidate_ids": _candidate_ids(packet),
        }
        _append_event(root, [], "snapshot_added", payload, clock=clock)
        inspect_workflow(root)
        return manifest
    except Exception:
        # The directory was created exclusively by this call.
        shutil.rmtree(root)
        raise


def inspect_workflow(run_dir, expected_head=None):
    """Validate the complete workflow and derive its current snapshot state."""

    root = Path(run_dir).resolve()
    manifest = _read_json(root / "workflow_manifest.json")
    required = {
        "kind",
        "schema_version",
        "workflow_id",
        "created_at",
        "initial_packet_sha256",
        "settings",
        "settings_sha256",
        "policy_ref",
        "policy_ref_sha256",
        "brief_sha256",
        "resources_sha256",
        "stage_run",
        "manifest_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise Stage2Error("workflow-manifest-shape")
    if manifest["kind"] != "Stage2WorkflowRun" or manifest["schema_version"] != VERSION:
        raise Stage2Error("workflow-manifest-version")
    if (
        manifest["manifest_sha256"] != _manifest_hash(manifest)
        or manifest["settings_sha256"] != canonical_hash(manifest["settings"])
        or manifest["policy_ref_sha256"] != canonical_hash(manifest["policy_ref"])
    ):
        raise Stage2Error("workflow-manifest-hash-mismatch")
    events, head = _load_events(root, manifest["manifest_sha256"])
    if expected_head is not None and expected_head != head:
        raise Stage2Error("workflow-head-receipt-mismatch")
    snapshot_events = [row for row in events if row["event_type"] == "snapshot_added"]
    if not snapshot_events:
        raise Stage2Error("workflow-missing-snapshot")
    snapshots_root = _inside(root, "snapshots", "snapshot")
    try:
        snapshot_entries = list(snapshots_root.iterdir())
    except OSError as error:
        raise Stage2Error(f"workflow-snapshot-list-failed: {error}") from error
    expected_snapshot_names = {
        f"{sequence:06d}" for sequence in range(1, len(snapshot_events) + 1)
    }
    if (
        any(path.is_symlink() or not path.is_dir() for path in snapshot_entries)
        or {path.name for path in snapshot_entries} != expected_snapshot_names
    ):
        raise Stage2Error("workflow-snapshot-directory-inventory-mismatch")
    previous_packet = None
    previous_snapshot_hash = None
    snapshots = []
    for sequence, event in enumerate(snapshot_events, 1):
        payload = event["payload"]
        if payload.get("snapshot_sequence") != sequence:
            raise Stage2Error("workflow-snapshot-sequence-invalid")
        _, checker, packet = _snapshot_state(root, sequence)
        if (
            payload.get("snapshot_sha256") != checker["manifest"]["manifest_sha256"]
            or payload.get("checker_manifest_sha256")
            != checker["manifest"]["manifest_sha256"]
            or payload.get("original_packet_sha256") != canonical_hash(packet)
            or payload.get("parent_snapshot_sha256") != previous_snapshot_hash
            or payload.get("source_versions") != _source_versions(packet)
            or payload.get("pending_candidate_ids") != _candidate_ids(packet)
        ):
            raise Stage2Error("workflow-snapshot-binding-mismatch")
        _validate_impact(packet, payload.get("impact"))
        if previous_packet is None:
            if canonical_hash(packet) != manifest["initial_packet_sha256"]:
                raise Stage2Error("workflow-initial-packet-hash-mismatch")
            if checker["manifest"]["stage_run"] != manifest["stage_run"]:
                raise Stage2Error("workflow-stage-run-binding-mismatch")
        else:
            _validate_append_only(
                previous_packet, packet, parent_snapshot_sha256=previous_snapshot_hash
            )
        if (
            canonical_hash(packet["brief"]) != manifest["brief_sha256"]
            or canonical_hash(packet["resources"]) != manifest["resources_sha256"]
        ):
            raise Stage2Error("workflow-brief-resource-binding-mismatch")
        snapshots.append({"event": event, "checker": checker, "packet": packet})
        previous_packet = packet
        previous_snapshot_hash = payload["snapshot_sha256"]

    action_events = {}
    active_snapshot = None
    for event in events:
        event_type = event["event_type"]
        if event_type == "snapshot_added":
            active_snapshot = (
                event["payload"]["snapshot_sequence"],
                event["payload"]["snapshot_sha256"],
            )
            continue
        if event_type not in {"action_started", "action_finished"}:
            raise Stage2Error(f"workflow-unknown-event-type: {event_type!r}")
        action_id = event["payload"].get("action_id")
        if not isinstance(action_id, str) or action_id in action_events.get(
            event_type, {}
        ):
            raise Stage2Error("workflow-action-event-invalid")
        if event_type == "action_started":
            request = event["payload"].get("request")
            request_fields = {
                "action_id",
                "action_kind",
                "inputs",
                "inputs_sha256",
                "settings",
                "settings_sha256",
                "snapshot_sequence",
                "snapshot_sha256",
                "runtime",
                "started_at",
                "request_sha256",
            }
            if (
                active_snapshot is None
                or not isinstance(request, dict)
                or set(request) != request_fields
                or request.get("action_id") != action_id
                or not isinstance(request.get("inputs"), dict)
                or not isinstance(request.get("settings"), dict)
                or (request.get("snapshot_sequence"), request.get("snapshot_sha256"))
                != active_snapshot
                or request.get("inputs_sha256") != canonical_hash(request.get("inputs"))
                or request.get("settings_sha256")
                != canonical_hash(request.get("settings"))
                or not isinstance(request.get("runtime"), dict)
                or request["runtime"].get("declared_action_settings_sha256")
                != request.get("settings_sha256")
                or request["runtime"].get("attests_model_bytes") is not False
            ):
                raise Stage2Error(
                    f"workflow-action-snapshot-input-binding-invalid: {action_id}"
                )
        elif action_id not in action_events.get("action_started", {}):
            raise Stage2Error(f"workflow-action-finish-before-start: {action_id}")
        action_events.setdefault(event_type, {})[action_id] = event
    actions = {}
    started = action_events.get("action_started", {})
    finished = action_events.get("action_finished", {})
    for action_id, event in started.items():
        action_dir = _action_directory(root, action_id)
        request = _read_json(action_dir / "request.json")
        if request != event["payload"]["request"] or request[
            "request_sha256"
        ] != canonical_hash(
            {key: value for key, value in request.items() if key != "request_sha256"}
        ):
            raise Stage2Error(f"workflow-action-request-mismatch: {action_id}")
        result = None
        if action_id not in finished and (
            (action_dir / "artifacts").exists() or (action_dir / "result.json").exists()
        ):
            raise Stage2Error(f"workflow-incomplete-finalization: {action_id}")
        if action_id in finished:
            result = _read_json(action_dir / "result.json")
            if result != finished[action_id]["payload"]["result"]:
                raise Stage2Error(f"workflow-action-result-mismatch: {action_id}")
            result_fields = {
                "action_id",
                "request_sha256",
                "status",
                "artifacts",
                "cost",
                "error",
                "finished_at",
                "result_sha256",
            }
            if (
                not isinstance(result, dict)
                or set(result) != result_fields
                or result.get("action_id") != action_id
                or result.get("status") not in TERMINAL_STATUSES
                or result.get("request_sha256") != request["request_sha256"]
                or result.get("result_sha256")
                != canonical_hash(
                    {
                        key: value
                        for key, value in result.items()
                        if key != "result_sha256"
                    }
                )
            ):
                raise Stage2Error(f"workflow-action-result-invalid: {action_id}")
            _validate_terminal_result(
                result["status"],
                result["artifacts"],
                result.get("cost"),
                result.get("error"),
            )
            _verify_result_artifacts(root, action_id, result)
        actions[action_id] = {"request": request, "result": result}
    if set(finished) - set(started):
        raise Stage2Error("workflow-finish-without-start")
    known_action_dirs = {
        path.name for path in (root / "actions").iterdir() if path.is_dir()
    }
    if known_action_dirs != set(started):
        raise Stage2Error("workflow-orphan-action-directory")
    latest = snapshots[-1]
    return {
        "root": root,
        "manifest": manifest,
        "events": events,
        "head_sha256": head,
        "snapshots": snapshots,
        "latest_snapshot": latest,
        "pending_candidate_ids": copy.deepcopy(
            latest["event"]["payload"]["pending_candidate_ids"]
        ),
        "actions": actions,
        "integrity_scope": "local edit detection with a retained expected head; not execution attestation",
    }


def add_snapshot(
    run_dir,
    packet_path,
    source_root,
    reason: str,
    impact: dict,
    expected_head: str,
    *,
    clock=_now,
):
    """Append an immutable checker snapshot after validating retained history."""

    if not isinstance(reason, str) or not reason.strip():
        raise Stage2Error("workflow-snapshot-reason-required")
    root = Path(run_dir).resolve()
    with _exclusive_lock(root):
        state = inspect_workflow(root, expected_head=expected_head)
        sequence = len(state["snapshots"]) + 1
        snapshot_dir = root / "snapshots" / f"{sequence:06d}"
        try:
            snapshot_dir.mkdir()
        except FileExistsError as error:
            raise Stage2Error("workflow-snapshot-directory-conflict") from error
        try:
            snapshot_packet = _read_json(Path(packet_path).resolve())
            checker_manifest = initialize_run(
                packet_path,
                source_root,
                snapshot_dir / "checker",
                canonical_hash(snapshot_packet),
                clock=clock,
            )
            checker = inspect_run(snapshot_dir / "checker")
            packet = _restore_packet(checker)
            _validate_append_only(
                state["latest_snapshot"]["packet"],
                packet,
                parent_snapshot_sha256=state["latest_snapshot"]["event"]["payload"][
                    "snapshot_sha256"
                ],
            )
            normalized_impact = _validate_impact(packet, impact)
            payload = {
                "snapshot_sequence": sequence,
                "snapshot_sha256": checker_manifest["manifest_sha256"],
                "parent_snapshot_sha256": state["latest_snapshot"]["event"]["payload"][
                    "snapshot_sha256"
                ],
                "original_packet_sha256": canonical_hash(packet),
                "checker_manifest_sha256": checker_manifest["manifest_sha256"],
                "source_versions": _source_versions(packet),
                "reason": reason,
                "impact": normalized_impact,
                "pending_candidate_ids": _candidate_ids(packet),
            }
            event = _append_event(
                root, state["events"], "snapshot_added", payload, clock=clock
            )
        except Exception:
            shutil.rmtree(snapshot_dir)
            raise
        inspect_workflow(root, expected_head=event["event_sha256"])
        return event


def start_action(
    run_dir,
    action_id,
    action_kind,
    inputs: dict,
    settings: dict,
    expected_head: str,
    *,
    clock=_now,
):
    """Record an action request without executing the external action."""

    if not isinstance(inputs, dict) or not isinstance(settings, dict):
        raise Stage2Error("workflow-action-inputs-settings-must-be-objects")
    if not isinstance(action_kind, str) or not action_kind.strip():
        raise Stage2Error("workflow-action-kind-required")
    root = Path(run_dir).resolve()
    with _exclusive_lock(root):
        state = inspect_workflow(root, expected_head=expected_head)
        request = _request_identity(
            action_id,
            action_kind,
            inputs,
            settings,
            state["latest_snapshot"]["event"],
        )
        existing = state["actions"].get(action_id)
        if existing is not None:
            if not _same_request(existing["request"], request):
                raise Stage2Error("workflow-action-id-input-conflict")
            result = existing["result"]
            if result is not None and result["status"] == "complete":
                _verify_result_artifacts(root, action_id, result)
                return {
                    "reuse": True,
                    "request": copy.deepcopy(existing["request"]),
                    "result": copy.deepcopy(result),
                }
            raise Stage2Error("workflow-action-replay-not-authorized")
        action_dir = _action_directory(root, action_id)
        try:
            action_dir.mkdir()
        except FileExistsError as error:
            raise Stage2Error("workflow-action-directory-conflict") from error
        try:
            request["started_at"] = clock()
            request["request_sha256"] = canonical_hash(
                {
                    key: value
                    for key, value in request.items()
                    if key != "request_sha256"
                }
            )
            _write_new(action_dir / "request.json", request)
            event = _append_event(
                root,
                state["events"],
                "action_started",
                {"action_id": action_id, "request": request},
                clock=clock,
            )
        except Exception:
            shutil.rmtree(action_dir)
            raise
        return {"reuse": False, "request": request, "event": event}


def finish_action(
    run_dir,
    action_id,
    status,
    artifacts: dict,
    cost: dict | None,
    error: str | None,
    expected_head: str,
    *,
    clock=_now,
):
    """Copy local artifacts into the run and append one terminal result."""

    if not isinstance(artifacts, dict) or (
        cost is not None and not isinstance(cost, dict)
    ):
        raise Stage2Error("workflow-invalid-action-result-shape")
    if error is not None and not isinstance(error, str):
        raise Stage2Error("workflow-invalid-action-error")
    _validate_terminal_result(status, artifacts, cost, error)
    root = Path(run_dir).resolve()
    with _exclusive_lock(root):
        state = inspect_workflow(root, expected_head=expected_head)
        action = state["actions"].get(action_id)
        if action is None:
            raise Stage2Error("workflow-action-not-started")
        if action["result"] is not None:
            raise Stage2Error("workflow-action-already-finished")
        action_dir = _action_directory(root, action_id)
        artifact_dir = action_dir / "artifacts"
        # Validate every input before publishing. Retain the checked bytes so a
        # source changing between validation and copying cannot change the result.
        prepared = []
        for name, spec in artifacts.items():
            relative = _safe_relative(name, "artifact-name")
            if not isinstance(spec, dict) or set(spec) != {"path", "sha256"}:
                raise Stage2Error(f"workflow-artifact-shape: {name}")
            if not isinstance(spec["path"], str):
                raise Stage2Error(f"workflow-artifact-path: {name}")
            source = Path(spec["path"])
            if source.is_symlink() or not source.is_file():
                raise Stage2Error(f"workflow-artifact-not-regular-file: {name}")
            raw = source.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            if actual != spec["sha256"]:
                raise Stage2Error(f"workflow-artifact-input-hash-mismatch: {name}")
            destination = _inside(
                root, f"actions/{action_id}/artifacts/{relative}", "artifact"
            )
            for _, previous, _, _ in prepared:
                if (
                    previous == destination
                    or previous in destination.parents
                    or destination in previous.parents
                ):
                    raise Stage2Error("workflow-artifact-path-conflict")
            prepared.append((name, destination, raw, actual))
        artifact_dir.mkdir()
        stored = {}
        try:
            for name, destination, raw, actual in prepared:
                destination.parent.mkdir(parents=True, exist_ok=True)
                _write_new(destination, raw)
                stored[name] = {
                    "stored_path": destination.relative_to(root).as_posix(),
                    "sha256": actual,
                    "size_bytes": len(raw),
                }
            result = {
                "action_id": action_id,
                "request_sha256": action["request"]["request_sha256"],
                "status": status,
                "artifacts": stored,
                "cost": copy.deepcopy(cost),
                "error": error,
                "finished_at": clock(),
            }
            result["result_sha256"] = canonical_hash(result)
            _write_new(action_dir / "result.json", result)
            event = _append_event(
                root,
                state["events"],
                "action_finished",
                {"action_id": action_id, "result": result},
                clock=clock,
            )
        except Exception:
            # Partial action data deliberately remains visible and blocks replay.
            raise
        inspect_workflow(root, expected_head=event["event_sha256"])
        return event
