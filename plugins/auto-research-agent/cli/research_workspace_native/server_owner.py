"""Explicit server ownership and one passive pump over an already bound session.

This module never spawns, initializes, creates, resumes or starts a model turn.
Configured callbacks and receipts do not authenticate Codex or grant authority.
GET/status calls never pump; stopped sessions never automatically reconnect.
"""

from copy import deepcopy
import math
from pathlib import Path
import threading
import time

from .controller import InjectedSessionController
from .process_channel import OwnedProcessChannel
from .process_deadline import Deadline, SessionLeaseExpired
from .session_api import SessionApi
from .store import _require

_SLOTS, _SLOT_LOCK = {}, threading.RLock()


class SessionOwners:
    def __init__(self, *, api):
        _require(isinstance(api, SessionApi), "existing session API required")
        self.api, self._owners, self._pending = api, {}, {}
        self._lock = threading.RLock()
        self._closed = False

    def register(
        self,
        project_ref,
        *,
        controller,
        owned_channel,
        principals,
        source_root,
        index_sha256,
        input_version,
        verify_source,
        admit_attach,
        start_offer=None,
        approval_policy=None,
        trusted_stage_unit=False,
    ):
        """Trusted configuration; pre-admission refusal leaves resources borrowed."""
        _require(type(trusted_stage_unit) is bool, "literal stage unit opt-in required")
        _require(
            type(controller) is InjectedSessionController
            and type(owned_channel) is OwnedProcessChannel
            and callable(verify_source)
            and callable(admit_attach),
            "server configured controller/channel/gates required",
        )
        channel = owned_channel

        def channel_bound():
            _require(
                controller.channel.channel is channel
                and controller.store is channel.store
                and controller.project_id == channel.project_id
                and controller.owner == channel.owner
                and controller.connection_id == channel.connection_id
                and index_sha256 == controller.index_sha256 == channel.index_sha256
                and input_version == channel.input_version
                and not channel.closed
                and not controller.failure,
                "owned channel/session binding differs",
            )

        channel_bound()
        root = Path(source_root)
        _require(root.is_absolute() and root.is_dir(), "source directory required")
        binding = dict(
            project_ref=project_ref,
            project_id=controller.project_id,
            source_root=root.resolve().as_posix(),
            index_sha256=index_sha256,
            input_version=input_version,
            thread_id=controller.thread_id,
            connection_id=controller.connection_id,
        )
        _require(admit_attach(deepcopy(binding)) is True, "attach admission refused")
        channel_bound()
        slot = (controller.store.path.resolve(), controller.project_id)
        marker = object()
        with self._lock, _SLOT_LOCK:
            _require(not self._closed, "session registry closed")
            _require(
                project_ref not in self._owners and slot not in _SLOTS,
                "session already process registered",
            )
            _SLOTS[slot] = marker
            pending = dict(done=threading.Event(), error=None, channel=channel)
            self._pending[slot] = pending
        try:
            with controller.store._lock:
                state = controller._context()
                _require(
                    not state.get("session_service"), "historical service retained"
                )
                options = dict(
                    controller=controller,
                    principals=principals,
                    source_root=root,
                    index_sha256=index_sha256,
                    input_version=input_version,
                    verify_source=lambda value: self._source(verify_source, value),
                )
                if trusted_stage_unit:
                    options["trusted_stage_unit"] = True
                if start_offer is not None:
                    options["start_offer"] = start_offer
                if approval_policy is not None:
                    options["approval_policy"] = approval_policy
                self.api.register(project_ref, **options)
                channel_bound()
                _require(not self._closed, "registry closed before transfer")
                owner = SessionOwner(
                    self, binding, controller, channel, verify_source, slot
                )
                with controller.store._edit(
                    controller.project_id,
                    controller.owner,
                    None,
                    "session-service-registered",
                    binding,
                ) as saved:
                    saved["session_service"] = dict(
                        binding=binding, status="registered"
                    )
            with self._lock, _SLOT_LOCK:
                _require(
                    not self._closed, "session registry closed during registration"
                )
                self._owners[project_ref] = owner
                _SLOTS[slot] = owner
            return owner
        except BaseException:
            channel.close()
            try:
                controller.close()
                receipt = channel.reap(10)
                _require(
                    receipt.get("leader_reaped") is True
                    and receipt.get("errors") == [],
                    "registration cleanup unobserved",
                )
            except BaseException as error:
                pending["error"] = type(error).__name__
            with _SLOT_LOCK:
                if pending["error"] is None and _SLOTS.get(slot) is marker:
                    del _SLOTS[slot]
            raise
        finally:
            pending["done"].set()

    def _source(self, verifier, value):
        _require(not self._closed, "session registry closed")
        result = verifier(deepcopy(value))
        _require(not self._closed, "session registry closed during source check")
        return result

    def bindings(self):
        with self._lock:
            return {
                ref: {
                    key: owner.binding[key]
                    for key in ("project_id", "index_sha256", "input_version")
                }
                for ref, owner in self._owners.items()
            }

    def shutdown(self, timeout=10):
        deadline = _deadline(timeout)
        with self._lock:
            self._closed = True
            owners = tuple(self._owners.items())
            pending = tuple(self._pending.values())
        # Request every physical close before waiting for any journal or pump.
        for _, owner in owners:
            owner._begin_stop("server-shutdown")
        for item in pending:
            if not item["done"].is_set():
                item["channel"].close()
        results, failures = {}, []
        for item in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not item["done"].wait(remaining):
                failures.append("registration-unobserved")
            elif item["error"] is not None:
                failures.append("registration-cleanup-unobserved")
        for ref, owner in owners:
            try:
                results[ref] = owner._wait_stop(deadline)
            except BaseException as error:
                failures.append(type(error).__name__)
        _require(not failures, "session cleanup unobserved: " + ",".join(failures))
        return results


