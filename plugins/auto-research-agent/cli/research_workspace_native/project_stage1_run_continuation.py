"""Owner-backed continuation for an explicitly saved Stage 1 run grant."""

import json
from copy import deepcopy
import threading
import time

from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical
from .project_stage1_continuation import (
    ContinuationSnapshot,
    DurableAction,
    continue_stage1,
)
from .project_stage1_producer_progress import project_producer_progress
from .project_stage1_producer_queue import ProjectStage1ProducerQueue
from .project_stage1_run_actions import ProjectStage1RunActions


TRACKED = frozenset(
    {
        "stage1-query-authorize",
        "stage1-query-bootstrap",
        "stage1-query-execute",
        "stage1-source-authorize",
        "stage1-source-execute",
        "model-operation",
        "model-authorization",
        "stage1-agent-pending",
        "stage1-agent-analysis",
        "stage1-agent-coverage",
        "stage1-coverage",
        "stage1-reading-registry",
        "stage1-source-registry",
        "stage1-checkpoint",
        "stage1-produce-records",
        "stage1-deliver",
    }
)


def round_query_progress(progress, coverage, query_offer, selection):
    """Navigation only, from current owner views; receipt and human barriers win."""
    current = progress.get("next_action")
    pending_receipt = any(
        o["operation"] == "receipt" and o["document"]["current_receipt"] is None
        for o in coverage.get("offers", [])
    )
    if (
        current is None
        or current["phase_id"] != "coverage"
        or any(row["status"] == "held" for row in progress["phases"])
        or selection is not None
        or query_offer is None
        or coverage.get("active_round") is None
        or query_offer.get("document", {}).get("round_number")
        != coverage["active_round"]
        or pending_receipt
    ):
        return progress
    result = deepcopy(progress)
    for row in result["phases"]:
        if row["phase_id"] == "query":
            row.update(status="available", reason="query-offered")
    result["next_action"] = dict(
        phase_id="query", target="query", reason="query-offered"
    )
    return result


