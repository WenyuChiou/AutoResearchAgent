"""Persistent injected JSON-RPC; no native launcher or execution admission."""

from copy import deepcopy
import json
import math
import time

PROTOCOL_COMMIT = "b5d805789d4033c911868f49118a264a7ab3d067"
SERVER_METHODS = {
    "item/tool/requestUserInput",
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}


class TransportError(ValueError):
    """Rejected input or a known pre-dispatch failure."""


class DispatchUnknown(TransportError):
    """Connection unusable; native outcomes require reconciliation, never resend."""


def _require(condition, message):
    if not condition:
        raise TransportError(message)


def _key(value):
    _require(type(value) in (int, str), "RPC ID must be an integer or string")
    if type(value) is int:
        _require(-(2**63) <= value < 2**63, "RPC integer ID is outside i64")
    return type(value).__name__, value


def _encode(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise TransportError("message must be finite UTF-8 JSON") from error


def _deadline(timeout):
    _require(
        type(timeout) in (int, float) and math.isfinite(timeout) and timeout >= 0,
        "finite nonnegative timeout required",
    )
    return time.monotonic() + timeout


def _decode(raw):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            _require(name not in result, "duplicate JSON key")
            result[name] = value
        return result

    def invalid(_):
        raise TransportError("non-finite JSON number")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    _encode(value)  # Reject numeric overflow such as 1e1000 as well as NaN literals.
    return value


def validate_answer(request, result):
    """Validate a response without dispatch or recording; return detached JSON."""
    method = request["method"]
    _require(
        method in SERVER_METHODS and isinstance(result, dict),
        "unsupported server response",
    )
    if method == "item/tool/requestUserInput":
        questions = [row["id"] for row in request["params"]["questions"]]
        _require(
            all(isinstance(value, str) and value for value in questions)
            and len(set(questions)) == len(questions),
            "invalid question IDs",
        )
        _require(
            set(result) == {"answers"} and isinstance(result["answers"], dict),
            "invalid answers",
        )
        _require(set(result["answers"]) == set(questions), "question IDs differ")
        for answer in result["answers"].values():
            _require(
                isinstance(answer, dict) and set(answer) == {"answers"},
                "invalid answer shape",
            )
            _require(
                isinstance(answer["answers"], list)
                and all(isinstance(value, str) for value in answer["answers"]),
                "answers must be strings",
            )
    else:
        _require(
            set(result) == {"decision"}
            and result["decision"] in ("accept", "decline", "cancel"),
            "only explicit one-request decisions are supported",
        )
    _encode(result)
    return deepcopy(result)


class JsonRpcTransport:
    """Single-owner pump over a deadline-aware binary channel.

    Channel read(size, timeout) returns bytes (empty means EOF); write(data,
    timeout) returns the written count. Both MUST honor the supplied deadline
    and raise TimeoutError on expiry. close() MUST be nonblocking. Plain file
    pipes do not satisfy this contract. The caller owns lifecycle containment.
    on_event must durably save its record before returning. verify_binding must
    raise on drift and runs before each write; it does not grant execution
    authority or attest a Windows process. No implicit retry,
    reconnect, thread creation, model dispatch, or native process launch exists.
    """

    def __init__(
        self,
        channel,
        *,
        connection_id,
        on_event,
        verify_binding,
        max_message_bytes=1024 * 1024,
        max_pending=64,
        max_requests=10000,
    ):
        _require(
            isinstance(connection_id, str) and connection_id, "connection ID required"
        )
        _require(callable(on_event), "durable event sink required")
        _require(callable(verify_binding), "runtime binding verifier required")
        _require(
            all(
                type(value) is int and value > 0
                for value in (max_message_bytes, max_pending, max_requests)
            ),
            "invalid bounds",
        )
        self.channel, self.connection_id, self.on_event = (
            channel,
            connection_id,
            on_event,
        )
        self.verify_binding = verify_binding
        self.max_message_bytes, self.max_pending = max_message_bytes, max_pending
        self.max_requests = max_requests
        self.buffer, self.failure = b"", None
        self.pending, self.responses, self.native = {}, {}, {}
        self.used, self.native_used, self.answered = set(), set(), set()
        self.initialized = False

    def _healthy(self):
        if self.failure:
            raise DispatchUnknown(self.failure)

    def _fail(self, reason):
        self.failure = reason
        try:
            self.channel.close()
        except Exception:
            pass  # Preserve the original ambiguous outcome.
        raise DispatchUnknown(reason)

    def _event(self, direction, kind, message, raw):
        record = {
            "connection_id": self.connection_id,
            "direction": direction,
            "kind": kind,
            "message": deepcopy(message),
            "raw_utf8": raw.decode("utf-8"),
        }
        self.on_event(record)
        return record

    def _send(self, message, kind, timeout):
        self._healthy()
        deadline = _deadline(timeout)
        _require(timeout > 0, "positive timeout required")
        raw = _encode(message) + b"\n"
        _require(len(raw) <= self.max_message_bytes, "outgoing message bound exceeded")
        if kind == "request":
            key = _key(message["id"])
            self.used.add(key)
            self.pending[key] = message["method"]
        try:
            self._event("outgoing", kind, message, raw)
        except Exception as error:
            raise TransportError("event persistence failed before dispatch") from error
        offset = 0
        while offset < len(raw):
            try:
                _require(self.verify_binding() is not False, "runtime binding rejected")
            except Exception as error:
                if offset:
                    self._fail("runtime binding changed after partial dispatch")
                raise TransportError(
                    "runtime binding failed before dispatch"
                ) from error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail("write timeout; dispatch outcome unknown")
            try:
                count = self.channel.write(raw[offset:], remaining)
                _require(
                    type(count) is int and 0 < count <= len(raw) - offset,
                    "invalid write count",
                )
                offset += count
            except Exception:
                self._fail("write failed; dispatch outcome unknown")

    def send_request(self, method, params, *, request_id, timeout=10):
        self._healthy()
        key = _key(request_id)
        _require(
            isinstance(method, str) and method and isinstance(params, dict),
            "invalid request",
        )
        _require(key not in self.used, "RPC ID already used; resend forbidden")
        _require(
            len(self.used) < self.max_requests, "connection request bound exceeded"
        )
        _require(
            len(self.pending) + len(self.responses) < self.max_pending,
            "pending request bound exceeded",
        )
        try:
            self._send(
                {"id": request_id, "method": method, "params": params},
                "request",
                timeout,
            )
        except TransportError:
            self.pending.pop(key, None)
            raise
        return request_id

    def notify(self, method, params=None, *, timeout=10):
        _require(isinstance(method, str) and method, "notification method required")
        message = {"method": method}
        if params is not None:
            message["params"] = params
        self._send(message, "notification", timeout)

    def poll(self, timeout=0):
        """Persist and route one frame; an idle timeout returns None."""
        self._healthy()
        deadline = _deadline(timeout)
        try:
            while b"\n" not in self.buffer:
                _require(
                    len(self.buffer) < self.max_message_bytes,
                    "incoming message bound exceeded",
                )
                size = min(4096, self.max_message_bytes - len(self.buffer))
                try:
                    chunk = self.channel.read(size, max(0, deadline - time.monotonic()))
                except TimeoutError:
                    return None
                _require(isinstance(chunk, bytes) and chunk, "connection ended")
                _require(len(chunk) <= size, "channel exceeded read bound")
                self.buffer += chunk
                if time.monotonic() > deadline and b"\n" not in self.buffer:
                    return None
            raw, self.buffer = self.buffer.split(b"\n", 1)
            _require(
                len(raw) + 1 <= self.max_message_bytes,
                "incoming message bound exceeded",
            )
            message = _decode(raw)
            _require(isinstance(message, dict), "RPC frame must be an object")
            if "method" in message:
                _require(isinstance(message["method"], str), "invalid RPC method")
                _require(
                    not ({"result", "error"} & message.keys()), "ambiguous RPC frame"
                )
                kind = "request" if "id" in message else "notification"
                if kind == "request":
                    key = _key(message["id"])
                    _require(
                        key not in self.native_used
                        and len(self.native_used) < self.max_requests
                        and len(self.native) < self.max_pending,
                        "reused or excessive server request",
                    )
                    _require(
                        isinstance(message.get("params"), dict),
                        "server request params required",
                    )
                    if message["method"] in SERVER_METHODS:
                        params = message["params"]
                        _require(
                            all(
                                isinstance(params.get(name), str) and params[name]
                                for name in ("threadId", "turnId", "itemId")
                            ),
                            "invalid native request identity",
                        )
                        if message["method"] == "item/commandExecution/requestApproval":
                            _require(
                                params.get("approvalId") is None
                                or isinstance(params["approvalId"], str),
                                "invalid approval ID",
                            )
                        if message["method"] == "item/tool/requestUserInput":
                            questions = params.get("questions")
                            _require(
                                isinstance(questions, list)
                                and all(
                                    isinstance(row, dict)
                                    and isinstance(row.get("id"), str)
                                    and row["id"]
                                    for row in questions
                                ),
                                "invalid native questions",
                            )
                            _require(
                                len({row["id"] for row in questions}) == len(questions),
                                "duplicate native question ID",
                            )
            else:
                kind, key = "response", _key(message.get("id"))
                _require(
                    key in self.pending
                    and (("result" in message) != ("error" in message)),
                    "unmatched or ambiguous response",
                )
            record = self._event("incoming", kind, message, raw + b"\n")
            if kind == "request":
                self.native[key] = message
                self.native_used.add(key)
            elif kind == "response":
                self.pending.pop(key)
                self.responses[key] = message
            elif message["method"] == "serverRequest/resolved":
                params = message["params"]
                key = _key(params["requestId"])
                if key in self.native:
                    _require(
                        params["threadId"] == self.native[key]["params"]["threadId"],
                        "resolved request thread mismatch",
                    )
                    self.native.pop(key)
                    self.answered.discard(key)
            return record
        except Exception:
            self._fail("invalid or lost incoming frame; reconciliation required")

    def wait_response(self, request_id, *, timeout=10):
        self._healthy()
        key, deadline = _key(request_id), _deadline(timeout)
        _require(key in self.pending or key in self.responses, "unknown client request")
        while key not in self.responses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail("response timeout; dispatch outcome unknown")
            self.poll(remaining)
        return deepcopy(self.responses.pop(key))

    def request(self, method, params, *, request_id, timeout=10):
        deadline = _deadline(timeout)
        self.send_request(method, params, request_id=request_id, timeout=timeout)
        return self.wait_response(
            request_id, timeout=max(0, deadline - time.monotonic())
        )

    def initialize(self, client_info, *, request_id, timeout=10):
        _require(not self.initialized, "already initialized")
        response = self.request(
            "initialize",
            {"clientInfo": client_info},
            request_id=request_id,
            timeout=timeout,
        )
        _require("result" in response, "initialization rejected")
        self.notify("initialized", timeout=timeout)
        self.initialized = True
        return response

    def pending_requests(self):
        return [
            {"connection_id": self.connection_id, "request": deepcopy(row)}
            for row in self.native.values()
        ]

    def answer(self, request_id, result, *, binding, timeout=10):
        self._healthy()
        key = _key(request_id)
        _require(
            key in self.native and key not in self.answered,
            "server request is absent or already answered",
        )
        request = self.native[key]
        expected = {"connection_id": self.connection_id, "request": request}
        _require(
            _encode(binding) == _encode(expected), "stale or altered request binding"
        )
        result = validate_answer(request, result)
        self._send({"id": request_id, "result": result}, "response", timeout)
        self.answered.add(key)

    def close(self):
        self.failure = "connection closed; unsettled outcomes require reconciliation"
        self.channel.close()
