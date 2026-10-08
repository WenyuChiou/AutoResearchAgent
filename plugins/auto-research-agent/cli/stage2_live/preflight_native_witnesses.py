"""Check capability semantics only after the caller authenticates trace/capture bytes.

This helper reads already archived probe files, never dispatches tools, and does
not by itself authenticate execution, prove role isolation, or grant readiness.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shlex

from .preflight import PreflightError, _capture_path, read_probe_command
from .preflight_trace_witnesses import project_tool_witness, _trace_events
from .trace_files import _ref


def _require(condition, reason):
    if not condition:
        raise PreflightError(reason)


def _arguments(invocation):
    payload = invocation.get("payload")
    _require(isinstance(payload, dict), "observed-invocation-payload-invalid")
    _require(payload.get("type") == "function", "observed-invocation-not-typed")
    try:
        args = json.loads(payload["arguments"])
    except (KeyError, TypeError, ValueError) as error:
        raise PreflightError("observed-invocation-arguments-invalid") from error
    _require(isinstance(args, dict), "observed-invocation-arguments-not-object")
    return args


def _same_shell(actual, executor):
    requested = executor["shell_path"]
    if actual == requested:
        return True
    # Aliases require execution-host identity and the pre-bound binary hash.
    # A different host must not resolve POSIX paths through its own filesystem.
    if os.name != "posix" or executor["family"] != "posix":
        return False
    try:
        return (
            os.path.samefile(actual, requested)
            and hashlib.sha256(Path(actual).read_bytes()).hexdigest()
            == executor["shell_sha256"]
        )
    except OSError:
        return False


def _exec_witness(witness, executor, raw):
    invocation = witness["invocation"]
    _require(
        invocation.get("tool_name") == "exec_command"
        and invocation.get("tool_namespace") in {None, "functions"},
        "observed-exec-tool-mismatch",
    )
    args = _arguments(invocation)
    _require(
        not set(args)
        - {"cmd", "workdir", "shell", "login", "yield_time_ms", "max_output_tokens"}
        and args.get("shell") == executor["shell_path"]
        and args.get("workdir") == executor["working_directory"]
        and args.get("login") is False
        and isinstance(args.get("cmd"), str),
        "observed-exec-arguments-mismatch",
    )
    start, end = witness["runtime_start"], witness["runtime_end"]
    _require(
        isinstance(start, dict) and isinstance(end, dict),
        "observed-exec-runtime-missing",
    )
    rows = {row["seq"]: row for row in _trace_events(raw)}
    refs = {ref["role"]: ref for ref in witness["evidence_refs"]}
    for role, runtime in (("runtime_start", start), ("runtime_end", end)):
        command = runtime.get("command")
        _require(
            isinstance(command, list)
            and len(command) == 3
            and command[1:] == ["-c", args["cmd"]]
            and isinstance(command[0], str)
            and _same_shell(command[0], executor)
            and runtime.get("cwd") == executor["working_directory"]
            and runtime.get("call_id") == witness["call_id"],
            "observed-exec-runtime-binding-mismatch",
        )
        row = rows.get(refs[role]["seq"], {})
        _require(
            isinstance(row.get("codex_turn_id"), str)
            and bool(row["codex_turn_id"])
            and runtime.get("turn_id") == row["codex_turn_id"],
            "observed-exec-runtime-turn-mismatch",
        )
    _require(
        start.get("process_id") is not None
        and start.get("process_id") == end.get("process_id")
        and start.get("turn_id") is not None
        and start.get("turn_id") == end.get("turn_id")
        and type(end.get("exit_code")) is int
        and end["exit_code"] == 0,
        "observed-exec-runtime-failed",
    )
    result = witness["result"]
    value = result.get("value") if result.get("type") == "code_mode_response" else None
    output = end.get("aggregated_output")
    _require(
        isinstance(value, dict)
        and type(value.get("exit_code")) is int
        and value["exit_code"] == 0
        and isinstance(output, str)
        and value.get("output") == output,
        "observed-exec-result-mismatch",
    )
    return args, output


def _check_child(raw, root_id, witness, probe_spec):
    child = probe_spec["probes"]["child"]["child_thread_id"]
    invocation, runtime = witness["invocation"], witness["runtime_end"]
    _require(
        invocation.get("tool_name") == "spawn_agent"
        and invocation.get("tool_namespace") == "collaboration"
        and isinstance(runtime, dict)
        and runtime.get("event_id") == witness["call_id"]
        and runtime.get("agent_thread_id") == child
        and runtime.get("kind") == "started",
        "observed-child-spawn-mismatch",
    )
    configured, results, ended = [], [], []
    for row in _trace_events(raw):
        payload = row["payload"]
        if (
            payload["type"] == "protocol_event_observed"
            and payload.get("event_type") == "session_configured"
        ):
            _, value, _ = _ref(payload, "event_payload", raw)
            _require(isinstance(value, dict), "observed-child-config-invalid")
            if value.get("thread_id") == child:
                configured.append((row, value))
        if (
            payload["type"] == "agent_result_observed"
            and payload.get("child_thread_id") == child
        ):
            _, value, _ = _ref(payload, "carried_payload", raw)
            _require(isinstance(value, dict), "observed-child-result-invalid")
            _require(
                payload.get("parent_thread_id") == root_id,
                "observed-child-parent-mismatch",
            )
            _require(
                isinstance(value.get("status"), dict)
                and isinstance(value["status"].get("completed"), str)
                and bool(value["status"]["completed"].strip())
                and payload.get("message") == value.get("message"),
                "observed-child-result-failed",
            )
            results.append(row)
        if payload["type"] == "thread_ended" and payload.get("thread_id") == child:
            _require(
                payload.get("status") == "completed", "observed-child-thread-failed"
            )
            ended.append(row)
    _require(
        len(configured) == len(results) == len(ended) == 1,
        "observed-child-lifecycle-incomplete",
    )
    config_row, config = configured[0]
    _require(
        config.get("parent_thread_id") == root_id
        and config.get("forked_from_id") == root_id
        and config.get("model") == probe_spec["expected"]["model"]
        and config.get("reasoning_effort") == probe_spec["expected"]["reasoning"]
        and witness["start_seq"]
        < config_row["seq"]
        < results[0]["seq"]
        < ended[0]["seq"],
        "observed-child-config-mismatch",
    )


def _check_witnesses(raw, thread_id, probe_spec, capture):
    """Check semantic proof only after the caller has authenticated all bytes."""
    probes, executor = probe_spec["probes"], probe_spec["executor"]
    witnesses = {
        name: project_tool_witness(raw, thread_id, probe["event_id"])
        for name, probe in probes.items()
    }
    read = probes["read"]
    source = _capture_path(
        capture, "archive/workspace-start/" + read["source_path"], "read source"
    )
    nonce = read["nonce"].encode()
    _require(
        source.is_file() and source.read_bytes().count(nonce) == 1,
        "observed-read-source-invalid",
    )
    _require(
        sum(
            p.read_bytes().count(nonce)
            for p in (capture / "archive/workspace-start").rglob("*")
            if p.is_file()
        )
        == 1,
        "observed-read-nonce-not-unique",
    )
    for relative in ("archive/prompt.bin", "archive/profile-config.toml"):
        path = _capture_path(capture, relative, "initial context")
        _require(
            not path.is_file() or nonce not in path.read_bytes(),
            "observed-read-nonce-disclosed",
        )
    initial_requests = 0
    for row in _trace_events(raw):
        if row["seq"] >= witnesses["read"]["start_seq"]:
            break
        payload = row["payload"]
        if payload["type"] == "inference_started" and row.get("thread_id") == thread_id:
            _, request, _ = _ref(payload, "request_payload", raw)
            initial_requests += 1
            _require(
                nonce not in json.dumps(request, ensure_ascii=False).encode(),
                "observed-read-nonce-disclosed",
            )
    _require(initial_requests > 0, "observed-read-initial-request-missing")
    args, output = _exec_witness(witnesses["read"], executor, raw)
    allowed = {read_probe_command(read["command_path"], "posix")}
    if re.fullmatch(r"/[A-Za-z0-9_./-]+", read["command_path"]):
        allowed.add("cat " + read["command_path"])
    _require(
        args["cmd"] in allowed and read["nonce"] not in args["cmd"],
        "observed-read-not-exact",
    )
    _require(read["nonce"] in output, "observed-read-output-missing")

    write = probes["write"]
    before = _capture_path(
        capture, "archive/workspace-start/" + write["output_path"], "write start"
    )
    after = _capture_path(
        capture, "archive/workspace-end/" + write["output_path"], "write end"
    )
    _require(not before.exists() and after.is_file(), "observed-write-not-new")
    _require(
        hashlib.sha256(after.read_bytes()).hexdigest() == write["sha256"],
        "observed-write-digest-mismatch",
    )
    args, _ = _exec_witness(witnesses["write"], executor, raw)
    path_type = (
        PurePosixPath
        if executor["working_directory"].startswith("/")
        else PureWindowsPath
    )
    target = str(path_type(executor["working_directory"]) / write["output_path"])
    try:
        text = after.read_bytes().decode("utf-8")
    except UnicodeError as error:
        raise PreflightError("observed-write-not-text-probe") from error
    _require(len(text) <= 1024 and "\x00" not in text, "observed-write-not-text-probe")
    writes = {
        f"printf %s {shlex.quote(text)} > {shlex.quote(target)}",
        f"printf '%s' {shlex.quote(text)} > {shlex.quote(target)}",
    }
    _require(args["cmd"] in writes, "observed-write-not-exact")

    search = witnesses["search"]
    invocation = search["invocation"]
    _require(
        invocation.get("tool_name") == "run"
        and invocation.get("tool_namespace") == "web",
        "observed-search-tool-mismatch",
    )
    queries = _arguments(invocation).get("search_query")
    _require(
        isinstance(queries, list)
        and bool(queries)
        and all(
            isinstance(q, dict) and isinstance(q.get("q"), str) and q["q"].strip()
            for q in queries
        ),
        "observed-search-query-invalid",
    )
    result = search["result"]
    text = result.get("value")
    _require(
        result.get("type") == "code_mode_response"
        and isinstance(text, str)
        and re.search(r"https?://[^\s<>]+", text)
        and re.search(r"(?:\ue202|\u3010)turn\d+(?:search|view|fetch)\d+", text)
        and not re.match(
            r"\s*(?:error\b|tool error\b|web search failed\b|rate limit\b)",
            text,
            re.IGNORECASE,
        ),
        "observed-search-result-empty-or-failed",
    )
    _check_child(raw, thread_id, witnesses["child"], probe_spec)
    return {
        name: {
            "status": "passed",
            "reason": "externally receipted typed native lifecycle verified",
            "event_id": value["call_id"],
            "evidence_refs": value["evidence_refs"],
        }
        for name, value in witnesses.items()
    }
