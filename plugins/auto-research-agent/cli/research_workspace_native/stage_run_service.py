"""One explicitly admitted repository-content pilot, with a durable shared budget.

This is an implementation diagnostic, not a canonical Stage1 handoff or scientific
evaluation. A GET never launches work. Interrupted intents are retained as unknown.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
import threading
import time
import uuid

from stage1_deliverable.common import private_output, sha
from .session_api import SessionApiError
from .store import ProjectStore

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
HASH = re.compile(r"[0-9a-f]{64}")


def _check(condition, reason, status=409):
    if not condition:
        raise SessionApiError(reason, status)


class StageRunService:
    """Server-owned workflow: browser submits a pinned task and idempotency key.

    The trusted launcher writes one immutable permit containing the canonical
    budget store. Alternate HTTP hosts therefore cannot reset this permit's budget.
    The model must call ``admit`` before runtime composition and every later I/O.
    """

    def __init__(
        self,
        permit_path,
        permit_sha256,
        *,
        pipeline,
        authenticate,
        principal="local-viewer",
        project_ref="repo-content-pilot",
    ):
        self.permit_path = private_output(permit_path).resolve()
        raw = self.permit_path.read_bytes()
        _check(sha(raw) == permit_sha256, "pilot-permit-bytes-differ")
        permit = json.loads(raw)
        required = {
            "kind",
            "schema_version",
            "project_id",
            "source_sha256",
            "case_sha256",
            "output_root",
            "model",
            "max_calls",
            "max_seconds",
            "execution_scope",
            "external_search",
            "frozen_subjects",
            "permission_id",
        }
        _check(
            set(permit) == required
            and permit["kind"] == "NativeStagePilotPermit"
            and permit["schema_version"] == "1.0.0",
            "pilot-permit-fields",
        )
        _check(
            type(permit["max_calls"]) is int
            and 1 <= permit["max_calls"] <= 8
            and type(permit["max_seconds"]) is int
            and 1 <= permit["max_seconds"] <= 900,
            "pilot-budget-exceeds-confirmed-scope",
        )
        _check(
            permit["execution_scope"] == "repository-saved-content-only"
            and permit["external_search"] is False
            and permit["frozen_subjects"] is False,
            "pilot-scope-invalid",
        )
        _check(
            all(
                isinstance(permit[k], str) and 0 < len(permit[k]) <= 128
                for k in ("permission_id", "model", "project_id")
            )
            and isinstance(project_ref, str)
            and KEY.fullmatch(project_ref),
            "pilot-explicit-permission-and-identity-required",
            400,
        )
        _check(
            all(
                isinstance(permit[k], str) and HASH.fullmatch(permit[k])
                for k in ("source_sha256", "case_sha256")
            ),
            "pilot-hash-invalid",
        )
        _check(
            callable(authenticate) and isinstance(principal, str) and principal,
            "pilot-authentication-required",
            400,
        )
        root = Path(permit["output_root"])
        _check(root.is_absolute(), "pilot-canonical-output-required", 400)
        self.root = private_output(root).resolve()
        _check(root == self.root, "pilot-output-root-differs")
        self.root.mkdir(parents=True, exist_ok=True)
        self.permit, self.permit_sha = permit, permit_sha256
        _check(
            getattr(pipeline, "source_sha", None) == permit["source_sha256"]
            and getattr(pipeline, "max_calls", None) == permit["max_calls"],
            "pilot-pipeline-budget-or-source-differs",
        )
        self.pipeline, self.model = pipeline, None
        self.authenticate, self.principal, self.ref = (
            authenticate,
            principal,
            project_ref,
        )
        self._lock, self._worker, self._closed = threading.RLock(), None, False
        self._mono_deadline = None
        self.store = ProjectStore(self.root / "pilot-budget.sqlite3")
        self.pid = permit["project_id"]
        self.store.bind_project(self.pid, permit_sha256)
        try:
            self.owner = self.store.acquire_owner(
                self.pid, "stage-pilot-" + uuid.uuid4().hex
            )
            with self.store._edit(
                self.pid, self.owner, None, "pilot-open", {}
            ) as state:
                row = state.setdefault(
                    "stage_pilot",
                    dict(
                        permit_sha256=permit_sha256,
                        calls=0,
                        started_at=None,
                        deadline_at=None,
                        jobs={},
                        reservations={},
                        blocked=None,
                    ),
                )
                _check(row["permit_sha256"] == permit_sha256, "pilot-binding-differs")
                for job in row["jobs"].values():
                    if job["status"] in {"intent-recorded", "running"}:
                        job["status"] = "execution-unknown"
                        row["blocked"] = "owner-recovery-execution-unknown"
            self._next = self.pipeline.next_task()
        except BaseException:
            self.store.close()
            raise

    def attach_model(self, model):
        _check(
            self.model is None and callable(getattr(model, "run", None)),
            "pilot-model-already-bound",
        )
        self.model = model

    def _row(self):
        return self.store.snapshot(self.pid)["stage_pilot"]

    def _auth(self, credential, ref):
        _check(
            not self._closed
            and ref == self.ref
            and self.authenticate(credential) == self.principal,
            "pilot-project-not-authorized",
            403,
        )

    def _guard(self):
        _check(
            sha(self.permit_path.read_bytes()) == self.permit_sha,
            "pilot-permit-changed",
        )
        _check(not self._closed, "pilot-closed")

    def _remaining(self, row):
        if row["started_at"] is None:
            return self.permit["max_seconds"]
        now = time.time()
        _check(now >= row["started_at"], "pilot-clock-regressed")
        remaining = row["deadline_at"] - now
        if self._mono_deadline is not None:
            remaining = min(remaining, self._mono_deadline - time.monotonic())
        return max(0, remaining)

    def admit(self, event):
        """Literal True only for the current task and still-pinned bounded permit."""
        with self._lock:
            self._guard()
            _check(
                isinstance(event, dict)
                and event.get("permit_sha256") == self.permit_sha
                and event.get("source_sha256") == self.permit["source_sha256"],
                "pilot-admission-binding-differs",
            )
            key, phase = event.get("unit_key"), event.get("phase")
            row = self._row()
            _check(
                key in row["jobs"]
                and row["jobs"][key]["status"] == "running"
                and row["blocked"] is None,
                "pilot-current-intent-required",
            )
            _check(self._remaining(row) > 0, "pilot-time-budget-exhausted")
            task = row["jobs"][key]["task"]
            _check(
                event.get("prompt_sha256") == sha(task["prompt"].encode("utf-8")),
                "pilot-prompt-binding-differs",
            )
            if phase == "reserve":
                _check(
                    key not in row["reservations"]
                    and row["calls"] < self.permit["max_calls"],
                    "pilot-call-budget-exhausted",
                )
                with self.store._edit(
                    self.pid, self.owner, None, "model-unit-reserved", {"key": key}
                ) as state:
                    current = state["stage_pilot"]
                    if current["started_at"] is None:
                        current["started_at"] = time.time()
                        current["deadline_at"] = (
                            current["started_at"] + self.permit["max_seconds"]
                        )
                        self._mono_deadline = (
                            time.monotonic() + self.permit["max_seconds"]
                        )
                    current["calls"] += 1
                    current["reservations"][key] = dict(
                        prompt_sha256=event["prompt_sha256"], outcome="reserved"
                    )
            else:
                _check(
                    phase in {"spawn", "lifecycle", "attach", "action"}
                    and key in row["reservations"],
                    "pilot-reservation-required",
                )
            return True

    def view(self, credential, ref):
        with self._lock:
            self._auth(credential, ref)
            row, state = self._row(), self.store.snapshot(self.pid)
            remaining = self._remaining(row)
            next_task = deepcopy(self._next)
            if next_task is not None:
                next_task.pop("prompt", None)
                next_task.pop("schema", None)
            jobs = deepcopy(list(row["jobs"].values()))
            for job in jobs:
                job["task"].pop("prompt", None)
                job["task"].pop("schema", None)
            return dict(
                project_ref=self.ref,
                revision=state["revision"],
                content_provenance="repository-synthetic-corpus",
                scientific_acceptance=False,
                canonical_stage1_handoff=False,
                budget=dict(
                    reserved=row["calls"],
                    max_calls=self.permit["max_calls"],
                    seconds_remaining=round(remaining, 1),
                    usage_cost="Unknown",
                ),
                blocked=row["blocked"],
                next_task=next_task,
                ready=(
                    next_task is not None
                    and row["blocked"] is None
                    and row["calls"] < self.permit["max_calls"]
                    and remaining > 0
                    and not self._worker_active()
                ),
                jobs=jobs,
                deliveries=deepcopy(row.get("deliveries", {})),
                pipeline=self.pipeline.view(),
            )

    def _worker_active(self):
        return self._worker is not None and self._worker.is_alive()

    def execute(self, credential, ref, body, *, pre_dispatch=None):
        with self._lock:
            self._auth(credential, ref)
            self._guard()
            _check(
                isinstance(body, dict)
                and set(body) == {"key", "revision", "task_sha256", "confirmed"}
                and isinstance(body["key"], str)
                and KEY.fullmatch(body["key"])
                and type(body["revision"]) is int
                and body["confirmed"] is True,
                "pilot-action-fields",
                400,
            )
            row = self._row()
            previous = row["jobs"].get(body["key"])
            if previous is not None:
                _check(
                    previous["task_sha256"] == body["task_sha256"],
                    "pilot-key-payload-differs",
                )
                return deepcopy(previous)
            _check(
                self.model is not None
                and not self._worker_active()
                and row["blocked"] is None,
                "pilot-not-ready",
            )
            _check(
                row["calls"] < self.permit["max_calls"] and self._remaining(row) > 0,
                "pilot-budget-exhausted",
            )
            _check(
                self._next is not None
                and body["task_sha256"] == self._next["task_sha256"],
                "pilot-task-differs",
            )
            if pre_dispatch is not None:
                _check(pre_dispatch() is True, "pilot-request-expired")
            job = dict(
                key=body["key"],
                task_sha256=body["task_sha256"],
                task=deepcopy(self._next),
                status="intent-recorded",
                started_at=None,
                receipt=None,
                error=None,
            )
            with self.store._edit(
                self.pid,
                self.owner,
                body["revision"],
                "pilot-intent-recorded",
                {"key": body["key"], "task_sha256": body["task_sha256"]},
            ) as state:
                state["stage_pilot"]["jobs"][body["key"]] = job
            self._worker = threading.Thread(
                target=self._run, args=(body["key"],), daemon=True
            )
            self._worker.start()
            return deepcopy(job)

    def _run(self, key):
        receipt = None
        try:
            with self._lock:
                self._guard()
                with self.store._edit(
                    self.pid, self.owner, None, "pilot-dispatching", {"key": key}
                ) as state:
                    job = state["stage_pilot"]["jobs"][key]
                    job["status"], job["started_at"] = "running", time.time()
                task = deepcopy(self._row()["jobs"][key]["task"])
                deadline = time.monotonic() + self._remaining(self._row())
            self.pipeline.begin_task(task["task_sha256"])
            receipt = self.model.run(key, task["prompt"], deadline)
            result = self.pipeline.accept(task["task_sha256"], receipt)
            verified = self.model.verify_receipt(
                receipt,
                expected_prompt_sha256=sha(task["prompt"].encode("utf-8")),
                expected_source_sha256=self.permit["source_sha256"],
            )
            accepted = result["history"][-1]["status"] == "accepted"
            with self._lock:
                next_task, next_error = None, None
                try:
                    next_task = self.pipeline.next_task()
                except (ValueError, KeyError, TypeError) as error:
                    next_error = type(error).__name__ + ": " + str(error)[:1024]
                with self.store._edit(
                    self.pid, self.owner, None, "pilot-result-recorded", {"key": key}
                ) as state:
                    job = state["stage_pilot"]["jobs"][key]
                    status = "validated" if accepted else "validation-failed"
                    job.update(
                        status=status,
                        receipt=receipt,
                        result=result,
                        final_text=verified["final_text"],
                    )
                    state["stage_pilot"]["reservations"][key]["outcome"] = status
                    if next_error:
                        state["stage_pilot"]["blocked"] = (
                            "next-step-review-required: " + next_error
                        )
                self._next = next_task
        except BaseException as error:
            with self._lock:
                with self.store._edit(
                    self.pid, self.owner, None, "pilot-failure", {"key": key}
                ) as state:
                    row = state["stage_pilot"]
                    # No automatic replay after an uncertain dispatch or failed validation.
                    row["jobs"][key].update(
                        status="failed-or-unknown",
                        receipt=receipt,
                        error=type(error).__name__ + ": " + str(error)[:1024],
                    )
                    row["blocked"] = "explicit-review-required"

    def publish(self, credential, ref, body, *, pre_dispatch=None):
        """Export retained results, including pending review; never starts a model."""
        with self._lock:
            self._auth(credential, ref)
            self._guard()
            _check(
                isinstance(body, dict)
                and set(body) == {"key", "revision", "confirmed"}
                and isinstance(body["key"], str)
                and KEY.fullmatch(body["key"])
                and type(body["revision"]) is int
                and body["confirmed"] is True,
                "pilot-delivery-fields",
                400,
            )
            row = self._row()
            previous = row.get("deliveries", {}).get(body["key"])
            if previous is not None:
                return deepcopy(previous)
            _check(not self._worker_active(), "pilot-delivery-waits-for-running-unit")
            _check(
                self.pipeline.view().get("candidates"), "pilot-no-validated-candidate"
            )
            if pre_dispatch is not None:
                _check(pre_dispatch() is True, "pilot-request-expired")
            with self.store._edit(
                self.pid,
                self.owner,
                body["revision"],
                "pilot-delivery-intent",
                {"key": body["key"]},
            ) as state:
                state["stage_pilot"].setdefault("deliveries", {})[body["key"]] = {
                    "status": "intent-recorded"
                }
            folder = self.root / "deliveries" / sha(body["key"].encode())
            try:
                manifest = self.pipeline.publish(folder)
                path = folder / "selection.html"
                raw = path.read_bytes()
                _check(len(raw) <= 1024 * 1024, "pilot-delivery-bound-exceeded")
                receipt = dict(
                    status="saved",
                    file_sha256=sha(raw),
                    manifest=manifest,
                    scientific_acceptance=False,
                    file_path=str(path),
                )
            except Exception as error:
                receipt = dict(
                    status="failed-or-unknown",
                    error=type(error).__name__,
                    scientific_acceptance=False,
                )
            with self.store._edit(
                self.pid,
                self.owner,
                None,
                "pilot-delivery-result",
                {"key": body["key"]},
            ) as state:
                state["stage_pilot"]["deliveries"][body["key"]] = receipt
            return deepcopy(receipt)

    def delivery(self, credential, ref, key):
        with self._lock:
            self._auth(credential, ref)
            _check(
                isinstance(key, str) and KEY.fullmatch(key),
                "pilot-delivery-ref-invalid",
                400,
            )
            row = self._row().get("deliveries", {}).get(key)
            _check(
                row is not None and row["status"] == "saved",
                "pilot-delivery-unavailable",
                404,
            )
            path = Path(row["file_path"])
            _check(
                not path.is_symlink()
                and path.is_file()
                and path.resolve().is_relative_to(self.root / "deliveries"),
                "pilot-delivery-binding-differs",
            )
            raw = path.read_bytes()
            _check(
                len(raw) <= 1024 * 1024 and sha(raw) == row["file_sha256"],
                "pilot-delivery-bytes-differ",
            )
            return raw

    def wait(self, seconds=5):
        if self._worker is not None:
            self._worker.join(seconds)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self.model is not None:
            closer = getattr(self.model, "close", None)
            if callable(closer):
                closer()
        self.wait(5)
        if self._worker_active():
            raise SessionApiError("pilot-worker-shutdown-unobserved", 409)
        self.store.release_owner(self.pid, self.owner)
        self.store.close()
