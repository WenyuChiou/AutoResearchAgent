"""Project typed tool witnesses from already receipt-bound trace bytes.

This module does not authenticate a trace, execute a tool, or establish readiness.
The caller is responsible for passing the exact mapping returned by
``trace_files._load_inventory`` and for authenticating its trace root.
"""

import hashlib

from .trace_files import MAX_EVENTS, _fail, _json, _ref, _require


_TOOL_EVENTS = {
    "tool_call_started",
    "tool_call_runtime_started",
    "tool_call_runtime_ended",
    "tool_call_ended",
}


def _event_ref(role, event_type, row, payload, field, raw, expected_kind):
    name, value, digest = _ref(payload, field, raw)
    reference = payload[field]
    _require(reference["kind"]["type"] == expected_kind, f"{role}-reference-kind")
    _require(isinstance(value, dict) and bool(value), f"{role}-payload-invalid")
    event_id = row.get("event_id")
    _require(
        event_id is None or isinstance(event_id, str) and bool(event_id),
        f"{role}-event-id-invalid",
    )
    evidence = {
        "role": role,
        "event_type": event_type,
        "event_id": event_id,
        "seq": row["seq"],
        "raw_payload_id": reference["raw_payload_id"],
        "kind": reference["kind"],
        "path": name,
        "sha256": digest,
    }
    return value, evidence


def _trace_events(raw):
    _require(isinstance(raw, dict), "tool-witness-inventory-invalid")
    _require("trace.jsonl" in raw, "tool-witness-trace-missing")
    _require(
        all(
            isinstance(name, str) and isinstance(value, bytes)
            for name, value in raw.items()
        ),
        "tool-witness-inventory-invalid",
    )
    lines = raw["trace.jsonl"].splitlines()
    _require(bool(lines) and len(lines) <= MAX_EVENTS, "tool-witness-event-count")
    events = []
    previous = 0
    for number, line in enumerate(lines, 1):
        row = _json(line, f"trace.jsonl:{number}")
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("payload"), dict)
            or not isinstance(row["payload"].get("type"), str)
            or isinstance(row.get("seq"), bool)
            or not isinstance(row.get("seq"), int)
            or row["seq"] <= previous
        ):
            _fail("tool-witness-event-invalid")
        previous = row["seq"]
        events.append(row)
    return events


def project_tool_witness(raw, root_thread_id, call_id):
    """Return one completed root-thread tool lifecycle without executing it."""

    _require(
        isinstance(root_thread_id, str) and bool(root_thread_id),
        "tool-witness-root-thread-invalid",
    )
    _require(isinstance(call_id, str) and bool(call_id), "tool-witness-call-id-invalid")
    matched = []
    for row in _trace_events(raw):
        payload = row["payload"]
        if (
            payload.get("type") in _TOOL_EVENTS
            and payload.get("tool_call_id") == call_id
        ):
            _require(
                row.get("thread_id") == root_thread_id,
                "tool-witness-foreign-thread",
            )
            matched.append(row)

    by_type = {event_type: [] for event_type in _TOOL_EVENTS}
    for row in matched:
        by_type[row["payload"]["type"]].append(row)
    _require(
        len(by_type["tool_call_started"]) == 1,
        "tool-witness-start-count",
    )
    _require(len(by_type["tool_call_ended"]) == 1, "tool-witness-end-count")
    _require(
        len(by_type["tool_call_runtime_started"]) <= 1,
        "tool-witness-runtime-start-count",
    )
    _require(
        len(by_type["tool_call_runtime_ended"]) <= 1,
        "tool-witness-runtime-end-count",
    )

    start = by_type["tool_call_started"][0]
    end = by_type["tool_call_ended"][0]
    start_payload, end_payload = start["payload"], end["payload"]
    _require(end_payload.get("status") == "completed", "tool-witness-end-incomplete")
    tool_kind = start_payload.get("kind")
    _require(
        isinstance(tool_kind, dict)
        and isinstance(tool_kind.get("type"), str)
        and bool(tool_kind["type"]),
        "tool-witness-kind-invalid",
    )

    invocation, invocation_ref = _event_ref(
        "invocation",
        "tool_call_started",
        start,
        start_payload,
        "invocation_payload",
        raw,
        "tool_invocation",
    )
    result, result_ref = _event_ref(
        "result",
        "tool_call_ended",
        end,
        end_payload,
        "result_payload",
        raw,
        "tool_result",
    )

    runtime_start = runtime_end = None
    runtime_start_ref = runtime_end_ref = None
    started = by_type["tool_call_runtime_started"]
    ended = by_type["tool_call_runtime_ended"]
    _require(not started or ended, "tool-witness-runtime-end-missing")
    if started:
        runtime_start, runtime_start_ref = _event_ref(
            "runtime_start",
            "tool_call_runtime_started",
            started[0],
            started[0]["payload"],
            "runtime_payload",
            raw,
            "tool_runtime_event",
        )
    if ended:
        runtime_end_payload = ended[0]["payload"]
        _require(
            runtime_end_payload.get("status") == "completed",
            "tool-witness-runtime-end-incomplete",
        )
        runtime_end, runtime_end_ref = _event_ref(
            "runtime_end",
            "tool_call_runtime_ended",
            ended[0],
            runtime_end_payload,
            "runtime_payload",
            raw,
            "tool_runtime_event",
        )
        if "status" in runtime_end:
            _require(
                runtime_end["status"] == "completed",
                "tool-witness-runtime-payload-incomplete",
            )

    for label, value in (
        ("runtime-start", runtime_start),
        ("runtime-end", runtime_end),
    ):
        if value is not None and "call_id" in value:
            _require(value["call_id"] == call_id, f"tool-witness-{label}-call-id")
        if value is not None and "sender_thread_id" in value:
            _require(
                value["sender_thread_id"] == root_thread_id,
                f"tool-witness-{label}-sender-thread",
            )
        if (
            value is not None
            and tool_kind["type"] == "spawn_agent"
            and "event_id" in value
        ):
            _require(value["event_id"] == call_id, f"tool-witness-{label}-event-id")

    lifecycle = [start]
    if started:
        lifecycle.append(started[0])
    if ended:
        lifecycle.append(ended[0])
    lifecycle.append(end)
    _require(
        [row["seq"] for row in lifecycle] == sorted(row["seq"] for row in lifecycle)
        and len({row["seq"] for row in lifecycle}) == len(lifecycle),
        "tool-witness-chronology",
    )

    evidence_refs = [invocation_ref]
    if runtime_start_ref is not None:
        evidence_refs.append(runtime_start_ref)
    if runtime_end_ref is not None:
        evidence_refs.append(runtime_end_ref)
    evidence_refs.append(result_ref)
    _require(
        all(
            ref["sha256"] == hashlib.sha256(raw[ref["path"]]).hexdigest()
            for ref in evidence_refs
        ),
        "tool-witness-reference-hash",
    )
    return {
        "call_id": call_id,
        "thread_id": root_thread_id,
        "start_seq": start["seq"],
        "end_seq": end["seq"],
        "kind": tool_kind["type"],
        "invocation": invocation,
        "runtime_start": runtime_start,
        "runtime_end": runtime_end,
        "result": result,
        "evidence_refs": evidence_refs,
    }
