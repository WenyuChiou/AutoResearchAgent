"""Fail-closed functional preflight for an archived Stage 2 native capture.

``probe_spec`` is a host-frozen object outside the subject run with this shape::

    {
      "kind": "Stage2RuntimeProbeSpec", "schema_version": "1.0.0",
      "expected": {"model": str, "reasoning": str,
                   "sandbox": "workspace-write", "network_access": true},
      "probes": {
        "read": {"event_id": str, "source_path": relative-str, "nonce": str},
        "write": {"event_id": str, "output_path": relative-str,
                  "sha256": 64-lower-hex},
        "search": {"event_id": str},
        "child": {"event_id": str, "child_thread_id": str},
        "isolation": {"sentinels": {
          "judge": {"event_id": str, "path": str, "request_sha256": hex,
                    "receipt_path": relative-str, "receipt_sha256": hex,
                    "sentinel_sha256": hex, "nonce": str},
          "peer": {...}, "expected-outcomes": {...}}}}
    }

Event IDs name archived native calls/items, not subject-authored status fields.
The read nonce must occur only in the named workspace-start file; the write
digest binds a workspace-end file.  Search, child, and isolation checks require
archived call/output evidence.  Missing proof is reported as ``unknown`` and
blocks the gate; a proved denial/failure is reported as ``failed``.

The optional ``inventory_receipt`` is a frozen
``Stage2RuntimeInventoryReceipt``. Historical v1 receipts bind six RPC response
files, including tools/list. V2 binds the five RPCs supported by the current
CLI and represents tools separately: only a hash-bound native model-request
transport artifact can establish the complete offered-tool inventory. Missing
tool evidence remains unknown. Turn-context inventory fields are synthetic
compatibility evidence only and cannot open the runtime gate.

``Stage2ProductionRuntimeProbeSpec`` uses the same expected runtime, executor,
and read/write/search/child witnesses without isolation sentinels. Its missing
inventory evidence remains an explicit observation and cannot establish a
complete inventory or filesystem-read isolation.

Production probe v1.1 adds an absolute ``read.command_path``. It must name
exactly the frozen working directory plus the relative archived source_path;
archive containment and native command/output checks remain unchanged. Formal
isolation probes retain v1.0 and do not opt into this production-only contract.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from .codemode import (
    CodeModeWitnessError,
    _cwd_path,
    inspect_production_child,
    inspect_production_wrapper,
)
from .native import CaptureError, verify_capture
from .native_policy import NAMED_POLICY_KIND, NamedPolicyError, verify_named_runtime


class PreflightError(ValueError):
    """The probe contract or archived evidence is malformed or inconsistent."""


_HEX = re.compile(r"[0-9a-f]{64}")
_DENIED = re.compile(
    r"permission denied|access denied|sandbox.*den(?:y|ied)|not permitted|"
    r"operation not permitted|restricted",
    re.IGNORECASE,
)
_FAILED = re.compile(
    r"\berror\b|\bfailed\b|not found|no such file|timed? out",
    re.IGNORECASE,
)
_INVENTORY_KEYS = ("instructions", "skills", "plugins", "mcp", "tools", "settings")
_INVENTORY_V2_KEYS = ("instructions", "skills", "plugins", "mcp", "settings")
_INVENTORY_SOURCES = {
    "settings": "config/read",
    "instructions": "thread/start",
    "skills": "skills/list",
    "plugins": "plugin/list",
    "mcp": "mcpServerStatus/list",
    "tools": "tools/list",
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value):
    return _sha(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _relative_path(value, label):
    if not _nonempty_string(value):
        raise PreflightError(f"{label} must be a non-empty relative path")
    path = Path(value)
    windows = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows.root
        or windows.drive
        or ":" in value
        or ".." in path.parts
        or ".." in windows.parts
    ):
        raise PreflightError(f"{label} must be a contained relative path")
    return path


def _capture_path(capture, value, label):
    path = capture / _relative_path(value, label)
    for item in (path, *path.parents):
        if not item.is_relative_to(capture):
            break
        try:
            attributes = item.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise PreflightError(f"{label} cannot inspect capture ancestry") from error
        if item.is_symlink() or getattr(attributes, "st_file_attributes", 0) & 0x400:
            raise PreflightError(f"{label} contains a symlink or reparse ancestor")
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as error:
        raise PreflightError(f"{label} cannot resolve verified capture") from error
    if not resolved.is_relative_to(capture):
        raise PreflightError(f"{label} escapes the verified capture")
    return path


def _read_command_path(spec):
    """Bind a v1.1 absolute command to the same relative archived source."""
    read = spec["probes"]["read"]
    if spec["schema_version"] == "1.0.0":
        return read["source_path"]
    command = read["command_path"]
    if not _nonempty_string(command):
        raise PreflightError("read command_path must be a non-empty absolute path")
    path_type = (
        PureWindowsPath if spec["executor"]["family"] == "windows" else PurePosixPath
    )
    base = path_type(spec["executor"]["working_directory"])
    target = path_type(command)
    source = _relative_path(read["source_path"], "read source_path")
    if (
        not base.is_absolute()
        or not target.is_absolute()
        or ".." in target.parts
        or target != base.joinpath(*source.parts)
    ):
        raise PreflightError("read command_path is not the bound workspace source")
    return command


def _validate_probe_spec(spec):
    if not isinstance(spec, dict):
        raise PreflightError("probe_spec must be an object")
    kind = spec.get("kind")
    if (
        kind
        not in {
            "Stage2RuntimeProbeSpec",
            "Stage2ProductionRuntimeProbeSpec",
        }
        or spec.get("schema_version") not in {"1.0.0", "1.1.0"}
        or (
            spec.get("schema_version") == "1.1.0"
            and kind != "Stage2ProductionRuntimeProbeSpec"
        )
    ):
        raise PreflightError("probe_spec kind/schema_version mismatch")
    production = kind == "Stage2ProductionRuntimeProbeSpec"
    executor = spec.get("executor")
    if not isinstance(executor, dict) or set(executor) != {
        "shell_path",
        "shell_sha256",
        "working_directory",
        "family",
    }:
        raise PreflightError("probe executor binding missing")
    names = {
        "windows": {"powershell.exe", "pwsh.exe", "pwsh"},
        "posix": {"sh", "bash", "dash"},
    }
    if (
        executor["family"] not in names
        or not _HEX.fullmatch(str(executor["shell_sha256"]))
        or not _nonempty_string(executor["working_directory"])
        or not _nonempty_string(executor["shell_path"])
        or PureWindowsPath(executor["shell_path"]).name.lower()
        not in names[executor["family"]]
    ):
        raise PreflightError("unsupported probe executor")
    expected = spec.get("expected")
    if not isinstance(expected, dict) or set(expected) != {
        "model",
        "reasoning",
        "sandbox",
        "network_access",
    }:
        raise PreflightError("expected runtime fields are invalid")
    if not _nonempty_string(expected["model"]) or not _nonempty_string(
        expected["reasoning"]
    ):
        raise PreflightError("expected model and reasoning are required")
    if (
        expected["sandbox"] != "workspace-write"
        or expected["network_access"] is not True
    ):
        raise PreflightError(
            "probe_spec must require workspace-write and network access"
        )
    probes = spec.get("probes")
    required_probes = {"read", "write", "search", "child"}
    if not production:
        required_probes.add("isolation")
    if not isinstance(probes, dict) or set(probes) != required_probes:
        raise PreflightError("probe_spec requires exact capability probes")
    read = probes["read"]
    read_keys = {"event_id", "source_path", "nonce"}
    if spec["schema_version"] == "1.1.0":
        read_keys.add("command_path")
    if not isinstance(read, dict) or set(read) != read_keys:
        raise PreflightError("read probe fields are invalid")
    _relative_path(read["source_path"], "read source_path")
    _read_command_path(spec)
    if not _nonempty_string(read["event_id"]) or not _nonempty_string(read["nonce"]):
        raise PreflightError("read probe values are invalid")
    write = probes["write"]
    if not isinstance(write, dict) or set(write) != {
        "event_id",
        "output_path",
        "sha256",
    }:
        raise PreflightError("write probe fields are invalid")
    _relative_path(write["output_path"], "write output_path")
    if (
        not _nonempty_string(write["event_id"])
        or not isinstance(write["sha256"], str)
        or not _HEX.fullmatch(write["sha256"])
    ):
        raise PreflightError("write probe values are invalid")
    for name in ("search", "child"):
        probe = probes[name]
        required = {"event_id"} | ({"child_thread_id"} if name == "child" else set())
        if (
            not isinstance(probe, dict)
            or set(probe) != required
            or not all(_nonempty_string(probe[key]) for key in required)
        ):
            raise PreflightError(f"{name} probe fields are invalid")
    event_ids = []
    if not production:
        isolation = probes["isolation"]
        sentinels = isolation.get("sentinels") if isinstance(isolation, dict) else None
        if not isinstance(sentinels, dict) or set(sentinels) != {
            "judge",
            "peer",
            "expected-outcomes",
        }:
            raise PreflightError("isolation sentinel fields are invalid")
        for name, sentinel in sentinels.items():
            required = {
                "event_id",
                "path",
                "request_sha256",
                "receipt_path",
                "receipt_sha256",
                "sentinel_sha256",
                "nonce",
            }
            if (
                not isinstance(sentinel, dict)
                or set(sentinel) != required
                or not all(_nonempty_string(sentinel[key]) for key in required)
                or not all(
                    _HEX.fullmatch(sentinel[key])
                    for key in (
                        "request_sha256",
                        "receipt_sha256",
                        "sentinel_sha256",
                    )
                )
            ):
                raise PreflightError(f"isolation {name} fields are invalid")
            _relative_path(sentinel["receipt_path"], f"isolation {name} receipt_path")
            event_ids.append(sentinel["event_id"])
    all_ids = [
        probes[name]["event_id"] for name in ("read", "write", "search", "child")
    ]
    all_ids.extend(event_ids)
    if len(all_ids) != len(set(all_ids)):
        raise PreflightError("probe event IDs must be unique")
    return production


def require_matching_preflight_contract(report, probe_spec):
    """Reject a report whose validation scope does not match its probe kind."""
    if not isinstance(report, dict) or not isinstance(probe_spec, dict):
        raise PreflightError("preflight report/probe contract mismatch")
    production = probe_spec.get("kind") == "Stage2ProductionRuntimeProbeSpec"
    if production:
        matches = (
            report.get("kind") == "Stage2ProductionRuntimePreflight"
            and report.get("validation_scope") == "production-single"
            and report.get("filesystem_read_isolation") == "not-assessed"
            and report.get("quality_improvement") == "not-established"
            and report.get("formal_ready") is False
        )
    else:
        matches = (
            probe_spec.get("kind") == "Stage2RuntimeProbeSpec"
            and report.get("kind") == "Stage2RuntimePreflight"
            and "validation_scope" not in report
        )
    if not matches:
        raise PreflightError("preflight report/probe contract mismatch")


def _load_jsonl(path):
    events = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("event is not an object")
            events.append(value)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise PreflightError(
            f"malformed native session JSONL: {path}:{number}"
        ) from error
    return events


def _payload(event):
    value = event.get("payload")
    return value if isinstance(value, dict) else event


def _session_id(events):
    identities = []
    for event in events:
        payload = _payload(event)
        if event.get("type") == "session_meta" or payload.get("type") == "session_meta":
            identity = payload.get("id") or payload.get("thread_id")
            if identity is not None:
                identities.append(identity)
    if len(set(identities)) > 1:
        raise PreflightError("one archived session declares conflicting identities")
    return identities[0] if identities else None


def _session_identity(events, production):
    """Select native child metadata only for the production archive shape."""
    if not production:
        return _session_id(events)
    children = []
    for event in events:
        payload = _payload(event)
        source = payload.get("source")
        subagent = source.get("subagent") if isinstance(source, dict) else None
        if subagent is not None and not isinstance(subagent, dict):
            raise PreflightError("native subagent metadata must be an object")
        spawn = subagent.get("thread_spawn") if subagent is not None else None
        if event.get("type") == "session_meta" and isinstance(spawn, dict):
            identity = payload.get("id")
            if _nonempty_string(identity):
                children.append(identity)
    if len(set(children)) > 1:
        raise PreflightError(
            "one archived child session declares conflicting identities"
        )
    return children[0] if children else _session_id(events)


def _turn_context(events):
    contexts = []
    for event in events:
        payload = _payload(event)
        if event.get("type") == "turn_context" or payload.get("type") == "turn_context":
            context = (
                event.get("payload") if event.get("type") == "turn_context" else payload
            )
            if not isinstance(context, dict):
                raise PreflightError("turn_context payload must be an object")
            contexts.append(context)
    if len(contexts) > 1:
        raise PreflightError("ambiguous primary turn_context")
    return contexts[0] if contexts else None


def _text(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _decode_json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _event_index(events):
    calls = {}
    outputs = {}
    items = {}
    for event in events:
        if event.get("type") == "item.completed" and isinstance(
            event.get("item"), dict
        ):
            item = event["item"]
            identity = item.get("id") or item.get("call_id")
            if _nonempty_string(identity):
                if identity in items or identity in calls:
                    raise PreflightError(f"duplicate archived event ID: {identity}")
                items[identity] = item
            continue
        payload = _payload(event)
        kind = payload.get("type")
        identity = payload.get("call_id") or payload.get("id")
        if kind in {"function_call", "custom_tool_call"} and _nonempty_string(identity):
            if identity in calls or identity in items:
                raise PreflightError(f"duplicate archived event ID: {identity}")
            calls[identity] = payload
        elif kind in {
            "function_call_output",
            "custom_tool_call_output",
        } and _nonempty_string(identity):
            if identity in outputs:
                raise PreflightError(f"duplicate archived output ID: {identity}")
            outputs[identity] = payload
    return calls, outputs, items


def _named_event(identity, indexes):
    calls, outputs, items = indexes
    if identity in items:
        return {"item": items[identity], "call": None, "output": None}
    if identity in calls:
        return {"item": None, "call": calls[identity], "output": outputs.get(identity)}
    return None


def _named_event_any(identity, *indexes):
    for index in indexes:
        entry = _named_event(identity, index)
        if entry is not None:
            return entry
    return None


def _event_kind(entry):
    value = entry["item"] or entry["call"]
    wrapper = value.get("type")
    if wrapper in {"function_call", "custom_tool_call"}:
        return str(value.get("name") or value.get("tool") or wrapper).lower()
    return str(wrapper or value.get("name") or value.get("tool") or "").lower()


def _event_request(entry):
    value = entry["item"] or entry["call"]
    return _text(
        value.get("command")
        or value.get("arguments")
        or value.get("input")
        or value.get("query")
        or ""
    )


def _event_output(entry):
    value = entry["item"] or entry.get("output") or {}
    for key in ("output", "aggregated_output", "result", "results", "content", "text"):
        if key in value:
            return _text(value[key])
    return ""


def _event_failed(entry):
    value = entry["item"] or entry.get("output") or {}
    status = str(value.get("status", "")).lower()
    exit_code = value.get("exit_code")
    output = _event_output(entry)
    return (
        status in {"failed", "error", "cancelled"}
        or (
            isinstance(exit_code, int)
            and not isinstance(exit_code, bool)
            and exit_code != 0
        )
        or bool(_FAILED.search(output))
    )


def _proved_policy_rejection(entry):
    value = entry["item"] or entry.get("output") or {}
    status = str(value.get("status", "")).lower()
    exit_code = value.get("exit_code")
    output = _event_output(entry)
    failed = status in {"failed", "error", "rejected"} or (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
    )
    if (
        failed
        and _DENIED.search(output)
        and not re.search(r"not found|no such file", output, re.IGNORECASE)
    ):
        return True
    return False


def read_probe_command(path, platform="windows"):
    """Generate an exact, literal read operation; never accept subject shell code."""
    if not _nonempty_string(path) or any(c in path for c in "\r\n\x00"):
        raise PreflightError("invalid probe path")
    if platform == "windows":
        return (
            "Get-Content -LiteralPath '"
            + path.replace("'", "''")
            + "' -Raw -Encoding UTF8"
        )
    if platform == "posix":
        return "/bin/cat -- '" + path.replace("'", "'\"'\"'") + "'"
    raise PreflightError("unsupported probe platform")


def _allowed_read_commands(path, platform):
    """Retain exact historical reads while using a cmdlet in constrained shells."""
    commands = {read_probe_command(path, platform)}
    if platform == "windows":
        commands.add("[System.IO.File]::ReadAllText('" + path.replace("'", "''") + "')")
    return commands


def _is_exact_read(entry, path, executor):
    """Text printed by arbitrary code is not proof of a read or policy denial."""
    if _event_kind(entry) not in {
        "command_execution",
        "exec_command",
        "functions.exec_command",
    }:
        return False
    request = _event_request(entry)
    decoded = _decode_json(request)
    if isinstance(decoded, dict):
        if set(decoded) - {
            "cmd",
            "workdir",
            "shell",
            "login",
            "yield_time_ms",
            "max_output_tokens",
        }:
            return False
        if (
            _cwd_path(decoded.get("shell")) != _cwd_path(executor["shell_path"])
            or _cwd_path(decoded.get("workdir"))
            != _cwd_path(executor["working_directory"])
            or decoded.get("login") is not False
        ):
            return False
        command = decoded.get("cmd")
    else:
        return False
    return command in _allowed_read_commands(path, executor["family"])


def _check_nonce_inputs(capture, events, read_probe, read_entry):
    """Reject a read answer disclosed before the read, including injected context."""
    nonce = read_probe["nonce"]
    inputs = ["archive/prompt.bin", "archive/profile-config.toml"]
    for category in ("input_bindings", "config_bindings"):
        root = capture / "archive" / category
        if root.exists():
            inputs.extend(
                p.relative_to(capture).as_posix()
                for p in root.rglob("*")
                if p.is_file()
            )
    for relative in inputs:
        path = _capture_path(capture, relative, "probe input")
        if path.is_file() and nonce.encode() in path.read_bytes():
            raise PreflightError("read nonce exposed in archived input")
    if read_entry is not None and nonce in _event_request(read_entry):
        raise PreflightError("read nonce exposed in read request")
    for event in events:
        payload = _payload(event)
        if payload.get("call_id", payload.get("id")) == read_probe["event_id"]:
            break
        if nonce in _text(event):
            raise PreflightError("read nonce exposed before read event")


def _archive_hash(path, capture):
    return {
        "path": path.relative_to(capture).as_posix(),
        "sha256": _sha(path.read_bytes()),
    }


def _capability(status, reason, event_id=None, evidence_file=None):
    return {
        "status": status,
        "reason": reason,
        "event_id": event_id,
        "evidence_file": evidence_file,
    }


def _unknown_capabilities(reason, *, production=False):
    capabilities = {
        name: _capability("unknown", reason)
        for name in ("read", "write", "search", "child")
    }
    if not production:
        capabilities["isolation"] = _capability("unknown", reason)
    return capabilities


def _assistant_result(events):
    for event in events:
        payload = _payload(event)
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            content = payload.get("content")
            if isinstance(content, list) and any(
                isinstance(part, dict)
                and part.get("type") in {"output_text", "text"}
                and _nonempty_string(part.get("text"))
                for part in content
            ):
                return True
            if _nonempty_string(content):
                return True
        if event.get("type") == "item.completed" and isinstance(
            event.get("item"), dict
        ):
            item = event["item"]
            if item.get("type") == "agent_message" and _nonempty_string(
                item.get("text")
            ):
                return True
    return False


def _context_inventory(context):
    source = context.get("capability_inventory")
    if source is not None and not isinstance(source, dict):
        raise PreflightError("capability_inventory must be an object")
    source = source or {}
    inventory = {}
    for name in _INVENTORY_KEYS:
        value = source[name] if name in source else context.get(name)
        inventory[name] = {
            "status": "unknown",
            "value": None,
            "synthetic_context_value": value if value is not None else None,
            "source": "turn_context",
            "evidence_file": None,
        }
    return inventory


def _unwrap_result(value):
    return (
        value.get("result") if isinstance(value, dict) and "result" in value else value
    )


def _parse_inventory_source(name, source, value):
    value = _unwrap_result(value)
    if not isinstance(value, dict) or value.get("error") or value.get("errors"):
        return None
    if value.get("nextCursor") is not None or value.get("next_cursor") is not None:
        return None
    if name == "settings" and source == "config/read":
        if (
            not isinstance(value.get("config"), dict)
            or not isinstance(value.get("origins"), dict)
            or not isinstance(value.get("layers"), list)
        ):
            return None
        layers = []
        for layer in value["layers"]:
            if not isinstance(layer, dict) or not {
                "name",
                "version",
                "config",
            }.issubset(layer):
                return None
            disabled = layer.get("disabledReason")
            layers.append(
                {
                    "name": layer["name"],
                    "version": layer["version"],
                    "state": "disabled" if disabled is not None else "active",
                    "disabled_reason": disabled,
                }
            )
        return {"layer_count": len(layers), "layers": layers}
    if name == "instructions" and source == "thread/start":
        sources = value.get("instructionSources")
        return {"instruction_sources": sources} if isinstance(sources, list) else None
    if name == "skills" and source == "skills/list":
        data = value.get("data")
        if not isinstance(data, list) or not all(
            isinstance(row, dict)
            and isinstance(row.get("skills"), list)
            and isinstance(row.get("errors"), list)
            and not row["errors"]
            for row in data
        ):
            return None
        return {"cwd_count": len(data), "rows": data}
    if name == "plugins" and source == "plugin/list":
        marketplaces = value.get("marketplaces")
        errors = value.get("marketplaceLoadErrors")
        if not isinstance(marketplaces, list) or not isinstance(errors, list) or errors:
            return None
        return {"marketplaces": marketplaces, "load_errors": errors}
    if name == "mcp" and source == "mcpServerStatus/list":
        data = value.get("data")
        if not isinstance(data, list):
            return None
        return {"servers": data, "next_cursor": value.get("nextCursor")}
    if name == "tools" and source == "tools/list":
        tools = value.get("tools")
        if not isinstance(tools, list) or not all(
            isinstance(tool, dict) for tool in tools
        ):
            return None
        return {"tools": tools}
    return None


def _tool_identity(tool):
    if not isinstance(tool, dict):
        return None
    kind = tool.get("type")
    if kind == "function":
        parameters = tool.get("parameters")
        if (
            _nonempty_string(tool.get("name"))
            and isinstance(parameters, dict)
            and parameters.get("type") == "object"
        ):
            return tool["name"].strip()
    elif kind == "custom":
        form = tool.get("format")
        if (
            _nonempty_string(tool.get("name"))
            and isinstance(form, dict)
            and form.get("type") in ("text", "grammar")
        ):
            return tool["name"].strip()
    elif kind in ("web_search", "web_search_preview"):
        return kind
    return None


def _parse_model_request_tools(value, context, thread_id):
    if not isinstance(value, dict) or set(value) != {
        "kind",
        "schema_version",
        "backend",
        "thread_id",
        "request_id",
        "request",
    }:
        return None
    if (
        value["kind"] != "Stage2NativeModelRequest"
        or value["schema_version"] != "1.0.0"
        or value["backend"] != "responses"
        or not _nonempty_string(value["request_id"])
    ):
        return None
    request = value["request"]
    if (
        not isinstance(request, dict)
        or not _nonempty_string(request.get("model"))
        or not isinstance(request.get("input"), list)
        or not request["input"]
    ):
        return None
    if not _nonempty_string(thread_id) or not _nonempty_string(context.get("model")):
        return None
    if value["thread_id"] != thread_id or request["model"] != context["model"]:
        return None
    tools = request.get("tools")
    if not isinstance(tools, list) or not tools:
        return None
    identities = [_tool_identity(tool) for tool in tools]
    if any(identity is None for identity in identities) or len(set(identities)) != len(
        identities
    ):
        return None
    return {
        "tools": tools,
        "tool_identities": identities,
        "backend": value["backend"],
        "thread_id": thread_id,
        "model": request["model"],
        "request_id": value["request_id"],
    }


def _inventory_entry(name, capture, entry, archive_files):
    if not isinstance(entry, dict) or set(entry) != {"source", "path", "sha256"}:
        raise PreflightError(f"inventory {name} receipt fields are invalid")
    if entry["source"] != _INVENTORY_SOURCES[name] or not _HEX.fullmatch(
        str(entry["sha256"])
    ):
        raise PreflightError(f"inventory {name} source or hash is invalid")
    path = _capture_path(capture, entry["path"], f"inventory {name} path")
    if not path.is_file():
        return {
            "status": "unknown",
            "value": None,
            "source": entry["source"],
            "evidence_file": entry["path"],
        }
    raw = path.read_bytes()
    if _sha(raw) != entry["sha256"]:
        raise PreflightError(f"inventory {name} raw-response hash differs")
    archive_files.append(_archive_hash(path, capture))
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise PreflightError(f"inventory {name} raw response is malformed") from error
    value = _parse_inventory_source(name, entry["source"], parsed)
    return {
        "status": "present" if value is not None else "unknown",
        "value": value,
        "source": entry["source"],
        "evidence_file": entry["path"],
    }


def _v2_tools(capture, receipt, archive_files, context, thread_id):
    entry = receipt.get("tools")
    if entry is None:
        return {
            "status": "unknown",
            "value": None,
            "source": "native-model-request",
            "evidence_file": None,
        }
    required = {"status", "source", "path", "sha256"}
    if not isinstance(entry, dict) or not required.issubset(entry):
        raise PreflightError("inventory tools receipt fields are invalid")
    if (
        entry["source"] != "native-model-request"
        or not isinstance(entry["status"], str)
        or entry["status"]
        not in {
            "unknown",
            "captured",
        }
    ):
        raise PreflightError("inventory tools source or status is invalid")
    if entry["status"] == "unknown":
        if entry["path"] is not None or entry["sha256"] is not None:
            raise PreflightError("unknown inventory tools cannot claim evidence")
        return {
            "status": "unknown",
            "value": None,
            "source": entry["source"],
            "evidence_file": None,
        }
    if not _HEX.fullmatch(str(entry["sha256"])):
        raise PreflightError("inventory tools hash is invalid")
    relative = _relative_path(entry["path"], "inventory tools path")
    parts = tuple(part.lower() for part in relative.parts)
    if len(parts) < 3 or parts[:2] not in {
        ("archive", "transport"),
        ("archive", "native-model-requests"),
    }:
        raise PreflightError(
            "inventory tools must bind a host transport model-request artifact"
        )
    path = _capture_path(capture, entry["path"], "inventory tools path")
    if not path.is_file():
        return {
            "status": "unknown",
            "value": None,
            "source": entry["source"],
            "evidence_file": entry["path"],
        }
    raw = path.read_bytes()
    if _sha(raw) != entry["sha256"]:
        raise PreflightError("inventory tools raw-response hash differs")
    archive_files.append(_archive_hash(path, capture))
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as error:
        raise PreflightError("inventory tools model request is malformed") from error
    value = _parse_model_request_tools(request, context, thread_id)
    if value is None:
        raise PreflightError(
            "inventory tools model request has invalid tool identities or runtime binding"
        )
    return {
        "status": "present",
        "value": value,
        "source": entry["source"],
        "evidence_file": entry["path"],
    }


def _inventory(
    context,
    capture,
    receipt,
    archive_files,
    primary_thread_id=None,
    *,
    require_session_owner=False,
):
    fallback = _context_inventory(context)
    if receipt is None:
        return fallback, None
    if (
        not isinstance(receipt, dict)
        or receipt.get("kind") != "Stage2RuntimeInventoryReceipt"
        or not isinstance(receipt.get("entries"), dict)
    ):
        raise PreflightError("inventory receipt kind/schema/entries are invalid")
    version = receipt.get("schema_version")
    if version == "1.0.0":
        keys = _INVENTORY_KEYS
    elif version == "2.0.0":
        keys = _INVENTORY_V2_KEYS
    else:
        raise PreflightError("inventory receipt kind/schema/entries are invalid")
    if set(receipt["entries"]) != set(keys):
        raise PreflightError("inventory receipt kind/schema/entries are invalid")
    inventory = {}
    for name in keys:
        inventory[name] = _inventory_entry(
            name, capture, receipt["entries"][name], archive_files
        )
    if require_session_owner:
        entry = receipt["entries"]["instructions"]
        path = _capture_path(capture, entry["path"], "inventory instructions path")
        if path.is_file():
            value = _unwrap_result(json.loads(path.read_bytes()))
            thread = value.get("thread") if isinstance(value, dict) else None
            owner = thread.get("id") if isinstance(thread, dict) else None
            if owner is not None and owner != primary_thread_id:
                raise PreflightError("inventory instructions thread mismatch")
            if owner is None:
                inventory["instructions"].update(status="unknown", value=None)
    if version == "2.0.0":
        inventory["tools"] = _v2_tools(
            capture, receipt, archive_files, context, primary_thread_id
        )
    return inventory, _canonical_hash(receipt)


def _normal_sandbox(value):
    return {
        "workspaceWrite": "workspace-write",
        "readOnly": "read-only",
        "dangerFullAccess": "danger-full-access",
    }.get(value, value)


def _entry_writes_workspace(entry, workspace):
    if not isinstance(entry, dict):
        return False
    path_value = entry.get("path")
    access = entry.get("access", entry.get("mode", entry.get("permissions")))
    if isinstance(access, str):
        write = access.lower() in {"read-write", "write", "rw", "workspace-write"}
    elif isinstance(access, list):
        write = any(
            str(item).lower() in {"write", "read-write", "rw"} for item in access
        )
    else:
        write = False
    if not write:
        return False
    if isinstance(path_value, dict):
        if path_value.get("type") == "special":
            special = path_value.get("value")
            kind = special.get("kind") if isinstance(special, dict) else special
            return kind in {"project_roots", "current_working_directory"}
        if path_value.get("type") != "path":
            return False
        path_value = path_value.get("path")
    if not _nonempty_string(path_value):
        return False
    root = str(Path(path_value).resolve()).casefold().rstrip("\\/")
    target = str(Path(workspace).resolve()).casefold().rstrip("\\/")
    return (
        target == root
        or target.startswith(root + "\\")
        or target.startswith(root + "/")
    )


def _actual_runtime(context, workspace):
    sandbox = context.get("sandbox_policy")
    sandbox_type = _normal_sandbox(
        sandbox.get("type") if isinstance(sandbox, dict) else sandbox
    )
    sandbox_network = (
        sandbox.get("network_access") if isinstance(sandbox, dict) else None
    )
    permission = context.get("permission_profile")
    permission_network = (
        permission.get("network") if isinstance(permission, dict) else None
    )
    permission_file_system = (
        permission.get("file_system") if isinstance(permission, dict) else None
    )
    permission_file_system_type = (
        permission_file_system.get("type")
        if isinstance(permission_file_system, dict)
        else permission_file_system
    )
    permission_entries = (
        permission_file_system.get("entries")
        if isinstance(permission_file_system, dict)
        else None
    )
    if permission_file_system_type == "restricted" and isinstance(
        permission_entries, list
    ):
        permission_workspace_write = any(
            _entry_writes_workspace(entry, workspace) for entry in permission_entries
        )
        permission_state = (
            "workspace-write" if permission_workspace_write else "read-only"
        )
    elif permission_file_system_type in {"read-only", "disabled"}:
        permission_workspace_write = False
        permission_state = "read-only"
    elif permission_file_system_type in {"unrestricted", "danger-full-access"}:
        permission_workspace_write = None
        permission_state = "danger-unrestricted"
    else:
        permission_workspace_write = None
        permission_state = "unknown"
    restricted = permission_network in {"restricted", "disabled", False}
    if sandbox_network is False:
        restricted = True
    if restricted:
        network = False
    elif sandbox_network is True or permission_network in {
        "enabled",
        "unrestricted",
        True,
    }:
        network = True
    else:
        network = None
    return {
        "sandbox_policy": sandbox,
        "sandbox": sandbox_type,
        "permission_profile": permission,
        "permission_file_system": permission_file_system_type,
        "permission_workspace_write": permission_workspace_write,
        "permission_state": permission_state,
        "network_access": network,
        "model": context.get("model"),
        "reasoning": context.get("effort", context.get("reasoning")),
        "approval_policy": context.get("approval_policy"),
    }


def inspect_preflight(
    capture_dir, record_sha256_receipt, probe_spec, *, inventory_receipt=None
):
    """Reconstruct functional capability evidence from one authentic capture."""
    if isinstance(probe_spec, dict) and probe_spec.get("schema_version") == "1.2.0":
        from .preflight_observed import inspect_observed_preflight

        if inventory_receipt is not None:
            raise PreflightError("observed probe uses its own producer inventory")
        return inspect_observed_preflight(
            capture_dir, record_sha256_receipt, probe_spec
        )
    production = _validate_probe_spec(probe_spec)
    capture = Path(capture_dir).resolve()
    try:
        record, _ = verify_capture(capture, record_sha256_receipt)
    except CaptureError as error:
        raise PreflightError(f"capture verification failed: {error}") from error
    if not isinstance(record, dict):
        raise PreflightError("verified capture record must be an object")
    expected = probe_spec["expected"]
    stable = record.get("stable_request_binding")
    if not isinstance(stable, dict):
        raise PreflightError("verified capture lacks stable_request_binding")
    executor = probe_spec["executor"]
    bound_shell = stable.get("config_bindings", {}).get("probe_shell")
    if (
        not isinstance(bound_shell, dict)
        or set(bound_shell) != {"kind", "path", "sha256"}
        or bound_shell["kind"] != "file"
        or bound_shell["sha256"] != executor["shell_sha256"]
        or _cwd_path(bound_shell["path"]) != _cwd_path(executor["shell_path"])
    ):
        raise PreflightError("probe shell differs from archived host binding")
    shell_archive = _capture_path(
        capture, "archive/config_bindings/probe_shell", "probe shell"
    )
    if (
        not shell_archive.is_file()
        or _sha(shell_archive.read_bytes()) != executor["shell_sha256"]
    ):
        raise PreflightError("probe shell bytes mismatch")
    workspace = stable.get("workspace")
    if not _nonempty_string(workspace):
        raise PreflightError("verified capture lacks its bound workspace path")
    if executor["working_directory"] != workspace:
        raise PreflightError("probe working directory differs from bound workspace")
    requested_policy = stable.get("policy_bindings")
    requested = {
        "model": stable.get("model"),
        "reasoning": stable.get("reasoning"),
        "policy_bindings": requested_policy,
    }
    summary = record.get("event_summary")
    if not isinstance(summary, dict):
        raise PreflightError("verified capture lacks event_summary")
    thread_id = summary.get("thread_id")
    sessions_root = capture / "archive/native-sessions"
    session_files = (
        sorted(sessions_root.rglob("*.jsonl")) if sessions_root.is_dir() else []
    )
    session_rows = [(path, _load_jsonl(path)) for path in session_files]
    archive_files = [_archive_hash(path, capture) for path in session_files]
    stdout_path = capture / "stdout.jsonl"
    stdout_events = _load_jsonl(stdout_path) if stdout_path.is_file() else []
    if stdout_path.is_file():
        archive_files.append(_archive_hash(stdout_path, capture))
    blockers = []
    context = None
    primary_matches = [
        (path, events)
        for path, events in session_rows
        if _session_identity(events, production) == thread_id
    ]
    if len(primary_matches) > 1:
        raise PreflightError("ambiguous primary session for captured thread_id")
    if not _nonempty_string(thread_id) or not primary_matches:
        blockers.append("primary-session-missing")
        inventory, inventory_receipt_sha256 = _inventory(
            {},
            capture,
            inventory_receipt,
            archive_files,
            thread_id,
            require_session_owner=production,
        )
        capabilities = _unknown_capabilities(
            "primary archived session is unavailable", production=production
        )
        actual = {
            "sandbox_policy": None,
            "sandbox": None,
            "permission_profile": None,
            "permission_file_system": None,
            "permission_workspace_write": None,
            "permission_state": "unknown",
            "network_access": None,
            "model": None,
            "reasoning": None,
            "approval_policy": None,
        }
    else:
        primary_path, primary_events = primary_matches[0]
        context = _turn_context(primary_events)
        if context is None:
            blockers.append("primary-turn-context-missing")
            inventory, inventory_receipt_sha256 = _inventory(
                {},
                capture,
                inventory_receipt,
                archive_files,
                thread_id,
                require_session_owner=production,
            )
            capabilities = _unknown_capabilities(
                "primary turn_context is unavailable", production=production
            )
            actual = {
                "sandbox_policy": None,
                "sandbox": None,
                "permission_profile": None,
                "permission_file_system": None,
                "permission_workspace_write": None,
                "permission_state": "unknown",
                "network_access": None,
                "model": None,
                "reasoning": None,
                "approval_policy": None,
            }
        else:
            inventory, inventory_receipt_sha256 = _inventory(
                context,
                capture,
                inventory_receipt,
                archive_files,
                thread_id,
                require_session_owner=production,
            )
            actual = _actual_runtime(context, workspace)
            indexes = _event_index(primary_events)
            stdout_indexes = _event_index(stdout_events)
            primary_ref = primary_path.relative_to(capture).as_posix()
            probes = probe_spec["probes"]

            read_probe = probes["read"]
            read_command_path = _read_command_path(probe_spec)
            read_path = _capture_path(
                capture,
                "archive/workspace-start/" + read_probe["source_path"],
                "read source_path",
            )
            read_entry = _named_event_any(
                read_probe["event_id"], indexes, stdout_indexes
            )
            _check_nonce_inputs(capture, primary_events, read_probe, read_entry)
            code_read = None
            if (
                production
                and read_entry is not None
                and _event_kind(read_entry) == "exec"
            ):
                try:
                    code_read = inspect_production_wrapper(
                        primary_events,
                        read_probe["event_id"],
                        "exec_command",
                        executor,
                    )
                except CodeModeWitnessError:
                    code_read = None
            if not read_path.is_file():
                capabilities = {
                    "read": _capability(
                        "unknown",
                        "bound source file is missing",
                        read_probe["event_id"],
                        primary_ref,
                    )
                }
                blockers.append("read-source-missing")
            else:
                archive_files.append(_archive_hash(read_path, capture))
                nonce_bytes = read_probe["nonce"].encode("utf-8")
                occurrences = sum(
                    path.read_bytes().count(nonce_bytes)
                    for path in (capture / "archive/workspace-start").rglob("*")
                    if path.is_file()
                )
                if occurrences != 1 or nonce_bytes not in read_path.read_bytes():
                    raise PreflightError(
                        "read nonce is not unique to the bound source bytes"
                    )
                if read_entry is None:
                    capabilities = {
                        "read": _capability(
                            "unknown",
                            "specified read event is missing",
                            read_probe["event_id"],
                            primary_ref,
                        )
                    }
                    blockers.append("read-event-missing")
                elif not _is_exact_read(
                    read_entry, read_command_path, executor
                ) and not (
                    code_read is not None
                    and code_read["arguments"].get("cmd")
                    in _allowed_read_commands(read_command_path, executor["family"])
                ):
                    capabilities = {
                        "read": _capability(
                            "failed",
                            "specified read event does not reference the frozen source",
                            read_probe["event_id"],
                            primary_ref,
                        )
                    }
                    blockers.append("read-event-unrelated")
                elif code_read is None and (
                    _DENIED.search(_event_output(read_entry))
                    or _event_failed(read_entry)
                ):
                    capabilities = {
                        "read": _capability(
                            "failed",
                            "specified read event was denied or failed",
                            read_probe["event_id"],
                            primary_ref,
                        )
                    }
                    blockers.append("read-capability-failed")
                elif read_probe["nonce"] not in (
                    code_read["output"]["output"]
                    if code_read is not None
                    else _event_output(read_entry)
                ):
                    capabilities = {
                        "read": _capability(
                            "unknown",
                            "specified read output lacks the frozen nonce",
                            read_probe["event_id"],
                            primary_ref,
                        )
                    }
                    blockers.append("read-nonce-unproven")
                else:
                    capabilities = {
                        "read": _capability(
                            "passed",
                            "frozen nonce appears in the specified successful tool output",
                            read_probe["event_id"],
                            primary_ref,
                        )
                    }
                    if code_read is not None:
                        capabilities["read"]["native_event_id"] = code_read[
                            "native_item_id"
                        ]

            write_probe = probes["write"]
            write_path = _capture_path(
                capture,
                "archive/workspace-end/" + write_probe["output_path"],
                "write output_path",
            )
            write_start_path = _capture_path(
                capture,
                "archive/workspace-start/" + write_probe["output_path"],
                "write output_path",
            )
            write_entry = _named_event_any(
                write_probe["event_id"], indexes, stdout_indexes
            )
            code_write = None
            if (
                production
                and write_entry is not None
                and _event_kind(write_entry) == "exec"
            ):
                try:
                    code_write = inspect_production_wrapper(
                        primary_events,
                        write_probe["event_id"],
                        "exec_command",
                        executor,
                    )
                except CodeModeWitnessError:
                    code_write = None
            if write_start_path.exists():
                capabilities["write"] = _capability(
                    "failed",
                    "frozen output already existed at workspace start",
                    write_probe["event_id"],
                    primary_ref,
                )
                blockers.append("write-output-not-new")
            elif not write_path.is_file():
                capabilities["write"] = _capability(
                    "unknown",
                    "bound output file is missing",
                    write_probe["event_id"],
                    primary_ref,
                )
                blockers.append("write-output-missing")
            else:
                archive_files.append(_archive_hash(write_path, capture))
                if _sha(write_path.read_bytes()) != write_probe["sha256"]:
                    capabilities["write"] = _capability(
                        "failed",
                        "bound output digest differs",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("write-digest-mismatch")
                elif write_entry is None:
                    capabilities["write"] = _capability(
                        "unknown",
                        "specified write event is missing",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("write-event-missing")
                elif _event_kind(write_entry) == "exec" and code_write is None:
                    capabilities["write"] = _capability(
                        "failed",
                        "specified Code Mode write lacks authenticated terminal evidence",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("write-capability-failed")
                elif write_probe["output_path"] not in (
                    code_write["arguments"]["cmd"]
                    if code_write is not None
                    else _event_request(write_entry)
                ):
                    capabilities["write"] = _capability(
                        "failed",
                        "specified write event does not reference the frozen output",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("write-event-unrelated")
                elif code_write is None and _event_failed(write_entry):
                    capabilities["write"] = _capability(
                        "failed",
                        "specified write event failed",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("write-capability-failed")
                else:
                    capabilities["write"] = _capability(
                        "passed",
                        "specified successful event is bound to output bytes",
                        write_probe["event_id"],
                        primary_ref,
                    )
                    if code_write is not None:
                        capabilities["write"]["native_event_id"] = code_write[
                            "native_item_id"
                        ]

            search_probe = probes["search"]
            search_entry = _named_event_any(
                search_probe["event_id"], indexes, stdout_indexes
            )
            code_search = None
            if (
                production
                and search_entry is not None
                and _event_kind(search_entry) == "exec"
            ):
                try:
                    code_search = inspect_production_wrapper(
                        primary_events,
                        search_probe["event_id"],
                        "web__run",
                        executor,
                    )
                except CodeModeWitnessError:
                    code_search = None
            if search_entry is None:
                capabilities["search"] = _capability(
                    "unknown",
                    "specified search event is missing",
                    search_probe["event_id"],
                    primary_ref,
                )
                blockers.append("search-result-missing")
            else:
                kind = _event_kind(search_entry)
                output = _event_output(search_entry)
                item = search_entry["item"] or {}
                has_result = bool(output.strip()) or bool(item.get("results"))
                if "search" not in kind and code_search is None:
                    capabilities["search"] = _capability(
                        "failed",
                        "specified event is not a search",
                        search_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("search-event-unrelated")
                elif code_search is None and _event_failed(search_entry):
                    capabilities["search"] = _capability(
                        "failed",
                        "specified search failed",
                        search_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("search-capability-failed")
                elif not has_result and code_search is None:
                    capabilities["search"] = _capability(
                        "unknown",
                        "search declaration has no archived result",
                        search_probe["event_id"],
                        primary_ref,
                    )
                    blockers.append("search-result-missing")
                else:
                    capabilities["search"] = _capability(
                        "passed",
                        "specified native search has an archived successful result",
                        search_probe["event_id"],
                        primary_ref,
                    )
                    if code_search is not None:
                        capabilities["search"]["native_event_id"] = code_search[
                            "native_item_id"
                        ]

            child_probe = probes["child"]
            child_entry = _named_event_any(
                child_probe["event_id"], indexes, stdout_indexes
            )
            child_matches = [
                (path, events)
                for path, events in session_rows
                if _session_identity(events, production)
                == child_probe["child_thread_id"]
            ]
            if len(child_matches) > 1:
                raise PreflightError("ambiguous child session identity")
            child_link = _text(child_entry) if child_entry is not None else ""
            child_kind = _event_kind(child_entry) if child_entry is not None else ""
            production_child = None
            if production and child_entry is not None:
                try:
                    production_child = inspect_production_child(
                        primary_events,
                        child_probe["event_id"],
                        child_probe["child_thread_id"],
                        thread_id,
                        [
                            (_session_identity(events, production), events)
                            for _, events in session_rows
                        ],
                    )
                except CodeModeWitnessError:
                    production_child = None
            if child_entry is None or not (
                "subagent" in child_kind or child_kind in {"spawn_agent", "spawn-agent"}
            ):
                capabilities["child"] = _capability(
                    "unknown",
                    "specified linking subagent call is missing",
                    child_probe["event_id"],
                    primary_ref,
                )
                blockers.append("child-link-missing")
            elif (production and production_child is None) or (
                not production and child_probe["child_thread_id"] not in child_link
            ):
                capabilities["child"] = _capability(
                    "failed",
                    "specified call does not link the frozen child thread",
                    child_probe["event_id"],
                    primary_ref,
                )
                blockers.append("child-link-mismatch")
            elif _event_failed(child_entry):
                capabilities["child"] = _capability(
                    "failed",
                    "specified child call failed",
                    child_probe["event_id"],
                    primary_ref,
                )
                blockers.append("child-capability-failed")
            elif not child_matches or not _assistant_result(child_matches[0][1]):
                capabilities["child"] = _capability(
                    "unknown",
                    "linked child session result is missing",
                    child_probe["event_id"],
                    primary_ref,
                )
                blockers.append("child-session-result-missing")
            else:
                child_path = child_matches[0][0]
                capabilities["child"] = _capability(
                    "passed",
                    "specified call links an archived child session result",
                    child_probe["event_id"],
                    child_path.relative_to(capture).as_posix(),
                )

            sentinel_failures = []
            sentinel_unknowns = []
            for name, sentinel in (
                probes.get("isolation", {}).get("sentinels", {}).items()
            ):
                entry = _named_event_any(sentinel["event_id"], indexes, stdout_indexes)
                receipt_path = _capture_path(
                    capture,
                    sentinel["receipt_path"],
                    f"isolation {name} receipt_path",
                )
                if not receipt_path.is_file():
                    sentinel_unknowns.append(name)
                    continue
                receipt_bytes = receipt_path.read_bytes()
                if _sha(receipt_bytes) != sentinel["receipt_sha256"]:
                    raise PreflightError(f"isolation {name} receipt hash differs")
                archive_files.append(_archive_hash(receipt_path, capture))
                try:
                    sentinel_receipt = json.loads(receipt_bytes)
                except (UnicodeDecodeError, ValueError) as error:
                    raise PreflightError(
                        f"isolation {name} receipt is malformed"
                    ) from error
                expected_receipt = {
                    "exists": True,
                    "path": sentinel["path"],
                    "sha256": sentinel["sentinel_sha256"],
                    "nonce": sentinel["nonce"],
                    "phase": "before-run",
                }
                if sentinel_receipt != expected_receipt:
                    sentinel_failures.append(name)
                    continue
                if entry is None:
                    sentinel_unknowns.append(name)
                    continue
                request = _event_request(entry)
                output = _event_output(entry)
                if _sha(request.encode("utf-8")) != sentinel["request_sha256"]:
                    sentinel_failures.append(name)
                elif not _is_exact_read(entry, sentinel["path"], executor):
                    sentinel_failures.append(name)
                elif sentinel["nonce"] in request or sentinel["nonce"] in output:
                    sentinel_failures.append(name)
                elif not _proved_policy_rejection(entry):
                    sentinel_failures.append(name)
            if sentinel_failures:
                capabilities["isolation"] = _capability(
                    "failed",
                    "specified sentinels lack matching denied-read evidence: "
                    + ",".join(sorted(sentinel_failures)),
                    evidence_file=primary_ref,
                )
                blockers.append("isolation-denial-mismatch")
            elif sentinel_unknowns:
                capabilities["isolation"] = _capability(
                    "unknown",
                    "specified sentinel attempts are missing: "
                    + ",".join(sorted(sentinel_unknowns)),
                    evidence_file=primary_ref,
                )
                blockers.append("isolation-denial-missing")
            elif not production:
                capabilities["isolation"] = _capability(
                    "passed",
                    "each frozen sentinel has a matching archived denied read",
                    evidence_file=primary_ref,
                )

    if requested.get("model") != expected["model"]:
        blockers.append("requested-model-mismatch")
    if requested.get("reasoning") != expected["reasoning"]:
        blockers.append("requested-reasoning-mismatch")
    if not isinstance(requested_policy, dict):
        blockers.append("requested-policy-unknown")
    else:
        # verify_capture already checked the exact named restrictive config.
        # Preserve raw requested bindings; only interpret their policy semantics.
        semantics = (
            {"sandbox": "workspace-write", "network_access": True}
            if requested_policy.get("kind") == NAMED_POLICY_KIND
            else requested_policy
        )
        if semantics.get("sandbox") != expected["sandbox"]:
            blockers.append("requested-sandbox-mismatch")
        if semantics.get("network_access") is not expected["network_access"]:
            blockers.append("requested-network-mismatch")
    try:
        verify_named_runtime(record["stable_request_binding"], context or {})
    except NamedPolicyError as error:
        blockers.append(f"effective-named-policy-invalid:{error}")
    if actual["model"] is None:
        blockers.append("actual-model-unknown")
    elif actual["model"] != expected["model"]:
        blockers.append("model-mismatch")
    if actual["reasoning"] is None:
        blockers.append("actual-reasoning-unknown")
    elif actual["reasoning"] != expected["reasoning"]:
        blockers.append("reasoning-mismatch")
    if actual["sandbox"] is None:
        blockers.append("sandbox-unknown")
    elif actual["sandbox"] != "workspace-write":
        blockers.append("sandbox-not-workspace-write")
    if actual["permission_profile"] is None:
        blockers.append("permission-profile-unknown")
    elif actual["permission_state"] == "danger-unrestricted":
        blockers.append("permission-profile-danger-unrestricted")
    elif actual["permission_workspace_write"] is False:
        blockers.append("permission-profile-readonly")
    elif actual["permission_workspace_write"] is None:
        blockers.append("permission-profile-write-unknown")
    if actual["network_access"] is None:
        blockers.append("network-access-unknown")
    elif actual["network_access"] is not True:
        blockers.append("network-restricted")
    if actual["approval_policy"] is None:
        blockers.append("approval-policy-unknown")
    inventory_observations = []
    for name, value in inventory.items():
        if value["status"] != "present":
            observation = f"inventory-{name}-{value['status']}"
            if production:
                inventory_observations.append(observation)
            else:
                blockers.append(observation)
    blockers = sorted(set(blockers))
    archive_files = sorted(
        {item["path"]: item for item in archive_files}.values(),
        key=lambda item: item["path"],
    )
    runtime_gate = not blockers and all(
        capability["status"] == "passed" for capability in capabilities.values()
    )
    report = {
        "kind": (
            "Stage2ProductionRuntimePreflight"
            if production
            else "Stage2RuntimePreflight"
        ),
        "schema_version": "1.0.0",
        "status": "passed" if runtime_gate else "blocked",
        "runtime_gate": runtime_gate,
        "formal_ready": False,
        "scientific_improvement": False,
        "capture_record_sha256_receipt": record_sha256_receipt,
        "probe_spec_sha256": _canonical_hash(probe_spec),
        "inventory_receipt_sha256": inventory_receipt_sha256,
        "primary_thread_id": thread_id,
        "requested_runtime": requested,
        "actual_runtime": actual,
        "inventory": inventory,
        "capabilities": capabilities,
        "blockers": blockers,
        "archive_files": archive_files,
    }
    if production:
        report.update(
            {
                "validation_scope": "production-single",
                "filesystem_read_isolation": "not-assessed",
                "quality_improvement": "not-established",
                "observations": sorted(inventory_observations),
            }
        )
    return report


def verify_preflight(
    report, capture_dir, receipt, probe_spec, *, inventory_receipt=None
):
    """Recompute a preflight and require exact report equality."""
    if not isinstance(report, dict):
        raise PreflightError("preflight report must be an object")
    recomputed = inspect_preflight(
        capture_dir, receipt, probe_spec, inventory_receipt=inventory_receipt
    )
    require_matching_preflight_contract(recomputed, probe_spec)
    if report != recomputed:
        raise PreflightError(
            "submitted preflight report does not equal recomputed evidence"
        )
    return recomputed
