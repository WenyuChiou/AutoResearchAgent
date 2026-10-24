"""Explicit project search seals, admitted bootstrap and durable query actions.

Source acquisition and model execution need their own permits. Creating this
service, loading history or reopening SQLite never initializes/probes a runtime.
"""

from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import threading
import time

from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.validation import validate_run
from stage1_retrieval.runner import execute as execute_backend
from .planned_queries import PlannedQueryService
from .planned_query_contract import HASH, KEY, require, tree_sha
from .project_intake_contract import BOUND_FIELDS, _fields, _text
from .project_query_permit import (
    check_configuration,
    derived_registration,
    inspect_seal as inspect_query_seal,
    proposal,
    save_seal,
)
from .project_stage1 import ProjectStage1Service, _basis
from .query_execution_source import check_execution_source
from .project_query_history import admitted_query, bound_run, reserved_intents
from .project_resource_budget import reserve_resource, resource_view
from .project_query_versions import archived_versions, current_budget
from . import project_query_run as run_adapter

FIELDS = BOUND_FIELDS | {"offer_ref", "offer_sha256", "confirmed"}


class ProjectStage1QueryService:
    def __init__(
        self,
        stage1,
        *,
        runtime_pin,
        execution_source_root,
        execution_source_sha256,
        verify_source,
        admit,
        caps,
        backends,
        run_grants=None,
    ):
        require(isinstance(stage1, ProjectStage1Service), "project-stage1-required")
        require(
            callable(verify_source) and callable(admit), "project-query-gates-required"
        )
        require(
            isinstance(execution_source_sha256, str)
            and HASH.fullmatch(execution_source_sha256),
            "project-query-source-pin-required",
        )
        root = Path(execution_source_root)
        require(
            root.is_absolute() and root.is_dir(), "project-query-source-root-required"
        )
        self.stage1, self.intake = stage1, stage1.intake
        self.run_grants = run_adapter.configured(self.intake, run_grants)
        self.config = check_configuration(
            runtime_pin,
            root.resolve().as_posix(),
            execution_source_sha256,
            caps,
            backends,
        )
        self.verify_source, self.admit = verify_source, admit
        self.services, self.workers, self.closing = {}, {}, False
        require(
            getattr(stage1, "query_service", None) is None
            and self.intake._query_service is None,
            "project-query-service-already-attached",
        )
        stage1.query_service = self
        self.intake._query_service = self

    def _state(self, credential, ref):
        principal = self.intake._principal(credential)
        return principal, self.intake._load(principal, ref)

    def _inspect_seal(self, intake, ref, authorization, config, *, ready=True):
        require(
            intake is self.intake and config is self.config,
            "query-run-composition-differs",
        )
        return inspect_query_seal(
            intake, ref, authorization, config, ready=ready, run_grants=self.run_grants
        )

    def _request(self, body, *, authorization=False, derived=False):
        _fields(body, FIELDS | ({"user_input"} if authorization else set()))
        require(
            (body["confirmed"] is False if derived else body["confirmed"] is True)
            and isinstance(body["key"], str)
            and KEY.fullmatch(body["key"])
            and type(body["revision"]) is int
            and body["revision"] >= 0,
            "project-query-explicit-action-required",
            400,
        )
        if authorization:
            _text(body["user_input"], 8192 if derived else 4096)

    def read(self, credential, ref):
        with self.intake._lock:
            principal, state = self._state(credential, ref)
            authorization = state.get("stage1_query_authorization")
            result = dict(
                connected=True,
                execution_authorized=False,
                authorization_offer=None,
                bootstrap_offer=None,
                query_offer=None,
                owner_offer=None,
                status="permission-required",
                model_execution=False,
                source_acquisition=False,
                automatic_retry=False,
                budget=deepcopy(state.get("stage1_query_budget")),
                lifetime_budget=deepcopy(state.get("stage1_query_budget")),
                archived_versions=[],
                jobs=[
                    {
                        k: deepcopy(job[k])
                        for k in (
                            "key",
                            "status",
                            "request_sha256",
                            "permit_sha256",
                            "receipt",
                            "error",
                            "automatic_retry",
                        )
                        if k in job
                    }
                    for job in state.get("stage1_query_jobs", {}).values()
                ],
            )
            try:
                result["archived_versions"] = archived_versions(self.intake, state)
                result["budget"] = current_budget(self.intake, state, principal)
                # Archive/resource integrity is checked before identifying the
                # fresh brief prerequisite. Generic exceptions remain failures.
                current = self.intake.read(credential, ref)
                if (
                    authorization is None
                    and not result["jobs"]
                    and not state.get("stage1_active")
                    and current.get("plan") is None
                    and current.get("intake_report", {}).get(
                        "necessary_clarification_complete"
                    )
                    is False
                ):
                    result.update(
                        status="intake-prerequisite-required",
                        refusal="project-query-intake-not-ready",
                    )
                    return result
                if authorization is None:
                    _, _, offer = proposal(self.intake, ref, principal, self.config)
                    result["authorization_offer"] = offer
                    return result
                _, permit = self._inspect_seal(
                    self.intake, ref, authorization, self.config, ready=False
                )
                result.update(
                    execution_authorized=time.time()
                    + 30
                    + self.config["pin"]["timeout_seconds"]
                    < permit["expires_at_unix"],
                    expires_at_unix=permit["expires_at_unix"],
                    permit_sha256=authorization["sha256"],
                    limits=deepcopy(permit["limits"]),
                )
                reserved_intents(
                    self.intake,
                    state,
                    principal,
                    permit["limits"],
                    self.config["pin"]["timeout_seconds"],
                )
                jobs = state.get("stage1_query_jobs", {})
                if not jobs:
                    self._inspect_seal(self.intake, ref, authorization, self.config)
                    digest = sha(
                        canonical(
                            dict(
                                permit_sha256=authorization["sha256"],
                                project_ref=ref,
                                principal=principal,
                            )
                        )
                    )
                    result.update(
                        status="ready-for-explicit-runtime-initialization",
                        bootstrap_offer=dict(
                            offer_ref="project-bootstrap-" + digest[:32],
                            offer_sha256=digest,
                        ),
                    )
                else:
                    job = next(iter(jobs.values()))
                    result["status"] = job["status"]
                    worker = self.workers.get(ref)
                    if job["status"] in {"dispatch-unobserved", "dispatching"} and (
                        worker is None or not worker.is_alive()
                    ):
                        result["status"] = "execution-unknown"
                        result["jobs"][0].update(
                            saved_status=job["status"], status="execution-unknown"
                        )
                    if job["status"] == "completed":
                        service = self.services.get(ref)
                        if service is None:
                            result["status"] = "owner-reopen-required"
                            digest = sha(
                                canonical(
                                    dict(
                                        project_ref=ref,
                                        principal=principal,
                                        receipt=job["receipt"],
                                    )
                                )
                            )
                            result["owner_offer"] = dict(
                                offer_ref="project-query-owner-" + digest[:32],
                                offer_sha256=digest,
                            )
                        else:
                            result["query_history"] = service.view(credential, ref)
                            try:
                                result["query_offer"] = service.offer(credential, ref)
                            except Exception as error:
                                result["query_offer_refusal"] = getattr(
                                    error, "code", "query-offer-unavailable"
                                )
            except Exception as error:
                result.update(
                    status="unavailable-or-stale",
                    refusal=getattr(error, "code", "query-binding-unavailable"),
                )
            return result

    def authorize(
        self, credential, ref, body, *, check_deadline=None, run_authorization=None
    ):
        self._request(body, authorization=True, derived=run_authorization is not None)
        guard = run_adapter.request(
            self, credential, ref, body, run_authorization, "query-authorize"
        )
        if guard is not None:
            check_deadline = guard.deadline_check(check_deadline)
        principal = self.intake._principal(credential)

        def work(state, request_hash, actor):
            require(not self.closing, "project-query-service-closing")
            require(
                not state.get("stage1_query_authorization"),
                "project-query-seal-replacement-refused",
            )
            archived_versions(self.intake, state)
            _, document, offer = proposal(self.intake, ref, actor, self.config)
            require(
                body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "project-query-authorization-offer-differs",
            )
            authorization = save_seal(
                self.intake,
                ref,
                actor,
                self.config,
                request_hash,
                document,
                body["user_input"],
                run_guard=guard,
            )
            state["stage1_query_authorization"] = authorization
            state.setdefault(
                "stage1_query_budget", dict(probes=0, attempts=0, seconds=0)
            )
            return dict(
                permit_sha256=authorization["sha256"],
                scope=["initialize-query-runtime", "execute-planned-query"],
                query_status="permission-saved-not-executed",
                model_execution=False,
                source_acquisition=False,
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-query-authorize",
            deepcopy(body) if guard is None else deepcopy(guard.request),
            work,
            check_deadline=check_deadline,
        )

    def _reserve(
        self,
        state,
        principal,
        key,
        request_hash,
        *,
        probe=False,
        expansion=False,
        run_guard=None,
    ):
        authorization = state.get("stage1_query_authorization")
        require(authorization is not None, "project-query-permission-required")
        _, permit = self._inspect_seal(
            self.intake,
            state["project_ref"],
            authorization,
            self.config,
            ready=not expansion,
        )
        run_adapter.check_mode(run_guard, permit)
        budget = current_budget(self.intake, state, principal)
        limits = permit["limits"]
        reserved_intents(
            self.intake,
            state,
            permit["principals"][0],
            limits,
            self.config["pin"]["timeout_seconds"],
        )
        seconds = 30 if probe else self.config["pin"]["timeout_seconds"] + 30
        require(
            budget["seconds"] + seconds <= limits["max_reserved_seconds"]
            and (
                budget["probes"] < 1
                if probe
                else budget["attempts"] < limits["max_attempts"]
            ),
            "project-query-total-budget-exhausted",
            429,
        )
        reserve_resource(
            self.intake,
            state,
            principal,
            lane="query",
            kind="stage1-query-bootstrap"
            if probe
            else "stage1-expansion-execute"
            if expansion
            else "stage1-query-execute",
            key=key,
            request_sha256=request_hash,
            seconds=seconds,
            calls=0 if probe else 1,
        )
        state["stage1_query_budget"]["seconds"] += seconds
        state["stage1_query_budget"]["probes" if probe else "attempts"] += 1
        return permit

    def bootstrap(
        self, credential, ref, body, *, check_deadline=None, run_authorization=None
    ):
        self._request(body, derived=run_authorization is not None)
        guard = run_adapter.request(
            self, credential, ref, body, run_authorization, "query-bootstrap"
        )
        if guard is not None:
            check_deadline = guard.deadline_check(check_deadline)
        principal = self.intake._principal(credential)

        def reserve(state, request_hash, actor):
            require(
                not self.closing and not state.get("stage1_query_jobs"),
                "project-query-bootstrap-requires-reconciliation",
            )
            offer = self.read(credential, ref)["bootstrap_offer"]
            require(
                offer is not None
                and body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "project-query-bootstrap-offer-differs",
            )
            permit = self._reserve(
                state, actor, body["key"], request_hash, probe=True, run_guard=guard
            )
            state["stage1_query_jobs"] = {
                request_hash: dict(
                    status="dispatch-unobserved",
                    key=body["key"],
                    principal=actor,
                    request_sha256=request_hash,
                    permit_sha256=state["stage1_query_authorization"]["sha256"],
                    deadline_unix=min(
                        permit["expires_at_unix"],
                        time.time() + permit["limits"]["bootstrap_probe_seconds"],
                    ),
                    automatic_retry=False,
                    **(
                        {}
                        if guard is None
                        else dict(run_request=deepcopy(guard.request))
                    ),
                )
            }

        def work(state, request_hash, _):
            worker = threading.Thread(
                target=self._bootstrap_worker,
                args=(credential, ref, request_hash),
                daemon=True,
            )
            self.workers[ref] = worker
            worker.start()
            return dict(
                query_status="bootstrap-queued",
                stage1_complete=False,
                model_execution=False,
                source_acquisition=False,
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-query-bootstrap",
            deepcopy(body) if guard is None else deepcopy(guard.request),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )

    def _save_job(self, principal, ref, key, change, *, run=None):
        with self.intake._lock:
            self.intake.db.execute("BEGIN IMMEDIATE")
            try:
                state = self.intake._load(principal, ref)
                deadline = None
                if run is not None:
                    job = state["stage1_query_jobs"][key]
                    authorization = state["stage1_query_authorization"]
                    require(
                        not self.closing
                        and change.get("status") == "completed"
                        and job["status"] == "dispatching"
                        and job["permit_sha256"] == authorization["sha256"],
                        "project-query-bootstrap-commit-authority-differs",
                    )
                    _, permit = self._inspect_seal(
                        self.intake, ref, authorization, self.config
                    )
                    reserved_intents(
                        self.intake,
                        state,
                        principal,
                        permit["limits"],
                        self.config["pin"]["timeout_seconds"],
                    )
                    run_adapter.check_job(self, principal, ref, job, permit)
                    deadline = job["deadline_unix"]
                    require(time.time() < deadline, "project-query-bootstrap-expired")
                state["stage1_query_jobs"][key].update(deepcopy(change))
                if run is not None:
                    state.setdefault("stage1_runs", {})[run["run_ref"]] = run
                    state["stage1_active"] = run["run_ref"]
                state["revision"] += 1
                self.intake._save(
                    state,
                    "stage1-query-bootstrap-observation",
                    state["stage1_query_jobs"][key],
                )
                if deadline is not None:
                    require(
                        not self.closing and time.time() < deadline,
                        "project-query-bootstrap-expired",
                    )
                self.intake.db.commit()
            except BaseException:
                self.intake.db.rollback()
                raise

    def _guard(self, credential, ref, authorization, phase, *, expansion=None):
        with self.intake._lock:
            principal, state = self._state(credential, ref)
            require(
                not self.closing
                and state.get("stage1_query_authorization") == authorization,
                "project-query-authority-changed",
            )
            _, permit = self._inspect_seal(
                self.intake, ref, authorization, self.config, ready=expansion is None
            )
            reserved_intents(
                self.intake,
                state,
                principal,
                permit["limits"],
                self.config["pin"]["timeout_seconds"],
            )
            require(
                principal in permit["principals"], "project-query-principal-denied", 403
            )
            resource_view(self.intake, state, principal)
        source_item = {
            k: self.config[k]
            for k in ("execution_source_root", "execution_source_sha256")
        }
        check_execution_source(
            self.verify_source, ref, source_item, phase, execute_backend
        )

        # Finish this verifier with callback-free byte/binding checks too.
        with self.intake._lock:
            _, current = self._state(credential, ref)
            require(
                current.get("stage1_query_authorization") == authorization,
                "project-query-authority-changed-after-source-check",
            )
            self._inspect_seal(
                self.intake, ref, authorization, self.config, ready=expansion is None
            )
            reserved_intents(
                self.intake,
                current,
                principal,
                permit["limits"],
                self.config["pin"]["timeout_seconds"],
            )
            resource_view(self.intake, current, principal)
        require(
            self.admit(
                dict(
                    project_ref=ref,
                    principal=principal,
                    phase=deepcopy(phase),
                    permit_sha256=authorization["sha256"],
                    expansion=deepcopy(expansion),
                )
            )
            is True,
            "project-query-admission-refused",
            403,
        )
        # A trusted admission callback can still mutate settings/config; recheck.
        with self.intake._lock:
            _, current = self._state(credential, ref)
            require(
                not self.closing
                and current.get("stage1_query_authorization") == authorization,
                "project-query-authority-changed-during-admission",
            )
            self._inspect_seal(
                self.intake, ref, authorization, self.config, ready=expansion is None
            )
        check_execution_source(
            self.verify_source, ref, source_item, phase, execute_backend
        )

        with self.intake._lock:
            _, current = self._state(credential, ref)
            require(
                not self.closing
                and current.get("stage1_query_authorization") == authorization,
                "project-query-authority-changed-after-final-source-check",
            )
            self._inspect_seal(
                self.intake, ref, authorization, self.config, ready=expansion is None
            )
            reserved_intents(
                self.intake,
                current,
                principal,
                permit["limits"],
                self.config["pin"]["timeout_seconds"],
            )
            resource_view(self.intake, current, principal)

    def _service(self, credential, ref, authorization, registration):
        def expansion_authority(event):
            from .project_expansions import validate_expansion

            with self.intake._lock:
                require(
                    event["project_ref"] == ref, "project-expansion-project-differs"
                )
                validate_expansion(
                    self,
                    ref,
                    event["principal"],
                    event["offer"],
                    event["phase"],
                    client_key=event["client_key"],
                )
            return True

        def final_resources(event):
            with self.intake._lock:
                principal, state = self._state(credential, ref)
                require(
                    not self.closing
                    and state.get("stage1_query_authorization") == authorization
                    and event["project_ref"] == ref
                    and event["principal"] == principal,
                    "project-query-authority-changed-after-final-source-check",
                )
                is_expansion = "expansion_grant_sha256" in event["offer"]
                if is_expansion:
                    expansion_authority(event)
                _, permit = self._inspect_seal(
                    self.intake, ref, authorization, self.config, ready=not is_expansion
                )
                intents = reserved_intents(
                    self.intake,
                    state,
                    principal,
                    permit["limits"],
                    self.config["pin"]["timeout_seconds"],
                )
                admitted_query(intents, event, ref, principal)
                resource_view(self.intake, state, principal)
                run_adapter.check_execution(self, credential, ref, authorization, event)
            return True

        def admission(event):
            expansion = event if "expansion_grant_sha256" in event["offer"] else None
            if expansion is not None:
                expansion_authority(event)
            self._guard(
                credential, ref, authorization, event["phase"], expansion=expansion
            )
            if expansion is not None:
                expansion_authority(event)
            with self.intake._lock:
                _, state = self._state(credential, ref)
                permit = authorization["permit"]
                intents = reserved_intents(
                    self.intake,
                    state,
                    event["principal"],
                    permit["limits"],
                    self.config["pin"]["timeout_seconds"],
                )
                admitted_query(intents, event, ref, event["principal"])
                resource_view(self.intake, state, event["principal"])
            return True

        return PlannedQueryService(
            registration["control_store_path"],
            registrations={ref: registration},
            authenticate=self.intake.authenticate,
            admit=admission,
            verify_source=self.verify_source,
            check_resources=final_resources,
            check_expansion=expansion_authority,
            check_result=lambda event: run_adapter.check_execution(
                self, credential, ref, authorization, event
            ),
        )

    def _bootstrap_worker(self, credential, ref, request_hash):
        entered, service = False, None
        principal = self.intake._principal(credential)
        try:
            with self.intake._lock:
                _, state = self._state(credential, ref)
                job = deepcopy(state["stage1_query_jobs"][request_hash])
                authorization = deepcopy(state["stage1_query_authorization"])
                action = self.intake.action(credential, job["key"], project_ref=ref)
                require(
                    action["status"] == "saved"
                    and action["request_sha256"] == request_hash,
                    "project-query-bootstrap-dispatch-unobserved",
                )
                require(
                    time.time() < job["deadline_unix"],
                    "project-query-bootstrap-expired",
                )
                binding, permit = self._inspect_seal(
                    self.intake, ref, authorization, self.config
                )
                run_adapter.check_job(self, principal, ref, job, permit)
            self._guard(credential, ref, authorization, "before-bootstrap-probe")
            self._save_job(principal, ref, request_hash, dict(status="dispatching"))
            # Persist dispatching before any Core.create/probe. A crash is unknown.
            entered = True
            parent, working = (
                Path(permit["binding"][k])
                for k in ("parent_ledger_root", "ledger_root")
            )
            require(
                not parent.exists() and not working.exists(),
                "project-query-bootstrap-output-exists",
            )
            require(
                time.time() < job["deadline_unix"], "project-query-bootstrap-expired"
            )
            seed = CoverageLedger.create(
                parent,
                run_id="project-search-" + request_hash[:24],
                objective=self.intake.brief_binding(ref, require_confirmed=True)[
                    "brief"
                ]["original_description"],
                research_hub_pin=self.config["pin"],
            )
            self._guard(credential, ref, authorization, "after-bootstrap-probe")
            seed.bind_plan(
                binding["plan_root"],
                backends=self.config["backends"],
                limit=self.config["caps"]["max_results"],
                citation_backends=["semantic-scholar"],
            )
            seed.open_round()
            report = validate_run(parent)
            require(
                report["valid"] and time.time() < job["deadline_unix"],
                "project-query-bootstrap-replay-or-deadline",
            )
            parent_hash = tree_sha(parent)
            shutil.copytree(parent, working)
            require(
                tree_sha(working) == parent_hash,
                "project-query-bootstrap-clone-differs",
            )
            receipt = dict(
                kind="ProjectStage1QueryBootstrapReceipt",
                schema_version="1.0.0",
                project_ref=ref,
                request_sha256=request_hash,
                permit_sha256=authorization["sha256"],
                ledger_manifest_sha256=sha((parent / "run_manifest.json").read_bytes()),
                parent_ledger_sha256=parent_hash,
                state_sha256=report["state_sha256"],
                probe_observation="Core.create-returned-no-raw-probe-capture",
                actual_model_calls=0,
                stage1_complete=False,
            )
            registration = derived_registration(
                self.intake,
                ref,
                authorization,
                receipt,
                self.config,
                run_grants=self.run_grants,
            )
            service = self._service(credential, ref, authorization, registration)
            self._guard(credential, ref, authorization, "before-bootstrap-commit")
            run_ref = "stage1-live-" + request_hash[:24]
            run = dict(
                run_ref=run_ref,
                path=working.name,
                binding=_basis(binding),
                manifest_sha256=receipt["ledger_manifest_sha256"],
                query_owned=True,
            )
            with self.intake._lock:
                self._save_job(
                    principal,
                    ref,
                    request_hash,
                    dict(
                        status="completed", receipt=receipt, registration=registration
                    ),
                    run=run,
                )
                self.services[ref] = service
        except BaseException as error:
            if service is not None:
                service.close()
            self._save_job(
                principal,
                ref,
                request_hash,
                dict(
                    status="execution-unknown" if entered else "refused-known-unsent",
                    error=dict(
                        code=getattr(error, "code", "bootstrap-failed"),
                        type=type(error).__name__,
                    ),
                ),
            )

    def reopen(self, credential, ref):
        """Explicit trusted owner restoration; never called by GET or replay."""
        with self.intake._lock:
            _, state = self._state(credential, ref)
            require(ref not in self.services, "project-query-owner-already-open")
            jobs = list(state.get("stage1_query_jobs", {}).values())
            require(
                len(jobs) == 1 and jobs[0]["status"] == "completed",
                "project-query-bootstrap-not-completed",
            )
            authorization = state["stage1_query_authorization"]
            self._inspect_seal(
                self.intake, ref, authorization, self.config, ready=False
            )
            events = self.intake.db.execute(
                "SELECT payload FROM intake_events WHERE project=? AND kind=?",
                (ref, "stage1-query-bootstrap-observation"),
            ).fetchall()
            require(
                any(json.loads(row[0]) == jobs[0] for row in events),
                "project-query-bootstrap-saved-observation-differs",
            )
            expected = derived_registration(
                self.intake,
                ref,
                authorization,
                jobs[0]["receipt"],
                self.config,
                write=False,
                run_grants=self.run_grants,
            )
            require(
                jobs[0]["registration"] == expected,
                "project-query-bootstrap-registration-differs",
            )
            self.services[ref] = self._service(
                credential, ref, authorization, jobs[0]["registration"]
            )

    def restore_owner(self, credential, ref, body, *, check_deadline=None):
        self._request(body)
        principal = self.intake._principal(credential)

        def work(_, __, ___):
            offer = self.read(credential, ref)["owner_offer"]
            require(
                offer is not None
                and body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "project-query-owner-offer-differs",
            )
            self.reopen(credential, ref)
            return dict(
                query_status="owner-restored-history-only", actual_search_attempts=0
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-query-restore-owner",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def execute(
        self, credential, ref, body, *, check_deadline=None, run_authorization=None
    ):
        self._request(body, derived=run_authorization is not None)
        guard = run_adapter.request(
            self, credential, ref, body, run_authorization, "query-execute"
        )
        if guard is not None:
            check_deadline = guard.deadline_check(check_deadline)
        principal = self.intake._principal(credential)

        def reserve(state, request_hash, actor):
            self._reserve(state, actor, body["key"], request_hash, run_guard=guard)
            require(ref in self.services, "project-query-owner-reopen-required")
            offer = self.services[ref].offer(credential, ref)
            require(
                body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "project-query-offer-differs",
            )

        def work(state, request_hash, _):
            service = self.services[ref]
            offer = service.offer(credential, ref)
            require(
                body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "project-query-offer-differs",
            )
            limits = state["stage1_query_authorization"]["permit"]
            deadline = time.monotonic() + min(
                limits["expires_at_unix"] - time.time(),
                self.config["pin"]["timeout_seconds"] + 30,
            )
            inner = dict(
                key="project-" + request_hash,
                revision=offer["revision"],
                **{k: offer["document"][k] for k in ("index_sha256", "input_version")},
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True if guard is None else False,
                **(
                    {}
                    if guard is None
                    else dict(run_authority=deepcopy(guard.request["run_authority"]))
                ),
            )
            observed = service.execute(
                credential, ref, inner, deadline=deadline, run_authorization=guard
            )
            return dict(
                query_status=observed["status"],
                query_action_key=inner["key"],
                query_request_sha256=observed["request_sha256"],
                stage1_complete=False,
            )

        return self.intake._perform(
            principal,
            ref,
            "stage1-query-execute",
            deepcopy(body) if guard is None else deepcopy(guard.request),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )

    def mutate(self, credential, ref, state, run, ledger, request_hash, kind, producer):
        require(
            run.get("query_owned") is True and ref in self.services,
            "project-query-owner-required",
        )
        service = self.services[ref]
        registration = bound_run(
            self.intake, state, _basis(self.intake.binding(ref)), run
        )
        require(
            ledger.root.as_posix() == registration["ledger_root"],
            "project-query-write-root-differs",
        )
        frontier = service.inspect_saved(credential, ref)
        require(
            frontier["state_sha256"] == ledger.state_hash(),
            "project-query-write-state-differs",
        )
        row = service.mutate_saved(
            credential,
            ref,
            "project-" + request_hash,
            request_hash,
            frontier["tree_sha256"],
            kind,
            lambda owned: producer(owned),
        )
        require(
            row["status"] == "completed" and row.get("outcome") == "observed",
            "project-query-write-outcome-unknown",
        )
        return deepcopy(row["result"])

    def saved_frontier(self, ref):
        """Trusted ledger reader guard, under intake -> query lock order.

        This is not a browser endpoint or a search admission. It protects saved
        producers that already checked project ownership/current input binding.
        """
        require(
            not self.closing and getattr(self.stage1, "query_service", None) is self,
            "project-query-saved-owner-unavailable",
        )
        service = self.services.get(ref)
        require(service is not None, "project-query-owner-reopen-required")
        with service._lock:
            project = service._projects[ref]
            saved = service.store.snapshot(project["pid"])
            _, _, frontier = service._saved_frontier(ref, project, saved)
            return deepcopy(frontier)

    def produce_saved(self, ref, state, run, ledger, producer):
        """Build a package while holding the saved ledger frontier read guard.

        Its outer intake intent owns package output; no ledger event, query
        reservation, native dispatch or additional inner mutation is created.
        """
        registration = bound_run(
            self.intake, state, _basis(self.intake.binding(ref)), run
        )
        require(
            ledger.root.as_posix() == registration["ledger_root"],
            "project-query-package-root-differs",
        )
        service = self.services.get(ref)
        require(service is not None, "project-query-owner-reopen-required")
        with service._lock:
            before = self.saved_frontier(ref)
            result = producer(ledger)
            require(
                self.saved_frontier(ref) == before,
                "project-query-package-frontier-changed",
            )
            return result

    @contextmanager
    def saved_records_guard(self, run, ledger, report):
        """Hold an existing owner for local records; never reopen or dispatch.

        The returned check must run inside the intake action transaction before
        it commits. A check only on context exit is too late to revoke a saved
        receipt. Intake always precedes the query lock, including shutdown.
        """
        with self.intake._lock:
            require(run.get("query_owned") is True, "project-query-owner-required")
            require(not self.closing, "project-query-records-owner-unavailable")
            root = ledger.root.as_posix()
            expected_state = report.get("state_sha256")
            require(report.get("valid") is True, "project-query-records-state-differs")

            def resolve():
                matches = [
                    (ref, service)
                    for ref, service in self.services.items()
                    if (service._projects.get(ref) or {})
                    .get("item", {})
                    .get("ledger_root")
                    == root
                ]
                require(len(matches) == 1, "project-query-records-owner-ambiguous")
                return matches[0]

            ref, service = resolve()
            original_run = deepcopy(run)

            def current():
                require(
                    not self.closing
                    and not service._closing
                    and not service._closed
                    and self.services.get(ref) is service
                    and getattr(self.stage1, "query_service", None) is self,
                    "project-query-records-owner-unavailable",
                )
                require(
                    resolve() == (ref, service),
                    "project-query-records-owner-unavailable",
                )
                row = self.intake.db.execute(
                    "SELECT principal FROM intake_projects WHERE ref=?", (ref,)
                ).fetchone()
                require(row is not None, "project-query-records-project-unavailable")
                state = self.intake._load(row[0], ref)
                binding = self.intake.binding(ref)
                active = state.get("stage1_active")
                require(
                    active == original_run["run_ref"]
                    and state.get("stage1_runs", {}).get(active) == original_run,
                    "project-query-records-run-stale",
                )
                registration = bound_run(
                    self.intake, state, _basis(binding), original_run
                )
                job = next(iter(state["stage1_query_jobs"].values()))
                require(
                    derived_registration(
                        self.intake,
                        ref,
                        state["stage1_query_authorization"],
                        job["receipt"],
                        self.config,
                        write=False,
                        run_grants=self.run_grants,
                    )
                    == registration,
                    "project-query-records-registration-differs",
                )
                project = service._projects.get(ref)
                require(
                    project is not None
                    and project["item"] == registration
                    and registration["project_id"] == binding["project_id"]
                    and registration["principals"] == [row[0]]
                    and registration["ledger_root"] == root,
                    "project-query-records-binding-differs",
                )
                saved = service.store.snapshot(project["pid"])
                _, _, frontier = service._saved_frontier(ref, project, saved)
                require(
                    frontier["state_sha256"] == expected_state
                    and sha((ledger.root / "run_manifest.json").read_bytes())
                    == original_run["manifest_sha256"],
                    "project-query-records-state-differs",
                )
                return frontier

            with service._lock:
                before = current()

                def check_current():
                    require(
                        current() == before,
                        "project-query-records-frontier-changed",
                    )

                yield check_current
                check_current()

    def create_records_service(self, delivery, *, materials_root):
        """Trusted bootstrap only; configured does not mean sources were read."""
        from .project_stage1_delivery import ProjectStage1DeliveryService
        from .project_stage1_records import ProjectStage1RecordsService

        require(
            isinstance(delivery, ProjectStage1DeliveryService)
            and delivery.stage1 is self.stage1
            and delivery.intake is self.intake,
            "project-query-records-delivery-differs",
        )
        root = Path(materials_root).resolve()
        source = Path(self.config["execution_source_root"]).resolve()
        require(
            not root.is_relative_to(self.intake.root)
            and not self.intake.root.is_relative_to(root)
            and not root.is_relative_to(source)
            and not source.is_relative_to(root),
            "project-query-records-storage-overlap",
        )
        return ProjectStage1RecordsService(
            delivery,
            materials_root=materials_root,
            mutation_guard=self.saved_records_guard,
        )

    def close(self):
        # Serialize the stop transition with saved producers' final check and
        # commit. Release intake before joining workers to avoid a lock cycle.
        with self.intake._lock:
            self.closing = True
        for worker in self.workers.values():
            worker.join(2)
        require(
            not any(w.is_alive() for w in self.workers.values()),
            "project-query-bootstrap-cleanup-unobserved",
        )
        for service in self.services.values():
            service.close()
        self.services.clear()
        if self.intake._query_service is self:
            self.intake._query_service = None
