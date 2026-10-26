"""Adapt the existing full-analysis/adoption/registration owners, not a new engine."""

from copy import deepcopy
import json

from stage1_deliverable.common import canonical, private_output, sha
from .project_agent_analysis import ProjectStage1AnalysisService
from .project_full_analysis import ANALYZE_OPERATION, full_analysis_draft
from .project_resource_budget import resource_view
from .project_stage1 import _basis
from .project_stage1_delivery import MAX_RECORD_BYTES
from .project_stage1_producer_queue import ProjectStage1ProducerQueue
from .project_stage1_run_grant import ProjectStage1RunGrantService
from .session_api import _check, _hash


def full_analysis_projection(raw, snapshot):
    """Replay the original validator, then retain every field while flattening."""
    proposal = full_analysis_draft(raw, snapshot)
    reading = proposal["reading"]
    metadata = snapshot["reading_input"]["saved_reading"]
    claims = []
    for claim in proposal["claims"]:
        span = reading["evidence"][claim["evidence_index"]]
        claims.append(
            dict(
                text=claim["claim_text"],
                relation=claim["relation"],
                **{
                    k: deepcopy(span[k])
                    for k in (
                        "source_id",
                        "text_sha256",
                        "start_byte",
                        "end_byte",
                        "quote",
                    )
                },
                assessment=deepcopy(claim["assessment"]),
                claim_key=claim["claim_key"],
                section=claim["section"],
            )
        )
    return dict(
        kind="Stage1FullAnalysisRootProjection",
        schema_version="1.0.0",
        snapshot_sha256=proposal["snapshot_sha256"],
        work_id=proposal["work_id"],
        version_id=proposal["version_id"],
        summary=reading["summary"],
        classification=deepcopy(reading["classification"]),
        findings=deepcopy(reading["findings"]),
        limitations=deepcopy(reading["limitations"]),
        claims=claims,
        decision=proposal["screening"]["decision"],
        rationale=proposal["screening"]["rationale"],
        reason_code=proposal["screening"]["reason_code"],
        questions=deepcopy(reading["open_questions"]),
        missing_information=deepcopy(proposal["screening"]["missing_information"]),
        coverage=deepcopy(proposal.get("coverage")),
        source_failures=deepcopy(metadata["source_failures"]),
        original_source_scopes=[
            dict(
                source_id=row["source_id"],
                source_observation_scope=deepcopy(row["source_observation_scope"]),
            )
            for row in metadata["sources"]
        ],
        full_analysis=proposal,
        entire_extracted_text_supplied=True,
        semantic_projection_complete=True,
        publication_completeness_verified=False,
        paper_figures_verified=False,
        human_acceptance=False,
        scientific_acceptance=False,
    )


def full_analysis_note(projection):
    """Preserve the full validated result and every original locator and reason."""
    raw = (
        "# Saved full-source analysis\n\n"
        "AI proposal; human/scientific acceptance: false.\n"
        "Scope: all admitted extracted UTF-8 text; publication and figures unverified.\n\n"
        + json.dumps(projection, ensure_ascii=False, indent=2)
        + "\n"
    ).encode("utf8")
    _check(len(raw) <= MAX_RECORD_BYTES, "full-source-note-too-large")
    return raw


