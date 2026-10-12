"""Bounded passive projection of saved API intents and validated native frames.

It performs no pump or I/O. Item/turn status is observed protocol content, not
native authentication, successful research, or evidence that all deltas arrived.
"""

import json
from stage1_deliverable.common import canonical, sha
from .transport import _decode

EVENT_LIMIT, ENTRY_LIMIT, ITEM_BYTES, TOTAL_BYTES = 128, 128, 16384, 65536
PAYLOAD_BYTES = 65536
TOOLS = {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall"}


def _id(value):
    return isinstance(value, str) and 0 < len(value) <= 256


def _clip(text, bound):
    raw = text.encode("utf-8")
    return raw[:bound].decode("utf-8", errors="ignore"), len(raw) > bound


def project_transcript(store, state, binding, principal, make_ref):
    """Called only under the facade's source-verified project lock."""
    entries, turns, omitted, truncated = {}, {}, 0, False

    def entry(key, action_ref, role, kind, status, text, revision, failure=None):
        return dict(
            entry_ref=make_ref(binding, "transcript", key),
            action_ref=action_ref,
            role=role,
            kind=kind,
            status=status,
            text=text,
            failure=failure,
            frame_refs=[],
            _revision=revision,
        )

    messages = [
        (key, row)
        for key, row in state.get("session_api_actions", {}).items()
        if row["principal"] == principal and row["kind"] == "message"
    ]
    if len(messages) > 64:
        truncated = True
    for key, row in messages[-64:]:
        document = row.get("start_offer", {}).get("document", {})
        if any(
            document.get(name) != binding[name]
            for name in ("project_id", "index_sha256", "input_version", "source_root")
        ):
            omitted += 1
            continue
        action_ref = make_ref(binding, "action", key)
        observed = state.get("controller_actions", {}).get(key, {})
        text, clipped = _clip(row["request"]["text"], ITEM_BYTES)
        truncated |= clipped
        entries[(key, "user")] = entry(
            key,
            action_ref,
            "user",
            "message-intent",
            observed.get("status", "dispatch-unobserved"),
            text,
            row["admitted_revision"],
            row.get("failure"),
        )
        intent = state["intents"].get(key)
        if (
            not intent
            or intent["method"] != "turn/start"
            or not _id(intent.get("native_turn_id"))
        ):
            continue
        correlated = [
            c["binding"]
            for c in state["protocol"].get("correlations", {}).values()
            if c["binding"]["intent_key"] == key
        ]
        if len(correlated) != 1:
            continue
        native = correlated[0]
        action = observed.get("action", {})
        if (
            native["connection_id"] != row["connection_id"]
            or native["thread_id"] != binding["thread_id"]
            or action.get("project_id") != binding["project_id"]
            or action.get("index_sha256") != binding["index_sha256"]
            or action.get("connection_id") != row["connection_id"]
            or action.get("thread_id") != binding["thread_id"]
            or native["intent_sha256"] != intent["record_sha256"]
        ):
            continue
        identity = (native["connection_id"], intent["native_turn_id"])
        # Reused/ambiguous identities are never attributed to either message.
        turns[identity] = None if identity in turns else (key, action_ref)

    rows = store.db.execute(
        "SELECT revision,length(CAST(payload AS BLOB)) AS size,"
        "substr(CAST(payload AS BLOB),1,?) AS payload FROM events "
        "WHERE project=? AND kind='protocol-frame' AND revision<=? "
        "ORDER BY revision DESC LIMIT ?",
        (PAYLOAD_BYTES, binding["project_id"], state["revision"], EVENT_LIMIT + 1),
    ).fetchall()
    if len(rows) > EVENT_LIMIT:
        truncated = True
    for saved in reversed(rows[:EVENT_LIMIT]):
        if saved["size"] > PAYLOAD_BYTES:
            omitted += 1
            truncated = True
            continue
        payload = json.loads(saved["payload"])
        frame = payload["frame"]
        if (
            payload.get("quarantine") is not None
            or frame["direction"] != "incoming"
            or frame["kind"] != "notification"
        ):
            continue
        message, raw = frame["message"], frame["raw_utf8"]
        if sha(raw.encode("utf-8")) != payload["raw_sha256"] or canonical(
            _decode(raw)
        ) != canonical(message):
            omitted += 1
            continue
        params = message.get("params", {})
        if (
            not isinstance(params, dict)
            or params.get("threadId") != binding["thread_id"]
        ):
            omitted += 1
            continue
        turn = params.get("turnId")
        if message["method"] == "turn/completed" and isinstance(
            params.get("turn"), dict
        ):
            turn = params["turn"].get("id")
        owner = turns.get((frame["connection_id"], turn)) if _id(turn) else None
        if owner is None:
            omitted += 1
            continue
        key, action_ref = owner
        method = message["method"]
        item = params.get("item", {})
        item_id = (
            params.get("itemId")
            if method == "item/agentMessage/delta"
            else item.get("id")
            if isinstance(item, dict)
            else None
        )
        record = None
        if (
            method == "item/agentMessage/delta"
            and _id(item_id)
            and isinstance(params.get("delta"), str)
        ):
            identity = (key, "assistant", item_id)
            record = entries.setdefault(
                identity,
                entry(
                    canonical(identity).decode(),
                    action_ref,
                    "assistant",
                    "assistant-delta",
                    "partial",
                    "",
                    saved["revision"],
                ),
            )
            if record["kind"] == "assistant-delta":
                record["text"], clipped = _clip(
                    record["text"] + params["delta"], ITEM_BYTES
                )
                truncated |= clipped
        elif method == "item/completed" and _id(item_id) and isinstance(item, dict):
            identity = (key, "assistant", item_id)
            if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                text, clipped = _clip(item["text"], ITEM_BYTES)
                prior = entries.get(identity)
                text_sha = sha(item["text"].encode("utf-8"))
                if prior and prior.get("_final_sha") not in (None, text_sha):
                    prior.update(
                        kind="assistant-conflict",
                        status="unknown",
                        text=None,
                        failure="conflicting-saved-item",
                    )
                    prior["frame_refs"].append(
                        dict(
                            frame_sequence=payload["frame_seq"],
                            raw_sha256=payload["raw_sha256"],
                        )
                    )
                    continue
                if prior and prior["kind"] == "assistant-conflict":
                    prior["frame_refs"].append(
                        dict(
                            frame_sequence=payload["frame_seq"],
                            raw_sha256=payload["raw_sha256"],
                        )
                    )
                    continue
                record = entry(
                    canonical(identity).decode(),
                    action_ref,
                    "assistant",
                    "assistant-final",
                    "partial" if clipped else "completed",
                    text,
                    saved["revision"],
                )
                record["frame_refs"] = prior["frame_refs"] if prior else []
                record["_final_sha"] = text_sha
                truncated |= clipped
                entries[identity] = record
            elif isinstance(item.get("type"), str) and item["type"] in TOOLS:
                identity = (key, "tool", item_id, saved["revision"])
                native_status = item.get("status")
                malformed = (
                    native_status is not None
                    and (
                        not isinstance(native_status, str)
                        or native_status
                        not in {"inProgress", "completed", "failed", "declined"}
                    )
                ) or any(
                    item.get(name) is not None and type(item[name]) is not expected
                    for name, expected in (("success", bool), ("exitCode", int))
                )
                failed = (
                    isinstance(native_status, str)
                    and native_status in {"failed", "declined"}
                    or item.get("success") is False
                    or item.get("error") is not None
                )
                failed |= type(item.get("exitCode")) is int and item["exitCode"] != 0
                status = (
                    "failed"
                    if failed
                    else "unknown"
                    if malformed
                    else "completed"
                    if item.get("status") == "completed" or item.get("success") is True
                    else "unknown"
                )
                record = entry(
                    canonical(identity).decode(),
                    action_ref,
                    "tool",
                    "tool-status",
                    status,
                    None,
                    saved["revision"],
                    "native-tool-failed"
                    if failed
                    else "malformed-native-tool-status"
                    if malformed
                    else None,
                )
                entries[identity] = record
        elif method == "turn/completed":
            status = params["turn"].get("status")
            if status in {"completed", "failed", "interrupted"}:
                identity = (key, "terminal")
                record = entry(
                    canonical(identity).decode(),
                    action_ref,
                    "system",
                    "turn-terminal",
                    status,
                    None,
                    saved["revision"],
                )
                entries[identity] = record
        elif method == "error":
            identity = (key, "error", saved["revision"])
            record = entry(
                canonical(identity).decode(),
                action_ref,
                "system",
                "native-error",
                "failed",
                None,
                saved["revision"],
                "native-error-observed",
            )
            entries[identity] = record
        if record is not None:
            record["frame_refs"].append(
                dict(
                    frame_sequence=payload["frame_seq"],
                    raw_sha256=payload["raw_sha256"],
                )
            )

    output, remaining = [], TOTAL_BYTES
    ordered = sorted(entries.values(), key=lambda row: row["_revision"])
    if len(ordered) > ENTRY_LIMIT:
        truncated = True
    for record in ordered[-ENTRY_LIMIT:]:
        record.pop("_revision")
        record.pop("_final_sha", None)
        if record["text"] is not None:
            record["text"], clipped = _clip(record["text"], remaining)
            remaining -= len(record["text"].encode("utf-8"))
            truncated |= clipped
            if clipped and record["role"] == "assistant":
                record["status"] = "partial"
        output.append(record)
    return dict(
        schema_version="1.0.0",
        entries=output,
        window=dict(
            event_limit=EVENT_LIMIT,
            entry_limit=ENTRY_LIMIT,
            text_byte_limit=TOTAL_BYTES,
            truncated=truncated,
            omitted_frames=omitted,
        ),
    )
