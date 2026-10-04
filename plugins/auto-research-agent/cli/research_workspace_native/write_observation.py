"""Read-only complete-frame observations; injected I/O is not native proof."""

import json

from stage1_deliverable.common import sha
from .recording import records
from .store import _require


def observe_frame_write(
    store,
    *,
    project_id,
    owner,
    index_sha256,
    thread_id,
    connection_id,
    first_seq,
    outgoing,
    max_records=20000,
):
    """Verify a saved outgoing frame and its paired, contiguous write records.

    first_seq is the exclusive cursor captured before writing. No state changes,
    retries, native acknowledgement or execution authority result from this read.
    """
    _require(
        type(max_records) is int and 1 <= max_records <= 20000, "invalid record bound"
    )
    _require(type(first_seq) is int and 0 <= first_seq < 2**63, "invalid first cursor")
    _require(
        isinstance(outgoing, dict) and set(outgoing) == {"raw", "frame_seq"},
        "outgoing frame observation required",
    )
    raw, frame_seq = outgoing["raw"], outgoing["frame_seq"]
    _require(
        type(raw) is bytes
        and 1 < len(raw) <= 1024 * 1024
        and raw.endswith(b"\n")
        and b"\n" not in raw[:-1],
        "invalid frame bytes",
    )
    _require(type(frame_seq) is int and frame_seq > 0, "invalid frame sequence")
    with store._lock:
        state = store.snapshot(project_id)
        binding = dict(
            connection_id=connection_id,
            owner=owner,
            index_sha256=index_sha256,
            thread_id=thread_id,
        )
        protocol = state.get("protocol", {})
        channel = state.get("byte_channels", {}).get(connection_id, {})
        _require(
            state["index_sha256"] == index_sha256
            and state["thread_id"] == thread_id
            and isinstance(thread_id, str)
            and thread_id
            and isinstance(state.get("owner"), dict)
            and state["owner"].get("token") == owner
            and store._owners.get(project_id, (None,))[0] == owner
            and protocol.get("binding") == binding
            and not protocol.get("quarantine")
            and protocol.get("frame_seq") == frame_seq
            and channel.get("owner") == owner
            and channel.get("index_sha256") == index_sha256
            and channel.get("pending") == {}
            and not channel.get("fault"),
            "write observation owner/project/epoch differs or is unsettled",
        )
        saved = store.db.execute(
            "SELECT payload FROM events WHERE project=? AND kind='protocol-frame' "
            "ORDER BY revision DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        _require(saved is not None, "persisted outgoing frame required")
        event = json.loads(saved["payload"])
        frame = event.get("frame", {})
        _require(
            event.get("frame_seq") == frame_seq
            and event.get("raw_sha256") == sha(raw)
            and event.get("quarantine") is None
            and frame.get("connection_id") == connection_id
            and frame.get("direction") == "outgoing"
            and frame.get("kind") in {"request", "response"}
            and isinstance(frame.get("raw_utf8"), str)
            and frame["raw_utf8"].encode("utf-8") == raw,
            "saved outgoing frame differs",
        )
        last = channel.get("seq")
        _require(
            type(last) is int
            and first_seq < last < 2**63
            and last - first_seq <= max_records,
            "invalid write record range",
        )
        expected = dict(project_id=project_id, **binding, operation="write")
        cursor, offset, pending = first_seq, 0, None
        while cursor < last:
            page = records(
                store, project_id, connection_id, after_seq=cursor, limit=100
            )
            _require(
                isinstance(page, list) and 0 < len(page) <= 100,
                "write evidence missing",
            )
            for row in page:
                _require(
                    isinstance(row, dict)
                    and type(row.get("seq")) is int
                    and row["seq"] == cursor + 1
                    and row["seq"] <= last
                    and all(row.get(k) == v for k, v in expected.items()),
                    "write observation sequence or binding differs",
                )
                if row.get("phase") == "intent":
                    _require(
                        pending is None
                        and offset < len(raw)
                        and type(row.get("data")) is bytes
                        and row["data"] == raw[offset:]
                        and row.get("sha256") == sha(raw[offset:]),
                        "write intent suffix differs",
                    )
                    pending = row["seq"]
                else:
                    count = row.get("count")
                    _require(
                        row.get("phase") == "result"
                        and pending is not None
                        and type(row.get("intent_seq")) is int
                        and row["intent_seq"] == pending
                        and row.get("outcome") == "returned"
                        and type(count) is int
                        and 0 < count <= len(raw) - offset
                        and row.get("data") is None
                        and row.get("sha256") is None,
                        "write result differs",
                    )
                    offset += count
                    pending = None
                cursor = row["seq"]
        _require(pending is None and offset == len(raw), "frame write incomplete")
        return dict(
            classification="observed-full-frame-write",
            connection_id=connection_id,
            frame_seq=frame_seq,
            raw_sha256=sha(raw),
            first_seq=first_seq + 1,
            last_seq=last,
            observed_bytes=offset,
        )