class ProjectStage1FullSourceAdapter:
    """One trusted existing-host binding; creates no consent or model permission."""

    def __init__(
        self, host, credential, ref, *, run_grants, grant_ref, grant_sha256, output_root
    ):
        _check(
            type(run_grants) is ProjectStage1RunGrantService
            and run_grants.intake is host.projects
            and getattr(host, "project_stage1_execution", None) is None
            and getattr(host.project_models, "automatic_stage1", None) is None,
            "full-source-original-run-owner-required",
        )
        self.host, self.intake, self.ref = host, host.projects, ref
        self.issuer, self.grant_ref, self.grant_sha256 = (
            run_grants,
            grant_ref,
            grant_sha256,
        )
        self.principal = self.intake._principal(credential)
        self.models, self.records = host.project_models, host.project_stage1_records
        self.analysis = ProjectStage1AnalysisService(
            host.project_stage1, self.models, self.records
        )
        self.queue = ProjectStage1ProducerQueue(
            host.project_stage1, self.models, self.records, host.project_stage1_sources
        )
        _check(
            self.models.run_grants is run_grants, "full-source-model-run-owner-differs"
        )
        self.root = private_output(output_root).resolve()
        _check(
            self.root.is_dir()
            and not self.root.is_relative_to(self.intake.root)
            and not self.intake.root.is_relative_to(self.root),
            "full-source-output-root-invalid",
        )
        document = self._binding(credential, ref, active=True)[1]
        _check(
            {ANALYZE_OPERATION, "agent-adoption", "records"}
            <= set(document["operations"]),
            "full-source-run-operations-not-authorized",
        )

    def _binding(self, credential, ref, *, active=False):
        actor = self.intake._principal(credential)
        _check(
            actor == self.principal and ref == self.ref, "full-source-project-differs"
        )
        state, document = self.issuer._document(
            actor, ref, self.grant_ref, self.grant_sha256
        )
        _check(
            document["binding"] == self.issuer._binding(state),
            "full-source-original-run-binding-changed",
        )
        if active:
            self.issuer.inspect(credential, ref, self.grant_ref, self.grant_sha256)
        return state, document

    def _saved(self, credential, ref):
        """Reopen completed jobs/adoptions; never serialize future model prompts."""
        state, document = self._binding(credential, ref)
        binding = self.intake.binding(ref)
        run, ledger, report = self.host.project_stage1._ledger(state, binding)
        context = self.records._context(ref, report["state_sha256"])
        entries = self.records._entries(context)
        saved, unresolved = self.queue._actions(self.principal, ref, binding)
        adopted = []
        for receipt in saved:
            request = receipt["request"]
            if receipt["kind"] != "stage1-agent-analysis":
                continue
            data = self.analysis._job(
                self.principal,
                ref,
                state,
                receipt["output_ref"],
                receipt["draft_sha256"],
            )
            # Adoption changes the decision/claim frontier intentionally. Reuse
            # its post-mutation guard: the saved job, owner, permit, brief,
            # budget and every physical source must remain exact. Comparing a
            # newly generated pre-adoption prompt would reject our own append.
            facts = self.analysis._sources(ledger, entries, data["metadata"])
            self.analysis._stable(
                self.principal,
                ref,
                state,
                ledger,
                dict(
                    data=data,
                    output_ref=receipt["output_ref"],
                    draft_sha256=receipt["draft_sha256"],
                    entries=entries,
                    facts=facts,
                ),
                lambda: None,
            )
            _check(
                receipt["request_sha256"]
                == sha(canonical({"kind": receipt["kind"], "body": request}))
                and receipt["model_job_sha256"] == sha(canonical(data["job"]))
                and receipt["model_request_sha256"] == data["job"]["request_sha256"]
                and receipt["proposal_sha256"] == sha(data["raw"])
                and receipt["reading_sha256"] == sha(canonical(receipt["reading"])),
                "full-source-saved-adoption-differs",
            )
            adopted.append(
                (receipt, full_analysis_projection(data["raw"], data["snapshot"]))
            )
        _check(len(ledger.candidates()) <= 512, "full-source-work-bound")
        return (
            state,
            binding,
            run,
            ledger,
            report,
            adopted,
            document,
            entries,
            unresolved,
            saved,
        )

    def _registration_reading(self, adoption, saved, ledger):
        """Follow only the exact saved coverage of this original adoption."""
        reading = adoption["reading"]
        coverage = [
            row
            for row in saved
            if row["kind"] == "stage1-agent-coverage"
            and row["request"].get("adoption_key") == adoption["key"]
            and row["request"].get("adoption_request_sha256")
            == adoption["request_sha256"]
        ]
        if not coverage:
            return reading, adoption["reading_sha256"]
        _check(len(coverage) == 1, "full-source-saved-coverage-ambiguous")
        coverage = coverage[0]
        expected = deepcopy(reading)
        expected["review_event_id"] = coverage["event_id"]
        _check(
            all(
                coverage[field] == adoption[field]
                for field in (
                    "output_ref",
                    "draft_sha256",
                    "proposal_sha256",
                    "model_job_sha256",
                )
            )
            and coverage["reading"] == expected
            and coverage["reading_sha256"] == sha(canonical(expected)),
            "full-source-saved-coverage-differs",
        )
        event = ledger.event(coverage["event_id"], "CoverageWorkReview")
        decision = ledger.event(reading["decision_event_id"], "DecisionEvent")
        _check(
            event["work_id"] == reading["work_id"]
            and event["version_id"] == reading["version_id"]
            and event["decision_event_id"] == reading["decision_event_id"]
            and event["assessor"] == "agent:" + self.principal
            and decision["new_decision"] == "include"
            and ledger.coverage_state().evidence.current().get(reading["work_id"])
            == event,
            "full-source-current-coverage-differs",
        )
        return expected, coverage["reading_sha256"]

    def read(self, credential, ref):
        with self.intake._lock:
            (
                state,
                binding,
                run,
                ledger,
                report,
                adopted,
                _,
                entries,
                unresolved,
                saved,
            ) = self._saved(credential, ref)
            readiness = self.records.reading_readiness(
                credential, ref, expected_ledger_state_sha256=report["state_sha256"]
            )
            readings = self.records._matching_readings(
                ledger,
                [
                    row["payload"]
                    for row in entries
                    if row["ref"].startswith("stage1-reading-registry-")
                ],
            )
            recorded, pending, notes = [], [], []
            for receipt, projection in adopted:
                reading, reading_sha256 = self._registration_reading(
                    receipt, saved, ledger
                )
                note = full_analysis_note(projection)
                row = dict(
                    work_id=reading["work_id"],
                    version_id=reading["version_id"],
                    decision=projection["decision"],
                    rationale=projection["rationale"],
                    decision_event_id=reading["decision_event_id"],
                    review_event_id=reading["review_event_id"],
                    note_sha256=sha(note),
                    semantic_projection_complete=True,
                    reading_registration_complete=bool(
                        readiness["status"] != "held"
                        and readings.get(reading["work_id"])
                        and sha(canonical(readings[reading["work_id"]][-1]))
                        == reading_sha256
                        and not any(
                            r["work_ref"] == reading["work_id"]
                            for r in readiness["missing_works"]
                        )
                    ),
                    processing_status="automatic-pending",
                    human_acceptance=False,
                    scientific_acceptance=False,
                )
                recorded.append(row)
                pending.append(dict(row, next_step="saved-full-analysis-follow-up"))
                notes.append(
                    dict(
                        work_id=reading["work_id"],
                        version_id=reading["version_id"],
                        sha256=sha(note),
                        url=f"/api/projects/{ref}/stage1/automatic-notes/{sha(note)}",
                    )
                )
            known = {(row["work_id"], row["version_id"]) for row in recorded}
            reviews = ledger.coverage_state().evidence.current()
            versions = {
                work: reviews[work]["version_id"]
                if work in reviews
                else candidate["discoveries"][-1]["version_id"]
                for work, candidate in ledger.candidates().items()
            }
            pending += [
                dict(
                    work_id=work,
                    version_id=version,
                    next_step="full-source-analysis-required",
                    automatic=True,
                )
                for work, version in sorted(versions.items())
                if (work, version) not in known
            ]
            jobs = [
                j
                for j in state.get("model_operations", {}).get("jobs", {}).values()
                if j["operation"] == ANALYZE_OPERATION
                and type(j["input_version"]) is type(binding["input_version"])
                and j["input_version"] == binding["input_version"]
                and j["brief_sha256"] == binding["brief_sha256"]
            ]
            return dict(
                kind="Stage1AutomaticProductionProgress",
                schema_version="1.1.0",
                execution_profile="existing-full-analysis-adopt-register",
                project_ref=ref,
                binding=_basis(binding),
                run_ref=run["run_ref"],
                ledger_state_sha256=report["state_sha256"],
                permit_sha256=self.grant_sha256,
                automatically_recorded=recorded,
                automatic_resolved=[],
                automatic_pending=pending,
                technical_blocked=(
                    []
                    if readiness["status"] != "held"
                    else [dict(reason=readiness["reason"])]
                )
                + [
                    dict(
                        reason="producer-current-action-reconciliation-required",
                        kind=row["kind"],
                        key=row["key"],
                        request_sha256=row["request_sha256"],
                        status=row["status"],
                    )
                    for row in unresolved
                ],
                researcher_questions=[
                    dict(
                        work_id=projection["work_id"],
                        version_id=projection["version_id"],
                        questions=deepcopy(projection["questions"]),
                        missing_information=deepcopy(projection["missing_information"]),
                    )
                    for _, projection in adopted
                    if projection["questions"] or projection["missing_information"]
                ],
                notes=notes,
                model_calls_reserved=len(jobs),
                model_units_completed=sum(
                    j["status"] == "content-review-pending" for j in jobs
                ),
                failed_or_unobserved=[
                    dict(key=j["key"], status=j["status"])
                    for j in jobs
                    if j["status"] != "content-review-pending"
                ],
                stage1_complete=False,
                scientific_acceptance=False,
                stage2_started=False,
            )

    def project_view(self, credential, ref):
        if ref != self.ref or self.intake._principal(credential) != self.principal:
            return None
        return self.read(credential, ref)

    def note_by_hash(self, credential, ref, digest):
        _check(_hash(digest), "full-source-note-hash-invalid", 400)
        with self.intake._lock:
            progress = self.read(credential, ref)
            for receipt, projection in self._saved(credential, ref)[5]:
                raw = full_analysis_note(projection)
                if sha(raw) == digest:
                    return dict(
                        work_id=receipt["reading"]["work_id"],
                        version_id=receipt["reading"]["version_id"],
                        execution_profile="existing-full-analysis-adopt-register",
                        note_ref="automatic-note-" + digest,
                        bytes=len(raw),
                        source_basis_sha256=projection["snapshot_sha256"],
                        sha256=digest,
                        text=raw.decode("utf8"),
                        binding=progress["binding"],
                        run_ref=progress["run_ref"],
                        ledger_state_sha256=progress["ledger_state_sha256"],
                        entire_extracted_text_supplied=True,
                        paper_figures_verified=False,
                        human_acceptance=False,
                        scientific_acceptance=False,
                        stage2_started=False,
                    )
        _check(False, "full-source-current-note-unavailable", 404)

    def preflight(self, credential, ref):
        """Explicit operator work; does not mint a permission or reservation."""
        with self.intake._lock:
            state, _ = self._binding(credential, ref, active=True)
            binding = self.intake.binding(ref)
            resources = resource_view(self.intake, state, self.principal)
            ledger = self.host.project_stage1._ledger(state, self.intake.binding(ref))[
                1
            ]
            jobs = [
                j
                for j in state.get("model_operations", {}).get("jobs", {}).values()
                if j["operation"] == ANALYZE_OPERATION
                and type(j["input_version"]) is type(binding["input_version"])
                and j["input_version"] == binding["input_version"]
                and j["brief_sha256"] == binding["brief_sha256"]
            ]
            observed = {
                (j["analysis_draft"]["work_id"], j["analysis_draft"]["version_id"])
                for j in jobs
                if j["status"] == "content-review-pending"
                and not j.get("retirement")
                and not j.get("close_failure")
                and isinstance(j.get("analysis_draft"), dict)
            }
            evidence = ledger.coverage_state().evidence
            reviews = evidence.current()
            saved, _ = self.queue._actions(self.principal, ref, binding)
            needed = 0
            for work, candidate in ledger.candidates().items():
                decision = evidence.decisions.get(work)
                version = (
                    reviews[work]["version_id"]
                    if work in reviews
                    else candidate["discoveries"][-1]["version_id"]
                )
                adopted = any(
                    row["kind"] == "stage1-agent-analysis"
                    and row.get("reading", {}).get("work_id") == work
                    and row.get("reading", {}).get("version_id") == version
                    for row in saved
                )
                # The original queue initializes undecided works to pending
                # before analysis in this same continuation; count them now.
                if (
                    decision is not None
                    and decision["new_decision"] == "exclude"
                    and not adopted
                ):
                    continue
                needed += (work, version) not in observed
            remaining = resources["remaining"]["model_calls"]
            return dict(
                required_call_lower_bound=needed,
                remaining_model_calls=remaining,
                feasible_by_call_lower_bound=needed <= remaining,
                whole_source_prompt_and_RPC_fit_not_guaranteed=True,
                resources=resources,
            )

    def _save_projection(self, credential, ref, result):
        progress = self.read(credential, ref)
        artifact = dict(
            kind="Stage1FullSourceNotesCompanion",
            schema_version="1.0.0",
            progress=progress,
            continuation_status=result["status"],
            continuation_reason=result.get("reason"),
            scientific_acceptance=False,
            stage2_started=False,
        )
        for _, projection in self._saved(credential, ref)[5]:
            note = full_analysis_note(projection)
            # Ancestry may have changed since trusted registration. Reuse the
            # fresh private-root guard before every source-bearing publication.
            destination = private_output(self.root / (sha(note) + ".md"))
            if destination.exists():
                _check(
                    destination.read_bytes() == note, "full-source-note-bytes-differ"
                )
            else:
                with destination.open("xb") as stream:
                    stream.write(note)
        raw = canonical(artifact) + b"\n"
        _check(len(raw) <= MAX_RECORD_BYTES, "full-source-companion-too-large")
        path = private_output(self.root / (sha(raw) + ".json"))
        if path.exists():
            _check(path.read_bytes() == raw, "full-source-companion-bytes-differ")
        else:
            with path.open("xb") as stream:
                stream.write(raw)
        return dict(
            path=str(path),
            bytes=len(raw),
            sha256=sha(raw),
            note_count=len(progress["notes"]),
        )

    def run(self, credential, ref, *, run_id, deadline, max_actions, **explicit):
        from .project_stage1_auto import ProjectStage1AutoDriver

        _check(
            all(value is None for value in explicit.values())
            or explicit
            == dict(
                run_grants=self.issuer,
                grant_ref=self.grant_ref,
                grant_sha256=self.grant_sha256,
            ),
            "full-source-explicit-run-binding-differs",
        )
        check = self.preflight(credential, ref)
        if not check["feasible_by_call_lower_bound"]:
            result = dict(
                status="partial",
                reason="remaining-model-call-budget-insufficient",
                action_count=0,
                actions=[],
                stage1_complete=False,
                scientific_acceptance=False,
                stage2_started=False,
            )
        else:
            result = ProjectStage1AutoDriver(self.host, credential, ref).run(
                run_id=run_id,
                deadline=deadline,
                max_actions=max_actions,
                run_grants=self.issuer,
                grant_ref=self.grant_ref,
                grant_sha256=self.grant_sha256,
            )
        result["full_source_preflight"] = check
        result["automatic_production"] = self.read(credential, ref)
        result["automatic_notes_companion"] = self._save_projection(
            credential, ref, result
        )
        return result
