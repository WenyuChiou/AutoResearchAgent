"""Durable project source grants and transport jobs, without a default reader.

This broker never imports a source into Core, creates claims, runs a model, or
weakens the query owner's saved frontier. The trusted server may explicitly
dispatch a queued job through a typed runner. Runner bindings and observations
are not native authentication or hard process-containment evidence. GET never
claims an owner, creates a worker, adopts files, or resumes a queued job.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid

from stage1_deliverable.common import (
    canonical,
    identifier,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from stage1_ledger.journal import LedgerError as CoreLedgerError
from .acquired_source_parser import _acquisition
from .bounded_public_source import request_binding
from .planned_query_contract import tree_sha
from .project_intake import ProjectIntakeService
from .project_resource_budget import reserve_resource, resource_view
from .project_source_permit import configuration, proposal, _selected
from .project_stage1 import ProjectStage1Service, _basis
from .session_api import SessionApiError, _check, _hash

STORE = "stage1_source_operations"
PROOF = "stage1-source-service-proof"
BOUND = {"key", "revision", "input_version", "brief_sha256", "confirmed"}
AUTHORIZE_FIELDS = BOUND | {"work_ref", "offer_ref", "offer_sha256"}
EXECUTE_FIELDS = BOUND | {"grant_ref", "grant_sha256"}
MAX_ITEMS = 128
MAX_JSON = 1024 * 1024
TERMINAL = {"source-observation-saved", "failed-observed", "refused-known-unsent"}
UNSETTLED = {"intent-recorded", "queued", "dispatching", "execution-unknown"}


class SourceJobRunner(ABC):
    """Server-only transport seam; a subclass or its hash is not attestation.

    A production runner must enforce an outer wall deadline and contain/reap
    its children. This service's before/after checks cannot stop a hung runner.
    Return only the original acquisition receipt's relative path and SHA-256;
    the broker verifies physical bytes independently. No SDK parse or Core
    mutation is allowed in this transport seam.
    """

    @property
    @abstractmethod
    def binding_sha256(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def resolver_sha256(self):
        raise NotImplementedError

    @abstractmethod
    def run(self, request, output_dir, *, check_current):
        raise NotImplementedError


def _shape(body, fields):
    _check(
        type(body) is dict and set(body) == fields, "source-action-fields-invalid", 400
    )
    _check(len(canonical(body)) <= 8192, "source-action-too-large", 400)
    identifier(body["key"])
    _check(
        type(body["revision"]) is int
        and body["revision"] >= 0
        and type(body["input_version"]) is int
        and body["input_version"] > 0
        and _hash(body["brief_sha256"])
        and body["confirmed"] is True,
        "source-action-binding-invalid",
        400,
    )
    for field in fields - BOUND:
        if field.endswith("sha256"):
            _check(_hash(body[field]), "source-action-hash-invalid", 400)
        else:
            _check(
                type(body[field]) is str and 0 < len(body[field]) <= 128,
                "source-action-reference-invalid",
                400,
            )


def _request_hash(kind, body):
    return sha(
        canonical(
            dict(kind=kind, body={k: v for k, v in body.items() if k != "revision"})
        )
    )


def _scope(document):
    binding = deepcopy(document["binding"])
    for field in ("ledger_state_sha256", "journal_sha256", "reservation_state_sha256"):
        binding.pop(field)
    return dict(
        project_ref=document["project_ref"],
        principal=document["principal"],
        binding=binding,
        selected=deepcopy(document["selected"]),
        runtime_sha256=document["runtime_sha256"],
        execution_source_sha256=document["execution_source_sha256"],
        server_configuration_sha256=document["server_configuration_sha256"],
        url_policy=deepcopy(document["url_policy"]),
        **(
            {"pipeline_sha256": document["pipeline_sha256"]}
            if "pipeline_sha256" in document
            else {}
        ),
    )


@contextmanager
def _core_boundary():
    """Only expected Core readiness failures become a typed UI refusal."""
    try:
        yield
    except CoreLedgerError as error:
        raise SessionApiError("source-core-not-ready") from error


class ProjectStage1SourceService:
    """One shared intake database; immutable grants and no-resend source jobs."""

    def __init__(
        self,
        intake,
        stage1,
        *,
        config,
        materials_root,
        runner=None,
        verify_configuration=None,
        clock=time.time,
        pipeline=None,
    ):
        _check(
            isinstance(intake, ProjectIntakeService)
            and isinstance(stage1, ProjectStage1Service)
            and stage1.intake is intake,
            "source-project-service-required",
        )
        _check(
            runner is None or isinstance(runner, SourceJobRunner),
            "source-runner-type-required",
        )
        _check(
            verify_configuration is None or callable(verify_configuration),
            "source-configuration-verifier-invalid",
        )
        _check(callable(clock), "source-clock-required")
        self.intake, self.stage1 = intake, stage1
        self.config = configuration(config)
        self.config_sha256 = sha(canonical(self.config))
        self.materials_root = private_output(materials_root).resolve()
        _check(self.materials_root.is_dir(), "source-materials-root-required")
        _check(
            not self.materials_root.is_relative_to(intake.root)
            and not intake.root.is_relative_to(self.materials_root),
            "source-storage-overlap",
        )
        self.runner, self.verify_configuration, self.clock = (
            runner,
            verify_configuration,
            clock,
        )
        self.pipeline = self._bound_pipeline = pipeline
        _check(
            (pipeline is None) == ("pipeline_sha256" not in self.config),
            "source-pipeline-config-required",
        )
        if pipeline is not None:
            from .project_source_saved_pipeline import SourceSavedPipeline

            _check(
                type(pipeline) is SourceSavedPipeline,
                "source-pipeline-typed-registration-required",
            )
            pipeline.verify(self)
        self._bound_runner = runner
        self._configuration_verifier = verify_configuration
        self._owners, self._tokens, self._identities = {}, {}, {}
        self._closed = False

    @staticmethod
    def _row(state, *, create=False):
        row = state.get(STORE)
        if row is None and create:
            row = dict(schema_version="1.0.0", owner=None, grants={}, jobs={})
            state[STORE] = row
        if row is not None:
            _check(
                type(row) is dict
                and set(row) == {"schema_version", "owner", "grants", "jobs"}
                and row["schema_version"] == "1.0.0"
                and type(row["grants"]) is dict
                and type(row["jobs"]) is dict
                and len(row["grants"]) <= MAX_ITEMS
                and len(row["jobs"]) <= MAX_ITEMS,
                "source-saved-state-invalid",
            )
        return row

    def _proof(self, state, reason, observation):
        payload = dict(
            reason=reason,
            store_sha256=sha(canonical(self._row(state))),
            observation=deepcopy(observation),
        )
        _check(len(canonical(payload)) <= MAX_JSON, "source-proof-too-large")
        self.intake.db.execute(
            "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
            (state["project_ref"], PROOF, canonical(payload).decode()),
        )

    def _validate(self, state, principal):
        row = self._row(state)
        if row is None:
            return None
        saved = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=? ORDER BY id DESC LIMIT 1",
            (state["project_ref"], PROOF),
        ).fetchone()
        _check(
            saved is not None
            and json.loads(saved[0])["store_sha256"] == sha(canonical(row)),
            "source-state-proof-differs",
        )
        for ref, grant in row["grants"].items():
            _check(
                ref == grant["grant_ref"]
                and grant["principal"] == principal
                and grant["project_ref"] == state["project_ref"]
                and grant["offer_sha256"] == sha(canonical(grant["offer"]))
                and grant["scope"] == _scope(grant["offer"])
                and grant["grant_sha256"] == sha(canonical(grant["document"])),
                "source-grant-proof-differs",
            )
            action = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, state["project_ref"], grant["key"]),
            ).fetchone()
            _check(
                action is not None and action[0] == grant["request_sha256"],
                "source-grant-action-missing",
            )
            receipt = json.loads(action[1])
            _check(
                receipt["kind"] == "stage1-source-authorize"
                and receipt["request_sha256"] == grant["request_sha256"]
                and receipt["request"] == grant["request"],
                "source-grant-action-differs",
            )
        for key, job in row["jobs"].items():
            _check(
                key == job["key"]
                and job["principal"] == principal
                and job["project_ref"] == state["project_ref"]
                and job["grant_ref"] in row["grants"]
                and job["job_binding_sha256"] == sha(canonical(job["binding"]))
                and request_binding(job["transport_request"])
                == job["transport_request"]
                and job["transport_request"]["job_binding_sha256"]
                == job["job_binding_sha256"]
                and job["transport_request"]["source_uri"]
                == job["binding"]["scope"]["selected"]["source_uri"]
                and job["transport_request"]["runtime_sha256"]
                == job["binding"]["scope"]["runtime_sha256"]
                and job["transport_request"]["resolver_sha256"]
                == job["binding"]["resolver_sha256"]
                and job["request_sha256"]
                == _request_hash("stage1-source-execute", job["action_request"])
                and job["status"] in TERMINAL | UNSETTLED,
                "source-job-proof-differs",
            )
            action = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, state["project_ref"], key),
            ).fetchone()
            _check(
                action is not None and action[0] == job["request_sha256"],
                "source-job-action-missing",
            )
            receipt = json.loads(action[1])
            _check(
                receipt["kind"] == "stage1-source-execute"
                and receipt["request"]
                == {k: v for k, v in job["action_request"].items() if k != "revision"},
                "source-job-action-differs",
            )
        return row

    def _past(self, principal, ref, kind, body):
        self.intake._load(principal, ref)
        saved = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (principal, ref, body["key"]),
        ).fetchone()
        if saved is None:
            return None
        _check(saved[0] == _request_hash(kind, body), "idempotency-payload-differs")
        return self.intake._receipt(json.loads(saved[1]), replayed=True)

    def _claim(self, state, *, recovery=False):
        ref, row = state["project_ref"], self._row(state, create=True)
        _check(not self._closed, "source-service-closed")
        if ref in self._owners:
            self._check_owner(state)
            return
        _check(
            recovery or row["owner"] is None, "source-explicit-owner-reopen-required"
        )
        path = self.intake._path(ref, "source-owner.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        private_output(path)
        lock = sqlite3.connect(
            path, timeout=0, isolation_level=None, check_same_thread=False
        )
        try:
            lock.execute("CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY)")
            lock.execute("BEGIN IMMEDIATE")
            info = path.stat()
            _check(
                stat.S_ISREG(info.st_mode) and info.st_ino != 0,
                "source-owner-file-identity-required",
            )
            epoch = 1 if row["owner"] is None else row["owner"]["epoch"] + 1
            token = uuid.uuid4().hex
            row["owner"] = dict(token=token, epoch=epoch)
            self._owners[ref], self._tokens[ref] = lock, deepcopy(row["owner"])
            self._identities[ref] = (info.st_dev, info.st_ino)
            self._proof(state, "owner-acquired", row["owner"])
        except BaseException:
            lock.close()
            self._owners.pop(ref, None)
            self._tokens.pop(ref, None)
            self._identities.pop(ref, None)
            raise

    def _check_owner(self, state):
        ref = state["project_ref"]
        _check(
            not self._closed
            and ref in self._owners
            and self._owners[ref].in_transaction
            and self._row(state)["owner"] == self._tokens[ref],
            "source-owner-lost",
        )
        path = self.intake._path(ref, "source-owner.sqlite")
        reject_links(path)
        info = path.stat()
        _check(
            stat.S_ISREG(info.st_mode)
            and (info.st_dev, info.st_ino) == self._identities[ref],
            "source-owner-file-differs",
        )

    def _drop_uncommitted_owner(self, principal, ref):
        state = self.intake._load(principal, ref)
        row = self._row(state)
        if ref in self._owners and (row is None or row["owner"] != self._tokens[ref]):
            self._owners.pop(ref).close()
            self._tokens.pop(ref, None)
            self._identities.pop(ref, None)

    def _current_scope(self, principal, ref, grant):
        with _core_boundary():
            return self._scope_snapshot(principal, ref, grant)

    def _scope_snapshot(self, principal, ref, grant):
        state = self.intake._load(principal, ref)
        binding = self.intake.binding(ref)
        run, ledger, _ = self.stage1._ledger(state, binding)
        current = dict(
            project_ref=ref,
            principal=principal,
            binding=dict(
                _basis(binding),
                plan_sha256=tree_sha(binding["plan_root"]),
                run_ref=run["run_ref"],
                run_id=ledger.manifest["research_run"]["run_id"],
                manifest_sha256=run["manifest_sha256"],
            ),
            selected=_selected(
                ledger, grant["scope"]["selected"]["work_id"], self.config
            ),
            runtime_sha256=self.config["runtime_sha256"],
            execution_source_sha256=self.config["execution_source_sha256"],
            server_configuration_sha256=sha(canonical(configuration(self.config))),
            url_policy=deepcopy(self.config["url_policy"]),
            **(
                {"pipeline_sha256": self.config["pipeline_sha256"]}
                if "pipeline_sha256" in self.config
                else {}
            ),
        )
        _check(
            current == grant["scope"]
            and binding["settings"]["consent"]["public_source_read"] is True,
            "source-grant-scope-stale",
        )
        return state, ledger

    def offers(self, credential, ref, work_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            self._validate(state, principal)
            with _core_boundary():
                _, _, offer = proposal(
                    self.intake, self.stage1, ref, principal, self.config, work_ref
                )
            return dict(
                offer,
                work_ref=work_ref,
                revision=state["revision"],
                runner_connected=self.runner is not None,
                execution_authorized=False,
                native_attestation=False,
                parser_connected=False,
                core_source_bridge=False,
                reading_connected=False,
            )

    def authorize(self, credential, ref, body, *, check_deadline=None):
        _shape(body, AUTHORIZE_FIELDS)
        principal = self.intake._principal(credential)
        with self.intake._lock:
            old = self._past(principal, ref, "stage1-source-authorize", body)
            if old is not None:
                return old

            def reserve(state, digest, actor):
                self._validate(state, actor)
                with _core_boundary():
                    _, document, offer = proposal(
                        self.intake,
                        self.stage1,
                        ref,
                        actor,
                        self.config,
                        body["work_ref"],
                    )
                _check(
                    body["offer_ref"] == offer["offer_ref"]
                    and body["offer_sha256"] == offer["offer_sha256"],
                    "source-offer-stale",
                )
                self._claim(state)
                row = self._row(state)
                _check(
                    not any(
                        g["offer_sha256"] == offer["offer_sha256"]
                        for g in row["grants"].values()
                    ),
                    "source-offer-already-authorized",
                )
                _check(len(row["grants"]) < MAX_ITEMS, "source-grant-bound-exceeded")
                grant_ref = "source-grant-" + digest[:32]
                issued = self.clock()
                seal = dict(
                    kind="Stage1ProjectSourceGrant",
                    schema_version="1.0.0",
                    project_ref=ref,
                    principal=actor,
                    authorization_request_sha256=digest,
                    offer_sha256=offer["offer_sha256"],
                    offer=deepcopy(document),
                    issued_at=issued,
                    expires_at=issued + document["limits"]["validity_seconds"],
                    automatic_retry=False,
                    execution_authorized=False,
                )
                row["grants"][grant_ref] = dict(
                    grant_ref=grant_ref,
                    grant_sha256=sha(canonical(seal)),
                    document=seal,
                    offer=deepcopy(document),
                    offer_sha256=offer["offer_sha256"],
                    scope=_scope(document),
                    project_ref=ref,
                    principal=actor,
                    key=body["key"],
                    request_sha256=digest,
                    request={
                        k: deepcopy(v) for k, v in body.items() if k != "revision"
                    },
                    status="authorization-intent",
                    issued_at=issued,
                    expires_at=seal["expires_at"],
                )
                self._proof(state, "grant-intent", row["grants"][grant_ref])

            def work(state, digest, actor):
                self._check_owner(state)
                grant = self._row(state)["grants"]["source-grant-" + digest[:32]]
                self._current_scope(actor, ref, grant)
                grant["status"] = "authorized"
                self._proof(state, "grant-authorized", grant)
                return dict(
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    source_permission_status="saved-explicit-transport-grant",
                    execution_authorized=False,
                    source_acquisition=False,
                )

            try:
                return self.intake._perform(
                    principal,
                    ref,
                    "stage1-source-authorize",
                    deepcopy(body),
                    work,
                    reserve=reserve,
                    check_deadline=check_deadline,
                )
            finally:
                self._drop_uncommitted_owner(principal, ref)

    def _runner_guard(self, *, verify=True):
        runner = self.runner
        _check(isinstance(runner, SourceJobRunner), "source-runner-unconnected")
        _check(runner is self._bound_runner, "source-runner-instance-changed")
        bindings = (runner.binding_sha256, runner.resolver_sha256)
        _check(
            _hash(bindings[0])
            and _hash(bindings[1])
            and bindings[0] == self.config["execution_source_sha256"],
            "source-runner-binding-differs",
        )
        if verify:
            verifier = self.verify_configuration
            _check(
                verifier is self._configuration_verifier
                and callable(verifier)
                and verifier(deepcopy(self.config)) is True,
                "source-execution-configuration-unverified",
            )
            _check(
                not self._closed and self.verify_configuration is verifier,
                "source-execution-verifier-changed",
            )
            _check(self.runner is runner, "source-runner-instance-changed")
            _check(
                (runner.binding_sha256, runner.resolver_sha256) == bindings,
                "source-runner-binding-differs",
            )
        _check(
            sha(canonical(configuration(self.config))) == self.config_sha256,
            "source-server-configuration-changed",
        )
        _check(
            self.pipeline is self._bound_pipeline,
            "source-pipeline-registration-changed",
        )
        if self.pipeline is not None:
            self.pipeline.verify(self)
        return runner

    def execute(self, credential, ref, body, *, check_deadline=None):
        _shape(body, EXECUTE_FIELDS)
        principal = self.intake._principal(credential)
        with self.intake._lock:
            old = self._past(principal, ref, "stage1-source-execute", body)
            if old is not None:
                return old
            self._runner_guard()  # No reservation or queued action when unconnected.

            def reserve(state, digest, actor):
                row = self._validate(state, actor)
                self._check_owner(state)
                _check(
                    row is not None and body["grant_ref"] in row["grants"],
                    "source-grant-unavailable",
                )
                grant = row["grants"][body["grant_ref"]]
                _check(
                    grant["status"] == "authorized"
                    and grant["grant_sha256"] == body["grant_sha256"],
                    "source-grant-differs",
                )
                action = self.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (actor, ref, grant["key"]),
                ).fetchone()
                _check(
                    json.loads(action[0])["status"] == "saved",
                    "source-grant-authorization-not-saved",
                )
                receipt = json.loads(action[0])
                saved = self.intake.db.execute(
                    "SELECT payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
                    (ref, "stage1-source-authorize-saved"),
                ).fetchall()
                _check(
                    any(json.loads(event[0]) == receipt for event in saved),
                    "source-grant-saved-event-missing",
                )
                _check(
                    len(row["jobs"]) < MAX_ITEMS
                    and not any(j["status"] in UNSETTLED for j in row["jobs"].values()),
                    "source-job-reconciliation-required",
                )
                current, ledger = self._current_scope(actor, ref, grant)
                resources = resource_view(self.intake, current, actor)
                self._runner_guard(verify=False)
                limits = grant["offer"]["limits"]
                now = self.clock()
                seconds = min(limits["timeout_seconds"], grant["expires_at"] - now)
                _check(seconds > 0, "source-grant-expired", 408)
                _check(
                    sum(
                        j["grant_ref"] == grant["grant_ref"]
                        for j in row["jobs"].values()
                    )
                    < limits["max_fetches"],
                    "source-grant-budget-exhausted",
                    429,
                )
                _check(
                    sum(
                        j["binding"]["reservation_seconds"]
                        for j in row["jobs"].values()
                        if j["grant_ref"] == grant["grant_ref"]
                    )
                    + seconds
                    <= limits["max_reserved_seconds"],
                    "source-grant-time-budget-exhausted",
                    429,
                )
                output = (
                    self.materials_root
                    / ref
                    / ("input-" + str(state["input_version"]))
                    / ("source-" + digest[:24])
                )
                private_output(output)
                _check(
                    not output.exists()
                    and (os.name != "nt" or len(str(output)) <= 170),
                    "source-fresh-private-output-required",
                )
                binding = dict(
                    project_ref=ref,
                    project_id=state["project_id"],
                    principal=actor,
                    input_version=body["input_version"],
                    brief_sha256=body["brief_sha256"],
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    authorization_request_sha256=grant["request_sha256"],
                    action_request_sha256=digest,
                    owner=deepcopy(row["owner"]),
                    runner_binding_sha256=self.runner.binding_sha256,
                    resolver_sha256=self.runner.resolver_sha256,
                    scope=deepcopy(grant["scope"]),
                    ledger_state_sha256=ledger.state_hash(),
                    journal_sha256=sha(
                        (ledger.root / "stage_events.jsonl").read_bytes()
                    ),
                    reservation_state_sha256=resources["reservation_state_sha256"],
                    materials_root=str(self.materials_root),
                    output_dir=str(output),
                    started_at=now,
                    deadline_at=now + seconds,
                    reservation_seconds=seconds,
                    **(
                        {"pipeline_sha256": self.config["pipeline_sha256"]}
                        if "pipeline_sha256" in self.config
                        else {}
                    ),
                )
                job_sha = sha(canonical(binding))
                transport = request_binding(
                    dict(
                        kind="BoundedPublicSourceRequest",
                        schema_version="1.0.0",
                        request_id="source-" + digest[:32],
                        job_binding_sha256=job_sha,
                        source_uri=grant["scope"]["selected"]["source_uri"],
                        runtime_sha256=self.config["runtime_sha256"],
                        resolver_sha256=binding["resolver_sha256"],
                        deadline_utc=datetime.fromtimestamp(
                            now + seconds, timezone.utc
                        ).isoformat(),
                        total_timeout_seconds=seconds,
                        io_timeout_seconds=min(seconds, limits["timeout_seconds"]),
                        max_http_attempts=limits["max_http_attempts"],
                        max_response_bytes=limits["max_response_bytes"],
                        max_aggregate_bytes=limits["max_response_bytes"],
                    )
                )
                job = dict(
                    key=body["key"],
                    principal=actor,
                    project_ref=ref,
                    grant_ref=grant["grant_ref"],
                    request_sha256=digest,
                    action_request=deepcopy(body),
                    binding=binding,
                    job_binding_sha256=job_sha,
                    transport_request=transport,
                    status="intent-recorded",
                    runner_invoked=False,
                    invocation_claimed=False,
                    invocation_observation="not-dispatched",
                    result=None,
                    failure=None,
                )
                row["jobs"][body["key"]] = job
                self._proof(state, "job-intent", job)
                # Keep this event immediately adjacent to the first action intent.
                reserve_resource(
                    self.intake,
                    state,
                    actor,
                    lane="source",
                    kind="stage1-source-execute",
                    key=body["key"],
                    request_sha256=digest,
                    seconds=seconds,
                )

            def work(state, _digest, _actor):
                self._check_owner(state)
                job = self._row(state)["jobs"][body["key"]]
                job["status"] = "queued"
                self._proof(state, "job-queued", job)
                return dict(
                    job_status="queued",
                    job_binding_sha256=job["job_binding_sha256"],
                    source_acquisition=False,
                    execution_authorized=False,
                    automatic_dispatch=False,
                )

            return self.intake._perform(
                principal,
                ref,
                "stage1-source-execute",
                deepcopy(body),
                work,
                reserve=reserve,
                check_deadline=check_deadline,
            )

    def _job_current(self, principal, ref, key, *, verify=False):
        state, job = self._saved_job_current(principal, ref, key)
        if verify:
            before = sha(canonical(state))
            self._runner_guard()
            state, job = self._saved_job_current(principal, ref, key)
            _check(sha(canonical(state)) == before, "source-admission-state-changed")
        return state, job

    def _saved_job_current(self, principal, ref, key):
        state = self.intake._load(principal, ref)
        row = self._validate(state, principal)
        self._check_owner(state)
        job = row["jobs"][key]
        action = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (principal, ref, key),
        ).fetchone()
        receipt = json.loads(action[0])
        _check(receipt["status"] == "saved", "source-execute-action-not-saved")
        saved = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
            (ref, "stage1-source-execute-saved"),
        ).fetchall()
        _check(
            any(json.loads(event[0]) == receipt for event in saved),
            "source-execute-saved-event-missing",
        )
        _check(job["binding"]["owner"] == row["owner"], "source-job-epoch-differs")
        _check(
            self.clock() < job["binding"]["deadline_at"],
            "source-job-deadline-expired",
            408,
        )
        grant = row["grants"][job["grant_ref"]]
        _check(self.clock() < grant["expires_at"], "source-grant-expired", 408)
        _, ledger = self._current_scope(principal, ref, grant)
        _check(
            ledger.state_hash() == job["binding"]["ledger_state_sha256"]
            and sha((ledger.root / "stage_events.jsonl").read_bytes())
            == job["binding"]["journal_sha256"],
            "source-job-ledger-frontier-changed",
        )
        resources = resource_view(self.intake, state, principal)
        reservation = state["project_resource_reservations"]["reservations"].get(
            job["request_sha256"]
        )
        _check(
            reservation is not None
            and reservation["kind"] == "stage1-source-execute"
            and reservation["key"] == key
            and reservation["seconds"] == job["binding"]["reservation_seconds"],
            "source-job-reservation-differs",
        )
        _check(
            resources["remaining"]["source_reads"] >= 0,
            "source-job-resource-state-invalid",
        )
        runner = self._runner_guard(verify=False)
        _check(
            runner.resolver_sha256 == job["transport_request"]["resolver_sha256"],
            "source-job-resolver-changed",
        )
        _check(
            self.clock() < job["binding"]["deadline_at"],
            "source-job-deadline-expired",
            408,
        )
        return state, job

    def _change_job(
        self,
        principal,
        ref,
        key,
        reason,
        change,
        *,
        require_owner=True,
        check_commit=None,
    ):
        with self.intake._lock:
            self.intake.db.execute("BEGIN IMMEDIATE")
            try:
                state = self.intake._load(principal, ref)
                row = self._validate(state, principal)
                if require_owner:
                    self._check_owner(state)
                change(row["jobs"][key], state)
                self._proof(state, reason, row["jobs"][key])
                state["revision"] += 1
                self.intake._save(
                    state, reason, dict(key=key, status=row["jobs"][key]["status"])
                )
                if check_commit is not None:
                    check_commit()
                self.intake.db.commit()
                if check_commit is not None:
                    check_commit()
                return deepcopy(row["jobs"][key])
            except BaseException:
                self.intake.db.rollback()
                raise

    def dispatch_pending(self, credential, ref, key):
        """Trusted server call only; POST execute and GET never invoke a runner."""
        principal = self.intake._principal(credential)
        identifier(key)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            row = self._validate(state, principal)
            _check(row is not None and key in row["jobs"], "source-job-unavailable")
            if row["jobs"][key]["status"] != "queued":
                return self._public_job(row["jobs"][key])
            try:
                self._job_current(principal, ref, key, verify=True)
            except (SessionApiError, OSError, ValueError, KeyError, TypeError) as error:
                code = getattr(error, "code", "source-pre-dispatch-refused")
                # A stale/expired scope under the same live owner is known unsent.
                # An uncertain owner or action publication is always unknown.
                known = isinstance(error, SessionApiError) and code in {
                    "source-job-deadline-expired",
                    "source-grant-expired",
                    "source-grant-scope-stale",
                    "source-job-ledger-frontier-changed",
                    "source-core-not-ready",
                    "source-runner-unconnected",
                    "source-runner-instance-changed",
                    "source-runner-binding-differs",
                    "source-job-resolver-changed",
                    "source-execution-configuration-unverified",
                    "source-execution-verifier-changed",
                    "source-server-configuration-changed",
                    "source-admission-state-changed",
                }
                if known:
                    try:
                        latest = self.intake._load(principal, ref)
                        self._validate(latest, principal)
                        self._check_owner(latest)
                    except (SessionApiError, OSError, ValueError, KeyError, TypeError):
                        known = False

                def refused(actual, _state):
                    actual.update(
                        status="refused-known-unsent" if known else "execution-unknown",
                        failure=dict(code=code),
                        invocation_observation="not-dispatched",
                    )

                changed = self._change_job(
                    principal,
                    ref,
                    key,
                    "source-job-pre-dispatch-refused",
                    refused,
                    require_owner=known,
                )
                return self._public_job(changed)

            def claim(job, _state):
                _check(job["status"] == "queued", "source-job-not-queued")
                self._job_current(principal, ref, key)
                job.update(
                    status="dispatching",
                    invocation_claimed=True,
                    invocation_observation="unobserved",
                )

            job = self._change_job(
                principal, ref, key, "source-job-dispatch-claimed", claim
            )
        entered = False
        pipeline_deadline = None
        try:
            if self.pipeline is not None:
                from .project_source_saved_pipeline import SourceJobDeadline

                pipeline_deadline = SourceJobDeadline(self, job)
            output = Path(job["binding"]["output_dir"])
            output.parent.mkdir(parents=True, exist_ok=True)

            def current():
                if pipeline_deadline is not None:
                    pipeline_deadline.check()
                with self.intake._lock:
                    _, actual = self._job_current(principal, ref, key)
                    _check(
                        actual["status"] == "dispatching", "source-job-dispatch-lost"
                    )

            current()
            runner = self._runner_guard(verify=False)
            entered = True
            observed = runner.run(
                deepcopy(job["transport_request"]), output, check_current=current
            )
            current()
            result = self._physical_result(job, observed)
            current()

            observation_status = (
                "source-observation-saved"
                if result["body_complete"]
                else "failed-observed"
            )

            def finish(actual, _state):
                current()
                _check(actual["status"] == "dispatching", "source-job-dispatch-lost")
                actual.update(
                    status=observation_status,
                    result=result,
                    runner_invoked=True,
                    invocation_observation="returned",
                )

            def saved_current():
                # Pure saved guards after _save, immediately before and after commit.
                # A post-commit failure keeps that observation in history, then
                # persists unknown separately; it never adopts a late success.
                _, actual = self._job_current(principal, ref, key)
                _check(
                    actual["status"] == observation_status
                    and actual["result"] == result,
                    "source-job-observation-commit-differs",
                )

            self._change_job(
                principal,
                ref,
                key,
                "source-job-observation-saved",
                finish,
                check_commit=saved_current,
            )
            if self.pipeline is not None and result["body_complete"]:
                self.pipeline.run_saved(self, credential, ref, key, pipeline_deadline)
        except BaseException as error:
            error_type = type(error).__name__

            def unknown(actual, _state):
                actual.update(
                    status="execution-unknown",
                    runner_invoked=entered,
                    invocation_observation="raised" if entered else "unobserved",
                    failure=dict(
                        code="source-job-failed-or-unobserved",
                        error_type=error_type,
                    ),
                )

            # Losing ownership forbids success, but failure evidence never adopts a new epoch.
            self._change_job(
                principal,
                ref,
                key,
                "source-job-execution-unknown",
                unknown,
                require_owner=False,
            )
            if not isinstance(error, Exception):
                raise
        return self.read(credential, ref)["jobs"][key]

    def _physical_result(self, job, observed):
        _check(
            type(observed) is dict
            and set(observed) == {"receipt_path", "receipt_sha256"}
            and observed["receipt_path"] == "public-source-acquisition.json"
            and _hash(observed["receipt_sha256"]),
            "source-runner-observation-invalid",
        )
        root = Path(job["binding"]["output_dir"])
        private_output(root)
        _check(
            not os.path.lexists(root / "public-source-acquisition-failure.json"),
            "source-late-acquisition-failure",
        )
        path = safe_path(root, observed["receipt_path"])
        receipt, artifacts = _acquisition(
            path,
            observed["receipt_sha256"],
            job["transport_request"],
            job["job_binding_sha256"],
            self.config["runtime_sha256"],
        )
        began = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        _check(
            began.timestamp() >= job["binding"]["started_at"],
            "source-acquisition-start-before-job",
        )
        return dict(
            receipt_path=observed["receipt_path"],
            receipt_sha256=observed["receipt_sha256"],
            outcome=receipt["outcome"],
            body_complete=receipt["body_complete"],
            raw_sha256=receipt["raw_sha256"],
            artifacts=artifacts,
            evidence_scope="saved-transport-observation-only",
            native_attestation=False,
            parser_connected=False,
            core_source_bridge=False,
            reading_complete=False,
            stage1_complete=False,
        )

    @staticmethod
    def _public_job(job, *, owned=False):
        status = job["status"]
        return dict(
            key=job["key"],
            grant_ref=job["grant_ref"],
            job_binding_sha256=job["job_binding_sha256"],
            input_version=job["binding"]["input_version"],
            brief_sha256=job["binding"]["brief_sha256"],
            work_ref=job["binding"]["scope"]["selected"]["work_id"],
            saved_status=status,
            status="execution-unknown" if status in UNSETTLED and not owned else status,
            runner_invoked=job["runner_invoked"],
            invocation_claimed=job["invocation_claimed"],
            invocation_observation=job["invocation_observation"],
            result=deepcopy(job["result"]),
            result_scope="historical-saved-observation",
            current_physical_bytes_verified=False,
            failure=deepcopy(job["failure"]),
            **({"followup": deepcopy(job["followup"])} if "followup" in job else {}),
            automatic_retry=False,
            execution_authorized=False,
        )

    def read(self, credential, ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            row = self._validate(state, principal)
            live_owner = (
                not self._closed
                and ref in self._owners
                and self._owners[ref].in_transaction
                and row is not None
                and row["owner"] == self._tokens.get(ref)
            )
            jobs = (
                {}
                if row is None
                else {
                    k: self._public_job(v, owned=live_owner)
                    for k, v in row["jobs"].items()
                }
            )
            grants = (
                {}
                if row is None
                else {
                    k: dict(
                        grant_ref=k,
                        grant_sha256=g["grant_sha256"],
                        offer_ref="project-source-" + g["offer_sha256"][:32],
                        status=g["status"],
                        work_ref=g["scope"]["selected"]["work_id"],
                        input_version=g["scope"]["binding"]["input_version"],
                        brief_sha256=g["scope"]["binding"]["brief_sha256"],
                        expires_at=g["expires_at"],
                        execution_authorized=False,
                    )
                    for k, g in row["grants"].items()
                }
            )
            return dict(
                project_ref=ref,
                revision=state["revision"],
                grants=grants,
                jobs=jobs,
                runner_connected=self.runner is not None,
                execution_authorized=False,
                automatic_dispatch=False,
                **(
                    {"source_saved_pipeline_registered": True}
                    if self.pipeline is not None
                    else {}
                ),
                parser_connected=False,
                core_source_bridge=False,
                reading_connected=False,
                stage1_complete=False,
            )

    def history(self, credential, ref):
        return self.read(credential, ref)

    def reopen(self, credential, ref):
        """Explicit local ownership recovery only; never adopt or resend a job."""
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            self._validate(state, principal)
            _check(ref not in self._owners, "source-owner-already-open")
            self.intake.db.execute("BEGIN IMMEDIATE")
            try:
                state = self.intake._load(principal, ref)
                self._validate(state, principal)
                self._claim(state, recovery=True)
                row = self._row(state)
                for job in row["jobs"].values():
                    if job["status"] in UNSETTLED:
                        job.update(
                            status="execution-unknown",
                            failure=dict(code="source-owner-recovery-no-resend"),
                        )
                self._proof(
                    state,
                    "owner-reopened-no-resend",
                    dict(owner=row["owner"], automatic_retry=False),
                )
                state["revision"] += 1
                self.intake._save(
                    state, "stage1-source-owner-reopened", dict(automatic_retry=False)
                )
                self.intake.db.commit()
            except BaseException:
                self.intake.db.rollback()
                self._drop_uncommitted_owner(principal, ref)
                raise
        return self.read(credential, ref)

    def close(self):
        """Release local locks. Durable unsettled jobs remain unknown, never retryable."""
        with self.intake._lock:
            self._closed = True
            for lock in self._owners.values():
                lock.close()
            self._owners.clear()
            self._tokens.clear()
            self._identities.clear()
