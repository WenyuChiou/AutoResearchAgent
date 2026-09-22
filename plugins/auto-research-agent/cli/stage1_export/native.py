"""Wrap supplied public codex exec JSONL; never read private session storage."""

from collections import Counter
from datetime import datetime
from pathlib import Path

from stage1_ledger.journal import LedgerError, canonical, contained, decode, digest
from .contracts import check


CONTRACT = "codex-exec-json-v1"
FILES = {"native/capture.json", "native/events.jsonl", "native_usage.json"}
TOOLS = {
    "command_execution",
    "mcp_tool_call",
    "web_search",
    "file_change",
    "collab_tool_call",
}
OTHER_ITEMS = {"agent_message", "reasoning", "todo_list", "error"}


def require(value, message):
    if not value:
        raise LedgerError("native-" + message)


def read_capture(root):
    data = {}
    for name in ["capture.json", "events.jsonl"]:
        path = contained(Path(root).resolve(), name)
        require(path.stat().st_size <= 16 * 1024 * 1024, "capture-too-large")
        data["native/" + name] = path.read_bytes()
        require(len(data["native/" + name]) <= 16 * 1024 * 1024, "capture-too-large")
    return data


def outcome(item):
    status = item.get("status")
    if status == "declined":
        return "declined"
    if status == "failed":
        return "failed"
    if item["type"] == "command_execution":
        code = item.get("exit_code")
        if type(code) is int:
            return (
                "succeeded"
                if code == 0 and status == "completed"
                else "failed"
                if code != 0
                else "unknown"
            )
    elif status == "completed":
        return "succeeded"
    return "unknown"


def summarize(data, run_id, state_hash, journal_hash):
    context = decode(data["native/capture.json"], "native capture")
    check(context)
    require(context["kind"] == "Stage1NativeCaptureSpec", "capture-kind")
    for key, expected in [
        ("source_run_id", run_id),
        ("source_state_sha256", state_hash),
        ("source_journal_sha256", journal_hash),
    ]:
        require(context[key] == expected, "source-binding:" + key)
    raw = data["native/events.jsonl"]
    require(digest(raw) == context["events_sha256"], "event-hash")
    start, end = [
        datetime.fromisoformat(context[key].replace("Z", "+00:00"))
        for key in ("started_at", "ended_at")
    ]
    require(
        start.utcoffset() is not None and end.utcoffset() is not None and end >= start,
        "time-bounds",
    )
    require(raw.endswith(b"\n"), "incomplete-jsonl-line")
    events = [
        decode(line, f"native line {i}") for i, line in enumerate(raw.splitlines(), 1)
    ]
    require(
        bool(events)
        and isinstance(events[0], dict)
        and events[0].get("type") == "thread.started",
        "thread-first",
    )
    require(
        events[0].get("thread_id") == context["expected_thread_id"], "thread-binding"
    )
    started, terminal, usage = False, None, None
    items, unknown_events, unknown_items, fatal = {}, set(), set(), []
    for line, event in enumerate(events, 1):
        require(
            isinstance(event, dict) and isinstance(event.get("type"), str),
            "event-shape",
        )
        kind = event["type"]
        if kind == "thread.started":
            require(line == 1, "multiple-threads")
        elif kind == "turn.started":
            require(not started and terminal is None, "multiple-turns")
            started = True
        elif kind in {"turn.completed", "turn.failed"}:
            require(started and terminal is None, "turn-order")
            terminal = kind
            if kind == "turn.completed":
                usage = event.get("usage")
                require(isinstance(usage, dict), "usage-shape")
                require(
                    {"input_tokens", "cached_input_tokens", "output_tokens"}
                    <= usage.keys(),
                    "usage-missing",
                )
                require(
                    all(type(v) is int and v >= 0 for v in usage.values()),
                    "usage-count",
                )
                require(
                    usage["cached_input_tokens"] <= usage["input_tokens"], "usage-cache"
                )
                require(
                    usage.get("reasoning_output_tokens", 0) <= usage["output_tokens"],
                    "usage-reasoning",
                )
        elif kind == "error":
            fatal.append(line)
        elif kind in {"item.started", "item.updated", "item.completed"}:
            require(started and terminal is None, "item-outside-turn")
            item = event.get("item")
            require(
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and bool(item["id"])
                and isinstance(item.get("type"), str),
                "item-shape",
            )
            previous = items.get(item["id"])
            require(
                previous is None
                or (
                    previous["type"] == item["type"]
                    and previous["end_line"] is None
                    and kind != "item.started"
                ),
                "item-order",
            )
            record = previous or dict(
                id=item["id"],
                type=item["type"],
                first_line=line,
                end_line=None,
                outcome="pending",
            )
            if kind == "item.completed":
                record.update(end_line=line, outcome=outcome(item))
            items[item["id"]] = record
            if item["type"] not in TOOLS | OTHER_ITEMS:
                unknown_items.add(item["type"])
        else:
            unknown_events.add(kind)
    tools = [v for v in items.values() if v["type"] in TOOLS]
    gaps = bool(
        unknown_events
        or unknown_items
        or any(v["end_line"] is None for v in items.values())
    )
    status = (
        "failed"
        if terminal == "turn.failed" or fatal
        else "complete"
        if terminal == "turn.completed" and context["exit_code"] == 0 and not gaps
        else "incomplete"
    )
    return dict(
        kind="Stage1NativeUsage",
        schema_version="1.0.0",
        format=CONTRACT,
        scope="captured-invocation",
        source_state_sha256=state_hash,
        runtime_version=context["runtime_version"],
        thread_id=context["expected_thread_id"],
        capture_status=status,
        elapsed_seconds=(end - start).total_seconds(),
        observed_tool_items=len(tools),
        tool_outcomes=dict(sorted(Counter(v["outcome"] for v in tools).items())),
        tool_items=tools,
        reported_turn_usage=usage,
        unknown_event_types=sorted(unknown_events),
        unknown_item_types=sorted(unknown_items),
        fatal_error_lines=fatal,
        terminal_event=terminal,
        exit_code=context["exit_code"],
        model_calls=None,
        human_interventions=None,
        retries=None,
        cost=None,
        limitation="Reported capture only; not authenticated or proven to cover the whole research run. Turns are not model calls; tokens are not billed cost.",
    )


def attach(data, efficiency, ledger, report):
    result = summarize(
        data,
        ledger.manifest["research_run"]["run_id"],
        report["state_sha256"],
        digest(data["source/stage_events.jsonl"]),
    )
    efficiency["native_capture"] = dict(
        path="native_usage.json", scope="captured-invocation"
    )
    check(result)
    return canonical(result) + b"\n"
