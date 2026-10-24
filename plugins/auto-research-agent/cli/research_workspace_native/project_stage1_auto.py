"""Trusted Stage1 continuation through existing project-owned operations.

This Python-only adapter starts no provider and grants no authority. Search still
requires its existing sealed permit; semantic decisions and content review remain
with their original producers. Default continuation covers admitted planned
queries and saved checkpoint/records/delivery, stopping at missing producers or
Core/Wiki review. It is not evidence of a complete topic-to-delivery run.
"""

import json
import threading
import time

from stage1_ledger.journal import canonical
from stage1_deliverable.common import sha
from .project_intake import ProjectIntakeService
from .project_stage1 import ProjectStage1Service
from .project_stage1_progress import project_progress
from .project_stage1_continuation import (
    ContinuationAction,
    ContinuationBinding,
    ContinuationSnapshot,
    DurableAction,
    continue_stage1,
)
from .session_api import _check


class ProjectStage1AutoDriver:
    """Server bootstrap only; never accept a host or callable from browser JSON."""

    def __init__(self, host, credential, project_ref):
        _check(
            isinstance(host.projects, ProjectIntakeService)
            and isinstance(host.project_stage1, ProjectStage1Service)
            and host.project_stage1.intake is host.projects
            and callable(host.overview),
            "stage1-auto-same-project-owner-required",
        )
        self.host, self.intake = host, host.projects
        self.credential, self.ref = credential, project_ref
        self.principal = self.intake._principal(credential)
        self._operations = {}
        self._last = None

    def _binding(self):
        value = self.intake.binding(self.ref)
        return ContinuationBinding(
            value["project_id"],
            self.ref,
            value["input_version"],
            value["brief_sha256"],
            value["plan_manifest_sha256"],
            sha(canonical(value["settings"])),
        )

    @property
    def queries(self):
        return self.host.project_stage1.query_service

    def _query_observation(self, receipt, state, view):
        queries = self.queries
        if queries is None:
            return "execution-unknown", None, None
        if receipt["kind"] == "stage1-query-bootstrap":
            observed = state.get("stage1_query_jobs", {}).get(receipt["request_sha256"])
            if observed is not None and (
                observed.get("key") != receipt["key"]
                or observed.get("request_sha256") != receipt["request_sha256"]
            ):
                return "execution-unknown", None, None
            worker = queries.workers.get(self.ref)
        else:
            child_key = receipt.get("query_action_key")
            rows = view.get("query_history", {}).get("history", [])
            observed = next((r for r in rows if r.get("client_key") == child_key), None)
            owner = queries.services.get(self.ref)
            worker = None if owner is None else owner._workers.get(self.ref)
        if observed is None:
            return "execution-unknown", None, None
        status = observed["status"]
        if status in {"dispatch-unobserved", "dispatching"}:
            status = (
                "running"
                if worker is not None and worker.is_alive()
                else "execution-unknown"
            )
        if status == "completed":
            # A recorded backend failure remains in observed.result; a known
            # unsent refusal or uncertain operation cannot unlock another step.
            outcome = observed.get("outcome", "observed")
            if outcome != "observed":
                return "execution-unknown", None, observed
            return "completed", "succeeded", observed
        return status, None, observed

    def snapshot(self):
        with self.intake._lock:
            state = self.intake._load(self.principal, self.ref)
            binding = self._binding()
            overview = self.host.overview(self.credential, self.ref)
            progress = project_progress(overview)
            stage = overview["stage1"] or {}
            query_view = stage.get("query_execution") or {}
            rows = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? ORDER BY rowid",
                (self.principal, self.ref),
            ).fetchall()
            actions, observations = [], []
            for raw in rows:
                saved = json.loads(raw[0])
                request = saved["request"]
                if not saved["key"].startswith("stage1-auto-") or not (
                    type(request.get("input_version")) is type(binding.input_version)
                    and request.get("input_version") == binding.input_version
                    and request.get("brief_sha256") == binding.brief_sha256
                ):
                    continue
                receipt = self.intake.action(
                    self.credential, saved["key"], project_ref=self.ref
                )
                status, outcome = receipt["status"], None
                observed = None
                if status == "saved" and receipt["kind"] in {
                    "stage1-query-execute",
                    "stage1-query-bootstrap",
                }:
                    status, outcome, observed = self._query_observation(
                        receipt, state, query_view
                    )
                observations.append(observed)
                actions.append(
                    DurableAction(
                        receipt["key"],
                        self.ref,
                        status,
                        receipt["request_sha256"],
                        sha(
                            canonical(
                                {"receipt": receipt, "owner_observation": observed}
                            )
                        ),
                        outcome,
                    )
                )
            frontier = sha(
                canonical({"state": state, "query_observations": observations})
            )
            self._last = overview
            return ContinuationSnapshot(binding, frontier, progress, tuple(actions))

    def next_action(self, snapshot):
        overview = self._last
        phase = snapshot.progress["next_action"]["phase_id"]
        stage = overview["stage1"] or {}
        current = overview["project"]
        common = {
            "revision": current["revision"],
            "input_version": current["input_version"],
            "brief_sha256": current["brief_sha256"],
            "confirmed": True,
        }
        operation, method, body = None, None, None
        if phase == "query" and self.queries is not None:
            view = stage.get("query_execution") or {}
            if view.get("execution_authorized") is not True:
                return None
            for name, candidate in (
                ("query_offer", "execute"),
                ("bootstrap_offer", "bootstrap"),
            ):
                offer = view.get(name)
                if offer is not None:
                    operation, method = candidate, getattr(self.queries, candidate)
                    body = {
                        **common,
                        "offer_ref": offer["offer_ref"],
                        "offer_sha256": offer["offer_sha256"],
                    }
                    break
        elif phase == "delivery":
            ledger = stage.get("ledger") or {}
            checkpoint = stage.get("checkpoint")
            offers = (stage.get("delivery") or {}).get("offers", [])
            if offers:
                offer = offers[0]
                operation, method = "deliver", self.host.project_stage1_delivery.deliver
                body = {
                    **common,
                    "offer_ref": offer["offer_ref"],
                    "offer_sha256": offer["offer_sha256"],
                }
            elif ledger and (
                checkpoint is None or checkpoint.get("current") is not True
            ):
                operation, method = "checkpoint", self.host.project_stage1.checkpoint
                body = {**common, "ledger_state_sha256": ledger["state_sha256"]}
            elif (
                checkpoint is not None and self.host.project_records_prepare is not None
            ):
                operation, method = "records", self.host.project_records_prepare.prepare
                body = {
                    **common,
                    "ledger_state_sha256": ledger["state_sha256"],
                    "checkpoint_event_id": checkpoint["event_id"],
                }
        if method is None:
            return None
        identity = sha(
            canonical(
                {
                    "operation": operation,
                    "body": {k: v for k, v in body.items() if k != "revision"},
                }
            )
        )
        kind = (
            "records"
            if operation == "records"
            else "delivery"
            if phase == "delivery"
            else "query"
        )
        self._operations[identity] = (method, body)
        return ContinuationAction(
            kind, identity, snapshot.binding, snapshot.frontier_sha256
        )

    def dispatch(self, action, key, deadline):
        _check(time.monotonic() < deadline, "stage1-auto-deadline-exhausted", 408)
        method, body = self._operations.pop(action.identity)
        _check(
            getattr(method.__self__, "intake", None) is self.intake,
            "stage1-auto-owner-differs",
        )

        def check():
            _check(time.monotonic() < deadline, "stage1-auto-deadline-exhausted", 408)

        return method(
            self.credential, self.ref, {**body, "key": key}, check_deadline=check
        )

    def wait(self, action, deadline):
        with self.intake._lock:
            receipt = self.intake.action(
                self.credential, action.key, project_ref=self.ref
            )
            if self.queries is None:
                return
            if receipt["kind"] == "stage1-query-bootstrap":
                worker = self.queries.workers.get(self.ref)
            elif receipt["kind"] == "stage1-query-execute":
                owner = self.queries.services.get(self.ref)
                worker = None if owner is None else owner._workers.get(self.ref)
            else:
                return
        if worker is not None and worker is not threading.current_thread():
            worker.join(max(0, deadline - time.monotonic()))

    def run(
        self,
        *,
        run_id,
        deadline,
        max_actions=32,
        run_grants=None,
        grant_ref=None,
        grant_sha256=None,
    ):
        if run_grants is not None or grant_ref is not None or grant_sha256 is not None:
            from .project_stage1_run_continuation import ProjectStage1RunContinuation

            return ProjectStage1RunContinuation(
                self, run_grants, grant_ref, grant_sha256
            ).run(
                run_id=run_id,
                deadline=deadline,
                max_actions=max_actions,
            )
        result = continue_stage1(
            run_id=run_id,
            binding=self._binding(),
            snapshot=self.snapshot,
            next_action=self.next_action,
            handlers={
                "query": self.dispatch,
                "records": self.dispatch,
                "delivery": self.dispatch,
            },
            deadline=deadline,
            max_actions=max_actions,
            wait=self.wait,
        )
        result["supported_operations"] = [
            "admitted-planned-query",
            "saved-checkpoint",
            "saved-records",
            "saved-delivery",
        ]
        result["unconnected_producers"] = [
            "automatic-screening",
            "automatic-full-note-review",
        ]
        return result
