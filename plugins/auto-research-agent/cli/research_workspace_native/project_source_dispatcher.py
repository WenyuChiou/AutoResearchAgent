"""Explicit trusted scheduling of one saved source queue, without recovery."""

import threading
import time

from .project_stage1_source_service import ProjectStage1SourceService
from .session_api import SessionApiError, _check

MAX_REMEMBERED = 128


class ProjectSourceDispatcher:
    """Portable setup owns this object; browser requests cannot construct it.

    The broker remains the durable authority and atomically claims a queue.
    This object only schedules newly saved actions once. It never discovers
    pending work on GET, restart or owner recovery. Thread state is local, not
    recoverable orchestration or source/native attestation.
    """

    def __init__(self, service):
        _check(
            type(service) is ProjectStage1SourceService,
            "source-dispatch-trusted-service-required",
        )
        self.service = self._bound_service = service
        self.intake = service.intake
        self._lock = threading.Lock()
        self._workers, self._observations = {}, {}
        self._closed = False

    def _bound(self):
        _check(
            self.service is self._bound_service and self.service.intake is self.intake,
            "source-dispatch-binding-changed",
        )

    def submit_saved(self, credential, ref, key, receipt):
        """Schedule only the exact newly saved execute receipt, once per key."""
        self._bound()
        _check(
            type(receipt) is dict
            and receipt.get("project_ref") == ref
            and receipt.get("key") == key
            and receipt.get("kind") == "stage1-source-execute",
            "source-dispatch-saved-receipt-required",
        )
        if (
            receipt.get("status") != "saved"
            or receipt.get("job_status") != "queued"
            or receipt.get("replayed") is not False
        ):
            return dict(submitted=False, replayed_or_not_queued=True)
        # A caller's literal receipt does not create a queue or authorize I/O.
        # Reopen actual saved state, then the broker rechecks its full causal
        # grant/reservation/owner/deadline before its atomic invocation claim.
        job = self.service.read(credential, ref)["jobs"].get(key)
        _check(
            job is not None
            and job["job_binding_sha256"] == receipt.get("job_binding_sha256")
            and job["status"] == "queued",
            "source-dispatch-current-queue-required",
        )
        marker = (ref, key)
        overflow = False
        with self._lock:
            _check(not self._closed, "source-dispatcher-closed")
            if marker in self._workers:
                return dict(submitted=False, already_scheduled=True)
            if len(self._workers) >= MAX_REMEMBERED:
                overflow = True
            else:
                worker = threading.Thread(
                    target=self._run,
                    args=(credential, ref, key),
                    name="stage1-source-dispatch",
                    daemon=True,
                )
                self._workers[marker] = worker
                self._observations[marker] = dict(status="start-unobserved")
        if overflow:
            self._uncertain(
                credential,
                ref,
                key,
                SessionApiError("source-dispatcher-local-bound-exceeded", 429),
                "local-capacity-unobserved",
            )
            return dict(submitted=False, status="execution-unknown")
        try:
            worker.start()
        except BaseException as error:
            self._uncertain(credential, ref, key, error, "thread-start-unobserved")
            if not isinstance(error, Exception):
                raise
            return dict(submitted=False, status="execution-unknown")
        return dict(submitted=True, status="scheduled", execution_observed=False)

    def _uncertain(self, credential, ref, key, error, phase):
        observed = dict(
            status="execution-unknown",
            phase=phase,
            error_type=type(error).__name__,
            failure_saved=False,
            automatic_retry=False,
        )
        try:
            principal = self.intake._principal(credential)

            def unknown(job, _state):
                # Preserve any original result/counters and earlier proof.
                # Failure to observe scheduling cannot assert known-unsent.
                job.update(
                    status="execution-unknown",
                    failure=dict(
                        code="source-dispatch-failed-or-unobserved",
                        error_type=type(error).__name__,
                        phase=phase,
                    ),
                )

            self._bound_service._change_job(
                principal,
                ref,
                key,
                "source-dispatch-execution-unknown",
                unknown,
                require_owner=False,
            )
            observed["failure_saved"] = True
        except Exception as save_error:
            observed["failure_save_error_type"] = type(save_error).__name__
        with self._lock:
            marker = (ref, key)
            if marker in self._observations or len(self._observations) < MAX_REMEMBERED:
                self._observations[marker] = observed

    def _run(self, credential, ref, key):
        try:
            self._bound()
            with self._lock:
                if self._closed:
                    return
            result = self.service.dispatch_pending(credential, ref, key)
            with self._lock:
                self._observations[(ref, key)] = dict(
                    status=result["status"],
                    result_scope="saved-broker-observation",
                    automatic_retry=False,
                )
        except BaseException as error:
            self._uncertain(credential, ref, key, error, "dispatch-unobserved")
            if not isinstance(error, Exception):
                raise

    def close(self):
        """Stop admissions/owners; bounded join never extends a worker deadline."""
        with self._lock:
            self._closed = True
            workers = tuple(self._workers.values())
        # Source owner release makes the real worker's next current check fail;
        # its original Job watchdog/absolute deadline still owns containment.
        self._bound_service.close()
        end = time.monotonic() + 2
        for worker in workers:
            if worker is not threading.current_thread() and worker.ident is not None:
                worker.join(max(0, end - time.monotonic()))
        return dict(
            closed=True,
            thread_count=len(workers),
            threads_joined=all(not worker.is_alive() for worker in workers),
            cleanup_scope="dispatcher threads only; worker Job observations remain authoritative",
            automatic_retry=False,
        )
