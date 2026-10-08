"""Server-owned facade over an existing injected controller, without HTTP.

Trusted bootstrap supplies identity/source checks; neither callback proves native
authentication or lifecycle admission. Reads never pump. A persisted API intent
is never retried, including a crash before the controller records its own intent.
Scope changes, starts, launchers and reconnection are deliberately absent.
"""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json
import re
import threading

from stage1_deliverable.common import canonical, private_output, sha
from .controller import InjectedSessionController
from .store import JournalError
from .transport import validate_answer


class SessionApiError(JournalError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def _check(condition, code, status=409):
    if not condition:
        raise SessionApiError(code, status)


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 128


def _hash(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _pick(value, fields):
    return {k: deepcopy(value[k]) for k in fields.split() if k in value}


class SessionApi:
    def __init__(self, *, authenticate):
        _check(callable(authenticate), "identity-check-required")
        self._authenticate, self._projects = authenticate, {}
        self._lock = threading.RLock()

    def register(
        self,
        project_ref,
        *,
        controller,
        principals,
        source_root,
        index_sha256,
        input_version,
        verify_source,
    ):
        """Trusted startup only; all roots and controller identities stay server-side."""
        _check(
            _text(project_ref) and isinstance(controller, InjectedSessionController),
            "invalid-registration",
        )
        _check(
            not isinstance(principals, str)
            and principals
            and all(map(_text, principals)),
            "principal-allowlist-required",
        )
        _check(
            _hash(index_sha256) and _hash(input_version) and callable(verify_source),
            "source-binding-required",
        )
        root = Path(source_root)
        _check(
            root.is_absolute() and root.is_dir(), "absolute-source-directory-required"
        )
        root = private_output(root).resolve()
        binding = dict(
            project_ref=project_ref,
            project_id=controller.project_id,
            source_root=root.as_posix(),
            index_sha256=index_sha256,
            input_version=input_version,
            thread_id=controller.thread_id,
        )
        registration = (controller, frozenset(principals), binding, verify_source)
        with self._lock, controller.store._lock:
            _check(
                project_ref not in self._projects
                and not any(
                    item[0] is controller
                    or (
                        item[0].store.path == controller.store.path
                        and item[0].project_id == controller.project_id
                    )
                    for item in self._projects.values()
                ),
                "project-already-registered",
            )
            self._source(registration)
            state = controller._context()
            with controller.store._edit(
                controller.project_id,
                controller.owner,
                state["revision"],
                "session-api-bound",
                binding,
            ) as current:
                _check(
                    current.get("session_api_binding", binding) == binding,
                    "saved-source-binding-differs",
                )
                current["session_api_binding"] = deepcopy(binding)
            self._projects[project_ref] = registration

    @staticmethod
    def _source(registration):
        controller, _, binding, verifier = registration
        try:
            root = private_output(Path(binding["source_root"]))
            valid = root.is_dir() and controller.index_sha256 == binding["index_sha256"]
            valid = valid and controller.project_id == binding["project_id"]
            valid = valid and controller.thread_id == binding["thread_id"]
            checked = dict(binding, connection_id=controller.connection_id)
            _check(valid and verifier(deepcopy(checked)) is True, "source-check-failed")
        except Exception:
            raise SessionApiError("source-check-failed") from None

    @contextmanager
    def _access(self, credential, project_ref):
        try:
            principal = self._authenticate(credential)
        except Exception:
            raise SessionApiError("authentication-required", 401) from None
        _check(_text(principal), "authentication-required", 401)
        with self._lock:
            registration = (
                self._projects.get(project_ref) if _text(project_ref) else None
            )
        _check(
            registration is not None and principal in registration[1],
            "project-unavailable",
            404,
        )
        controller, _, binding, _ = registration
        with controller.store._lock:
            self._source(registration)
            try:
                state = controller._context()
                _check(
                    state.get("session_api_binding") == binding,
                    "saved-source-binding-differs",
                )
                yield controller, principal, binding, state
            except SessionApiError:
                raise
            except Exception:
                raise SessionApiError("session-unavailable") from None

    @staticmethod
    def _ref(binding, kind, key):
        return sha(
            canonical(
                [
                    binding["project_ref"],
                    binding["index_sha256"],
                    binding["input_version"],
                    kind,
                    key,
                ]
            )
        )

    def _operation(self, binding, key, item, state):
        return dict(
            action_ref=self._ref(binding, "operation", key),
            action_sha256=item["record_sha256"],
            status=item["status"],
            can_interrupt=item["status"] == "dispatched"
            and item["native_turn_id"] not in state["turns"]
            and not any(
                row["method"] == "turn/interrupt"
                and row["payload"].get("turnId") == item["native_turn_id"]
                for row in state["intents"].values()
            ),
        )

    def _public_action(self, binding, key, item, state, replayed=False):
        observed = state.get("controller_actions", {}).get(key, {})
        return dict(
            action_ref=self._ref(binding, "action", key),
            action_sha256=item["action_sha256"],
            kind=item["kind"],
            client_key=item["request"]["key"],
            target_ref=item["request"].get(
                "request_ref", item["request"].get("action_ref")
            ),
            status=observed.get("status", "dispatch-unobserved"),
            replayed=replayed,
            failure=item.get("failure"),
        )

    def view(self, credential, project_ref):
        with self._access(credential, project_ref) as (
            controller,
            principal,
            binding,
            state,
        ):
            requests = []
            for key, item in state["requests"].items():
                fields = (
                    "questions"
                    if item["method"] == "item/tool/requestUserInput"
                    else "command reason"
                )
                payload = _pick(item["payload"], fields)
                if "questions" in payload:
                    payload["questions"] = [
                        _pick(q, "id header question isOther isSecret options")
                        for q in payload["questions"]
                    ]
                    for question in payload["questions"]:
                        if isinstance(question.get("options"), list):
                            question["options"] = [
                                _pick(o, "label description")
                                for o in question["options"]
                            ]
                requests.append(
                    dict(
                        request_ref=self._ref(binding, "request", key),
                        request_sha256=item["record_sha256"],
                        method=item["method"],
                        status=item["status"],
                        payload=payload,
                    )
                )
            actions = [
                self._public_action(binding, key, item, state)
                for key, item in state.get("session_api_actions", {}).items()
                if item["principal"] == principal
            ]
            operations = [
                self._operation(binding, key, item, state)
                for key, item in state["intents"].items()
                if item["method"] == "turn/start" and item.get("native_turn_id")
            ]
            return dict(
                project_ref=project_ref,
                index_sha256=binding["index_sha256"],
                input_version=binding["input_version"],
                revision=state["revision"],
                failure="session-stopped" if controller.failure else None,
                requests=requests,
                actions=actions,
                operations=operations,
            )

    def action(self, credential, project_ref, action_ref):
        with self._access(credential, project_ref) as (_, principal, binding, state):
            for key, item in state.get("session_api_actions", {}).items():
                if (
                    item["principal"] == principal
                    and self._ref(binding, "action", key) == action_ref
                ):
                    return self._public_action(binding, key, item, state, True)
            raise SessionApiError("action-unavailable", 404)

    def answer(self, credential, project_ref, body):
        return self._submit(credential, project_ref, "answer", body)

    def interrupt(self, credential, project_ref, body):
        return self._submit(credential, project_ref, "interrupt", body)

    def _submit(self, credential, project_ref, kind, body):
        with self._access(credential, project_ref) as (
            controller,
            principal,
            binding,
            state,
        ):
            extra = (
                {"request_ref", "request_sha256", "result"}
                if kind == "answer"
                else {"action_ref", "action_sha256"}
            )
            fields = {"key", "revision", "index_sha256", "input_version"} | extra
            _check(
                isinstance(body, dict) and set(body) == fields,
                "invalid-action-fields",
                400,
            )
            _check(
                _text(body["key"])
                and type(body["revision"]) is int
                and 0 <= body["revision"] <= 2**63 - 1,
                "invalid-action-identity",
                400,
            )
            _check(
                body["index_sha256"] == binding["index_sha256"]
                and body["input_version"] == binding["input_version"],
                "source-version-differs",
            )
            try:
                json.dumps(body, allow_nan=False)
                encoded = canonical(body)
                _check(len(encoded) <= 32768, "action-too-large", 400)
                body = deepcopy(body)
            except (TypeError, ValueError):
                raise SessionApiError("invalid-action-json", 400) from None
            semantic = {k: v for k, v in body.items() if k != "revision"}
            request_hash = sha(canonical(dict(kind=kind, body=semantic)))
            key = "api-" + sha(
                canonical([controller.project_id, principal, body["key"]])
            )
            prior = state.get("session_api_actions", {}).get(key)
            if prior is not None:
                _check(
                    prior["action_sha256"] == request_hash,
                    "idempotency-payload-differs",
                )
                return self._public_action(binding, key, prior, state, True)
            _check(body["revision"] == state["revision"], "stale-revision")
            _check(
                key not in state["intents"]
                and key not in state.get("controller_actions", {}),
                "existing-controller-action",
            )
            if kind == "answer":
                matches = [
                    (k, row)
                    for k, row in state["requests"].items()
                    if self._ref(binding, "request", k) == body["request_ref"]
                ]
                _check(len(matches) == 1, "request-unavailable", 404)
                request_key, request = matches[0]
                _check(
                    request["record_sha256"] == body["request_sha256"]
                    and request["status"] == "pending",
                    "request-not-pending",
                )
                identity = request["request_identity"]
                _check(
                    identity["connection_id"] == controller.connection_id,
                    "request-epoch-expired",
                )
                result = validate_answer(
                    dict(
                        id=identity["native_id"],
                        method=request["method"],
                        params=request["payload"],
                    ),
                    body["result"],
                )
            else:
                matches = [
                    (k, row)
                    for k, row in state["intents"].items()
                    if row["method"] == "turn/start"
                    and row.get("native_turn_id")
                    and self._ref(binding, "operation", k) == body["action_ref"]
                ]
                _check(len(matches) == 1, "operation-unavailable", 404)
                operation_key, operation = matches[0]
                public = self._operation(binding, operation_key, operation, state)
                _check(
                    public["can_interrupt"]
                    and public["action_sha256"] == body["action_sha256"],
                    "operation-not-active",
                )
                params = dict(
                    threadId=controller.thread_id, turnId=operation["native_turn_id"]
                )
            entry = dict(
                principal=principal,
                kind=kind,
                action_sha256=request_hash,
                request=semantic,
                admitted_revision=body["revision"],
                connection_id=controller.connection_id,
                failure=None,
            )
            with controller.store._edit(
                controller.project_id,
                controller.owner,
                state["revision"],
                "session-api-intent",
                dict(key=key, entry=entry),
            ) as current:
                actions = current.setdefault("session_api_actions", {})
                _check(len(actions) < 512, "api-action-bound-exceeded")
                actions[key] = entry
            try:
                self._source(self._projects[project_ref])
                revision = controller._context()["revision"]
                if kind == "answer":
                    controller.answer(
                        key, request_key, body["request_sha256"], result, revision
                    )
                else:
                    controller.client_action(key, "turn/interrupt", params, revision)
            except Exception as error:
                with controller.store._edit(
                    controller.project_id,
                    controller.owner,
                    None,
                    "session-api-call-failed",
                    dict(key=key, error=type(error).__name__),
                ) as current:
                    current["session_api_actions"][key]["failure"] = type(
                        error
                    ).__name__
                raise SessionApiError("controller-action-failed") from None
            current = controller._context()
            return self._public_action(
                binding, key, current["session_api_actions"][key], current
            )
