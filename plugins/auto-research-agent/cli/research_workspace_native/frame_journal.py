"""Atomic complete-frame evidence, without a controller, launcher or write receipt.

Only turn/start and turn/interrupt client RPCs are correlated, not initialization.
Outgoing frames prove send intent, never full delivery. Other incoming notices
are passive observations. Malformed channel bytes are out of scope.
"""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, sha
from .journal import Journal, JournalError, _identity, _native_id, _rpc_key, _thread
from .store import _require, _invalidate
from .transport import SERVER_METHODS, _decode, _encode


def _record(key, method, payload, identity, status, evidence):
    record = dict(key=key, method=method, payload=payload, request_identity=identity)
    return dict(
        record, record_sha256=sha(canonical(record)), status=status, evidence=evidence
    )


def _unknown(state):
    return any(
        row["status"] == "execution-unknown"
        for name in ("intents", "requests")
        for row in state[name].values()
    )


def _validated(event):
    """Validate complete UTF-8 JSON frames; preserve whitespace and the newline."""
    _require(
        isinstance(event, dict)
        and set(event) == {"connection_id", "direction", "kind", "message", "raw_utf8"},
        "invalid frame envelope",
    )
    raw = event["raw_utf8"]
    _require(
        isinstance(raw, str) and raw.endswith("\n") and "\n" not in raw[:-1],
        "complete frame required",
    )
    try:
        _require(len(raw.encode("utf-8")) <= 1024 * 1024, "frame bound exceeded")
        message = _decode(raw)
        mismatch = _encode(message) != _encode(event["message"])
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise JournalError("invalid complete frame: " + str(error)) from error
    _require(isinstance(message, dict), "frame must contain an object")
    _require(
        isinstance(event["connection_id"], str) and event["connection_id"],
        "connection ID required",
    )
    _require(event["direction"] in ("incoming", "outgoing"), "invalid frame direction")
    if "method" in message:
        _require(
            isinstance(message["method"], str) and message["method"], "method required"
        )
        _require(not ({"result", "error"} & message.keys()), "ambiguous frame")
        kind = "request" if "id" in message else "notification"
        if kind == "request":
            _require(isinstance(message.get("params"), dict), "request params required")
    else:
        kind = "response"
        _require(("result" in message) != ("error" in message), "ambiguous response")
    if kind != "notification":
        _native_id(message.get("id"))
    failure = (
        "raw/message mismatch"
        if mismatch
        else "frame kind mismatch"
        if event["kind"] != kind
        else None
    )
    return deepcopy(event), failure


