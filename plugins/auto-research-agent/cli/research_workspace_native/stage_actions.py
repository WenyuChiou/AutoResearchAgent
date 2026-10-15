"""Durable offline stage actions; UI reviews never confer native authority.

Trusted registrations bind saved input directories. Stage1 checkpoint works on
an owned byte snapshot, preserving the original ledger; Stage2 completion calls
the repository inspector. Missing inputs remain missing. No search/model calls.
"""

from copy import deepcopy
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from stage1_deliverable.common import canonical, private_output, safe_path, sha
from research_workspace_native.session_api import SessionApiError
from research_workspace_native.stage_inputs import (
    _check,
    _hash,
    snapshot_inputs,
    source_digest,
    produce_stage_result,
    preflight_storage,
)
from research_workspace_native.store import ProjectStore


REF = re.compile(r"[A-Za-z0-9_-]{1,64}")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
ACTIONS = {
    1: ("checkpoint-stage1", "review-stage"),
    2: ("inspect-stage2", "review-stage"),
}
DECISIONS = ("review", "hold", "request-next")
MAX_ACTIONS = 128
MAX_RESULT = 512 * 1024


def _note(value):
    try:
        return isinstance(value, str) and len(value.encode("utf8")) <= 4096
    except UnicodeError:
        return False


def _public(row):
    value = deepcopy(row)
    if value.get("outcome") == "failed" and value["status"] == "completed":
        value["status"] = "failed"
    return value


def _summary(row):
    value = _public(row)
    result = value.pop("result", None)
    if result:
        readiness = result["readiness"]
        value["result_summary"] = dict(
            kind=result["kind"],
            readiness_status=readiness["status"],
            blocker_count=len(readiness["blockers"]),
            decision=result.get("decision"),
            next_stage_request=result.get("next_stage_request"),
        )
    return value


