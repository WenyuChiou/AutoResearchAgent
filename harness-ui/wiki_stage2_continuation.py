"""Explicit Wiki intent for an operator-configured Stage 2 controller."""

import json
import logging
import re
from threading import Lock

from research_workspace_native.project_stage2_controller import (
    _guard,
    _json,
    _raw,
    _read,
    _write,
)
from research_workspace_native.session_api import SessionApiError, _check, _hash
from research_workspace_native.transport import _decode
from stage1_deliverable.common import private_output
from stage2_common import canonical_hash
from stage2_live.preparation import _admitted
from stage2_workflow.decision_cards import derive_decision_cards
from stage2_workflow.ui_submission import valid_input_version


ROUTE = re.compile(r"/api/projects/([A-Za-z0-9_-]{1,64})/stage2/continuation")
REQUEST_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}")
IDENTITY = ("project_ref", "project_id", "input_version", "brief_sha256")
# The HTTP server has sixteen slots shared with ordinary reads. Only one
# long-running controller is admitted per Wiki, including graceful shutdown.
MAX_ACTIVE_RUNS = 1


class WikiStage2Continuation:
    def __init__(self, host):
        self.host = host
        self.lock = Lock()
        self.active = set()
        self.drivers = host.project_stage2_controllers
        records = [private_output(driver.records) for driver in self.drivers.values()]
        if len(set(records)) != len(records):
            raise ValueError(
                "Wiki Stage2 controllers require distinct record directories"
            )
        self.bindings = {}
        for ref in self.drivers:
            basis, _ = self._current(host.credential, ref)
            self.bindings[ref] = basis

    def _current(self, credential, ref):
        with self.host.projects._lock:
            project = self.host.projects.read(credential, ref)
            stage = self.host.project_stage2.read(credential, ref)
        activation = stage["activation"]
        _check(
            activation is not None
            and activation["stage2_status"] == "ready-for-explicit-stage2-run",
            "stage2-continuation-activation-required",
        )
        basis = {
            **{key: project[key] for key in IDENTITY},
            "activation_sha256": canonical_hash(activation),
        }
        return basis, stage["frontier"]

    def _bound(self, credential, ref):
        self.host.projects.read(credential, ref)
        _check(ref in self.drivers, "stage2-controller-not-connected")
        current, frontier = self._current(credential, ref)
        _check(current == self.bindings[ref], "stage2-continuation-project-stale")
        return current, self.drivers[ref], frontier

    @staticmethod
    def _admission(driver):
        _check(
            callable(getattr(driver.handler, "prepare", None))
            and isinstance(getattr(driver.handler, "identity", None), str)
            and 0 < len(driver.handler.identity) <= 128
            and "native" in driver.spec
            and _admitted(
                getattr(driver.handler, "admission_context", None), driver.spec
            ),
            "stage2-continuation-original-admission-unavailable",
        )

    @staticmethod
    def _public(basis, status, **extra):
        return {
            **{key: basis[key] for key in IDENTITY},
            "status": status,
            "execution_authorized": False,
            **extra,
        }

    @staticmethod
    def _request_path(driver):
        return _guard(driver.records / "wiki-request.json")

    def _request(self, driver, basis):
        path = self._request_path(driver)
        if not path.exists():
            return None
        request = _read(path)
        _check(
            request["basis"] == basis
            and request["controller_sha256"] == canonical_hash(driver._configuration()),
            "stage2-continuation-project-stale",
        )
        return request

    def submit(self, credential, ref, body, check_deadline):
        _check(
            type(body) is dict
            and set(body) == {"key", "input_version", "brief_sha256", "confirmed"}
            and type(body["key"]) is str
            and REQUEST_KEY.fullmatch(body["key"]) is not None
            and valid_input_version(body["input_version"], allow_string=True)
            and _hash(body["brief_sha256"])
            and body["confirmed"] is True,
            "stage2-continuation-intent-required",
            400,
        )
        with self.lock, self.host.projects._lock:
            basis, driver, _ = self._bound(credential, ref)
            _check(
                type(body["input_version"]) is type(basis["input_version"])
                and body["input_version"] == basis["input_version"]
                and body["brief_sha256"] == basis["brief_sha256"],
                "stage2-continuation-project-stale",
            )
            request = self._request(driver, basis)
            if request is None and not any(
                _guard(driver.records / name).exists()
                for name in ("intent.json", "result.json")
            ):
                self._admission(driver)
                _check(
                    len(self.active) < MAX_ACTIVE_RUNS,
                    "stage2-continuation-worker-busy",
                    503,
                )
                check_deadline()
                request = {
                    "basis": basis,
                    "key": body["key"],
                    "controller_sha256": canonical_hash(driver._configuration()),
                }
                try:
                    _write(self._request_path(driver), request)
                except FileExistsError:
                    request = self._request(driver, basis)
                else:
                    self.active.add(ref)
                    return True, self._public(
                        basis, "request-saved", dispatch_observed=False
                    )
            if request is not None:
                _check(
                    request["key"] == body["key"], "stage2-continuation-request-exists"
                )
        return False, self.read(credential, ref, check_deadline)

    def run(self, ref):
        driver = self.drivers[ref]
        status, reason = "execution-unknown", None
        try:
            credential = self.host.credential
            basis, _, _ = self._bound(credential, ref)
            request = self._request(driver, basis)
            self._admission(driver)
            # Never accept the browser's idempotency key as an operator argument.
            controller_key = "wiki-stage2-" + canonical_hash(request)
            result = self.host.continue_stage2(credential, ref, key=controller_key)
            status = result["status"]
            reason = (
                result.get("reason")
                if status == "unavailable-preparation-admission"
                else None
            )
        except SessionApiError as error:
            status, reason = "blocked", error.code
        except Exception:
            logging.exception("Wiki Stage 2 continuation could not be verified")
        finally:
            try:
                _write(
                    driver.records / "wiki-outcome.json",
                    {"status": status, "reason": reason},
                )
            finally:
                with self.lock:
                    self.active.discard(ref)

    def read(self, credential, ref, check_deadline):
        basis, driver, frontier = self._bound(credential, ref)
        with self.lock:
            if ref in self.active:
                return self._public(basis, "running")
            request = self._request(driver, basis)
        selection = self.host.project_stage2_selection
        if selection is not None and ref in selection.bindings:
            try:
                current = selection.read(credential, ref, check_deadline=check_deadline)
            except SessionApiError as error:
                if not error.code.startswith("stage2-selection-"):
                    raise
            else:
                if all(
                    current[key] == basis[key]
                    for key in ("project_ref", "input_version", "brief_sha256")
                ):
                    return self._public(basis, "selection-available")
        result_path = _guard(driver.records / "result.json")
        if result_path.exists():
            try:
                return self._read_result(
                    credential, ref, basis, driver, frontier, result_path
                )
            except (SessionApiError, ValueError, KeyError, TypeError, OSError) as error:
                raise SessionApiError(
                    "stage2-continuation-result-not-current"
                ) from error
        intent_path = _guard(driver.records / "intent.json")
        if request is not None or intent_path.exists():
            outcome = _guard(driver.records / "wiki-outcome.json")
            if outcome.exists():
                state = _read(outcome)
                if state["status"] in {"blocked", "unavailable-preparation-admission"}:
                    return self._public(basis, "blocked", reason=state["reason"])
            return self._public(basis, "execution-unknown")
        self._admission(driver)
        return self._public(basis, "ready")

    def _read_result(self, credential, ref, basis, driver, frontier, result_path):
        # Verify the complete original result on every reopen. The previous
        # read cannot attest to later changes in the workflow or delivery.
        saved = _read(result_path)
        intent = _read(driver.records / "intent.json")
        driver._same(intent, credential, ref, intent["key"])
        head = saved["controller"]["workflow_head_sha256"]
        _check(
            frontier is not None
            and frontier["activation_sha256"] == basis["activation_sha256"]
            and frontier["workflow_head_sha256"] == head,
            "stage2-continuation-result-not-current",
        )
        verified = driver._verify_result(saved, intent)
        original = intent["binding"]
        expected = {
            **original,
            "workflow_head_sha256": head,
            "frontier_sequence": original["frontier_sequence"]
            + (original["workflow_head_sha256"] != head),
        }
        _check(
            canonical_hash(_json(driver.service.binding(ref)))
            == canonical_hash(expected),
            "stage2-continuation-result-not-current",
        )
        _, _, current_frontier = self._bound(credential, ref)
        _check(frontier == current_frontier, "stage2-continuation-result-not-current")
        if verified["delivery"] is not None:
            packet = json.loads(_raw(intent["binding"]["packet_path"]))
            return self._delivery(basis, verified, packet["comparison"])
        return self._public(
            basis,
            "no-candidate",
            workflow_head_sha256=head,
            controller_status=saved["controller"]["status"],
        )

    def _delivery(self, basis, verified, initial_comparison):
        delivery = verified["delivery"]
        manifest = delivery["manifest"]
        cards = derive_decision_cards(delivery["selection"])["cards"]
        comparison = delivery["selection"]["evaluation_packet"]["comparison"]
        return self._public(
            basis,
            "candidate-ready",
            delivery_manifest_sha256=manifest["manifest_sha256"],
            snapshot_sha256=manifest["snapshot_sha256"],
            workflow_head_sha256=manifest["workflow_head_sha256"],
            comparison=comparison,
            comparison_is_input_baseline=comparison == initial_comparison,
            delivery_status=manifest["delivery_status"],
            assessment_status=verified["completion"]["assessment_status"],
            human_selection="pending",
            synthetic_test_only=verified["synthetic_test_only"],
            cards=[
                {
                    key: card[key]
                    for key in (
                        "candidate_id",
                        "candidate_version",
                        "candidate_question",
                        "suggested_approach",
                        "requirements",
                        "limitations",
                    )
                }
                for card in cards
            ],
        )


