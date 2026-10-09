"""Injected bootstrap context; no launch, authentication proof or automatic start.

A server-owned, version-bound thread/start intent and literal admission are
required. Raw byte/frame observations and callback consent are not authentication.
"""

from copy import deepcopy
from pathlib import Path
import time

from stage1_deliverable.common import canonical, sha
from .frame_journal import FrameJournal, _validated
from .recording import RecordingChannel, records
from .store import _require, _invalidate
from .transport import JsonRpcTransport, _key, _encode


def _rpc_id(value):
    return canonical(list(_key(value))).decode()


class BootstrapContext:
    def __init__(
        self,
        *,
        store,
        project_id,
        owner,
        connection_id,
        index_sha256,
        input_version,
        intent_key,
        channel,
        verify_binding,
        admit_lifecycle,
    ):
        _require(isinstance(store, FrameJournal), "frame journal required")
        _require(
            callable(verify_binding) and callable(admit_lifecycle), "gates required"
        )
        _require(
            isinstance(connection_id, str) and 0 < len(connection_id) <= 128,
            "connection ID required",
        )
        _require(
            isinstance(input_version, str)
            and len(input_version) == 64
            and all(c in "0123456789abcdef" for c in input_version),
            "input version required",
        )
        _require(
            all(
                callable(getattr(channel, n, None)) for n in ("read", "write", "close")
            ),
            "binary channel required",
        )
        self.store, self.project_id, self.owner = store, project_id, owner
        self.connection_id, self.index_sha256 = connection_id, index_sha256
        self.input_version, self.intent_key = input_version, intent_key
        self.verify_binding, self.admit_lifecycle = verify_binding, admit_lifecycle
        self.channel = self.transport = None
        self.failure, self.outgoing, self.thread_id = None, None, None
        with store._lock:
            state = store.snapshot(project_id)
            intent = state["intents"].get(intent_key, {})
            _require(
                state["index_sha256"] == index_sha256
                and state["thread_id"] is None
                and isinstance(state.get("owner"), dict)
                and state["owner"].get("token") == owner
                and store._owners.get(project_id, (None,))[0] == owner,
                "unbound project/index/exclusive owner required",
            )
            _require(
                intent.get("method") == "thread/start"
                and intent.get("status") == "intent-recorded",
                "explicit unsent new-session intent required",
            )
            self.params = deepcopy(intent["payload"])
            _require(
                set(self.params) == {"cwd", "model", "approvalPolicy", "sandbox"}
                and isinstance(self.params["cwd"], str)
                and Path(self.params["cwd"]).is_absolute()
                and isinstance(self.params["model"], str)
                and 0 < len(self.params["model"]) <= 128
                and self.params["approvalPolicy"]
                in {"untrusted", "on-failure", "on-request", "never"}
                and self.params["sandbox"] == "read-only",
                "bounded server thread parameters required",
            )
            _require(
                not state.get("bootstrap")
                and not state.get("protocol")
                and not any(
                    not row.get("fault")
                    for row in state.get("byte_channels", {}).values()
                )
                and not any(
                    row["status"] == "execution-unknown"
                    for name in ("intents", "requests")
                    for row in state[name].values()
                ),
                "existing connection or unresolved bootstrap forbids new dispatch",
            )
            self._allowed("new-session")
            with store._edit(
                project_id, owner, state["revision"], "bootstrap-recorded", {}
            ) as current:
                current["bootstrap"] = dict(
                    connection_id=connection_id,
                    owner=owner,
                    index_sha256=index_sha256,
                    input_version=input_version,
                    intent_key=intent_key,
                    intent_sha256=intent["record_sha256"],
                    phase="recorded",
                    frames=[],
                    correlations={},
                    written={},
                    bytes=0,
                    step=0,
                    expected=None,
                )
            try:
                self.raw_channel = channel
                self.channel = RecordingChannel(
                    channel,
                    store=store,
                    project_id=project_id,
                    owner=owner,
                    connection_id=connection_id,
                )
                self.transport = JsonRpcTransport(
                    self.channel,
                    connection_id=connection_id,
                    verify_binding=self._verify,
                    on_event=self._event,
                    max_message_bytes=262144,
                    max_requests=64,
                    max_pending=8,
                )
            except BaseException as error:
                self._fail(error)

    def _verify(self):
        _require(self.verify_binding() is True, "literal binding confirmation required")
        return True

    def _allowed(self, method):
        self._verify()
        _require(
            self.admit_lifecycle(
                dict(
                    project_id=self.project_id,
                    index_sha256=self.index_sha256,
                    input_version=self.input_version,
                    intent_key=self.intent_key,
                    method=method,
                    params_sha256=sha(canonical(self.params)),
                )
            )
            is True,
            "literal version-bound lifecycle admission required",
        )

    def _context(self):
        state = self.store.snapshot(self.project_id)
        row = state.get("bootstrap", {})
        intent = state["intents"].get(self.intent_key, {})
        _require(
            not self.failure
            and state["index_sha256"] == self.index_sha256
            and isinstance(state.get("owner"), dict)
            and state["owner"].get("token") == self.owner
            and self.store._owners.get(self.project_id, (None,))[0] == self.owner
            and all(
                row.get(n) == getattr(self, n)
                for n in (
                    "owner",
                    "connection_id",
                    "index_sha256",
                    "input_version",
                    "intent_key",
                )
            )
            and row.get("phase") not in {"failed", "adopted"},
            "bootstrap owner/version expired",
        )
        _require(
            intent.get("method") == "thread/start"
            and intent.get("record_sha256") == row.get("intent_sha256")
            and canonical(intent.get("payload")) == canonical(self.params),
            "saved new-session payload differs",
        )
        return state

    def _event(self, envelope):
        event, failure = _validated(envelope)
        _require(failure is None, "bootstrap frame differs")
        self._context()
        self._verify()
        with self.store._edit(
            self.project_id,
            self.owner,
            None,
            "bootstrap-frame",
            dict(frame=event, raw_sha256=sha(event["raw_utf8"].encode())),
        ) as state:
            boot = state["bootstrap"]
            _require(
                boot["connection_id"] == event["connection_id"]
                and boot["owner"] == self.owner,
                "bootstrap frame epoch differs",
            )
            _require(
                len(boot["frames"]) < 32
                and boot["bytes"] + len(event["raw_utf8"].encode()) <= 1048576,
                "bootstrap capture bound exceeded",
            )
            boot["frames"].append(event)
            boot["bytes"] += len(event["raw_utf8"].encode())
            message = event["message"]
            if event["direction"] == "outgoing":
                claim = boot.get("expected")
                _require(
                    isinstance(claim, dict)
                    and claim["message"] == message
                    and claim["raw_utf8"] == event["raw_utf8"]
                    and claim["step"] == boot["step"]
                    and (
                        message.get("method") != "thread/start"
                        or state["intents"][self.intent_key]["status"] == "dispatching"
                    ),
                    "exact saved bootstrap dispatch claim required",
                )
                boot["expected"] = None
                boot["step"] += 1
            if event["kind"] == "request" and event["direction"] == "outgoing":
                key = _rpc_id(message["id"])
                _require(
                    key not in boot["correlations"]
                    and message["method"]
                    in {"initialize", "account/read", "thread/start"},
                    "bootstrap RPC differs",
                )
                boot["correlations"][key] = dict(request=message, response=None)
            elif event["kind"] == "response" and event["direction"] == "incoming":
                correlation = boot["correlations"].get(_rpc_id(message["id"]))
                _require(
                    correlation is not None and correlation["response"] is None,
                    "bootstrap response correlation absent",
                )
                correlation["response"] = message
        if event["kind"] == "request" and event["direction"] == "incoming":
            raise ValueError("bootstrap server request retained; no automatic answer")
        if event["direction"] == "outgoing":
            self.outgoing = event["raw_utf8"].encode()

    def _written(self, first):
        state = self._context()
        last = state["byte_channels"][self.connection_id]["seq"]
        cursor, offset, pending = first, 0, None
        while cursor < last:
            page = records(
                self.store, self.project_id, self.connection_id, after_seq=cursor
            )
            _require(page, "bootstrap write evidence missing")
            for row in page:
                if row["seq"] > last:
                    break
                _require(
                    row["seq"] == cursor + 1
                    and row["operation"] == "write"
                    and row["owner"] == self.owner
                    and row["index_sha256"] == self.index_sha256
                    and row["thread_id"] is None,
                    "bootstrap write binding differs",
                )
                if row["phase"] == "intent":
                    _require(
                        pending is None
                        and row["data"] == self.outgoing[offset:]
                        and row["sha256"] == sha(row["data"]),
                        "bootstrap suffix differs",
                    )
                    pending = row["seq"]
                else:
                    count = row.get("count")
                    _require(
                        row["phase"] == "result"
                        and row.get("intent_seq") == pending
                        and pending is not None
                        and row.get("outcome") == "returned"
                        and type(count) is int
                        and 0 < count <= len(self.outgoing) - offset,
                        "bootstrap partial write unconfirmed",
                    )
                    offset += count
                    pending = None
                cursor = row["seq"]
        _require(
            pending is None and offset == len(self.outgoing),
            "bootstrap full write absent",
        )
        with self.store._edit(
            self.project_id, self.owner, None, "bootstrap-write-observed", {}
        ) as state:
            state["bootstrap"]["written"][sha(self.outgoing)] = dict(
                first_seq=first + 1, last_seq=last, bytes=offset
            )

    def _send(self, method, params, rpc_id, deadline):
        self._allowed(method)
        state = self._context()
        steps = (
            ("initialize", 1),
            ("initialized", None),
            ("account/read", "1"),
            ("thread/start", 2),
        )
        step = state["bootstrap"]["step"]
        _require(
            step < len(steps)
            and steps[step] == (method, rpc_id)
            and state["bootstrap"]["expected"] is None,
            "bootstrap RPC order differs",
        )
        message = {"method": method}
        if rpc_id is not None:
            message.update(id=rpc_id, params=params)
        elif params is not None:
            message["params"] = params
        first = state["byte_channels"][self.connection_id]["seq"]
        with self.store._edit(
            self.project_id,
            self.owner,
            state["revision"],
            "bootstrap-dispatch-claimed",
            {},
        ) as saved:
            saved["bootstrap"]["expected"] = dict(
                message=message, raw_utf8=(_encode(message) + b"\n").decode(), step=step
            )
        if rpc_id is None:
            self.transport.notify(method, timeout=max(0, deadline - time.monotonic()))
        else:
            self.transport.send_request(
                method,
                params,
                request_id=rpc_id,
                timeout=max(0, deadline - time.monotonic()),
            )
        self._written(first)
        if rpc_id is not None:
            reply = self.transport.wait_response(
                rpc_id, timeout=max(0, deadline - time.monotonic())
            )
            _require(
                "error" not in reply and isinstance(reply.get("result"), dict),
                "bootstrap RPC rejected",
            )
            return reply["result"]

    def _fail(self, error):
        self.failure = "bootstrap failed; no automatic resend"
        try:
            with self.store._edit(
                self.project_id,
                self.owner,
                None,
                "bootstrap-failed",
                {"exception_type": type(error).__name__},
            ) as state:
                _invalidate(state)
                state["bootstrap"].update(
                    phase="failed", failure_type=type(error).__name__
                )
        except BaseException:
            self.failure += "; failure persistence unobserved"
        finally:
            cleanup = dict(
                attempted=True, route="recorded" if self.channel is not None else "raw"
            )
            try:
                if self.transport is not None:
                    self.transport.close()
                elif self.channel is not None:
                    self.channel.close()
                else:
                    _require(
                        self.raw_channel.close() is None, "raw close return differs"
                    )
                cleanup["returned"] = True
            except BaseException as close_error:
                cleanup["exception_type"] = type(close_error).__name__
                self.failure += "; cleanup persistence unobserved"
            try:
                with self.store._edit(
                    self.project_id, self.owner, None, "bootstrap-cleanup", cleanup
                ) as state:
                    state["bootstrap"]["cleanup"] = cleanup
            except BaseException:
                self.failure += "; cleanup journal unobserved"
        raise ValueError(self.failure) from error
