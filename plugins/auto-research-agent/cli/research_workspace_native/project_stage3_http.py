"""Authenticated planning transport over the existing Host and job journal.

The explicit run response is flushed before continuing in that same HTTP
request thread. No queue, worker, scheduler or second execution owner is added.
HTTP admission and the configured native planning deadline remain separate.
"""

from copy import deepcopy
import re
import threading
import time

from stage3_plan.contracts import Stage3Error, digest
from stage3_plan.jobs import POLICY
from stage3_plan.preparation import sha256
from stage3_plan.storage import inspect_package

from .session_api import SessionApiError
from .transport import _decode
from .project_stage3_planning import SOURCE_FIELDS
from .project_stage3_direction_planning import DIRECTION_FIELDS


ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage3/planning"
    r"(?:/(prepare|run|inspect|recover))?"
)


class ProjectStage3Http:
    """A view and connection lifecycle; PlanningJobs remains the durable owner."""

    def __init__(self, service, *, recovery_pins=None, close_owner=None):
        self.service = service
        self.recovery_pins = deepcopy(recovery_pins or {})
        for (ref, key, request), pin in self.recovery_pins.items():
            if not all(type(value) is str and value for value in (ref, key)):
                raise ValueError("trusted planning recovery identity required")
            sha256(request)
            sha256(pin)
        if close_owner is not None and not callable(close_owner):
            raise ValueError("trusted planning owner cleanup required")
        self._close_owner = close_owner
        self._lock = threading.RLock()
        self._active = {}
        self._errors = {}
        self._closed = False
        self._owner_closed = False

    def check_open(self):
        with self._lock:
            if self._closed:
                raise TimeoutError("planning Host closed")

    def view(self, credential, ref, *, check_deadline=None):
        view = self.service.read(credential, ref, check_deadline=check_deadline)
        if view.get("planning_mode") == "direction-intent":
            if check_deadline:
                check_deadline()
            request = view.get("default_request") or {}
            with self._lock:
                return dict(
                    view,
                    submission_in_progress=ref in self._active,
                    submission_error=deepcopy(self._errors.get(ref)),
                    recovery_pin_available=(
                        ref,
                        request.get("key"),
                        request.get("request_sha256"),
                    )
                    in self.recovery_pins,
                )
        result = dict(view, default_request=None, job=None, plan=None)
        with self._lock:
            result["submission_in_progress"] = ref in self._active
            result["submission_error"] = deepcopy(self._errors.get(ref))
        if view["selection_request_sha256"] is None:
            return result
        body = {name: view[name] for name in SOURCE_FIELDS if name != "key"}
        body["key"] = "stage3-" + digest(
            [ref, view["input_version"], view["selection_request_sha256"]]
        )
        result["default_request"] = body
        configured = self.service.bindings.get(ref)
        if configured is None:
            return result
        with self.service.intake._lock:
            jobs = configured["jobs"]
            item = jobs.journal.snapshot(jobs.project_id)["intents"].get(
                jobs._key(body["key"])
            )
            if item is not None:
                body = dict(body, request_sha256=digest(item["payload"]))
                result["job"] = self.service.inspect(
                    credential, ref, body, check_deadline=check_deadline
                )
                result["default_request"] = body
                result["recovery_pin_available"] = (
                    ref,
                    body["key"],
                    body["request_sha256"],
                ) in self.recovery_pins
                if result["job"]["outcome"] == "saved":
                    verified = jobs.inspect(
                        body["key"],
                        expected_request_sha256=body["request_sha256"],
                        current_checkpoint=item["payload"]["checkpoint"],
                    )["result"]["plan"]
                    result["plan"] = inspect_package(
                        verified["package"], verified["manifest_sha256"]
                    )["artifacts"]["plan.json"]
        if check_deadline:
            check_deadline()
        return result

    def admit_run(self, credential, ref, body, check_deadline):
        if (
            type(body) is not dict
            or set(body)
            != (
                DIRECTION_FIELDS
                if body.get("mode") == "direction-intent"
                else SOURCE_FIELDS
            )
            | {"request_sha256", "confirmed"}
            or body["confirmed"] is not True
        ):
            raise SessionApiError("explicit-stage3-planning-required", 400)
        self.check_open()
        job = self.service.inspect(
            credential,
            ref,
            {name: value for name, value in body.items() if name != "confirmed"},
            check_deadline=check_deadline,
        )
        if job["status"] != "intent-recorded":
            return False, job
        marker = (body["key"], body["request_sha256"])
        with self._lock:
            self.check_open()
            if ref in self._active:
                if self._active[ref][0] != marker:
                    raise SessionApiError("stage3-planning-project-busy", 409)
                return False, dict(job, submission_in_progress=True)
            self._active[ref] = (marker, threading.current_thread())
            self._errors.pop(ref, None)
        return True, job

    def failed(self, ref, body, code):
        # The original jobs journal owns durable dispatch/result evidence.
        # Retain a bounded connection failure too; never retry after an ack.
        with self._lock:
            self._errors[ref] = {
                "key": body["key"],
                "request_sha256": body["request_sha256"],
                "code": code,
                "automatic_retry": False,
            }

    def finish(self, ref):
        with self._lock:
            row = self._active.get(ref)
            if row and row[1] is threading.current_thread():
                self._active.pop(ref)
            self._cleanup()

    def _cleanup(self):
        if self._closed and not self._active and not self._owner_closed:
            if self._close_owner is not None:
                self._close_owner()
            self._owner_closed = True

    def close(self):
        with self._lock:
            self._closed = True
            threads = tuple(row[1] for row in self._active.values())
        end = time.monotonic() + 2
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0, end - time.monotonic()))
        with self._lock:
            self._cleanup()
            return dict(
                closed=True,
                active_request_threads=len(self._active),
                threads_joined=not self._active,
                automatic_retry=False,
            )


