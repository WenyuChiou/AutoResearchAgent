"""Explicit new-thread lifecycle and same-transport handoff; injected tests only.

No launcher, authentication attestation, resume, model turn or execution permit
is provided. A trusted server records a version-bound thread/start intent first.
"""

import os

from stage1_deliverable.common import canonical, sha
from .bootstrap_context import BootstrapContext, _rpc_id
from .frame_journal import _validated
from .store import _require
from .transport import _deadline, _encode


def _cwd_matches(observed, requested, *, windows=None):
    if not isinstance(observed, str) or not isinstance(requested, str):
        return False
    if windows is None:
        windows = os.name == "nt"
    # Only separators vary. Do not normalize case, dot segments, aliases or roots.
    if windows:
        return observed.replace("\\", "/") == requested.replace("\\", "/")
    return observed == requested


def _account(value):
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    kind = value.get("type")
    if kind == "apiKey":
        return set(value) == {"type"}
    if kind == "amazonBedrock":
        return (
            set(value) == {"type", "usesCodexManagedCredentials"}
            and type(value["usesCodexManagedCredentials"]) is bool
        )
    return (
        kind == "chatgpt"
        and set(value) == {"type", "email", "planType"}
        and (value["email"] is None or isinstance(value["email"], str))
        and value["planType"]
        in {
            "free",
            "go",
            "plus",
            "pro",
            "prolite",
            "team",
            "self_serve_business_prolite",
            "self_serve_business_usage_based",
            "business",
            "ent26",
            "enterprise_cbp_automation",
            "enterprise_cbp_usage_based",
            "enterprise",
            "edu",
            "edu_plus",
            "edu_pro",
            "unknown",
        }
    )