class ProjectStage1RunContinuation:
    """Use original services and receipts; never recover or resend unknown work."""

    def __init__(self, driver, issuer, grant_ref, grant_sha256):
        self.driver = driver
        self.actions = ProjectStage1RunActions(driver, issuer, grant_ref, grant_sha256)
        self.intake, self.host = driver.intake, driver.host
        self.credential, self.ref, self.principal = (
            driver.credential,
            driver.ref,
            driver.principal,
        )
        self.queue = ProjectStage1ProducerQueue(
            self.host.project_stage1,
            self.host.project_models,
            self.host.project_stage1_records,
            self.host.project_stage1_sources,
        )
        self.overview, self.selection = None, None

    def _source_worker(self, key):
        dispatcher = getattr(self.host, "project_stage1_source_dispatcher", None)
        return None if dispatcher is None else dispatcher._workers.get((self.ref, key))

    def _observation(self, receipt, state, stage):
        kind, key = receipt["kind"], receipt["key"]
        if kind in {"stage1-query-bootstrap", "stage1-query-execute"}:
            return self.driver._query_observation(
                receipt, state, stage.get("query_execution") or {}
            )
        if kind == "model-operation":
            # Read the full stored history, not the public last32 projection.
            job = state.get("model_operations", {}).get("jobs", {}).get(key)
            worker = self.host.project_models._workers.get((self.ref, key))
            done = {"content-review-pending", "draft-review-pending"}
        elif kind == "stage1-source-execute":
            service = self.host.project_stage1_sources
            job = (
                None
                if service is None
                else service.read(self.credential, self.ref)["jobs"].get(key)
            )
            worker = self._source_worker(key)
            done = {
                "source-observation-saved",
                "failed-observed",
                "refused-known-unsent",
            }
        else:
            return "saved", None, None
        if job is None:
            return "execution-unknown", None, None
        status = job["status"]
        if status in {"intent-recorded", "queued", "dispatching", "running"}:
            status = (
                "running"
                if worker is not None and worker.is_alive()
                else "execution-unknown"
            )
        if worker is not None and worker.is_alive():
            # A source pipeline may still be registering the observed raw result.
            return "running", None, job
        if status in done:
            followup = job.get("followup")
            if (
                followup is not None
                and followup.get("status") != "source-core-registered"
            ):
                return "execution-unknown", None, job
            # Technical terminal observation only; failed transport stays in job.
            return "completed", "succeeded", job
        return status, None, job

    def snapshot(self):
        with self.intake._lock:
            self.actions.document()
            state = self.intake._load(self.principal, self.ref)
            binding = self.driver._binding()
            overview = self.host.overview(self.credential, self.ref)
            stage = overview.get("stage1") or {}
            ledger = stage.get("ledger")
            queue = None
            if ledger is not None:
                queue = self.queue.inspect(self.credential, self.ref)
            self.overview, self.selection = (
                overview,
                None if queue is None else queue["selection"],
            )
            progress = project_producer_progress(
                overview, None if queue is None else queue["view"]
            )
            coverage = stage.get("coverage_actions") or {}
            query_offer = (stage.get("query_execution") or {}).get("query_offer")
            progress = round_query_progress(
                progress, coverage, query_offer, self.selection
            )
            rows = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? ORDER BY rowid",
                (self.principal, self.ref),
            ).fetchall()
            actions, observations = [], []
            for raw in rows:
                saved = json.loads(raw[0])
                request = saved["request"]
                if saved["kind"] not in TRACKED or not all(
                    type(request.get(k)) is type(getattr(binding, k))
                    and request.get(k) == getattr(binding, k)
                    for k in ("input_version", "brief_sha256")
                ):
                    continue
                receipt = self.intake.action(
                    self.credential, saved["key"], project_ref=self.ref
                )
                status, outcome, observed = receipt["status"], None, None
                if status == "saved":
                    status, outcome, observed = self._observation(receipt, state, stage)
                observations.append(observed)
                actions.append(
                    DurableAction(
                        receipt["key"],
                        self.ref,
                        status,
                        receipt["request_sha256"],
                        sha(
                            canonical(dict(receipt=receipt, owner_observation=observed))
                        ),
                        outcome,
                    )
                )
            frontier = sha(
                canonical(dict(state=state, observations=observations, ledger=ledger))
            )
            return ContinuationSnapshot(binding, frontier, progress, tuple(actions))

    @staticmethod
    def _offer_body(offer):
        return dict(offer_ref=offer["offer_ref"], offer_sha256=offer["offer_sha256"])

    def _round(self, coverage, operation):
        for offer in coverage.get("offers", []):
            if offer["operation"] == operation and (
                operation != "receipt" or offer["document"]["current_receipt"] is None
            ):
                review = (
                    dict(
                        truncated=None,
                        note="Truncation not attested by this saved backend observation.",
                    )
                    if operation == "receipt"
                    else {}
                )
                return dict(
                    operation=operation, review=review, **self._offer_body(offer)
                )
        return None

    def next_action(self, snapshot):
        stage = self.overview.get("stage1") or {}
        phase = snapshot.progress["next_action"]["phase_id"]
        selection = self.selection
        if selection is not None and phase in {"screening", "reading", "coverage"}:
            return self.actions.prepare(
                snapshot, selection["operation"], selection["body"]
            )
        if phase == "query":
            view = stage.get("query_execution") or {}
            for name, operation in (
                ("authorization_offer", "query-authorize"),
                ("bootstrap_offer", "query-bootstrap"),
                ("query_offer", "query-execute"),
            ):
                offer = view.get(name)
                if offer is not None:
                    return self.actions.prepare(
                        snapshot, operation, self._offer_body(offer)
                    )
        elif phase == "coverage":
            coverage = stage.get("coverage_actions") or {}
            for operation in ("receipt", "close-round", "open-round"):
                body = self._round(coverage, operation)
                if body is not None:
                    return self.actions.prepare(snapshot, "round", body)
        elif phase == "delivery":
            ledger, checkpoint = stage.get("ledger") or {}, stage.get("checkpoint")
            offers = (stage.get("delivery") or {}).get("offers", [])
            if offers:
                return self.actions.prepare(
                    snapshot, "delivery", self._offer_body(offers[0])
                )
            if ledger and (checkpoint is None or checkpoint.get("current") is not True):
                return self.actions.prepare(snapshot, "checkpoint", {})
            if checkpoint is not None:
                return self.actions.prepare(
                    snapshot,
                    "records",
                    dict(checkpoint_event_id=checkpoint["event_id"]),
                )
        return None

    def wait(self, action, deadline):
        delegate = False
        with self.intake._lock:
            receipt = self.intake.action(
                self.credential, action.key, project_ref=self.ref
            )
            if receipt["kind"] == "model-operation":
                worker = self.host.project_models._workers.get((self.ref, action.key))
            elif receipt["kind"] == "stage1-source-execute":
                worker = self._source_worker(action.key)
            else:
                delegate = True
                worker = None
        # The original wait reacquires intake only to inspect; never join while
        # holding this outer lock needed by the actual query worker.
        if delegate:
            return self.driver.wait(action, deadline)
        if worker is not None and worker is not threading.current_thread():
            worker.join(max(0, deadline - time.monotonic()))

    def run(self, *, run_id, deadline, max_actions):
        result = continue_stage1(
            run_id=run_id,
            binding=self.driver._binding(),
            snapshot=self.snapshot,
            next_action=self.next_action,
            handlers={
                key: self.actions.dispatch
                for key in (
                    "query",
                    "screen",
                    "source",
                    "reading",
                    "coverage",
                    "records",
                    "delivery",
                )
            },
            deadline=deadline,
            max_actions=max_actions,
            wait=self.wait,
            key_for_action=self.actions.key_for,
        )
        result["supported_operations"] = [
            "saved-user-run-grant",
            "original-query-source-model",
            "agent-proposal-adoption",
            "coverage-companion",
            "saved-checkpoint-records-delivery",
        ]
        result["required_external_reviews"] = [
            "content-Core",
            "same-version-Wiki",
            "formal-Stage1-to-Stage2",
        ]
        return result