def handle_planning(handler, method):
    """Keep the existing Host/auth/body/CSP rules and explicit job semantics."""
    running = False
    sent = False
    transport = None
    ref = None
    try:
        token, length = handler._headers(method)
        if handler.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise SessionApiError("cross-site-rejected", 403)
        if handler.server.authenticate(token) is None:
            raise SessionApiError("credential-rejected", 401)
        ref, action = ROUTE.fullmatch(handler.path).groups()
        transport = handler.server.project_stage3_http
        if transport is None:
            raise SessionApiError("stage3-planning-unconnected", 409)
        handler._remaining()
        if method == "GET":
            if length or action is not None:
                raise SessionApiError("invalid-project-read", 400)
            result = transport.view(token, ref, check_deadline=handler._remaining)
        else:
            if action is None:
                raise SessionApiError("unknown-project-write", 404)
            if handler.headers.get("Content-Type", "").lower() != "application/json":
                raise SessionApiError("json-content-type-required", 415)
            if not 0 < length <= 4096:
                raise SessionApiError("stage3-planning-body-bound-exceeded", 413)
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise SessionApiError("partial-body", 400)
            body = _decode(raw.decode("utf8"))
            if type(body) is not dict:
                raise SessionApiError("stage3-planning-object-required", 400)
            handler._remaining()
            service = transport.service
            if action == "run":
                running, result = transport.admit_run(
                    token, ref, body, handler._remaining
                )
                if running:
                    handler._remaining()
                    handler._reply(
                        202,
                        dict(
                            kind="ProjectStage3PlanningSubmission",
                            submission_status="accepted",
                            dispatch_observed=False,
                            job=result,
                            **POLICY,
                        ),
                    )
                    handler.wfile.flush()
                    sent = True
                    handler.close_connection = True
                    # Reuse this existing authenticated request thread after its
                    # response. The original adapter still owns the native limit.
                    service.run(token, ref, body, check_deadline=transport.check_open)
                    return
            elif action == "recover":
                identity = (ref, body.get("key"), body.get("request_sha256"))
                pin = transport.recovery_pins.get(identity)
                if pin is None:
                    raise SessionApiError("trusted-stage3-recovery-pin-required", 409)
                result = service.recover(
                    token,
                    ref,
                    body,
                    expected_plan_manifest_sha256=pin,
                    check_deadline=handler._remaining,
                )
            else:
                result = getattr(service, action)(
                    token, ref, body, check_deadline=handler._remaining
                )
        handler._remaining()
        handler._reply(200, result)
    except SessionApiError as error:
        if sent:
            transport.failed(ref, body, error.code)
        else:
            handler._reply(error.status, {"error": error.code})
    except (ValueError, UnicodeError, KeyError, TypeError, RecursionError, Stage3Error):
        if sent:
            transport.failed(ref, body, "stage3-planning-input-rejected")
        else:
            handler._reply(400, {"error": "stage3-planning-input-rejected"})
    except (TimeoutError, OSError):
        if sent:
            transport.failed(ref, body, "stage3-planning-deadline-or-io-failed")
        handler.close_connection = True
    except Exception:
        if sent:
            transport.failed(ref, body, "stage3-planning-operation-failed")
        else:
            handler._reply(500, {"error": "stage3-planning-operation-failed"})
    finally:
        if running and transport is not None:
            transport.finish(ref)