class StageActions:
    def __init__(
        self, store_path, *, registrations, authenticate, planned_queries=None
    ):
        _check(callable(authenticate), "identity-check-required", 400)
        _check(
            isinstance(registrations, dict) and 1 <= len(registrations) <= 16,
            "bounded-registration-required",
            400,
        )
        self._authenticate, self._lock, self._closed = (
            authenticate,
            threading.RLock(),
            False,
        )
        self._projects, prepared = {}, []
        for ref, item in registrations.items():
            _check(
                isinstance(ref, str) and REF.fullmatch(ref), "project-ref-invalid", 400
            )
            _check(
                isinstance(item, dict)
                and set(item)
                == {
                    "project_id",
                    "index_sha256",
                    "input_version",
                    "source_sha256",
                    "inputs",
                    "output_root",
                    "principals",
                },
                "registration-fields",
                400,
            )
            _check(
                isinstance(item["project_id"], str)
                and 0 < len(item["project_id"]) <= 128
                and all(
                    _hash(item[k])
                    for k in ("index_sha256", "input_version", "source_sha256")
                ),
                "registration-binding-invalid",
                400,
            )
            _check(
                isinstance(item["principals"], (list, tuple, set, frozenset))
                and item["principals"]
                and all(
                    isinstance(p, str) and 0 < len(p) <= 128 for p in item["principals"]
                ),
                "principal-allowlist-required",
                400,
            )
            files = snapshot_inputs(item["inputs"])
            _check(
                source_digest(files) == item["source_sha256"],
                "saved-input-hash-differs",
            )
            root = Path(item["output_root"])
            _check(root.is_absolute(), "absolute-output-root-required", 400)
            root = private_output(root).resolve()
            for input_item in item["inputs"].values():
                for name, value in (input_item or {}).items():
                    if name.endswith("_root") and value is not None:
                        input_root = Path(value).resolve()
                        _check(
                            not root.is_relative_to(input_root)
                            and not input_root.is_relative_to(root),
                            "input-output-overlap",
                        )
            binding = {
                k: deepcopy(item[k])
                for k in (
                    "project_id",
                    "index_sha256",
                    "input_version",
                    "source_sha256",
                )
            }
            binding["inputs"] = {
                str(k): {
                    name: Path(value).resolve().as_posix()
                    if name.endswith("_root") and value is not None
                    else value
                    for name, value in stage_input.items()
                }
                if stage_input
                else None
                for k, stage_input in item["inputs"].items()
            }
            binding.update(project_ref=ref, output_root=root.as_posix())
            prepared.append((ref, item, root, binding))
        self.planned_queries = None
        if planned_queries is not None:
            from .query_http import bind_query_registration

            bind_query_registration(planned_queries, registrations)
        database = preflight_storage(prepared, store_path)
        self.store = ProjectStore(database)
        try:
            for ref, item, root, binding in prepared:
                pid = "stage-actions-" + sha(ref.encode())[:32]
                state = self.store.bind_project(pid, item["index_sha256"])
                _check(
                    state.get("stage_actions_binding", binding) == binding,
                    "saved-registration-differs",
                )
                owner = self.store.acquire_owner(pid, "offline-stage-actions")
                with self.store._edit(
                    pid, owner, None, "stage-actions-bound", binding
                ) as saved:
                    saved["stage_actions_binding"] = binding
                root.mkdir(parents=True, exist_ok=True)
                self._projects[ref] = dict(
                    binding=binding,
                    root=root,
                    pid=pid,
                    owner=owner,
                    principals=frozenset(item["principals"]),
                )
            self.planned_queries = planned_queries
        except BaseException:
            self.store.close()
            self._closed = True
            raise

    def _access(self, token, ref):
        _check(not self._closed, "service-closed", 503)
        try:
            principal = self._authenticate(token)
        except Exception:
            raise SessionApiError("identity-denied", 403) from None
        project = self._projects.get(ref) if isinstance(ref, str) else None
        _check(
            project is not None
            and isinstance(principal, str)
            and principal in project["principals"],
            "project-denied",
            403,
        )
        return project, principal

    def _deadline(self, deadline):
        _check(
            type(deadline) in (int, float)
            and math.isfinite(deadline)
            and time.monotonic() < deadline,
            "request-deadline-exceeded",
            408,
        )

    def bindings(self):
        return {
            ref: {
                k: p["binding"][k]
                for k in ("project_id", "index_sha256", "input_version")
            }
            for ref, p in self._projects.items()
        }

    def view(self, token, ref):
        with self._lock:
            p, principal = self._access(token, ref)
            state = self.store.snapshot(p["pid"])
            history = sorted(
                state["intents"].values(), key=lambda r: r["intent_revision"]
            )
            return dict(
                project_ref=ref,
                **{
                    k: p["binding"][k]
                    for k in (
                        "project_id",
                        "index_sha256",
                        "input_version",
                        "source_sha256",
                    )
                },
                revision=state["revision"],
                history=[_summary(r) for r in history if r["principal"] == principal][
                    -64:
                ],
                history_count=sum(r["principal"] == principal for r in history),
                input_status={
                    str(stage): "saved" if item else "missing"
                    for stage, item in p["binding"]["inputs"].items()
                },
                capabilities={str(k): list(v) for k, v in ACTIONS.items()},
                operation_scope="offline-saved-stage-input",
                native_execution=False,
                model_execution=False,
                next_stage_execution_authorized=False,
            )

    def offer(self, token, ref, stage, action):
        with self._lock:
            p, principal = self._access(token, ref)
            _check(
                type(stage) is int and stage in ACTIONS and action in ACTIONS[stage],
                "stage-action-unavailable",
                400,
            )
            _check(
                source_digest(snapshot_inputs(p["binding"]["inputs"]))
                == p["binding"]["source_sha256"],
                "saved-input-changed",
            )
            document = dict(
                project_ref=ref,
                principal=principal,
                stage=stage,
                action=action,
                **{
                    k: p["binding"][k]
                    for k in ("index_sha256", "input_version", "source_sha256")
                },
                decisions=list(DECISIONS) if action == "review-stage" else [],
                execution_authorized=False,
            )
            digest = sha(canonical(document))
            return dict(
                offer_ref=digest,
                offer_sha256=digest,
                revision=self.store.snapshot(p["pid"])["revision"],
                document=document,
            )

    def get_action(self, token, ref, key):
        with self._lock:
            p, principal = self._access(token, ref)
            _check(
                isinstance(key, str) and KEY.fullmatch(key), "invalid-action-key", 400
            )
            row = self.store.snapshot(p["pid"])["intents"].get(
                sha(canonical([principal, key]))
            )
            _check(
                row is not None and row["principal"] == principal,
                "action-not-found",
                404,
            )
            return _public(row)

    def execute(self, token, ref, request, *, deadline):
        self._deadline(deadline)
        with self._lock:
            self._deadline(deadline)
            p, principal = self._access(token, ref)
            fields = {
                "stage",
                "action",
                "key",
                "revision",
                "index_sha256",
                "input_version",
                "offer_ref",
                "offer_sha256",
                "decision",
                "note",
                "confirmed",
            }
            _check(
                isinstance(request, dict)
                and set(request) == fields
                and type(request["stage"]) is int
                and request["stage"] in ACTIONS
                and request["action"] in ACTIONS[request["stage"]]
                and isinstance(request["key"], str)
                and KEY.fullmatch(request["key"])
                and type(request["revision"]) is int
                and 0 <= request["revision"] < 2**63,
                "action-fields-invalid",
                400,
            )
            _check(
                all(
                    request[k] == p["binding"][k]
                    for k in ("index_sha256", "input_version")
                ),
                "source-version-differs",
            )
            review = request["action"] == "review-stage"
            _check(
                _note(request["note"])
                and (
                    (
                        review
                        and request["decision"] in DECISIONS
                        and request["confirmed"] is True
                        and request["note"].strip()
                    )
                    or (
                        not review
                        and request["decision"] is None
                        and request["note"] == ""
                        and request["confirmed"] is False
                    )
                ),
                "explicit-review-required",
                400,
            )
            request = deepcopy(request)
            digest = sha(
                canonical(
                    dict(
                        project_ref=ref,
                        principal=principal,
                        request={k: v for k, v in request.items() if k != "revision"},
                    )
                )
            )
            state = self.store.snapshot(p["pid"])
            key = sha(canonical([principal, request["key"]]))
            old = state["intents"].get(key)
            if old is not None:
                _check(old["request_sha256"] == digest, "idempotency-payload-differs")
                return _public(old)
            offer = self.offer(token, ref, request["stage"], request["action"])
            _check(
                request["offer_ref"] == offer["offer_ref"]
                and request["offer_sha256"] == offer["offer_sha256"],
                "offer-differs",
            )
            _check(request["revision"] == state["revision"], "stale-revision")
            _check(len(state["intents"]) < MAX_ACTIONS, "action-bound-exceeded", 429)
            row = dict(
                key=key,
                client_key=request["key"],
                principal=principal,
                method="stage-actions/" + request["action"],
                stage=request["stage"],
                action=request["action"],
                status="running",
                request=request,
                request_sha256=digest,
                intent_revision=state["revision"] + 1,
                source_sha256=p["binding"]["source_sha256"],
                output_ref=uuid.uuid4().hex,
                native_execution=False,
                model_execution=False,
                execution_authorized=False,
            )
            self._deadline(deadline)
            with self.store._edit(
                p["pid"], p["owner"], state["revision"], "stage-action-intent", row
            ) as saved:
                saved["intents"][key] = deepcopy(row)
            try:
                self._deadline(deadline)
                root = safe_path(p["root"], row["output_ref"])
                root.mkdir(exist_ok=False)
                result = self._produce(p, row, root)
                self._deadline(deadline)
                raw = canonical(result)
                _check(len(raw) <= MAX_RESULT, "result-bound-exceeded")
                with (root / "result.json").open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                _check(
                    (root / "result.json").read_bytes() == raw, "result-write-differs"
                )
                row.update(
                    status="completed",
                    outcome="succeeded",
                    result=result,
                    result_sha256=sha(raw),
                )
            except Exception as error:
                row.update(
                    status="completed",
                    outcome="failed",
                    error=dict(
                        code=getattr(error, "code", "stage-operation-failed"),
                        type=type(error).__name__,
                    ),
                )
            with self.store._edit(
                p["pid"], p["owner"], None, "stage-action-terminal", row
            ) as saved:
                saved["intents"][key] = row
            return _public(row)

    def _produce(self, p, row, root):
        return produce_stage_result(
            p["binding"], row, root, self.store.snapshot(p["pid"])
        )

    def close(self):
        with self._lock:
            if not self._closed:
                if self.planned_queries is not None:
                    self.planned_queries.close()
                self.store.close()
                self._closed = True