def install_stage2_continuation(host):
    service = WikiStage2Continuation(host)
    inherited = host.RequestHandlerClass

    class Stage2ContinuationHandler(inherited):
        def do_GET(self):
            match = ROUTE.fullmatch(self.path)
            return self._continuation("GET", match[1]) if match else super().do_GET()

        def do_POST(self):
            match = ROUTE.fullmatch(self.path)
            return self._continuation("POST", match[1]) if match else super().do_POST()

        def _continuation(self, method, ref):
            try:
                token, length = self._headers(method)
                _check(
                    self.headers.get("Sec-Fetch-Site") in (None, "none", "same-origin"),
                    "cross-site-rejected",
                    403,
                )
                _check(host.authenticate(token) is not None, "credential-rejected", 401)
                if method == "GET":
                    _check(not length, "invalid-project-read", 400)
                    result = service.read(token, ref, self._remaining)
                    self._remaining()
                    return self._reply(200, result)
                _check(
                    self.headers.get("Content-Type", "").lower() == "application/json",
                    "json-content-type-required",
                    415,
                )
                _check(
                    0 < length <= 2048, "stage2-continuation-body-bound-exceeded", 413
                )
                raw = self.rfile.read(length)
                _check(len(raw) == length, "partial-body", 400)
                start, result = service.submit(
                    token, ref, _decode(raw.decode("utf-8")), self._remaining
                )
            except SessionApiError as error:
                return self._reply(error.status, {"error": error.code})
            except (TimeoutError, OSError):
                self.close_connection = True
                return
            except (ValueError, TypeError, KeyError):
                return self._reply(
                    409, {"error": "stage2-continuation-verification-required"}
                )
            if not start:
                return self._reply(200, result)
            try:
                self._reply(202, result)
                self.wfile.flush()
            finally:
                # The retained request owns this handler until the original run returns.
                # Socket deadlines and lost responses do not authorize another attempt.
                service.run(ref)

    host.RequestHandlerClass = Stage2ContinuationHandler
