"""Source-bound offline Stage1 ledger operations over the existing core.

Initialization, planned-query intents, checkpoints and saved-artifact exports are
real core operations. The optional project query bridge owns live ledger writes
and requires a separately sealed search permit. This ledger adapter itself does
not acquire sources, run a model or declare Stage1 scientifically complete.
"""

from copy import deepcopy
import os

from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import identifier, private_output, sha
from stage1_export.bundle import export_run, validate_export
from stage1_ledger.journal import canonical
from stage1_ledger.readiness import readiness
from stage1_ledger.validation import validate_run

from .project_intake import ProjectIntakeService
from .project_intake_contract import _fields, _text
from .session_api import _check, _hash
from .project_query_history import bound_run

MAX_QUERIES = 256
BINDING_FIELDS = ("project_id", "input_version", "brief_sha256", "plan_manifest_sha256")
BODY_FIELDS = {"key", "revision", "input_version", "brief_sha256", "confirmed"}


def _basis(binding):
    return {
        **{key: binding[key] for key in BINDING_FIELDS},
        "settings_sha256": sha(canonical(binding["settings"])),
    }


class ProjectStage1Service:
    """One shared durable intake store; server selects every ledger/output root."""

    def __init__(self, intake, *, query_runner=None, backends=("openalex",), limit=40):
        _check(
            isinstance(intake, ProjectIntakeService), "project-intake-service-required"
        )
        _check(
            query_runner is None or callable(query_runner),
            "stage1-query-runner-invalid",
        )
        _check(
            type(backends) in (list, tuple)
            and 0 < len(backends) <= 16
            and len(set(backends)) == len(backends)
            and all(type(value) is str and identifier(value) for value in backends)
            and type(limit) is int
            and 0 < limit <= 100,
            "stage1-configuration-invalid",
            400,
        )
        self.intake, self.query_runner = intake, query_runner
        self.query_service = None
        self.backends, self.limit = list(backends), limit

    def _output(self, project_ref, relative):
        output = private_output(self.intake._path(project_ref, relative))
        # Core archives retain their full SHA filenames. Keep the host prefix
        # short instead of changing their evidence or relying on OS long paths.
        _check(
            os.name != "nt" or len(str(output)) <= 170, "stage1-private-root-too-deep"
        )
        return output

    def _init_offer(self, binding):
        basis = dict(_basis(binding), backends=self.backends, limit=self.limit)
        digest = sha(canonical(basis))
        return dict(
            basis,
            offer_ref="stage1-init-" + digest[:32],
            offer_sha256=digest,
            status="ready-for-offline-ledger-initialization",
            execution_authorized=False,
        )

    def _ledger(self, state, binding):
        run_ref = state.get("stage1_active")
        _check(run_ref is not None, "stage1-ledger-not-initialized")
        run = state["stage1_runs"][run_ref]
        _check(
            run["binding"] == _basis(binding), "stage1-ledger-source-version-differs"
        )
        if run.get("query_owned"):
            bound_run(self.intake, state, _basis(binding), run)
            _check(self.query_service is not None, "stage1-query-owner-unconnected")
            self.query_service.saved_frontier(state["project_ref"])
        ledger = CoverageLedger(self.intake._path(state["project_ref"], run["path"]))
        _check(
            sha((ledger.root / "run_manifest.json").read_bytes())
            == run["manifest_sha256"],
            "stage1-ledger-manifest-differs",
        )
        report = validate_run(ledger.root)
        _check(report["valid"], "stage1-ledger-replay-failed")
        if run.get("query_owned") and run.get("last_checkpoint") is not None:
            _check(
                any(
                    row["payload"]["kind"] == "Checkpoint"
                    and row["payload"]["event_id"] == run["last_checkpoint"]
                    for row in ledger.events()
                ),
                "stage1-query-checkpoint-reference-differs",
            )
        return run, ledger, report

    def _queries(self, run, ledger):
        coverage = ledger.coverage_state()
        _check(
            len(coverage.queries) <= MAX_QUERIES, "stage1-query-offer-bound-exceeded"
        )
        result = []
        for planned_id, query in coverage.queries.items():
            basis = dict(run_ref=run["run_ref"], binding=run["binding"], query=query)
            digest = sha(canonical(basis))
            starts = [
                row
                for row in coverage.starts.values()
                if row["operation"] == "search"
                and row["arguments"].get("coverage", {}).get("planned_query_id")
                == planned_id
                and row["arguments"]["coverage"].get("round_number") == coverage.active
            ]
            result.append(
                dict(
                    query_ref="stage1-query-" + digest[:32],
                    query_sha256=digest,
                    planned_query_id=planned_id,
                    purpose=query["purpose"],
                    cluster_id=query["cluster_id"],
                    family_id=query["family_id"],
                    query=query["query"],
                    year=query["year"],
                    status="intent-recorded-not-executed" if starts else "not-executed",
                    recorded_query_ids=[row["event_id"] for row in starts],
                    execution_available=False,
                )
            )
        return result

    def read(self, credential, project_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            result = dict(
                project_ref=project_ref,
                revision=state["revision"],
                input_version=state["input_version"],
                initialization_offer=None,
                ledger=None,
                queries=[],
                checkpoint=None,
                stage1_status="not-started",
                stage1_complete=False,
                canonical_package=None,
                query_execution_connected=False,
                query_runner_registered=self.query_runner is not None,
                execution_authorized=False,
                evaluation_status="not-scored",
                scientific_truth="not-evaluated",
                model_calls=None,
                source_acquisition_calls=None,
                monetary_cost=None,
                later_stages={
                    str(i): {"status": "planned", "connected": False}
                    for i in range(3, 7)
                },
            )
            current = self.intake.read(credential, project_ref)
            if not current.get("stage1_intake_ready"):
                result["stage1_status"] = "intake-not-ready"
                if state.get("stage1_active"):
                    result["stage1_status"] = "stale-input"
                return result
            binding = self.intake.binding(project_ref)
            result["initialization_offer"] = self._init_offer(binding)
            if not state.get("stage1_active"):
                return result
            saved = state["stage1_runs"][state["stage1_active"]]
            if saved["binding"] != _basis(binding):
                result["stage1_status"] = "stale-input"
                return result
            if saved.get("query_owned"):
                if self.query_service is None:
                    result["initialization_offer"] = None
                    result["stage1_status"] = "query-runtime-unconnected"
                    return result
                service = self.query_service.services.get(project_ref)
                if service is None:
                    result["initialization_offer"] = None
                    result["stage1_status"] = "owner-reopen-required"
                    return result
                else:
                    history = service.view(credential, project_ref)["history"]
                    pending = [row for row in history if row["status"] != "completed"]
                    if pending:
                        result["initialization_offer"] = None
                        result["stage1_status"] = (
                            "query-action-" + pending[-1]["status"]
                        )
                        return result  # Never replay files while an owned writer is active/unknown.
            run, ledger, report = self._ledger(state, binding)
            checkpoints = [
                row["payload"]
                for row in ledger.events()
                if row["payload"]["kind"] == "Checkpoint"
            ]
            latest = checkpoints[-1] if checkpoints else None
            gate, next_action = readiness(report)
            result.update(
                stage1_status="query-ledger-active"
                if run.get("query_owned")
                else "offline-ledger-active",
                initialization_offer=None,
                ledger=dict(
                    run_ref=run["run_ref"],
                    manifest_sha256=run["manifest_sha256"],
                    state_sha256=report["state_sha256"],
                    valid=report["valid"],
                    counts=report["counts"],
                    pending_actions=report["pending_actions"],
                    gate=gate,
                    next_allowed_action=next_action,
                    coverage=report.get("coverage"),
                    source_mode=ledger.manifest["mode"],
                ),
                queries=self._queries(run, ledger),
                checkpoint=None
                if latest is None
                else dict(
                    event_id=latest["event_id"],
                    state_sha256=latest["state_sha256"],
                    stage_result=deepcopy(latest["stage_result"]),
                    current=latest["state_sha256"] == report["state_sha256"],
                ),
            )
            from .project_stage1_coverage import offers, unresolved

            result["coverage_actions"] = offers(ledger, binding, run, report)
            result["coverage_actions"]["held"] = bool(
                unresolved(self, project_ref, principal, state["input_version"])
            )
            return result

    def offers(self, credential, project_ref):
        """Only inspect current source-bound choices; never initialize or pump."""
        return self.read(credential, project_ref)

    def history(self, credential, project_ref):
        return self.intake.history(credential, project_ref)

    def action(self, credential, project_ref, key):
        return self.intake.action(credential, key, project_ref=project_ref)

    def initialize(self, credential, project_ref, body, *, check_deadline=None):
        _fields(body, BODY_FIELDS | {"offer_ref", "offer_sha256"})
        _check(body["confirmed"] is True, "stage1-explicit-confirmation-required", 400)
        principal = self.intake._principal(credential)

        def work(state, request_hash, _):
            binding = self.intake.binding(project_ref)
            offer = self._init_offer(binding)
            _check(
                body["offer_ref"] == offer["offer_ref"]
                and body["offer_sha256"] == offer["offer_sha256"],
                "stage1-initialization-offer-differs",
            )
            prior = state.get("stage1_active")
            _check(
                not prior or state["stage1_runs"][prior]["binding"] != _basis(binding),
                "stage1-ledger-already-initialized",
            )
            relative = "s1-" + request_hash[:24]
            output = self._output(project_ref, relative)
            _check(not output.exists(), "stage1-ledger-output-requires-reconciliation")
            if check_deadline is not None:
                check_deadline()
            ledger = CoverageLedger.create(
                output,
                run_id="stage1-" + request_hash[:32],
                objective=self.intake.brief_binding(
                    project_ref, require_confirmed=True
                )["brief"]["original_description"],
            )
            ledger.bind_plan(
                binding["plan_root"], backends=self.backends, limit=self.limit
            )
            _check(
                len(ledger.coverage_state().queries) <= MAX_QUERIES,
                "stage1-query-offer-bound-exceeded",
            )
            ledger.open_round()
            report = validate_run(output)
            _check(report["valid"], "stage1-initialization-replay-failed")
            run_ref = "stage1-run-" + request_hash[:32]
            run = dict(
                run_ref=run_ref,
                path=relative,
                binding=_basis(binding),
                manifest_sha256=sha((output / "run_manifest.json").read_bytes()),
            )
            state.setdefault("stage1_runs", {})[run_ref] = run
            state["stage1_active"] = run_ref
            return dict(
                run_ref=run_ref,
                ledger_manifest_sha256=run["manifest_sha256"],
                ledger_state_sha256=report["state_sha256"],
                stage1_status="offline-ledger-active",
                stage1_complete=False,
                query_execution_connected=False,
                evaluation_status="not-scored",
            )

        return self.intake._perform(
            principal,
            project_ref,
            "stage1-initialize",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def _mutate(
        self,
        credential,
        project_ref,
        body,
        kind,
        producer,
        *,
        fields=(),
        preflight=None,
        check_deadline=None,
        run_authorization=None,
    ):
        _fields(body, BODY_FIELDS | {"ledger_state_sha256"} | set(fields))
        _check(
            (
                body["confirmed"] is True
                if run_authorization is None
                else body["confirmed"] is False
            )
            and _hash(body["ledger_state_sha256"]),
            "stage1-action-binding-invalid",
            400,
        )
        principal = self.intake._principal(credential)
        if run_authorization is not None:
            from .project_run_authority import RunActionGuard

            _check(
                kind in {"stage1-checkpoint", "stage1-deliver"},
                "stage1-run-saved-operation-invalid",
            )
            guard = RunActionGuard(
                self.intake,
                principal,
                project_ref,
                body,
                run_authorization,
                operation="records" if kind == "stage1-checkpoint" else "delivery",
                action=kind,
            )
            body = guard.request
            check_deadline = guard.deadline_check(check_deadline)

        def reserve(state, _, actor):
            from .project_stage1_coverage import unresolved

            _check(
                not unresolved(self, project_ref, actor, state["input_version"]),
                "stage1-coverage-write-outcome-unobserved",
            )
            if preflight is None:
                return
            binding = self.intake.binding(project_ref)
            run, ledger, report = self._ledger(state, binding)
            _check(
                report["state_sha256"] == body["ledger_state_sha256"],
                "stage1-ledger-state-stale",
            )
            if run.get("query_owned"):
                _check(self.query_service is not None, "stage1-query-owner-unconnected")
                frontier = self.query_service.saved_frontier(project_ref)
                _check(
                    frontier["state_sha256"] == report["state_sha256"],
                    "stage1-coverage-owner-state-differs",
                )
            if check_deadline is not None:
                check_deadline()
            preflight(state, run, ledger, report, actor)

        def work(state, request_hash, actor):
            binding = self.intake.binding(project_ref)
            run, ledger, report = self._ledger(state, binding)
            _check(
                report["state_sha256"] == body["ledger_state_sha256"],
                "stage1-ledger-state-stale",
            )
            if check_deadline is not None:
                check_deadline()
            if run.get("query_owned"):
                _check(self.query_service is not None, "stage1-query-owner-unconnected")
                if kind == "stage1-deliver":
                    return self.query_service.produce_saved(
                        project_ref,
                        state,
                        run,
                        ledger,
                        lambda owned: producer(state, run, owned, request_hash, actor),
                    )
                return self.query_service.mutate(
                    credential,
                    project_ref,
                    state,
                    run,
                    ledger,
                    request_hash,
                    kind,
                    lambda owned: producer(state, run, owned, request_hash, actor),
                )
            return producer(state, run, ledger, request_hash, actor)

        return self.intake._perform(
            principal,
            project_ref,
            kind,
            deepcopy(body),
            work,
            reserve=reserve,
            check_deadline=check_deadline,
        )

    def coverage(self, credential, project_ref, body, *, check_deadline=None):
        from .project_stage1_coverage import execute

        return execute(
            self, credential, project_ref, body, check_deadline=check_deadline
        )

    def plan_query(self, credential, project_ref, body, *, check_deadline=None):
        def producer(_, run, ledger, __, ___):
            query = next(
                (
                    row
                    for row in self._queries(run, ledger)
                    if row["query_ref"] == body["query_ref"]
                ),
                None,
            )
            _check(
                query is not None and query["query_sha256"] == body["query_sha256"],
                "stage1-query-offer-differs",
            )
            _check(query["status"] == "not-executed", "stage1-query-already-recorded")
            event_id = ledger.start_planned(query["planned_query_id"])
            return dict(
                query_ref=query["query_ref"],
                query_sha256=query["query_sha256"],
                query_event_id=event_id,
                query_status="intent-recorded-not-executed",
                ledger_state_sha256=ledger.state_hash(),
                query_execution_connected=False,
            )

        return self._mutate(
            credential,
            project_ref,
            body,
            "stage1-plan-query",
            producer,
            fields={"query_ref", "query_sha256"},
            check_deadline=check_deadline,
        )

    def execute_query(self, credential, project_ref, body, *, check_deadline=None):
        def refuse(_, run, ledger, __, ___):
            query = next(
                (
                    row
                    for row in self._queries(run, ledger)
                    if row["query_ref"] == body["query_ref"]
                ),
                None,
            )
            _check(
                query is not None and query["query_sha256"] == body["query_sha256"],
                "stage1-query-offer-differs",
            )
            # A callable alone proves neither authority nor native/tool receipts.
            # No I/O may occur until the sealed execution adapter is integrated.
            _check(False, "stage1-query-execution-unconnected")

        return self._mutate(
            credential,
            project_ref,
            body,
            "stage1-execute-query",
            refuse,
            fields={"query_ref", "query_sha256"},
            check_deadline=check_deadline,
        )

    def screen(self, credential, project_ref, body, *, check_deadline=None):
        """Save an explicit user's selection; source and scientific states stay separate."""
        _fields(
            body,
            BODY_FIELDS | {"ledger_state_sha256", "work_ref", "decision", "rationale"},
        )
        identifier(body["work_ref"])
        _check(
            body["decision"] in {"include", "exclude", "pending"},
            "stage1-screening-decision-invalid",
            400,
        )
        rationale = _text(body["rationale"])

        def producer(_state, _run, ledger, _request_hash, actor):
            candidate = ledger.candidates().get(body["work_ref"])
            _check(candidate is not None, "stage1-screening-work-unavailable", 404)
            discovery = candidate["discoveries"][-1]
            event = ledger.decide(
                body["work_ref"],
                body["decision"],
                reason="researcher-screening",
                rationale=rationale,
                evidence_refs=[discovery["source_ref"]],
                actor=actor,
                authorization={"input": rationale, "state_sha256": ledger.state_hash()},
            )
            return dict(
                work_ref=body["work_ref"],
                decision_event_id=event,
                decision=body["decision"],
                ledger_state_sha256=ledger.state_hash(),
                scientific_acceptance=False,
                stage1_complete=False,
            )

        return self._mutate(
            credential,
            project_ref,
            body,
            "stage1-screen",
            producer,
            fields={"work_ref", "decision", "rationale"},
            check_deadline=check_deadline,
        )

    def checkpoint(
        self,
        credential,
        project_ref,
        body,
        *,
        check_deadline=None,
        run_authorization=None,
    ):
        def producer(state, run, ledger, _, __):
            event = ledger.checkpoint()
            result = deepcopy(event["stage_result"])
            state["stage1_runs"][run["run_ref"]]["last_checkpoint"] = event["event_id"]
            return dict(
                checkpoint_event_id=event["event_id"],
                ledger_state_sha256=event["state_sha256"],
                gate=result["gate"],
                next_allowed_action=result["next_allowed_action"],
                stage_result=result,
                stage1_complete=False,
                canonical_package=None,
                evaluation_status="not-scored",
            )

        return self._mutate(
            credential,
            project_ref,
            body,
            "stage1-checkpoint",
            producer,
            check_deadline=check_deadline,
            run_authorization=run_authorization,
        )

    def export(self, credential, project_ref, body, *, check_deadline=None):
        def producer(state, run, ledger, request_hash, _):
            relative = "s1x-" + request_hash[:24]
            output = self._output(project_ref, relative)
            _check(not output.exists(), "stage1-export-output-requires-reconciliation")
            report = export_run(ledger.root, output)
            _check(report["valid"], "stage1-export-replay-failed")
            report = validate_export(output)
            _check(report["valid"], "stage1-export-replay-failed")
            digest = sha((output / "export_manifest.json").read_bytes())
            ref = "stage1-export-" + digest[:32]
            state.setdefault("stage1_exports", {})[ref] = dict(
                path=relative,
                manifest_sha256=digest,
                run_ref=run["run_ref"],
                source_state_sha256=report["source_state_sha256"],
            )
            return dict(
                artifact_ref=ref,
                manifest_sha256=digest,
                source_state_sha256=report["source_state_sha256"],
                artifact_kind="Stage1ExportManifest",
                evaluation_status="not-scored",
                canonical_package=None,
                stage1_complete=False,
            )

        return self._mutate(
            credential,
            project_ref,
            body,
            "stage1-export",
            producer,
            check_deadline=check_deadline,
        )
