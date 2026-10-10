"""Select strict current-session evidence from an authenticated native archive."""

import json
from pathlib import Path

from .preflight import PreflightError, _load_jsonl, _payload, _session_identity


class _TruncatedValue(ValueError):
    def __init__(self, path):
        self.path = path


def _unambiguous_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous event member")
        result[key] = value
    return result


def _partial_value(raw, offset, path, objects):
    """Parse the complete prefix without accepting duplicate object members."""
    decoder = json.JSONDecoder()
    offset += len(raw[offset:]) - len(raw[offset:].lstrip())
    token = raw[offset : offset + 1]
    if token not in {"{", "["}:
        try:
            return decoder.raw_decode(raw, offset)
        except json.JSONDecodeError as error:
            if error.msg == "Unterminated string starting at":
                raise _TruncatedValue(path) from error
            raise
    mapping = token == "{"
    result = {} if mapping else []
    if mapping:
        objects[path] = result
    seen = set()
    offset += 1
    closing = "}" if mapping else "]"
    offset += len(raw[offset:]) - len(raw[offset:].lstrip())
    if raw[offset : offset + 1] == closing:
        return result, offset + 1
    while True:
        if mapping:
            key, offset = decoder.raw_decode(raw, offset)
            if not isinstance(key, str) or key in seen:
                raise ValueError("ambiguous event member")
            seen.add(key)
            offset += len(raw[offset:]) - len(raw[offset:].lstrip())
            if raw[offset : offset + 1] != ":":
                raise ValueError("event member lacks a colon")
            offset += 1
        else:
            key = len(result)
        value, offset = _partial_value(raw, offset, path + (key,), objects)
        if mapping:
            result[key] = value
        else:
            result.append(value)
        offset += len(raw[offset:]) - len(raw[offset:].lstrip())
        if raw[offset : offset + 1] == closing:
            return result, offset + 1
        if raw[offset : offset + 1] != ",":
            raise ValueError("event member delimiter is invalid")
        offset += 1
        offset += len(raw[offset:]) - len(raw[offset:].lstrip())


def _non_metadata_body(raw):
    """Recognize only native body envelopes when their later content is truncated."""
    objects = {}
    try:
        _partial_value(raw, 0, (), objects)
    except _TruncatedValue as error:
        path = error.path
    except ValueError:
        return False
    else:
        return False
    outer = objects.get((), {}).get("type")
    inner = objects.get(("payload",), {}).get("type")
    return (
        len(path) >= 2
        and path[0] == "payload"
        and path[1] in {"item", "content", "text", "arguments", "output", "summary"}
        and outer in {"event_msg", "response_item"}
        and inner
        in {
            "item_started",
            "item_completed",
            "function_call",
            "function_call_output",
            "message",
            "reasoning",
        }
    )


def select_production_session(capture_root, thread_id):
    """Keep every archive byte authenticated, but strictly parse the selected body.

    The caller must first verify_capture with its external receipt. Scan all
    files for ownership, including inherited parent/child metadata and aliases.
    Only identifiable non-metadata body truncation can be deferred; if that file
    owns the current thread, the unchanged strict loader still rejects it.
    """
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise PreflightError("production session thread identity is missing")
    matches = []
    root = Path(capture_root) / "archive/native-sessions"
    for path in sorted(root.rglob("*.jsonl")):
        metadata = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise PreflightError(f"unclassified native session: {path}") from error
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=_unambiguous_members)
                if not isinstance(row, dict):
                    raise ValueError("event is not an object")
            except ValueError as error:
                if (
                    metadata
                    and isinstance(error, json.JSONDecodeError)
                    and error.msg == "Unterminated string starting at"
                    and _non_metadata_body(line)
                ):
                    continue
                raise PreflightError(
                    f"unclassified native session JSONL: {path}:{number}"
                ) from error
            payload = _payload(row)
            is_metadata = (
                row.get("type") == "session_meta"
                or payload.get("type") == "session_meta"
            )
            if not metadata and not is_metadata:
                raise PreflightError(f"native session ownership missing: {path}")
            if is_metadata:
                metadata.append(row)
        identity = _session_identity(metadata, True)
        if not isinstance(identity, str) or not identity.strip():
            raise PreflightError(f"native session ownership missing: {path}")
        if identity == thread_id:
            matches.append(path)
    if len(matches) != 1:
        raise PreflightError("production primary session is not unique")
    return _load_jsonl(matches[0])
