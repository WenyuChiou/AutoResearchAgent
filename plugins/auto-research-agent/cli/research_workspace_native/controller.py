"""Existing-thread injected controller; no launcher, handshake, API or admission.

The owner's admission callback and byte verifier are mandatory, not proof of
authority. Complete write observations are not authenticated native delivery.
No reconnect, automatic resend, thread import/create, or history RPC is exposed.
"""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha
from .construction import BoundControllerContext, ControllerError, _mirror_unknown
from .journal import _identity
from .store import _invalidate, _require
from .transport import DispatchUnknown, TransportError, _encode
from .transport import _key, validate_answer
from .write_observation import observe_frame_write


class InjectedSessionController(BoundControllerContext):
    @classmethod
    def adopt_ready(cls, ready, *, admit_action):
        from .bootstrap import BootstrapSession

        _require(
            cls is InjectedSessionController and type(ready) is BootstrapSession,
            "server-owned bootstrap session required",
        )
        return ready._adopt(cls, admit_action)

    def __init__(
        self,
        *,
        store,
        project_id,
        owner,
        connection_id,
        index_sha256,
        thread_id,
        channel,
        verify_binding,
        admit_action,
    ):
        super().__init__(
            store=store,
            project_id=project_id,
            owner=owner,
            connection_id=connection_id,
            index_sha256=index_sha256,
            thread_id=thread_id,
            channel=channel,
            verify_binding=verify_binding,
            admit_action=admit_action,
            on_event=self._event,
        )

    def _event(self, event):
        state = self.store.ingest_frame(self.project_id, self.owner, event)
        if event["direction"] == "outgoing":
            self.outgoing = dict(
                raw=event["raw_utf8"].encode("utf-8"),
                frame_seq=state["protocol"]["frame_seq"],
            )

    def _save(self, key, status, evidence):
        with self.store._edit(
            self.project_id,
            self.owner,
            None,
            "controller-action-status",
            dict(key=key, status=status, evidence=evidence),
        ) as state:
            state["controller_actions"][key].update(status=status, evidence=evidence)
        return dict(
            self.store.snapshot(self.project_id)["controller_actions"][key],
            replayed=False,
        )

    def _begin(self, key, action, expected_revision, request=None):
        _require(isinstance(key, str) and 0 < len(key) <= 128, "action key required")
        _require(type(expected_revision) is int, "revision required")
        state = self._context()
        existing = state.get("controller_actions", {}).get(key)
        if existing:
            _require(
                canonical(existing["action"]) == canonical(action),
                "idempotency payload differs",
            )
            return dict(existing, replayed=True)
        if self.failure:
            raise ControllerError(self.failure)
        self.transport._healthy()
        _require(key not in state["intents"], "existing intent cannot be adopted")
        _require(not state["protocol"].get("quarantine"), "epoch quarantined")
        _require(
            not any(
                row["status"] == "execution-unknown"
                for name in ("intents", "requests")
                for row in state[name].values()
            ),
            "reconcile unknown work first",
        )
        if request is not None:
            _require(
                request["status"] == "pending"
                and not any(
                    row["request_identity"] == request["request_identity"]
                    for row in state["intents"].values()
                ),
                "request is settled or already claimed",
            )
        with self.store._edit(
            self.project_id,
            self.owner,
            expected_revision,
            "controller-action-intent",
            dict(key=key, action=action),
        ) as state:
            actions = state.setdefault("controller_actions", {})
            _require(len(actions) < 512, "controller action bound exceeded")
            actions[key] = dict(action=action, status="intent-recorded", evidence=None)
        try:
            accepted = self.admit_action(deepcopy(action)) is True
        except Exception as error:
            return self._save(key, "refused", {"exception_type": type(error).__name__})
        if not accepted:
            return self._save(key, "refused", {"reason": "admission callback rejected"})
        return None

    def _action(self, method, payload, identity=None, request_sha256=None):
        return dict(
            project_id=self.project_id,
            index_sha256=self.index_sha256,
            thread_id=self.thread_id,
            connection_id=self.connection_id,
            method=method,
            payload=deepcopy(payload),
            request_identity=identity,
            request_sha256=request_sha256,
        )

    def _receipt(self, first):
        return observe_frame_write(
            self.store,
            project_id=self.project_id,
            owner=self.owner,
            index_sha256=self.index_sha256,
            thread_id=self.thread_id,
            connection_id=self.connection_id,
            first_seq=first,
            outgoing=self.outgoing,
            max_records=self.channel.max_records,
        )

    def _fault(self, key, error, first):
        self.failure = "controller stopped; reconciliation required"
        observed = None
        try:
            state = self.store.snapshot(self.project_id)
            observed = state["byte_channels"][self.connection_id]["seq"] > first
            with self.store._edit(
                self.project_id,
                self.owner,
                None,
                "controller-fault",
                dict(key=key, exception_type=type(error).__name__),
            ) as state:
                _invalidate(state)
                _mirror_unknown(state)
                status = (
                    "failed-known-unsent"
                    if not observed
                    and isinstance(error, TransportError)
                    and not isinstance(error, DispatchUnknown)
                    else "execution-unknown"
                )
                evidence = dict(
                    exception_type=type(error).__name__,
                    reason=str(error)[:300],
                    recording_range_changed=observed,
                )
                if key is not None:
                    state["controller_actions"][key].update(
                        status=status, evidence=evidence
                    )
                state.setdefault("controller_faults", {})[self.connection_id] = evidence
        except BaseException:
            self.failure += "; fault persistence unobserved"
        finally:
            try:
                self.transport.close()
            except Exception:
                pass
        raise ControllerError(self.failure) from error

    def answer(
        self,
        key,
        request_key,
        request_sha256,
        result,
        expected_revision,
        timeout=10,
        pre_dispatch=None,
    ):
        with self.store._lock:
            state = self._context()
            request = state["requests"].get(request_key)
            _require(
                request is not None and request["record_sha256"] == request_sha256,
                "native request hash differs",
            )
            identity = request["request_identity"]
            _require(
                identity["connection_id"] == self.connection_id,
                "native request epoch differs",
            )
            wire = dict(
                id=identity["native_id"],
                method=request["method"],
                params=request["payload"],
            )
            result = validate_answer(wire, result)
            _require(
                len(_encode(dict(id=wire["id"], result=result))) + 1
                <= self.transport.max_message_bytes,
                "answer frame bound exceeded",
            )
            action = self._action(request["method"], result, identity, request_sha256)
            saved = self._begin(key, action, expected_revision, request)
            if saved is not None:
                return saved
            first = self._context()["byte_channels"][self.connection_id]["seq"]
            try:
                self.store.record_intent(
                    self.project_id,
                    self.owner,
                    key,
                    request["method"],
                    result,
                    self._context()["revision"],
                    identity,
                )
                row = self.store.transition_intent(
                    self.project_id,
                    self.owner,
                    key,
                    "dispatching",
                    {"controller_admission": "caller-permitted"},
                    self._context()["revision"],
                )
                if row["status"] != "dispatching":
                    return self._save(key, row["status"], row["evidence"])
                self.outgoing = None
                if pre_dispatch is not None:
                    timeout = pre_dispatch(timeout)
                self.transport.answer(
                    wire["id"],
                    result,
                    binding=dict(connection_id=self.connection_id, request=wire),
                    timeout=timeout,
                )
                receipt = self._receipt(first)
                self.store.update_request(
                    self.project_id,
                    self.owner,
                    identity,
                    "answer-sent",
                    receipt,
                    self._context()["revision"],
                )
                self.store.transition_intent(
                    self.project_id,
                    self.owner,
                    key,
                    "dispatched",
                    receipt,
                    self._context()["revision"],
                )
                return self._save(key, "dispatched", receipt)
            except BaseException as error:
                self._fault(key, error, first)

    def client_action(
        self, key, method, params, expected_revision, timeout=10, pre_dispatch=None
    ):
        with self.store._lock:
            _require(
                method in {"turn/start", "turn/interrupt"}, "unsupported controller RPC"
            )
            _require(
                isinstance(params, dict) and params.get("threadId") == self.thread_id,
                "client action thread differs",
            )
            params = deepcopy(params)
            _require(
                method != "turn/interrupt"
                or isinstance(params.get("turnId"), str)
                and params["turnId"],
                "interrupt turn required",
            )
            rpc_id = "controller-" + sha(canonical([self.connection_id, key]))
            _require(
                len(_encode(dict(id=rpc_id, method=method, params=params))) + 1
                <= self.transport.max_message_bytes,
                "RPC frame bound exceeded",
            )
            saved = self._begin(key, self._action(method, params), expected_revision)
            if saved is not None:
                return saved
            first = self._context()["byte_channels"][self.connection_id]["seq"]
            try:
                self.store.record_intent(
                    self.project_id,
                    self.owner,
                    key,
                    method,
                    params,
                    self._context()["revision"],
                )
                self.store.correlate(
                    self.project_id,
                    self.owner,
                    self.connection_id,
                    rpc_id,
                    key,
                    self._context()["revision"],
                )
                row = self.store.transition_intent(
                    self.project_id,
                    self.owner,
                    key,
                    "dispatching",
                    {"controller_admission": "caller-permitted"},
                    self._context()["revision"],
                )
                _require(row["status"] == "dispatching", "dispatch transition refused")
                self.outgoing = None
                if pre_dispatch is not None:
                    timeout = pre_dispatch(timeout)
                self.transport.send_request(
                    method, params, request_id=rpc_id, timeout=timeout
                )
                return self._save(key, "write-observed", self._receipt(first))
            except BaseException as error:
                self._fault(key, error, first)

    def pump(self, timeout=0):
        with self.store._lock:
            state = self._context()
            if self.failure:
                raise ControllerError(self.failure)
            first = state["byte_channels"][self.connection_id]["seq"]
            try:
                event = self.transport.poll(timeout)
                if event is not None and event["kind"] == "response":
                    self.transport.responses.pop(_key(event["message"]["id"]), None)
                for key, row in self._context()["intents"].items():
                    identity = row["request_identity"]
                    if identity is not None and row["status"] == "dispatched":
                        request = self._context()["requests"][_identity(identity)]
                        if request["status"] == "request-resolved":
                            row = self.store.transition_intent(
                                self.project_id,
                                self.owner,
                                key,
                                "completed",
                                request["evidence"],
                                self._context()["revision"],
                            )
                    action = self._context().get("controller_actions", {}).get(key)
                    if action and row["status"] in {"dispatched", "completed"}:
                        self._save(key, row["status"], row["evidence"])
                return event
            except BaseException as error:
                self._fault(None, error, first)
