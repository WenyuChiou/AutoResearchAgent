"""One explicitly registered source job to saved SDK/Core observations.

No browser supplies a runtime, path, permission, deadline or callback. The
original source reservation covers every phase; no retry/adoption exists.
Current checks protect local commits, not preemption of synchronous OS calls.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import time

from stage1_deliverable.common import canonical, private_output, safe_path, sha
from stage1_ledger.validation import validate_run

from .acquired_source_parser import parse_acquired_source
from .planned_queries import PlannedQueryService
from .planned_query_contract import tree_sha
from .project_query_history import bound_run
from .project_resource_budget import resource_view
from .project_source_permit import _selected
from .project_stage1 import ProjectStage1Service, _basis
from .project_stage1_delivery import _source_attempt, _source_outcome
from .project_stage1_records import ProjectStage1RecordsService
from .project_stage1_saved_import import (
    _inspect,
    complete_saved_sdk_import,
    prepare_saved_sdk_import,
)
from .saved_source_parser_factory import ContainedSavedSourceParserFactory
from .session_api import SessionApiError, _check


class SourceJobDeadline:
    """One dispatch-local monotonic end, capped by the saved job's UTC end."""

    def __init__(self, service, job):
        self.service = service
        self.wall_end = job["binding"]["deadline_at"]
        self.utc_end = datetime.fromisoformat(
            job["transport_request"]["deadline_utc"].replace("Z", "+00:00")
        )
        left = min(
            self.wall_end - service.clock(),
            (self.utc_end - datetime.now(timezone.utc)).total_seconds(),
            job["transport_request"]["total_timeout_seconds"],
        )
        _check(left > 0, "source-pipeline-original-deadline-expired", 408)
        self.end = time.monotonic() + left
        self._end = self.end
        self.check()

    def check(self):
        _check(
            self.end == self._end
            and time.monotonic() < self.end
            and self.service.clock() < self.wall_end
            and datetime.now(timezone.utc) < self.utc_end,
            "source-pipeline-original-deadline-expired",
            408,
        )