class FrameJournal(Journal):
    @staticmethod
    def _context(state, owner, connection_id):
        protocol = state.get("protocol", {})
        expected = dict(
            connection_id=connection_id,
            owner=owner,
            index_sha256=state["index_sha256"],
            thread_id=state["thread_id"],
        )
        _require(
            protocol.get("binding") == expected, "connection/project binding differs"
        )
        _require(not protocol.get("quarantine"), "connection quarantined")
        return protocol

    def bind_connection(self, project_id, owner, connection_id, expected_revision):
        _require(
            isinstance(connection_id, str) and connection_id, "connection ID required"
        )
        with self._edit(
            project_id,
            owner,
            expected_revision,
            "connection-bound",
            {"connection_id": connection_id},
        ) as state:
            _require(state["thread_id"] is not None, "existing thread binding required")
            for row in self.db.execute("SELECT state FROM projects"):
                used = json.loads(row[0]).get("protocol", {})
                _require(
                    connection_id not in used.get("connections", [])
                    and all(
                        c["binding"]["connection_id"] != connection_id
                        for c in used.get("correlations", {}).values()
                    ),
                    "connection ID already bound",
                )
            protocol = state.setdefault(
                "protocol", dict(frame_seq=0, connections=[], correlations={})
            )
            if protocol["connections"] or protocol["correlations"]:
                _invalidate(state)
            protocol["connections"].append(connection_id)
            protocol["quarantine"] = None
            protocol["binding"] = dict(
                connection_id=connection_id,
                owner=owner,
                index_sha256=state["index_sha256"],
                thread_id=state["thread_id"],
            )
        return self.snapshot(project_id)["protocol"]

    def correlate(
        self, project_id, owner, connection_id, rpc_id, intent_key, expected_revision
    ):
        key = _rpc_key(connection_id, rpc_id)
        with self._edit(
            project_id,
            owner,
            expected_revision,
            "rpc-correlated",
            {
                "connection_id": connection_id,
                "rpc_id": rpc_id,
                "intent_key": intent_key,
            },
        ) as state:
            self._context(state, owner, connection_id)
            _require(
                not _unknown(state), "reconcile execution-unknown before correlation"
            )
            self._bind_rpc(state, owner, connection_id, rpc_id, intent_key)
        return self.snapshot(project_id)["protocol"]["correlations"][key]

    def ingest_frame(self, project_id, owner, event):
        event, mismatch = _validated(event)
        payload = dict(frame=event, raw_sha256=sha(event["raw_utf8"].encode("utf-8")))
        failure = None
        with self._edit(project_id, owner, None, "protocol-frame", payload) as state:
            protocol = state.setdefault(
                "protocol", dict(frame_seq=0, connections=[], correlations={})
            )
            seq = protocol["frame_seq"] + 1
            evidence = dict(frame_seq=seq, raw_sha256=payload["raw_sha256"])
            candidate = deepcopy(state)
            try:
                _require(mismatch is None, mismatch)
                self._context(candidate, owner, event["connection_id"])
                self._apply(candidate, event, evidence)
            except (JournalError, KeyError, TypeError, ValueError) as error:
                failure = str(error)
                _invalidate(state)
                state["protocol"]["quarantine"] = dict(frame_seq=seq, reason=failure)
            else:
                state.clear()
                state.update(candidate)
            state["protocol"]["frame_seq"] = seq
            payload.update(frame_seq=seq, quarantine=failure)
        if failure is not None:
            raise JournalError("frame saved in quarantine: " + failure)
        return self.snapshot(project_id)

    @staticmethod
    def _request(state, connection_id, native_id):
        key = _rpc_key(connection_id, native_id)
        matches = [
            row
            for row in state["requests"].values()
            if _rpc_key(
                row["request_identity"]["connection_id"],
                row["request_identity"]["native_id"],
            )
            == key
        ]
        _require(len(matches) == 1, "native request identity not found")
        return matches[0]

    def _apply(self, state, event, evidence):
        message, connection_id = event["message"], event["connection_id"]
        kind, incoming = event["kind"], event["direction"] == "incoming"
        if kind == "response" and incoming:
            self._response(state, connection_id, message, evidence)
            return
        if kind == "request" and not incoming:
            row = state["protocol"]["correlations"].get(
                _rpc_key(connection_id, message["id"])
            )
            _require(
                row is not None and not row["outgoing"], "uncorrelated or repeated send"
            )
            _require(
                canonical(row["binding"]["request"]) == canonical(message),
                "outgoing RPC differs",
            )
            item = state["intents"][row["binding"]["intent_key"]]
            self._bound_rpc(state, item, dispatch=True)
            _require(
                item["status"] == "dispatching" and not _unknown(state),
                "dispatch blocked",
            )
            row["outgoing"] = True
            return
        if kind == "response":
            request = self._request(state, connection_id, message["id"])
            _require(
                request["status"] == "pending" and "error" not in message,
                "response request is not pending",
            )
            answers = [
                row
                for row in state["intents"].values()
                if row["request_identity"] == request["request_identity"]
            ]
            _require(
                len(answers) == 1 and answers[0]["status"] == "dispatching",
                "answer intent required",
            )
            answer = answers[0]
            _require(
                canonical(answer["payload"]) == canonical(message["result"]),
                "answer payload differs",
            )
            _require(
                "response_frame" not in answer and not _unknown(state),
                "answer resend forbidden",
            )
            answer["response_frame"] = (
                evidence  # Pre-write observation, not answer-sent.
            )
            return
        params, method = message.get("params", {}), message["method"]
        if kind == "notification":
            _require(incoming, "unsupported outgoing notification")
            _require(isinstance(params, dict), "notification params must be an object")
            if "threadId" in params:
                _require(
                    params["threadId"] == state["thread_id"],
                    "notification thread differs",
                )
            if "thread" in params:
                _require(
                    isinstance(params["thread"], dict)
                    and params["thread"].get("id") == state["thread_id"],
                    "notification thread object differs",
                )
            if method not in {"serverRequest/resolved", "turn/completed"}:
                return  # Passive observations grant no dispatch or terminal authority.
        _require(
            incoming and params.get("threadId") == state["thread_id"],
            "incoming thread differs",
        )
        if kind == "request":
            _require(method in SERVER_METHODS, "unsupported native request")
            identity = dict(
                connection_id=connection_id,
                native_id=message["id"],
                thread_id=params["threadId"],
                turn_id=params.get("turnId"),
                item_id=params.get("itemId"),
                approval_id=params.get("approvalId"),
            )
            key = _identity(identity)
            if method == "item/tool/requestUserInput":
                questions = params.get("questions")
                _require(
                    isinstance(questions, list)
                    and all(
                        isinstance(q, dict) and isinstance(q.get("id"), str) and q["id"]
                        for q in questions
                    ),
                    "invalid question identities",
                )
                _require(
                    len({q["id"] for q in questions}) == len(questions),
                    "duplicate question identity",
                )
            record = _record(key, method, params, identity, "pending", evidence)
            for old in state["requests"].values():
                old_identity = old["request_identity"]
                if _rpc_key(
                    old_identity["connection_id"], old_identity["native_id"]
                ) == _rpc_key(connection_id, message["id"]):
                    _require(
                        old["record_sha256"] == record["record_sha256"],
                        "reused native request ID",
                    )
                    return
            state["requests"][key] = record
        elif method == "serverRequest/resolved":
            request = self._request(state, connection_id, params.get("requestId"))
            if request["status"] != "request-resolved":
                request.update(status="request-resolved", evidence=evidence)
        elif method == "turn/completed":
            _thread(state, params)
            turn = params.get("turn")
            _require(
                isinstance(turn, dict)
                and isinstance(turn.get("id"), str)
                and turn["id"],
                "terminal turn identity required",
            )
            _require(
                turn.get("status") in {"completed", "failed", "interrupted"},
                "turn is not terminal",
            )
            record = _record(
                turn["id"], turn["status"], params, None, turn["status"], evidence
            )
            old = state["turns"].get(turn["id"])
            _require(
                old is None or old["record_sha256"] == record["record_sha256"],
                "terminal evidence differs",
            )
            state["turns"].setdefault(turn["id"], record)
            for item in state["intents"].values():
                if (
                    item["status"] == "dispatched"
                    and item.get("native_turn_id") == turn["id"]
                ):
                    self._finish(state, item, evidence)

    def _response(self, state, connection_id, message, evidence):
        row = state["protocol"]["correlations"].get(
            _rpc_key(connection_id, message["id"])
        )
        _require(row is not None and row["outgoing"], "response correlation absent")
        _require("error" not in message, "RPC error; execution outcome remains unknown")
        if row["response"] is not None:
            _require(
                canonical(row["response"]) == canonical(message), "RPC response differs"
            )
            return
        item = state["intents"][row["binding"]["intent_key"]]
        _require(
            item["record_sha256"] == row["binding"]["intent_sha256"]
            and item["status"] == "dispatching",
            "response intent differs",
        )
        result = message.get("result")
        _require(isinstance(result, dict), "RPC result must be an object")
        turn_id = item["payload"].get("turnId")
        if item["method"] == "turn/start":
            _require(isinstance(result.get("turn"), dict), "response turn required")
            turn_id = result["turn"].get("id")
        receipt = dict(
            evidence,
            connection_id=connection_id,
            native_turn_id=turn_id,
            rpc_receipt=message,
        )
        self._completion_binding(state, item, "dispatched", receipt)
        item.update(status="dispatched", evidence=receipt)
        row["response"] = message
        if turn_id in state["turns"]:
            self._finish(state, item, evidence)

    def _finish(self, state, item, evidence):
        receipt = dict(evidence, native_turn_id=item["native_turn_id"])
        self._completion_binding(state, item, "completed", receipt)
        item.update(status="completed", evidence=receipt)
