"""Durable native intents; caller-supplied evidence is checked, never dispatched."""

import json

from stage1_deliverable.common import canonical, sha
from .store import JournalError as JournalError, ProjectStore, _require


def _native_id(value):
    _require(type(value) in (int, str), "native ID must be integer or string")
    if type(value) is int:
        _require(-(2**63) <= value < 2**63, "native integer ID is outside i64")


def _identity(value):
    _require(isinstance(value, dict), "native request identity required")
    _require(
        set(value)
        == {
            "connection_id",
            "native_id",
            "thread_id",
            "turn_id",
            "item_id",
            "approval_id",
        },
        "native request identity fields differ",
    )
    _native_id(value["native_id"])
    _require(
        all(
            isinstance(value[key], str) and value[key]
            for key in ("connection_id", "thread_id", "turn_id", "item_id")
        ),
        "native identity components required",
    )
    _require(
        value["approval_id"] is None or isinstance(value["approval_id"], str),
        "invalid approval ID",
    )
    return sha(canonical(value))


class Journal(ProjectStore):
    def _record(
        self,
        project_id,
        owner,
        key,
        method,
        payload,
        revision,
        collection,
        identity=None,
    ):
        _require(
            isinstance(key, str) and key and isinstance(method, str) and method,
            "key and method required",
        )
        # Strict serialization rejects NaN and non-JSON objects before any commit.
        _require(isinstance(payload, dict), "record payload must be an object")
        json.dumps(payload, allow_nan=False)
        record = {
            "key": key,
            "method": method,
            "payload": payload,
            "request_identity": identity,
        }
        record["record_sha256"] = sha(canonical(record))
        with self._edit(
            project_id, owner, None, collection + "-recorded", record
        ) as state:
            if identity is not None:
                _identity(identity)
                _require(
                    identity["thread_id"] == state["thread_id"],
                    "native request thread differs",
                )
            existing = state[collection].get(key)
            if existing:
                _require(
                    all(
                        canonical(existing[name]) == canonical(value)
                        for name, value in record.items()
                    ),
                    "idempotency key payload differs",
                )
                replayed = True
            else:
                _require(
                    type(revision) is int and revision == state["revision"],
                    "stale revision",
                )
                if collection == "turns":
                    _require(
                        state["thread_id"] is not None,
                        "project thread binding required",
                    )
                if collection == "intents":
                    if method == "thread/start":
                        _require(
                            state["thread_id"] is None
                            and not any(
                                row["method"] == method
                                for row in state["intents"].values()
                            ),
                            "project already has a thread or thread/start intent",
                        )
                    _require(
                        not any(
                            row["status"] == "execution-unknown"
                            for name in ("intents", "requests")
                            for row in state[name].values()
                        ),
                        "reconcile execution-unknown before new intents",
                    )
                    if identity is not None:
                        request = state["requests"].get(_identity(identity))
                        _require(
                            request is not None
                            and request["method"] == method
                            and request["status"] == "pending",
                            "pending native request binding required",
                        )
                        _require(
                            not any(
                                row["request_identity"] == identity
                                for row in state["intents"].values()
                            ),
                            "native request already has an answer intent",
                        )
                status = (
                    "intent-recorded"
                    if collection == "intents"
                    else method
                    if collection == "turns"
                    else "pending"
                )
                state[collection][key] = {**record, "status": status, "evidence": None}
                replayed = False
        return {**self.snapshot(project_id)[collection][key], "replayed": replayed}

    def record_intent(
        self,
        project_id,
        owner,
        key,
        method,
        payload,
        expected_revision,
        request_identity=None,
    ):
        return self._record(
            project_id,
            owner,
            key,
            method,
            payload,
            expected_revision,
            "intents",
            request_identity,
        )

    def record_request(
        self, project_id, owner, identity, method, payload, expected_revision
    ):
        return self._record(
            project_id,
            owner,
            _identity(identity),
            method,
            payload,
            expected_revision,
            "requests",
            identity,
        )

    def _transition(
        self, project_id, owner, key, status, evidence, revision, collection
    ):
        transitions = {
            "intents": {
                "intent-recorded": {"dispatching", "execution-unknown"},
                "dispatching": {"dispatched", "completed", "execution-unknown"},
                "dispatched": {"completed", "execution-unknown"},
                "execution-unknown": {"completed"},
                "completed": set(),
            },
            "requests": {
                "pending": {"answer-sent", "request-resolved", "execution-unknown"},
                "answer-sent": {"request-resolved", "execution-unknown"},
                "execution-unknown": {"request-resolved"},
                "request-resolved": set(),
            },
        }
        _require(
            isinstance(evidence, dict) and evidence, "transition evidence required"
        )
        json.dumps(evidence, allow_nan=False)
        with self._edit(
            project_id,
            owner,
            revision,
            status,
            {"collection": collection, "key": key, "evidence": evidence},
        ) as state:
            _require(key in state[collection], "unknown request or intent")
            item = state[collection][key]
            _require(
                status in transitions[collection][item["status"]],
                "invalid transition; replay dispatch is forbidden",
            )
            if collection == "intents" and status == "dispatching":
                _require(
                    not any(
                        row["status"] == "execution-unknown"
                        for name in ("intents", "requests")
                        for row in state[name].values()
                    ),
                    "reconcile execution-unknown before dispatch",
                )
            if (
                collection == "intents"
                and item["method"] == "thread/start"
                and status == "completed"
            ):
                _require(
                    isinstance(evidence.get("thread_id"), str)
                    and evidence["thread_id"],
                    "native thread ID required for reconciliation",
                )
            if collection == "intents":
                self._completion_binding(state, item, status, evidence)
            item.update(status=status, evidence=evidence)
        return self.snapshot(project_id)[collection][key]

    @staticmethod
    def _completion_binding(state, item, status, evidence):
        """Check saved identities, not the authenticity of caller-supplied receipts."""
        identity = item["request_identity"]
        if status == "completed" and identity is not None:
            request = state["requests"].get(_identity(identity))
            _require(
                request is not None and request["status"] == "request-resolved",
                "answer intent requires request-resolved, not merely answer-sent",
            )
        if item["method"] not in {"turn/start", "turn/interrupt"}:
            return
        if status == "dispatched":
            turn_id = evidence.get("native_turn_id")
            receipt = evidence.get("rpc_receipt")
            _require(
                isinstance(turn_id, str)
                and turn_id
                and isinstance(receipt, dict)
                and isinstance(receipt.get("result"), dict)
                and "error" not in receipt,
                "native turn ID and successful RPC receipt required",
            )
            _native_id(receipt.get("id"))
            turn = receipt["result"].get("turn")
            observed = item["payload"].get("turnId")
            if item["method"] == "turn/start":
                _require(isinstance(turn, dict), "RPC receipt turn must be an object")
                observed = turn.get("id")
            _require(
                observed == turn_id, "RPC receipt or interrupt target turn differs"
            )
            item["native_turn_id"] = turn_id
        if status == "completed":
            turn_id = item.get("native_turn_id")
            if turn_id is None and item["status"] == "execution-unknown":
                reconciliation = evidence.get("reconciliation", {})
                _require(
                    isinstance(reconciliation, dict)
                    and reconciliation.get("intent_record_sha256")
                    == item["record_sha256"]
                    and reconciliation.get("thread_id") == state["thread_id"],
                    "explicit intent-bound reconciliation required",
                )
                turn_id = reconciliation.get("native_turn_id")
            _require(
                isinstance(turn_id, str) and turn_id in state["turns"],
                "saved native turn terminal required; RPC acknowledgement is not completion",
            )
            _require(
                state["turns"][turn_id]["status"]
                in {"completed", "failed", "interrupted"},
                "native turn is not terminal",
            )
            _require(
                evidence.get("native_turn_id", turn_id) == turn_id,
                "completion turn identity differs",
            )
            if item["method"] == "turn/interrupt":
                _require(
                    item["payload"].get("turnId") == turn_id,
                    "interrupt terminal target differs",
                )
            item["native_turn_id"] = turn_id

    def transition_intent(
        self, project_id, owner, key, status, evidence, expected_revision
    ):
        return self._transition(
            project_id, owner, key, status, evidence, expected_revision, "intents"
        )

    def update_request(
        self, project_id, owner, identity, status, evidence, expected_revision
    ):
        return self._transition(
            project_id,
            owner,
            _identity(identity),
            status,
            evidence,
            expected_revision,
            "requests",
        )

    def record_terminal(
        self, project_id, owner, turn_id, status, evidence, expected_revision
    ):
        _require(
            status in {"completed", "failed", "interrupted"}, "invalid terminal status"
        )
        return self._record(
            project_id, owner, turn_id, status, evidence, expected_revision, "turns"
        )
