"""Bounded read-only native history pagination; no replay or launch authority."""

import time

from .transport import TransportError, _deadline, _require


def reconcile_thread(
    transport,
    thread_id,
    request_id_factory,
    *,
    timeout=10,
    max_pages=100,
    max_records=10000,
):
    """Exhaust bounded cursors, not an atomic snapshot or proof of execution."""
    _require(isinstance(thread_id, str) and thread_id, "thread ID required")
    _require(
        type(max_pages) is int
        and max_pages > 0
        and type(max_records) is int
        and max_records > 0,
        "invalid history bounds",
    )
    deadline = _deadline(timeout)

    def read(method, params):
        response = transport.request(
            method,
            params,
            request_id=request_id_factory(),
            timeout=max(0, deadline - time.monotonic()),
        )
        _require(isinstance(response.get("result"), dict), "native history read failed")
        return response["result"]

    thread = read("thread/read", {"threadId": thread_id, "includeTurns": False})
    _require(
        isinstance(thread.get("thread"), dict)
        and thread["thread"].get("id") == thread_id,
        "history thread mismatch",
    )
    result = {"thread": thread["thread"], "turns": [], "items": []}
    for kind in ("turns", "items"):
        cursor, seen = None, set()
        for _ in range(max_pages):
            params = {"threadId": thread_id, "limit": 100, "sortDirection": "asc"}
            if kind == "turns":
                params["itemsView"] = "notLoaded"
            if cursor is not None:
                params["cursor"] = cursor
            page = read("thread/" + kind + "/list", params)
            _require(
                isinstance(page.get("data"), list) and "nextCursor" in page,
                "incomplete history page",
            )
            result[kind].extend(page["data"])
            _require(len(result[kind]) <= max_records, "history record bound exceeded")
            cursor = page["nextCursor"]
            if cursor is None:
                break
            _require(
                isinstance(cursor, str) and cursor and cursor not in seen,
                "repeated or invalid history cursor",
            )
            seen.add(cursor)
        else:
            raise TransportError(
                "history page bound exceeded; reconciliation incomplete"
            )
    _require(
        all(
            isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]
            for row in result["turns"]
        ),
        "invalid history turn identity",
    )
    _require(
        all(
            isinstance(row, dict)
            and isinstance(row.get("turnId"), str)
            and row["turnId"]
            and isinstance(row.get("item"), dict)
            and isinstance(row["item"].get("id"), str)
            and row["item"]["id"]
            for row in result["items"]
        ),
        "invalid history item identity",
    )
    turns = [row["id"] for row in result["turns"]]
    items = [(row["turnId"], row["item"]["id"]) for row in result["items"]]
    _require(
        len(set(turns)) == len(turns) and len(set(items)) == len(items),
        "duplicate history identity",
    )
    _require(
        all(turn_id in turns for turn_id, _ in items), "item has an unobserved turn"
    )
    return result