def _deadline(timeout):
    _require(
        type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 10,
        "bounded shutdown timeout required",
    )
    return time.monotonic() + timeout


class SessionOwner:
    def __init__(self, registry, binding, controller, channel, verifier, slot):
        self.registry, self.binding = registry, deepcopy(binding)
        self.controller, self.channel, self._verifier = controller, channel, verifier
        self._slot, self._lock = slot, threading.RLock()
        self._stop, self._done = threading.Event(), threading.Event()
        self._thread, self._cleanup_thread = None, None
        self._started, self._stopping, self._running = False, False, False
        self._failure, self._receipt = None, None

    def start(self):
        """Explicit single-use passive pump; never launches or sends a new RPC."""
        with self._lock:
            _require(not self._started and not self._stopping, "pump cannot restart")
            _require(not self.registry._closed, "session registry closed")
            self._started = True
            self._running = True
            self._thread = threading.Thread(
                target=self._run, name="workspace-session-pump", daemon=True
            )
            try:
                self._thread.start()
            except BaseException as error:
                self._thread, self._running = None, False
                self._begin_stop("pump-start-failed:" + type(error).__name__)
                raise

    def status(self):
        with self._lock:
            return dict(
                project_ref=self.binding["project_ref"],
                index_sha256=self.binding["index_sha256"],
                input_version=self.binding["input_version"],
                running=self._running,
                started=self._started,
                stopped=self._stopping,
                cleanup_observed=self._done.is_set() and self._receipt is not None,
                failure=self._failure,
                authenticated_process=False,
                process_tree_containment_verified=False,
            )

    def _run(self):
        failure = "pump-stopped"
        phase = "source-check"
        try:
            while not self._stop.is_set():
                phase = "source-check"
                # Source verification shares a lock with full action admission.
                # Keep every poll verified within the bounded I/O allowance and
                # process lease; waiting grants no write or model authority.
                deadline = Deadline(30, self.channel.deadline)
                deadline.guard(lambda: self._verifier(deepcopy(self.binding)))
                _require(not self.channel.closed, "owned process closed")
                # Poll only queued bytes/complete frames. Idle timeout observations
                # would churn revisions and make every browser answer stale.
                if (
                    b"\n" in self.controller.transport.buffer
                    or self.channel._buffer
                    or not self.channel._stdout.empty()
                ):
                    phase = "passive-read"
                    self.controller.pump(0)
                self._stop.wait(0.01)
        except SessionLeaseExpired:
            failure = "session-lease-expired"
        except BaseException as error:
            failure = "pump-failed:" + phase + ":" + type(error).__name__
        finally:
            with self._lock:
                self._running = False
            self._begin_stop(failure)

    def _begin_stop(self, reason):
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            self._failure = reason
            self._stop.set()
            self.channel.close()  # Physical cleanup precedes controller/DB locks.
            self._cleanup_thread = threading.Thread(
                target=self._cleanup, daemon=True, name="workspace-session-cleanup"
            )
            self._cleanup_thread.start()

    def _cleanup(self):
        try:
            if self._thread is not None:
                self._thread.join(10)
                _require(not self._thread.is_alive(), "pump exit unobserved")
            self.controller.close()
            receipt = self.channel.reap(10)
            _require(
                receipt.get("leader_reaped") is True and receipt.get("errors") == [],
                "owned leader cleanup failed",
            )
            with self.controller.store._lock:
                with self.controller.store._edit(
                    self.controller.project_id,
                    self.controller.owner,
                    None,
                    "session-service-stopped",
                    dict(reason=self._failure),
                ) as saved:
                    _require(
                        saved["session_service"]["binding"] == self.binding,
                        "saved service binding differs",
                    )
                    saved["session_service"]["status"] = "stopped"
                    saved["session_service"]["cleanup"] = dict(
                        leader_reaped=True,
                        process_tree_containment_verified=False,
                        journal_cleanup_observed=receipt.get("journal_cleanup_observed")
                        is True,
                    )
            with self._lock:
                self._receipt = receipt
            with _SLOT_LOCK:
                if _SLOTS.get(self._slot) is self:
                    del _SLOTS[self._slot]
        except BaseException as error:
            with self._lock:
                self._failure += "; cleanup-unobserved:" + type(error).__name__
        finally:
            self._done.set()

    def _wait_stop(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._done.wait(remaining):
            raise TimeoutError("session shutdown deadline expired")
        with self._lock:
            _require(self._receipt is not None, self._failure or "cleanup unobserved")
            return deepcopy(self._receipt)

    def shutdown(self, timeout=10):
        deadline = _deadline(timeout)
        self._begin_stop("server-shutdown")
        return self._wait_stop(deadline)