class SourceSavedPipeline:
    """Trusted portable setup registers exact typed dependencies and consent."""

    def __init__(self, stage1, records, parser_factory, *, phase_admission=None):
        _check(
            type(stage1) is ProjectStage1Service
            and type(records) is ProjectStage1RecordsService
            and records.intake is stage1.intake
            and records.delivery.stage1 is stage1,
            "source-pipeline-same-services-required",
        )
        _check(
            type(parser_factory) is ContainedSavedSourceParserFactory,
            "source-pipeline-typed-parser-required",
        )
        _check(phase_admission is True, "source-pipeline-phase-unavailable", 503)
        self.stage1, self.records, self.factory = stage1, records, parser_factory
        self._stage1, self._records, self._factory = stage1, records, parser_factory
        self._record_guard = records.guard
        self._runtime_sha = parser_factory.binding_sha256
        self._worker = parser_factory.worker
        self.phase_admission = phase_admission
        self.document = dict(
            kind="RegisteredSourceSavedPipeline",
            schema_version="1.0.0",
            parser_runtime_sha256=self._runtime_sha,
            execution_source_sha256=self._worker.binding_sha256,
            materials_root=str(records.root),
            operations=["source-import-saved", "local-core-source-observation"],
            explicit_phase_admission=True,
            additional_resource_reservation=False,
            automatic_retry=False,
        )
        self._document = canonical(self.document)
        self.binding_sha256 = sha(self._document)

    def verify(self, service):
        _check(
            type(self) is SourceSavedPipeline
            and self.stage1 is self._stage1 is service.stage1
            and self.records is self._records
            and self.records.intake is service.intake
            and self.records.guard is self._record_guard
            and self.records.root == service.materials_root
            and self.factory is self._factory
            and self.factory.worker is self._worker is service.runner
            and self.factory.binding_sha256 == self._runtime_sha
            and sha(canonical(self.factory.runtime)) == self._runtime_sha
            and self.phase_admission is True
            and canonical(self.document) == self._document
            and self.binding_sha256 == sha(self._document)
            and service.config.get("pipeline_sha256") == self.binding_sha256,
            "source-pipeline-registration-changed",
        )
        return True

    def run_saved(self, service, credential, ref, key, deadline):
        """Called once after the broker saved its original transport receipt."""
        principal = service.intake._principal(credential)
        entered = False
        try:
            self.verify(service)
            with service.intake._lock:
                state, job = service._job_current(principal, ref, key)
                _check(
                    job["status"] == "source-observation-saved",
                    "source-pipeline-transport-required",
                )
                _check(job.get("followup") is None, "source-pipeline-replay-refused")
                _check(
                    job["binding"].get("pipeline_sha256") == self.binding_sha256,
                    "source-pipeline-job-binding-differs",
                )
                ledger = self.stage1._ledger(state, service.intake.binding(ref))[1]
                check = _OwnedPipelineGuard(
                    self, service, credential, ref, key, job, ledger, deadline
                )
                output = Path(job["binding"]["output_dir"])
                parsed = private_output(
                    output.parent / ("p-" + job["job_binding_sha256"][:24])
                )
                _check(
                    not parsed.exists(), "source-pipeline-fresh-parser-output-required"
                )
                followup = dict(
                    status="processing-intent",
                    pipeline_sha256=self.binding_sha256,
                    original_deadline_utc=job["transport_request"]["deadline_utc"],
                    parser_output_dir=str(parsed),
                    core_action_key="source-core-" + job["job_binding_sha256"][:32],
                    automatic_retry=False,
                    reading_complete=False,
                    stage1_complete=False,
                )
                self._save(service, principal, ref, key, followup, check)
            entered = True
            metadata = job["binding"]["scope"]["selected"]["metadata"]
            identity = {
                name: "" if metadata.get(name) is None else metadata[name]
                for name in ("doi", "title")
            }
            parser = self.factory.bind(
                request=job["transport_request"],
                deadline=deadline,
                check_current=lambda: check(worker_gate=True),
            )
            acquired = parse_acquired_source(
                materials_root=service.materials_root,
                acquisition_receipt_path=output / job["result"]["receipt_path"],
                expected_acquisition_sha256=job["result"]["receipt_sha256"],
                expected_request=job["transport_request"],
                expected_job_binding_sha256=job["job_binding_sha256"],
                runtime_sha256=service.config["runtime_sha256"],
                expected_identity=identity,
                parser_output_dir=parsed,
                parse_admission=True,
                deadline=deadline,
                parser_runner=parser,
                check_current=lambda: check(worker_gate=True),
            )
            check()
            followup.update(
                status="parser-observation-saved",
                bundle_path=acquired["bundle_path"],
                bundle_sha256=acquired["bundle_sha256"],
            )
            _check(
                sha(Path(acquired["bundle_path"]).read_bytes())
                == acquired["bundle_sha256"],
                "source-pipeline-bundle-readback-differs",
            )
            self._save(service, principal, ref, key, followup, check)
            sdk = acquired["bundle"]["parser"]
            result_path = safe_path(service.materials_root, sdk["receipt_path"])
            with service.intake._lock:
                state = service.intake._load(principal, ref)
                body = dict(
                    key=followup["core_action_key"],
                    revision=state["revision"],
                    input_version=job["binding"]["input_version"],
                    brief_sha256=job["binding"]["brief_sha256"],
                    confirmed=True,
                    ledger_state_sha256=ledger.state_hash(),
                    source_key=key,
                    bundle_sha256=acquired["bundle_sha256"],
                    pipeline_sha256=self.binding_sha256,
                )
                check.begin_core(body, result_path, sdk["receipt_sha256"])

                def produce(_state, _run, owned, request_hash, actor):
                    _check(
                        owned.root == ledger.root
                        and request_hash == check.request_hash
                        and actor == principal,
                        "source-pipeline-core-owner-differs",
                    )
                    check()
                    proposed = prepare_saved_sdk_import(
                        materials_root=service.materials_root,
                        result_path=result_path,
                        expected_result_sha256=sdk["receipt_sha256"],
                        runtime_sha256=service.config["runtime_sha256"],
                        check_current=check,
                    )
                    args = dict(
                        work_id=job["binding"]["scope"]["selected"]["work_id"],
                        version_id=job["binding"]["scope"]["selected"]["version_id"],
                        source_uri=proposed["source_uri"],
                        tool=proposed["tool"],
                        request=proposed["request"],
                        actor=actor,
                        reason="Local observation of the unchanged acquired SDK receipt.",
                    )
                    check.start_arguments = args
                    source_id = owned.start_source(**args)
                    check.source_id = source_id
                    check()
                    return complete_saved_sdk_import(
                        owned,
                        materials_root=service.materials_root,
                        source_id=source_id,
                        expected_start=owned.event(source_id, "SourceReadStarted"),
                        result_path=result_path,
                        expected_result_sha256=sdk["receipt_sha256"],
                        runtime_sha256=service.config["runtime_sha256"],
                        reason="Saved import; HTTP receipt and original timestamps preserved.",
                        check_current=check,
                    )

                core = self.stage1._mutate(
                    credential,
                    ref,
                    body,
                    "stage1-import-saved",
                    produce,
                    fields=("source_key", "bundle_sha256", "pipeline_sha256"),
                    check_deadline=check,
                )
                _check(
                    core["status"] == "saved", "source-pipeline-core-outcome-unknown"
                )
                check()
                _check(
                    check.source_id is not None and check.finished,
                    "source-pipeline-core-finish-required",
                )
                registry = self.records.register_source(
                    ref,
                    source_id=check.source_id,
                    result_path=result_path,
                    expected_result_sha256=sdk["receipt_sha256"],
                    access_note="Original saved SDK import; independent identity review remains required.",
                    expected_ledger_state_sha256=ledger.state_hash(),
                    check_current=check,
                )
                check()
                followup.update(
                    status="source-core-registered",
                    parser_connected=True,
                    core_source_bridge=True,
                    core_action=core,
                    registry_ref=registry["ref"],
                    owned_frontier=check.frontier(),
                    original_http_acquisition_verified=False,
                )
                self._save(service, principal, ref, key, followup, check)
            return deepcopy(followup)
        except BaseException as error:
            error_type = type(error).__name__
            error_code = error.code if isinstance(error, SessionApiError) else None

            def unknown(actual, _state):
                prior = actual.get("followup") or {}
                actual["followup"] = dict(
                    prior,
                    status="execution-unknown",
                    automatic_retry=False,
                    failure=dict(
                        code="source-pipeline-failed-or-unobserved",
                        error_type=error_type,
                        error_code=error_code,
                        parser_entered=entered,
                    ),
                )

            service._change_job(
                principal,
                ref,
                key,
                "source-pipeline-execution-unknown",
                unknown,
                require_owner=False,
            )
            if not isinstance(error, Exception):
                raise
            return service.read(credential, ref)["jobs"][key].get("followup")

    @staticmethod
    def _save(service, principal, ref, key, followup, check):
        check()

        def write(actual, _state):
            check()
            actual["followup"] = deepcopy(followup)

        service._change_job(
            principal,
            ref,
            key,
            "source-pipeline-phase-saved",
            write,
            check_commit=check,
        )


