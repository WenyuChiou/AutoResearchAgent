"""Read-only owner inspector for pending Stage 1 producer work."""

from copy import deepcopy

from .project_agent_analysis import ProjectStage1AnalysisService
from .project_model import ANALYZE_OPERATION, ProjectModelService, _output_ref
from .project_stage1 import ProjectStage1Service
from .project_stage1_records import ProjectStage1RecordsService
from .project_stage1_source_service import ProjectStage1SourceService
from .project_stage1_sources import source_record
from .session_api import SessionApiError
from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical, decode


TRACKED = {
    "stage1-agent-analysis",
    "stage1-agent-coverage",
    "stage1-reading-registry",
    "stage1-source-registry",
}


def _check(condition, code="stage1-producer-queue-invalid"):
    if not condition:
        raise SessionApiError(code)


def _selection(operation, body):
    return dict(operation=operation, body=deepcopy(body))


class ProjectStage1ProducerQueue:
    """Project current producer needs without granting or executing authority."""

    def __init__(self, stage1, models, records, sources=None):
        _check(
            isinstance(stage1, ProjectStage1Service)
            and isinstance(models, ProjectModelService)
            and isinstance(records, ProjectStage1RecordsService)
            and records is models.reading_records
            and records.delivery.stage1 is stage1
            and stage1.intake is models.intake is records.intake
            and (
                sources is None
                or (
                    isinstance(sources, ProjectStage1SourceService)
                    and sources.stage1 is stage1
                    and sources.intake is stage1.intake
                )
            ),
            "stage1-producer-queue-composition-differs",
        )
        self.stage1, self.models, self.records, self.sources = (
            stage1,
            models,
            records,
            sources,
        )
        self.intake = stage1.intake
        self.analysis = ProjectStage1AnalysisService(stage1, models, records)

    @staticmethod
    def _view(binding, state_hash, status, action, remaining, blocked):
        return dict(
            kind="ProjectStage1ProducerQueue",
            schema_version="1.0.0",
            binding=deepcopy(binding),
            ledger_state_sha256=state_hash,
            status=status,
            next_action=None
            if action is None
            else dict(
                phase_id=action["phase"],
                target=action["target"],
                reason=action["reason"][:256],
            ),
            remaining_work_count=remaining,
            blocked_work_count=blocked,
            research_complete=False,
        )

    def _actions(self, principal, ref, binding):
        rows = self.intake.db.execute(
            "SELECT key,request_hash,receipt FROM intake_actions "
            "WHERE principal=? AND project=? ORDER BY rowid",
            (principal, ref),
        ).fetchall()
        saved, unresolved = [], []
        for row in rows:
            receipt = decode(row["receipt"].encode(), "producer queue action")
            if receipt.get("kind") not in TRACKED:
                continue
            request = receipt.get("request")
            _check(
                type(request) is dict
                and receipt.get("key") == row["key"]
                and receipt.get("project_ref") == ref
                and row["request_hash"]
                == receipt.get("request_sha256")
                == sha(canonical({"kind": receipt["kind"], "body": request})),
                "stage1-producer-action-differs",
            )
            current = all(
                type(request.get(key)) is type(binding[key])
                and request.get(key) == binding[key]
                for key in ("input_version", "brief_sha256")
            )
            if not current:
                continue
            if receipt.get("status") == "saved":
                saved.append(receipt)
            else:
                unresolved.append(receipt)
        return saved, unresolved

    @staticmethod
    def _model_work(state, job):
        if type(job.get("work_ref")) is str:
            return job["work_ref"]
        offer = state["model_operations"]["offers"].get(job.get("offer_ref"))
        return None if offer is None else offer.get("context", {}).get("work_ref")

    @staticmethod
    def _task(phase, operation, body, reason, target=None):
        return dict(
            phase=phase,
            target=operation if target is None else target,
            reason=reason,
            selection=_selection(operation, body),
        )

    @staticmethod
    def _blocked(phase, reason):
        return dict(phase=phase, target="history", reason=reason, selection=None)

    def inspect(self, credential, ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, ref)
            trusted = self.intake.binding(ref)
            run, ledger, report = self.stage1._ledger(state, trusted)
            binding = dict(
                project_ref=ref,
                revision=state["revision"],
                input_version=trusted["input_version"],
                brief_sha256=trusted["brief_sha256"],
            )
            state_hash = report["state_sha256"]
            _check(state_hash == ledger.state_hash(), "stage1-producer-ledger-differs")
            saved, unresolved = self._actions(principal, ref, binding)
            if unresolved:
                action = self._blocked(
                    "reading", "producer-current-action-reconciliation-required"
                )
                return dict(
                    view=self._view(binding, state_hash, "held", action, 1, 1),
                    selection=None,
                )

            context = self.records._context(ref, state_hash)
            entries = self.records._entries(context)
            source_entries = [
                row["payload"]
                for row in entries
                if row["ref"].startswith("stage1-source-registry-")
            ]
            for entry in source_entries:
                source_record(ledger, self.records.root, entry)
            readiness = self.records.reading_readiness(
                credential, ref, expected_ledger_state_sha256=state_hash
            )
            if readiness["status"] == "held":
                action = self._blocked("reading", readiness["reason"])
                return dict(
                    view=self._view(binding, state_hash, "held", action, 1, 1),
                    selection=None,
                )
            missing_readings = {
                (row["work_ref"], row["version_id"])
                for row in readiness["missing_works"]
            }

            candidates = ledger.candidates()
            evidence = ledger.coverage_state().evidence
            decisions, reviews = evidence.decisions, evidence.current()
            model_state = state.get("model_operations", {})
            all_jobs = model_state.get("jobs", {})
            all_offers = model_state.get("offers", {})
            _check(
                type(all_jobs) is dict and type(all_offers) is dict,
                "stage1-producer-model-history-invalid",
            )
            public_offers = self.models.offers(credential, ref)["offers"]
            source_view = (
                None if self.sources is None else self.sources.read(credential, ref)
            )
            tasks, blocked, undecided = [], [], []

            for work in sorted(candidates):
                candidate = candidates[work]
                decision = decisions.get(work)
                if decision is None:
                    undecided.append(work)
                    continue
                version = (
                    reviews[work]["version_id"]
                    if work in reviews
                    else candidate["discoveries"][-1]["version_id"]
                )
                adoptions = [
                    row
                    for row in saved
                    if row["kind"] == "stage1-agent-analysis"
                    and row.get("reading", {}).get("work_id") == work
                    and row.get("reading", {}).get("version_id") == version
                ]
                if decision["new_decision"] == "exclude" and not adoptions:
                    continue

                sources = [
                    row
                    for row in source_entries
                    if row.get("work_id") == work and row.get("version_id") == version
                ]
                if not sources:
                    if source_view is None:
                        blocked.append(
                            self._blocked(
                                "reading", "producer-source-service-unconnected"
                            )
                        )
                        continue
                    source_jobs = [
                        row
                        for row in source_view["jobs"].values()
                        if row["work_ref"] == work
                        and row["input_version"] == binding["input_version"]
                        and row["brief_sha256"] == binding["brief_sha256"]
                    ]
                    if source_jobs:
                        if any(
                            row["saved_status"] == "source-observation-saved"
                            for row in source_jobs
                        ):
                            blocked.append(
                                self._blocked(
                                    "reading",
                                    "producer-source-registry-reconciliation-required",
                                )
                            )
                        else:
                            blocked.append(
                                self._blocked(
                                    "reading", "producer-source-observation-terminal"
                                )
                            )
                        continue
                    grants = [
                        row
                        for row in source_view["grants"].values()
                        if row["work_ref"] == work
                        and row["input_version"] == binding["input_version"]
                        and row["brief_sha256"] == binding["brief_sha256"]
                    ]
                    if grants:
                        grant = grants[-1]
                        if grant["status"] == "authorized":
                            tasks.append(
                                self._task(
                                    "reading",
                                    "source-execute",
                                    {
                                        "grant_ref": grant["grant_ref"],
                                        "grant_sha256": grant["grant_sha256"],
                                    },
                                    "producer-source-execution-required",
                                )
                            )
                        else:
                            blocked.append(
                                self._blocked(
                                    "reading", "producer-source-grant-unresolved"
                                )
                            )
                        continue
                    try:
                        offer = self.sources.offers(credential, ref, work)
                    except SessionApiError:
                        blocked.append(
                            self._blocked("reading", "producer-source-unavailable")
                        )
                    else:
                        tasks.append(
                            self._task(
                                "reading",
                                "source-authorize",
                                {
                                    "work_ref": work,
                                    "offer_ref": offer["offer_ref"],
                                    "offer_sha256": offer["offer_sha256"],
                                },
                                "producer-source-authorization-required",
                            )
                        )
                    continue

                matching_jobs = [
                    job
                    for job in all_jobs.values()
                    if job.get("operation") == ANALYZE_OPERATION
                    and self._model_work(state, job) == work
                    and type(job.get("input_version")) is type(binding["input_version"])
                    and job.get("input_version") == binding["input_version"]
                    and job.get("brief_sha256") == binding["brief_sha256"]
                ]
                if not adoptions:
                    if matching_jobs:
                        ready = [
                            job
                            for job in matching_jobs
                            if job.get("status") == "content-review-pending"
                            and not job.get("retirement")
                            and not job.get("close_failure")
                            and type(job.get("analysis_draft")) is dict
                        ]
                        if len(ready) == 1 and len(matching_jobs) == 1:
                            output_ref = _output_ref(ready[0])
                            draft_sha256 = ready[0]["analysis_draft"]["sha256"]
                            try:
                                data = self.analysis._job(
                                    principal,
                                    ref,
                                    state,
                                    output_ref,
                                    draft_sha256,
                                )
                                self.models._guard(
                                    ref, data["offer"], allow_expired=True
                                )
                            except (
                                SessionApiError,
                                ValueError,
                                OSError,
                                KeyError,
                                TypeError,
                                UnicodeError,
                            ):
                                blocked.append(
                                    self._blocked(
                                        "reading",
                                        "producer-analysis-adoption-unavailable",
                                    )
                                )
                            else:
                                tasks.append(
                                    self._task(
                                        "reading",
                                        "analysis-adopt",
                                        {
                                            "output_ref": output_ref,
                                            "draft_sha256": draft_sha256,
                                        },
                                        "producer-analysis-adoption-required",
                                    )
                                )
                        else:
                            blocked.append(
                                self._blocked("reading", "producer-model-job-terminal")
                            )
                        continue
                    offers = [
                        row
                        for row in public_offers
                        if row.get("operation") == ANALYZE_OPERATION
                        and row.get("work_ref") == work
                        and row.get("input_version") == binding["input_version"]
                        and row.get("brief_sha256") == binding["brief_sha256"]
                    ]
                    if offers:
                        available = [
                            row for row in offers if row.get("available") is True
                        ]
                        if len(offers) == len(available) == 1:
                            row = available[0]
                            tasks.append(
                                self._task(
                                    "reading",
                                    "model-execute",
                                    {
                                        "offer_ref": row["offer_ref"],
                                        "offer_sha256": row["offer_sha256"],
                                    },
                                    "producer-model-execution-required",
                                )
                            )
                        else:
                            blocked.append(
                                self._blocked(
                                    "reading", "producer-model-offer-unavailable"
                                )
                            )
                        continue
                    preview = self.models.full_analysis_offer(
                        credential,
                        ref,
                        work,
                        expected_input_version=binding["input_version"],
                        expected_ledger_state_sha256=state_hash,
                    )
                    if preview["available"] is True:
                        tasks.append(
                            self._task(
                                "reading",
                                "model-authorize",
                                {
                                    "operation": ANALYZE_OPERATION,
                                    "work_ref": work,
                                    "snapshot_sha256": preview["snapshot_sha256"],
                                },
                                "producer-model-authorization-required",
                            )
                        )
                    else:
                        blocked.append(
                            self._blocked(
                                "reading",
                                preview["blocked_reason"]
                                or "producer-model-unavailable",
                            )
                        )
                    continue

                if len(adoptions) != 1:
                    blocked.append(
                        self._blocked("reading", "producer-analysis-adoption-ambiguous")
                    )
                    continue
                adoption = adoptions[0]
                reading = adoption["reading"]
                if reading.get("decision_event_id") != decision["event_id"]:
                    blocked.append(
                        self._blocked("reading", "producer-analysis-adoption-stale")
                    )
                    continue
                if (work, version) not in missing_readings:
                    continue
                if decision["new_decision"] != "include":
                    tasks.append(
                        self._task(
                            "reading",
                            "register-analysis",
                            {
                                "adoption_key": adoption["key"],
                                "adoption_request_sha256": adoption["request_sha256"],
                                "reading_sha256": adoption["reading_sha256"],
                            },
                            "producer-analysis-registration-required",
                        )
                    )
                    continue
                review = reviews.get(work)
                if review is None:
                    try:
                        data = self.analysis._job(
                            principal,
                            ref,
                            state,
                            adoption["output_ref"],
                            adoption["draft_sha256"],
                        )
                        supported = (
                            data["snapshot"]["schema_version"] == "1.1.0"
                            and data["proposal"]["schema_version"] == "1.1.0"
                            and sha(canonical(data["job"]))
                            == adoption["model_job_sha256"]
                            and sha(data["raw"]) == adoption["proposal_sha256"]
                        )
                    except (
                        SessionApiError,
                        ValueError,
                        OSError,
                        KeyError,
                        TypeError,
                        UnicodeError,
                    ):
                        supported = False
                    if supported:
                        tasks.append(
                            self._task(
                                "coverage",
                                "coverage-review",
                                {
                                    "adoption_key": adoption["key"],
                                    "adoption_request_sha256": adoption[
                                        "request_sha256"
                                    ],
                                },
                                "producer-coverage-review-required",
                            )
                        )
                    else:
                        blocked.append(
                            self._blocked(
                                "coverage",
                                "producer-coverage-analysis-version-unsupported",
                            )
                        )
                    continue
                coverage = [
                    row
                    for row in saved
                    if row["kind"] == "stage1-agent-coverage"
                    and row.get("reading", {}).get("work_id") == work
                    and row.get("reading", {}).get("version_id") == version
                    and row.get("reading", {}).get("review_event_id")
                    == review["event_id"]
                ]
                if len(coverage) == 1:
                    receipt = coverage[0]
                    tasks.append(
                        self._task(
                            "reading",
                            "register-coverage",
                            {
                                "adoption_key": receipt["key"],
                                "adoption_request_sha256": receipt["request_sha256"],
                                "reading_sha256": receipt["reading_sha256"],
                            },
                            "producer-coverage-registration-required",
                        )
                    )
                else:
                    blocked.append(
                        self._blocked(
                            "coverage", "producer-coverage-receipt-unavailable"
                        )
                    )

            if undecided:
                tasks.insert(
                    0,
                    self._task(
                        "screening",
                        "initialize-pending",
                        {"work_refs": undecided[:64]},
                        "producer-pending-initialization-required",
                    ),
                )
            priority = {
                "initialize-pending": 0,
                "analysis-adopt": 1,
                "coverage-review": 2,
                "register-analysis": 3,
                "register-coverage": 3,
                "source-execute": 4,
                "model-execute": 5,
                "source-authorize": 6,
                "model-authorize": 7,
            }
            tasks.sort(key=lambda row: priority[row["selection"]["operation"]])
            remaining = (
                len(undecided) + len(tasks) - (1 if undecided else 0) + len(blocked)
            )
            terminal = next(
                (
                    row
                    for row in blocked
                    if row["reason"]
                    in {
                        "producer-model-job-terminal",
                        "producer-analysis-adoption-unavailable",
                        "producer-analysis-adoption-ambiguous",
                        "producer-analysis-adoption-stale",
                        "producer-coverage-analysis-version-unsupported",
                    }
                ),
                None,
            )
            chosen = terminal or (
                tasks[0] if tasks else blocked[0] if blocked else None
            )
            status = (
                "held"
                if terminal
                else "ready"
                if tasks
                else "held"
                if blocked
                else "idle"
            )
            return dict(
                view=self._view(
                    binding, state_hash, status, chosen, remaining, len(blocked)
                ),
                selection=(
                    None if chosen is None or status == "held" else chosen["selection"]
                ),
            )
