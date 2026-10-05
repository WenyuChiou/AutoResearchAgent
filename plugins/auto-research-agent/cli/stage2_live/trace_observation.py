"""Read-only inspection of receipt-bound native rollout telemetry."""

from .trace_compaction import CompactionState
from .trace_files import MAX_EVENTS, _fail, _require, _load_inventory, _json, _ref
from .trace_parsing import summarize_inferences


def inspect_native_trace(trace_dir, inventory_receipt, expected_receipt_sha256):
    """Inspect frozen raw telemetry; never create a receipt or readiness claim."""
    raw = _load_inventory(trace_dir, inventory_receipt, expected_receipt_sha256)
    manifest = _json(raw["manifest.json"], "manifest.json")
    required = {
        "schema_version",
        "trace_id",
        "rollout_id",
        "root_thread_id",
        "started_at_unix_ms",
        "raw_event_log",
        "payloads_dir",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or isinstance(manifest.get("schema_version"), bool)
        or manifest.get("schema_version") != 1
        or manifest.get("raw_event_log") != "trace.jsonl"
        or manifest.get("payloads_dir") != "payloads"
        or not all(
            isinstance(manifest.get(key), str) and manifest[key]
            for key in ("trace_id", "rollout_id", "root_thread_id")
        )
    ):
        _fail("manifest-invalid")
    lines = raw["trace.jsonl"].splitlines()
    _require(bool(lines) and len(lines) <= MAX_EVENTS, "event-count-limit")
    events = [
        _json(line, f"trace.jsonl:{number}") for number, line in enumerate(lines, 1)
    ]
    _require(
        all(isinstance(row, dict) for row in events)
        and all(
            isinstance(row.get("seq"), int) and not isinstance(row.get("seq"), bool)
            for row in events
        )
        and [row["seq"] for row in events] == list(range(1, len(events) + 1)),
        "sequence-invalid",
    )
    for row in events:
        if (
            isinstance(row.get("schema_version"), bool)
            or not isinstance(row.get("schema_version"), int)
            or row.get("schema_version") != 1
            or row.get("rollout_id") != manifest["rollout_id"]
            or not isinstance(row.get("payload"), dict)
            or not isinstance(row["payload"].get("type"), str)
            or "thread_id" not in row
            or "codex_turn_id" not in row
            or not (
                row["thread_id"] is None
                or isinstance(row["thread_id"], str)
                and bool(row["thread_id"])
            )
            or not (
                row["codex_turn_id"] is None
                or isinstance(row["codex_turn_id"], str)
                and bool(row["codex_turn_id"])
            )
        ):
            _fail("event-schema-invalid")
    if (
        events[0]["payload"]["type"] != "rollout_started"
        or sum(row["payload"]["type"] == "rollout_started" for row in events) != 1
        or events[0]["payload"].get("trace_id") != manifest["trace_id"]
        or events[0]["payload"].get("root_thread_id") != manifest["root_thread_id"]
    ):
        _fail("rollout-start-invalid")
    blockers, thread_starts, terminals, session_parents = [], {}, {}, {}
    inferences, responses, calls, edges, turns = {}, {}, {}, [], {}
    compactions = CompactionState()
    failures = failed_spawns = 0
    rollout_terminal = rollout_terminal_context = None

    def thread_ready_to_close(thread_id, turn_id):
        _require(isinstance(thread_id, str) and thread_id, "thread-terminal-invalid")
        scoped_turn = turns.get(turn_id) if isinstance(turn_id, str) else None
        scope_valid = turn_id is None or (
            scoped_turn is not None
            and scoped_turn["thread_id"] == thread_id
            and scoped_turn["terminal"] is not None
        )
        return (
            scope_valid
            and thread_id in thread_starts
            and all(
                item["terminal"] is not None
                for collection in (turns, inferences, calls)
                for item in collection.values()
                if item["thread_id"] == thread_id
            )
        )

    for row in events:
        payload, kind = row["payload"], row["payload"]["type"]
        if rollout_terminal is not None:
            repeated_rollout = (
                kind == "rollout_ended"
                and payload.get("status") == rollout_terminal
                and (row["thread_id"], row["codex_turn_id"]) == rollout_terminal_context
            )
            closing_thread = kind == "thread_ended" and thread_ready_to_close(
                payload.get("thread_id"), row["codex_turn_id"]
            )
            shutdown = False
            if (
                kind == "protocol_event_observed"
                and payload.get("event_type") == "shutdown_complete"
                and row["thread_id"] is None
                and row["codex_turn_id"] is None
            ):
                _, shutdown_payload, _ = _ref(payload, "event_payload", raw)
                shutdown = shutdown_payload == {"type": "shutdown_complete"}
            if not (repeated_rollout or closing_thread or shutdown):
                _fail("event-after-rollout-terminal")
        if row["thread_id"] is not None and row["thread_id"] not in thread_starts:
            _fail("thread-chronology-invalid")
        repeated_thread = (
            kind == "thread_ended"
            and payload.get("thread_id") == row["thread_id"]
            and payload.get("status") == terminals.get(row["thread_id"])
        )
        if row["thread_id"] in terminals and not repeated_thread:
            _fail("event-after-thread-terminal")
        compactions.observe(row, raw)
        if (
            kind == "protocol_event_observed"
            and payload.get("event_type") == "session_configured"
        ):
            _, configured, _ = _ref(payload, "event_payload", raw)
            _require(isinstance(configured, dict), "session-configured-invalid")
            configured_thread = configured.get("thread_id")
            _require(
                isinstance(configured_thread, str) and bool(configured_thread),
                "session-configured-thread-invalid",
            )
            if configured_thread not in thread_starts:
                _fail("session-configured-thread-invalid")
            parent = configured.get("parent_thread_id")
            _require(
                parent is None or isinstance(parent, str) and bool(parent),
                "session-parent-invalid",
            )
            if (
                configured_thread in session_parents
                and session_parents[configured_thread] != parent
            ):
                _fail("session-parent-mismatch")
            session_parents[configured_thread] = parent
        if kind == "thread_started":
            thread_id = payload.get("thread_id")
            _require(
                isinstance(thread_id, str) and thread_id not in thread_starts,
                "duplicate-thread-start",
            )
            name, metadata, digest = _ref(payload, "metadata_payload", raw)
            _require(isinstance(metadata, dict), "thread-metadata-invalid")
            _require(metadata.get("thread_id") == thread_id, "thread-metadata-mismatch")
            parent = metadata.get("parent_thread_id")
            _require(
                parent is None or isinstance(parent, str) and bool(parent),
                "thread-parent-invalid",
            )
            thread_starts[thread_id] = {
                "seq": row["seq"],
                "metadata_ref": name,
                "metadata_sha256": digest,
                "parent_thread_id": parent,
            }
        elif kind == "codex_turn_started":
            turn_id = payload.get("codex_turn_id")
            thread_id = payload.get("thread_id")
            if (
                not isinstance(turn_id, str)
                or turn_id in turns
                or thread_id != row["thread_id"]
                or turn_id != row["codex_turn_id"]
                or any(
                    value["thread_id"] == thread_id and value["terminal"] is None
                    for value in turns.values()
                )
            ):
                _fail("turn-start-invalid")
            turns[turn_id] = {
                "thread_id": thread_id,
                "seq": row["seq"],
                "terminal": None,
            }
        elif kind == "codex_turn_ended":
            turn_id = payload.get("codex_turn_id")
            item = turns.get(turn_id)
            if (
                item is None
                or item["terminal"] is not None
                or item["thread_id"] != row["thread_id"]
                or turn_id != row["codex_turn_id"]
            ):
                _fail("turn-terminal-invalid")
            item["terminal"] = payload.get("status")
            _require(
                isinstance(item["terminal"], str) and bool(item["terminal"]),
                "turn-terminal-invalid",
            )
            failures += item["terminal"] != "completed"
        elif kind == "thread_ended":
            thread_id, status = payload.get("thread_id"), payload.get("status")
            _require(
                isinstance(thread_id, str) and bool(thread_id),
                "thread-terminal-invalid",
            )
            _require(
                isinstance(status, str) and bool(status), "thread-terminal-invalid"
            )
            if thread_id not in thread_starts:
                _fail("foreign-thread-terminal")
            if row["thread_id"] is not None and row["thread_id"] != thread_id:
                _fail("thread-terminal-scope-mismatch")
            if thread_id in terminals and terminals[thread_id] != status:
                _fail("different-thread-terminal")
            first = thread_id not in terminals
            terminals[thread_id] = status
            failures += first and status != "completed"
        elif kind == "rollout_ended":
            status = payload.get("status")
            _require(
                isinstance(status, str) and bool(status), "rollout-terminal-invalid"
            )
            if rollout_terminal is not None and rollout_terminal != status:
                _fail("different-rollout-terminal")
            first = rollout_terminal is None
            rollout_terminal = status
            if first:
                rollout_terminal_context = (row["thread_id"], row["codex_turn_id"])
            failures += first and status != "completed"
        elif kind == "inference_started":
            call_id = payload.get("inference_call_id")
            _require(
                isinstance(call_id, str) and call_id not in inferences,
                "duplicate-inference-call-id",
            )
            turn = turns.get(row["codex_turn_id"])
            if (
                payload.get("thread_id") != row["thread_id"]
                or payload.get("codex_turn_id") != row["codex_turn_id"]
                or turn is None
                or turn["terminal"] is not None
                or turn["thread_id"] != row["thread_id"]
            ):
                _fail("inference-scope-mismatch")
            name, request, digest = _ref(payload, "request_payload", raw)
            _require(isinstance(request, dict), "inference-request-invalid")
            inferences[call_id] = {
                "seq": row["seq"],
                "thread_id": row["thread_id"],
                "codex_turn_id": row["codex_turn_id"],
                "request_ref": name,
                "request_sha256": digest,
                "request": request,
                "terminal": None,
                "completion_seq": None,
            }
        elif kind in {"inference_completed", "inference_failed", "inference_cancelled"}:
            call_id = payload.get("inference_call_id")
            item = inferences.get(call_id)
            turn = turns.get(row["codex_turn_id"])
            if (
                item is None
                or item["terminal"] is not None
                or item["thread_id"] != row["thread_id"]
                or item["codex_turn_id"] != row["codex_turn_id"]
                or turn is None
                or turn["terminal"] is not None
                or turn["thread_id"] != row["thread_id"]
            ):
                _fail("inference-chronology-invalid")
            item["terminal"] = kind
            item["completion_seq"] = row["seq"]
            if kind == "inference_completed":
                name, response, digest = _ref(payload, "response_payload", raw)
                _require(isinstance(response, dict), "inference-response-invalid")
                response_id = payload.get("response_id")
                if (
                    not isinstance(response_id, str)
                    or not response_id
                    or response.get("response_id") != response_id
                    or response_id in responses
                ):
                    _fail("response-id-invalid")
                item.update(
                    response_ref=name,
                    response_sha256=digest,
                    response=response,
                    response_id=response_id,
                )
                responses[response_id] = item
            else:
                failures += 1
        elif kind == "tool_call_started":
            call_id = payload.get("tool_call_id")
            _require(
                isinstance(call_id, str) and call_id not in calls,
                "duplicate-tool-call-id",
            )
            tool_kind = payload.get("kind")
            turn = turns.get(row["codex_turn_id"])
            if (
                not isinstance(tool_kind, dict)
                or not isinstance(tool_kind.get("type"), str)
                or turn is None
                or turn["terminal"] is not None
                or turn["thread_id"] != row["thread_id"]
            ):
                _fail("tool-call-scope-invalid")
            calls[call_id] = {
                "seq": row["seq"],
                "thread_id": row["thread_id"],
                "codex_turn_id": row["codex_turn_id"],
                "kind": tool_kind["type"],
                "terminal": None,
            }
        elif kind == "tool_call_ended":
            call_id, status = payload.get("tool_call_id"), payload.get("status")
            _require(isinstance(status, str) and bool(status), "tool-terminal-invalid")
            item = calls.get(call_id)
            turn = turns.get(row["codex_turn_id"])
            _require(
                item is not None
                and item["terminal"] is None
                and item["thread_id"] == row["thread_id"]
                and item["codex_turn_id"] == row["codex_turn_id"]
                and turn is not None
                and turn["terminal"] is None
                and turn["thread_id"] == row["thread_id"],
                "tool-call-chronology-invalid",
            )
            item["terminal"] = status
            failures += status != "completed"
            failed_spawns += item["kind"] == "spawn_agent" and status != "completed"
        elif kind in {"tool_call_runtime_started", "tool_call_runtime_ended"}:
            item = calls.get(payload.get("tool_call_id"))
            _require(
                item is not None
                and item["thread_id"] == row["thread_id"]
                and item["codex_turn_id"] == row["codex_turn_id"],
                "tool-runtime-chronology-invalid",
            )
            _, runtime, _ = _ref(payload, "runtime_payload", raw)
            _require(isinstance(runtime, dict), "tool-runtime-invalid")
            sender = runtime.get("sender_thread_id")
            if sender is not None and sender != item["thread_id"]:
                _fail("tool-runtime-sender-mismatch")
            child = runtime.get("agent_thread_id")
            if child is not None:
                _require(
                    isinstance(child, str) and bool(child),
                    "tool-runtime-child-invalid",
                )
                if item.get("child_thread_id") not in {None, child}:
                    _fail("tool-runtime-child-mismatch")
                item["child_thread_id"] = child
        elif kind == "agent_result_observed":
            edge = {
                "child_thread_id": payload.get("child_thread_id"),
                "parent_thread_id": payload.get("parent_thread_id"),
                "child_codex_turn_id": payload.get("child_codex_turn_id"),
            }
            if (
                not all(isinstance(value, str) and value for value in edge.values())
                or row["thread_id"] != edge["child_thread_id"]
                or row["codex_turn_id"] != edge["child_codex_turn_id"]
            ):
                _fail("agent-result-edge-invalid")
            edges.append(edge)
    root_id = manifest["root_thread_id"]
    if root_id not in thread_starts:
        blockers.append("root-thread-missing")
    for thread_id, item in thread_starts.items():
        if thread_id in session_parents:
            configured_parent = session_parents[thread_id]
            if item["parent_thread_id"] not in {None, configured_parent}:
                _fail("session-parent-mismatch")
            if item["parent_thread_id"] is None:
                item["parent_thread_id"] = configured_parent
        parent = item["parent_thread_id"]
        if parent is not None and (parent not in thread_starts or thread_id == root_id):
            _fail("foreign-child-thread")
        if thread_id != root_id and parent is None:
            blockers.append(f"thread-parent-missing:{thread_id}")
        if thread_id not in terminals:
            blockers.append(f"thread-terminal-missing:{thread_id}")
        elif terminals[thread_id] != "completed":
            blockers.append(f"thread-not-completed:{thread_id}")
    if root_id not in terminals:
        blockers.append("root-terminal-missing")
    if rollout_terminal is None:
        blockers.append("rollout-terminal-missing")
    elif rollout_terminal != "completed":
        blockers.append("rollout-not-completed")
    for thread_id in thread_starts:
        seen, current = set(), thread_id
        while current != root_id:
            if current in seen:
                _fail("thread-parent-cycle")
            seen.add(current)
            current = thread_starts[current]["parent_thread_id"]
            if current is None:
                break
            if current not in thread_starts:
                _fail("foreign-child-thread")
        if current is None and thread_id != root_id:
            blockers.append(f"thread-parent-chain-incomplete:{thread_id}")
    for turn_id, item in turns.items():
        if item["terminal"] is None:
            blockers.append(f"turn-terminal-missing:{turn_id}")
        elif item["terminal"] != "completed":
            blockers.append(f"turn-not-completed:{turn_id}")
    for edge in edges:
        child, parent = edge["child_thread_id"], edge["parent_thread_id"]
        if (
            child not in thread_starts
            or parent not in thread_starts
            or thread_starts[child]["parent_thread_id"] != parent
            or edge["child_codex_turn_id"] not in turns
            or turns[edge["child_codex_turn_id"]]["thread_id"] != child
        ):
            _fail("foreign-child-edge")
    for call_id, item in calls.items():
        if item["terminal"] is None:
            blockers.append(f"tool-call-terminal-missing:{call_id}")
        elif item["kind"] == "spawn_agent" and item["terminal"] == "completed":
            child = item.get("child_thread_id")
            if child not in thread_starts:
                blockers.append(f"spawn-child-missing:{call_id}")
            elif not any(
                edge["child_thread_id"] == child
                and edge["parent_thread_id"] == item["thread_id"]
                for edge in edges
            ):
                blockers.append(f"spawn-result-edge-missing:{call_id}")
    compaction_attempts = compactions.finalize(inferences)
    inference_rows, thread_tools, totals = summarize_inferences(
        inferences,
        responses,
        blockers,
        compaction_attempts,
        compactions.unverified,
    )
    return {
        "kind": "Stage2NativeTraceObservation",
        "schema_version": "1.0.0",
        "formal_ready": False,
        "trace_id": manifest["trace_id"],
        "rollout_id": manifest["rollout_id"],
        "root_thread_id": root_id,
        "receipt_sha256": expected_receipt_sha256,
        "raw_files": [
            {"path": name, "sha256": inventory_receipt[name]}
            for name in sorted(inventory_receipt)
        ],
        "inferences": inference_rows,
        "threads": [
            {
                "thread_id": thread_id,
                **item,
                "terminal_status": terminals.get(thread_id),
                "offered_tools": thread_tools.get(thread_id),
            }
            for thread_id, item in sorted(
                thread_starts.items(), key=lambda value: value[1]["seq"]
            )
        ],
        "thread_edges": edges,
        "token_usage_totals": totals,
        "counts": {
            "events": len(events),
            "inferences": len(inferences),
            "threads": len(thread_starts),
            "tool_calls": len(calls),
            "failed_tool_calls": sum(
                x["terminal"] not in {None, "completed"} for x in calls.values()
            ),
            "incomplete_tool_calls": sum(x["terminal"] is None for x in calls.values()),
            "incomplete_inferences": sum(
                x["terminal"] is None for x in inferences.values()
            ),
            "attempted_failed_spawns": failed_spawns,
            "compactions": len(compaction_attempts),
            "compaction_events": compactions.events,
            "failures": failures,
        },
        "blockers": sorted(set(blockers)),
    }