class _OwnedPipelineGuard:
    """A producer-local exception for its own exact intent and event suffix.

    Generic saved_frontier/_job_current remain strict. This guard never calls
    them while the query owner's own local mutation is pending.
    """

    def __init__(self, pipeline, service, credential, ref, key, job, ledger, deadline):
        self.pipeline, self.service, self.credential = pipeline, service, credential
        self.ref, self.key, self.job = ref, key, deepcopy(job)
        self.principal = service.intake._principal(credential)
        self.ledger, self.deadline = ledger, deadline
        self.deadline_end = deadline.end
        state = service.intake._load(self.principal, ref)
        self.run = deepcopy(state["stage1_runs"][state["stage1_active"]])
        self.project_queries = pipeline.stage1.query_service
        _check(
            self.run.get("query_owned") is True and self.project_queries is not None,
            "source-pipeline-query-owner-required",
        )
        self.query = self.project_queries.services.get(ref)
        _check(
            type(self.query) is PlannedQueryService,
            "source-pipeline-query-owner-required",
        )
        self.project = self.query._projects[ref]
        self.saved = deepcopy(self.query.store.snapshot(self.project["pid"]))
        # Validate the generic current selection before the own Core start.
        # Later _observe requires this exact prefix plus only owned source
        # events, which cannot alter Candidate/Decision/Discovery selection.
        self.selected = deepcopy(
            _selected(
                ledger, job["binding"]["scope"]["selected"]["work_id"], service.config
            )
        )
        _check(
            self.selected == job["binding"]["scope"]["selected"],
            "source-pipeline-original-selection-differs",
        )
        self.before = deepcopy(ledger.events())
        self.expected = deepcopy(self.before)
        self.request_hash = self.intent_key = None
        self.source_id = None
        self.start_arguments = None
        self.allowed_artifacts = {}
        self.observed_artifacts = {}
        self.finished = False

    def begin_core(self, body, result_path, result_sha256):
        self()
        _, _, receipt, original, data, mapping = _inspect(
            self.service.materials_root, result_path, result_sha256
        )
        attempt = _source_attempt(receipt)
        self.outcome = _source_outcome(receipt)
        raw_name = receipt["raw_path"] or attempt["raw_path"]
        raw = data[mapping[raw_name]] if raw_name is not None else original
        text = (
            data[mapping[receipt["extracted_text_path"]]]
            if self.outcome == "available"
            else None
        )
        self.raw_sha256 = sha(raw)
        self.text_sha256 = sha(text) if text is not None else None
        self.allowed_artifacts = {self.raw_sha256: len(raw)}
        if text is not None:
            self.allowed_artifacts[self.text_sha256] = len(text)
        self.sdk = receipt
        self.request_hash = sha(
            canonical(
                dict(
                    kind="stage1-import-saved",
                    body={k: v for k, v in body.items() if k != "revision"},
                )
            )
        )
        self.intent_key = sha(
            canonical([self.principal, "project-" + self.request_hash])
        )

    def _observe(self, *, full_validation=True):
        events = self.ledger.events()
        _check(
            events[: len(self.expected)] == self.expected,
            "source-pipeline-core-prefix-changed",
        )
        suffix = events[len(self.expected) :]
        for row in suffix:
            event = row["payload"]
            _check(
                not self.finished and self.source_id is not None,
                "source-pipeline-unowned-core-append",
            )
            if event["kind"] == "SourceReadStarted":
                _check(
                    len(self.expected) == len(self.before)
                    and event["event_id"] == self.source_id
                    and all(
                        event[name] == value
                        for name, value in self.start_arguments.items()
                    ),
                    "source-pipeline-start-differs",
                )
            elif event["kind"] == "ArtifactStored":
                ref = event["ref"]
                _check(
                    ref["producer"] == self.source_id
                    and ref["artifact_type"] == "raw-output"
                    and self.allowed_artifacts.get(ref["sha256"]) == event["bytes"]
                    and ref["sha256"] not in self.observed_artifacts,
                    "source-pipeline-artifact-differs",
                )
                self.observed_artifacts[ref["sha256"]] = deepcopy(ref)
            elif event["kind"] == "SourceReadFinished":
                _check(
                    event["attempt_id"] == self.source_id
                    and event["http_status"] is None
                    and event["outcome"] == self.outcome
                    and event["resolved_uri"] == self.sdk["final_url"]
                    and set(self.observed_artifacts) == set(self.allowed_artifacts)
                    and event["raw_ref"] == self.observed_artifacts[self.raw_sha256]
                    and event["text_ref"]
                    == (
                        self.observed_artifacts[self.text_sha256]
                        if self.text_sha256
                        else None
                    )
                    and event["extraction"]
                    == (
                        {
                            "method": self.start_arguments["tool"],
                            "version": "sha256:"
                            + self.service.config["runtime_sha256"],
                        }
                        if self.text_sha256
                        else None
                    )
                    and datetime.fromisoformat(
                        self.sdk["retrieved_at"].replace("Z", "+00:00")
                    )
                    <= datetime.fromisoformat(
                        self.ledger.event(self.source_id)["created_at"].replace(
                            "Z", "+00:00"
                        )
                    )
                    <= datetime.fromisoformat(
                        event["observed_at"].replace("Z", "+00:00")
                    )
                    <= datetime.fromisoformat(
                        event["created_at"].replace("Z", "+00:00")
                    ),
                    "source-pipeline-finish-differs",
                )
                self.finished = True
            else:
                _check(False, "source-pipeline-unowned-core-append")
            self.expected.append(deepcopy(row))
        if full_validation:
            _check(
                validate_run(self.ledger.root)["valid"], "source-pipeline-core-invalid"
            )

    def __call__(self, *, worker_gate=False):
        _check(type(worker_gate) is bool, "source-pipeline-invalid-worker-gate")
        if worker_gate:
            # The typed worker independently checks physical pins before every
            # SDK gate and publication. Its bounded callback checks live state;
            # it cannot use this path after any Core mutation starts.
            _check(
                self.intent_key is None
                and self.source_id is None
                and self.expected == self.before,
                "source-pipeline-worker-gate-after-core",
            )
        _check(
            self.deadline.end == self.deadline_end,
            "source-pipeline-original-deadline-changed",
        )
        self.deadline.check()
        service, intake = self.service, self.service.intake
        with intake._lock:
            self.pipeline.verify(service)
            state = intake._load(self.principal, self.ref)
            row = service._validate(state, self.principal)
            service._check_owner(state)
            actual = row["jobs"][self.key]
            _check(
                actual["binding"] == self.job["binding"]
                and actual["result"] == self.job["result"]
                and actual["status"] == "source-observation-saved"
                and actual["job_binding_sha256"] == self.job["job_binding_sha256"],
                "source-pipeline-job-changed",
            )
            binding = intake.binding(self.ref)
            grant = row["grants"][actual["grant_ref"]]
            _check(
                service.clock() < grant["expires_at"]
                and grant["scope"] == actual["binding"]["scope"]
                and state["stage1_active"] == self.run["run_ref"]
                and state["stage1_runs"][self.run["run_ref"]] == self.run,
                "source-pipeline-scope-changed",
            )
            scope = actual["binding"]["scope"]
            _check(
                all(
                    scope["binding"][k] == value for k, value in _basis(binding).items()
                )
                and scope["binding"]["plan_sha256"] == tree_sha(binding["plan_root"])
                and binding["settings"]["consent"]["public_source_read"] is True
                and self.selected == scope["selected"],
                "source-pipeline-input-changed",
            )
            registration = bound_run(intake, state, _basis(binding), self.run)
            _check(
                registration["ledger_root"] == self.ledger.root.as_posix()
                and sha((self.ledger.root / "run_manifest.json").read_bytes())
                == self.run["manifest_sha256"],
                "source-pipeline-ledger-binding-changed",
            )
            resource_view(intake, state, self.principal)
            reservation = state["project_resource_reservations"]["reservations"].get(
                actual["request_sha256"]
            )
            _check(
                reservation is not None
                and reservation["kind"] == "stage1-source-execute"
                and reservation["key"] == self.key
                and reservation["seconds"] == actual["binding"]["reservation_seconds"],
                "source-pipeline-reservation-changed",
            )
            service._runner_guard(verify=not worker_gate)
            if worker_gate:
                _check(
                    service.verify_configuration is service._configuration_verifier
                    and callable(service.verify_configuration)
                    and sha((self.ledger.root / "stage_events.jsonl").read_bytes())
                    == self.job["binding"]["journal_sha256"],
                    "source-pipeline-worker-gate-binding-changed",
                )
            _check(
                self.pipeline.stage1.query_service is self.project_queries
                and self.project_queries.services.get(self.ref) is self.query
                and not self.project_queries.closing
                and not self.query._closing
                and not self.query._closed
                and self.query._projects.get(self.ref) is self.project,
                "source-pipeline-query-owner-changed",
            )
            with self.query._lock:
                self.query._check_storage()
                saved = self.query.store.snapshot(self.project["pid"])
                self.query._saved_owner(self.project, saved)
                _check(
                    saved["query_budget"] == self.saved["query_budget"],
                    "source-pipeline-query-budget-changed",
                )
                baseline = self.saved["intents"]
                _check(
                    all(
                        saved["intents"].get(k) == value
                        for k, value in baseline.items()
                    ),
                    "source-pipeline-query-history-changed",
                )
                extra = set(saved["intents"]) - set(baseline)
                _check(
                    not extra
                    or self.intent_key is not None
                    and extra == {self.intent_key},
                    "source-pipeline-unowned-query-action",
                )
                intent = (
                    saved["intents"].get(self.intent_key) if self.intent_key else None
                )
                if intent is not None:
                    _check(
                        intent["method"] == "stage1/saved-ledger"
                        and intent["request_sha256"] == self.request_hash
                        and intent["request"]
                        == dict(
                            operation="stage1-import-saved",
                            request_sha256=self.request_hash,
                            expected_tree_sha256=self.saved["query_ledger_sha256"],
                        )
                        and intent["status"] in {"dispatch-unobserved", "completed"},
                        "source-pipeline-query-intent-changed",
                    )
                self._observe(full_validation=not worker_gate)
                expected_tree = (
                    tree_sha(self.ledger.root)
                    if intent and intent["status"] == "completed"
                    else self.saved["query_ledger_sha256"]
                )
                _check(
                    saved["query_ledger_sha256"] == expected_tree,
                    "source-pipeline-query-frontier-changed",
                )
            self.deadline.check()

    def frontier(self):
        self()
        return dict(
            ledger_state_sha256=self.ledger.state_hash(),
            journal_sha256=sha((self.ledger.root / "stage_events.jsonl").read_bytes()),
            query_tree_sha256=tree_sha(self.ledger.root),
            journal_sequence=len(self.expected),
            own_source_id=self.source_id,
        )