class BootstrapSession(BootstrapContext):
    def open_thread(self, client_info, *, timeout=10, total_timeout=None):
        _deadline(timeout)  # Validate finite/nonboolean before any I/O.
        _require(0 < timeout <= 30, "bootstrap deadline must be within 30 seconds")
        budget = timeout if total_timeout is None else total_timeout
        deadline = _deadline(budget)
        _require(timeout <= budget <= 120, "bounded total handshake timeout required")

        def step_deadline():
            return min(deadline, _deadline(timeout))

        with self.store._lock:
            _require(
                self.store.snapshot(self.project_id).get("bootstrap", {}).get("phase")
                == "recorded"
                and not self.failure,
                "bootstrap is single-use",
            )
            try:
                self._context()
                hello = self._send(
                    "initialize", {"clientInfo": client_info}, 1, step_deadline()
                )
                _require(
                    isinstance(hello.get("userAgent"), str) and hello["userAgent"],
                    "invalid hello",
                )
                self._send("initialized", None, None, step_deadline())
                self.transport.initialized = True
                account = self._send(
                    "account/read", {"refreshToken": False}, "1", step_deadline()
                )
                _require(
                    type(account.get("requiresOpenaiAuth")) is bool
                    and "account" in account
                    and _account(account["account"]),
                    "invalid account observation",
                )
                _require(
                    not account["requiresOpenaiAuth"]
                    or account.get("account") is not None,
                    "login required; thread/start not dispatched",
                )
                self._allowed("thread/start")
                state = self._context()
                dispatched = self.store.transition_intent(
                    self.project_id,
                    self.owner,
                    self.intent_key,
                    "dispatching",
                    {"lifecycle_admission": "caller-permitted"},
                    state["revision"],
                )
                _require(
                    dispatched["status"] == "dispatching", "bootstrap dispatch refused"
                )
                result = self._send("thread/start", self.params, 2, step_deadline())
                _require(
                    isinstance(result.get("thread"), dict)
                    and isinstance(result["thread"].get("id"), str)
                    and result["thread"]["id"]
                    and _cwd_matches(result.get("cwd"), self.params["cwd"])
                    and result.get("model") == self.params["model"]
                    and result.get("approvalPolicy") == self.params["approvalPolicy"]
                    and isinstance(result.get("sandbox"), dict)
                    and set(result["sandbox"]) == {"type", "networkAccess"}
                    and result["sandbox"]["type"] == "readOnly"
                    and result["sandbox"]["networkAccess"] is False,
                    "thread response binding differs",
                )
                self.thread_id = result["thread"]["id"]
                state = self._context()
                for frame in state["bootstrap"]["frames"]:
                    if frame["message"].get("method") == "thread/started":
                        _require(
                            frame["message"]
                            .get("params", {})
                            .get("thread", {})
                            .get("id")
                            == self.thread_id,
                            "thread notification differs",
                        )
                self.store.transition_intent(
                    self.project_id,
                    self.owner,
                    self.intent_key,
                    "completed",
                    {
                        "thread_id": self.thread_id,
                        "bootstrap_connection": self.connection_id,
                        "reply_sha256": sha(canonical(result)),
                    },
                    state["revision"],
                )
                self.store.bind_thread(
                    self.project_id,
                    self.owner,
                    self.thread_id,
                    self.store.snapshot(self.project_id)["revision"],
                )
                with self.store._edit(
                    self.project_id, self.owner, None, "bootstrap-ready", {}
                ) as state:
                    state["bootstrap"]["phase"] = "ready"
                return self
            except BaseException as error:
                self._fail(error)

    def _adopt(self, controller_type, admit_action):
        with self.store._lock:
            saved = self.store.snapshot(self.project_id).get("bootstrap", {})
            _require(
                saved.get("phase") == "ready" and not self.failure,
                "ready session is single-use",
            )
            try:
                _require(callable(admit_action), "action admission required")
                state = self._context()
                channel = state["byte_channels"].get(self.connection_id, {})
                _require(
                    state["bootstrap"]["phase"] == "ready"
                    and state["thread_id"] == self.thread_id
                    and self.transport.initialized
                    and not self.transport.failure
                    and not self.transport.pending
                    and not self.transport.responses
                    and not self.transport.native
                    and channel.get("owner") == self.owner
                    and not channel.get("fault")
                    and not channel.get("pending")
                    and not self.channel.closed
                    and not any(
                        k != self.connection_id and not v.get("fault")
                        for k, v in state["byte_channels"].items()
                    ),
                    "ready transport required",
                )
                self._allowed("handoff")
                controller = controller_type.__new__(controller_type)
                for name in (
                    "store",
                    "project_id",
                    "owner",
                    "connection_id",
                    "index_sha256",
                    "thread_id",
                    "channel",
                    "transport",
                ):
                    setattr(controller, name, getattr(self, name))
                controller.admit_action, controller.failure, controller.outgoing = (
                    admit_action,
                    None,
                    None,
                )
                self.store.bind_connection(
                    self.project_id, self.owner, self.connection_id, state["revision"]
                )
                with self.store._edit(
                    self.project_id, self.owner, None, "bootstrap-adopted", {}
                ) as state:
                    state["bootstrap"]["phase"] = "adopted"
                self.transport.on_event = controller._event
                controller._context()
                return controller
            except BaseException as error:
                self._fail(error)

    @staticmethod
    def recover_thread(
        store, project_id, owner, *, index_sha256, input_version, verify_binding
    ):
        """Complete only a saved local bind after a crash; never reopen or send."""
        with store._lock:
            state = store.snapshot(project_id)
            boot = state.get("bootstrap", {})
            intent = state["intents"].get(boot.get("intent_key"), {})
            correlation = boot.get("correlations", {}).get(_rpc_id(2), {})
            request = correlation.get("request", {})
            response = correlation.get("response", {})
            result = response.get("result", {})
            _require(
                callable(verify_binding)
                and verify_binding() is True
                and state["index_sha256"] == index_sha256
                and boot.get("input_version") == input_version
                and intent.get("method") == "thread/start"
                and intent.get("status") == "completed"
                and intent.get("record_sha256") == boot.get("intent_sha256")
                and type(request.get("id")) is int
                and request["id"] == 2
                and request.get("method") == "thread/start"
                and canonical(request.get("params")) == canonical(intent.get("payload"))
                and type(response.get("id")) is int
                and response["id"] == 2
                and "error" not in response
                and intent.get("evidence", {}).get("reply_sha256")
                == sha(canonical(result))
                and result.get("thread", {}).get("id")
                == intent.get("evidence", {}).get("thread_id")
                and sha(_encode(correlation.get("request")) + b"\n")
                in boot.get("written", {})
                and any(
                    frame.get("direction") == "incoming"
                    and frame.get("message") == response
                    and _validated(frame)[1] is None
                    for frame in boot.get("frames", [])
                ),
                "completed bootstrap reply required; no native recovery authority",
            )
            return store.bind_thread(
                project_id, owner, result["thread"]["id"], state["revision"]
            )
