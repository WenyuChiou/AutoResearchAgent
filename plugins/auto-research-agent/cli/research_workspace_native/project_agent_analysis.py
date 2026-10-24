"""Adopt saved analysis as agent observations; never replay a provider or accept science."""

from copy import deepcopy

from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_ledger.journal import decode

from .project_agent_mutation import mutate_agent
from .project_analysis_events import prepare_agent_events
from .project_analysis_reading import prepare_reading_record
from .project_full_analysis import ANALYZE_OPERATION, full_analysis_draft
from .project_intake_contract import BOUND_FIELDS, _fields
from .project_model import ProjectModelService, _output_ref, budget_digest
from .project_run_authority import RunActionGuard
from .project_stage1_claims import ProjectStage1ClaimService
from .project_stage1_sources import source_record
from .project_stage1_records import MAX_ENTRIES
from .session_api import SessionApiError, _check, _hash


class ProjectStage1AnalysisService:
    def __init__(self, stage1, models, records):
        _check(
            isinstance(models, ProjectModelService)
            and records is models.reading_records
            and records.delivery.stage1 is stage1
            and stage1.intake is models.intake is records.intake,
            "stage1-agent-analysis-composition-differs",
        )
        self.stage1, self.models, self.records = stage1, models, records
        self.intake = stage1.intake

    def _idle(self, credential, ref):
        view = self.models.read(credential, ref)
        _check(
            not view["active_jobs"]
            and not view["blocking_unknown_count"]
            and not any(
                k[0] == ref and worker.is_alive()
                for k, worker in self.models._workers.items()
            )
            and not any(k[0] == ref for k in self.models._providers),
            "stage1-agent-model-outcome-unobserved",
        )

    def _job(self, actor, ref, state, output_ref, draft_sha256):
        _check(
            _hash(output_ref) and _hash(draft_sha256),
            "stage1-agent-analysis-reference-invalid",
            400,
        )
        jobs = [
            j
            for j in state.get("model_operations", {}).get("jobs", {}).values()
            if _output_ref(j) == output_ref
        ]
        _check(len(jobs) == 1, "stage1-agent-analysis-output-unavailable")
        job = jobs[0]
        _check(
            job["operation"] == ANALYZE_OPERATION
            and job["status"] == "content-review-pending"
            and not job.get("retirement")
            and not job.get("close_failure")
            and job.get("analysis_draft", {}).get("sha256") == draft_sha256,
            "stage1-agent-analysis-output-unavailable",
        )
        offer = state["model_operations"]["offers"].get(job["offer_ref"])
        _check(
            offer is not None
            and offer["offer_sha256"]
            == job["offer_sha256"]
            == sha(canonical(offer["context"])),
            "stage1-agent-analysis-offer-differs",
        )
        context = offer["context"]
        snapshot = context["saved_reading"]
        _check(
            context["operation"] == ANALYZE_OPERATION
            and context["source_sha256"] == job["source_sha256"]
            and context["prompt_sha256"]
            == job["prompt_sha256"]
            == sha(offer["prompt"].encode("utf8"))
            and sha(canonical(snapshot))
            == context["snapshot_sha256"]
            == job["snapshot_sha256"],
            "stage1-agent-analysis-job-binding-differs",
        )
        folder = self.models._runtime_folder(actor, ref, job)
        raw = ProjectStage1ClaimService._raw(folder / "output.txt", job["raw_output"])
        proposal = full_analysis_draft(raw, snapshot)
        draft = ProjectStage1ClaimService._raw(
            folder / "analysis-draft.json", job["analysis_draft"]
        )
        ProjectStage1ClaimService._raw(
            folder / "provider-receipt.json", job["verified_receipt"]
        )
        _check(
            decode(draft, "saved analysis draft") == proposal
            and job["analysis_draft"]["snapshot_sha256"] == proposal["snapshot_sha256"]
            and (job["analysis_draft"]["work_id"], job["analysis_draft"]["version_id"])
            == (proposal["work_id"], proposal["version_id"]),
            "stage1-agent-analysis-draft-differs",
        )
        return dict(
            job=deepcopy(job),
            offer=deepcopy(offer),
            raw=raw,
            proposal=proposal,
            snapshot=snapshot,
            metadata=snapshot["reading_input"]["saved_reading"],
        )

    def _sources(self, ledger, entries, metadata):
        facts = []
        selected = {row["source_id"]: row for row in metadata["sources"]}
        for entry in entries:
            payload = entry["payload"]
            if (
                not entry["ref"].startswith("stage1-source-registry-")
                or payload["source_id"] not in selected
            ):
                continue
            _, sdk = source_record(ledger, self.records.root, payload)
            observed = selected[payload["source_id"]]
            finish = ledger.event(payload["finish_event_id"], "SourceReadFinished")
            _check(
                payload["work_id"] == metadata["work_id"]
                and payload["version_id"] == metadata["version_id"]
                and finish["text_ref"] == observed["text_ref"]
                and sdk["extracted_text_sha256"] == observed["text_sha256"],
                "stage1-agent-analysis-source-differs",
            )
            facts.append(
                dict(
                    source_id=payload["source_id"],
                    work_id=payload["work_id"],
                    version_id=payload["version_id"],
                    text_ref=deepcopy(finish["text_ref"]),
                    evidence_level=sdk["evidence_level"],
                    receipt_sha256=sdk["receipt_sha256"],
                )
            )
        _check(len(facts) == len(selected), "stage1-agent-analysis-source-set-differs")
        return facts

    def _stable(self, actor, ref, state, ledger, prepared, check):
        check()
        fresh = self._job(
            actor, ref, state, prepared["output_ref"], prepared["draft_sha256"]
        )
        _check(fresh == prepared["data"], "stage1-agent-analysis-job-changed")
        binding = self.intake.brief_binding(ref, require_confirmed=True)
        context = fresh["offer"]["context"]
        _check(
            binding["input_version"] == context["input_version"]
            and binding["brief_sha256"] == context["brief_sha256"]
            and binding["brief"] == context["brief"]
            and binding["settings"] == context["settings"]
            and budget_digest(binding) == context["budget_sha256"],
            "stage1-agent-analysis-input-changed",
        )
        registration = self.models._registrations.get(fresh["job"]["offer_ref"])
        _check(
            not self.models._closed
            and ref in self.models._owners
            and state["model_operations"].get("owner") == self.models._tokens.get(ref)
            and registration is not None
            and registration["project_ref"] == ref
            and sha(registration["path"].read_bytes()) == registration["permit_sha256"],
            "stage1-agent-analysis-owner-changed",
        )
        _check(
            self._sources(ledger, prepared["entries"], fresh["metadata"])
            == prepared["facts"],
            "stage1-agent-analysis-source-changed",
        )
        check()
        return fresh

    def _publication(self, context, reading):
        # Reuse the consumer's text/count and whole-entry limits, without Core IDs
        # being treated as evidence before their actual append and readback.
        try:
            self.records._reading_content(reading)
        except DeliverableError as exc:
            raise SessionApiError("stage1-agent-reading-publication-invalid") from exc
        self.records._entry(context, reading)
        _check(
            len(context[1].get("stage1_saved_registries", {})) < MAX_ENTRIES,
            "stage1-saved-registry-bound-exceeded",
        )

    def _preflight_publication(self, ledger, context, plan, metadata, prior):
        # These temporary IDs are never persisted or returned. One extra digit
        # conservatively bounds the original one-decision/one-event-per-claim
        # append sequence, including a decimal-width transition.
        digits = max(6, len(str(len(ledger.events()) + len(plan["claims"]) + 1))) + 1
        start = 10 ** (digits - 1)
        projected = prepare_reading_record(
            plan,
            metadata,
            decision_event_id=f"e{start}",
            claim_event_ids={
                row["claim_key"]: f"e{start + i}"
                for i, row in enumerate(plan["claims"], 1)
            },
            previous_claim_spans=prior,
            review_event_id=None,
        )
        self._publication(context, projected)

    def adopt(self, credential, ref, body, *, run_authorization, check_deadline=None):
        prepared = []
        self._idle(credential, ref)

        def preflight(state, run, ledger, report, actor, check):
            data = self._job(
                actor, ref, state, body["output_ref"], body["draft_sha256"]
            )
            self.models._guard(ref, data["offer"], allow_expired=True)
            rows = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                (actor, ref),
            ).fetchall()
            _check(
                not any(
                    (r := decode(row[0].encode(), "agent adoption"))["kind"]
                    == "stage1-agent-analysis"
                    and r["status"] == "saved"
                    and r["request"].get("output_ref") == body["output_ref"]
                    for row in rows
                ),
                "stage1-agent-analysis-already-adopted",
            )
            context = self.records._context(ref, report["state_sha256"])
            entries = self.records._entries(context)
            facts = self._sources(ledger, entries, data["metadata"])
            plan = prepare_agent_events(
                data["raw"],
                data["snapshot"],
                facts,
                actor=actor,
                method="saved-full-source-analysis-1.1",
                source_evidence=True,
            )
            prior = None
            sources = [
                r["payload"]
                for r in entries
                if r["ref"].startswith("stage1-source-registry-")
            ]
            required = {e["event_id"] for e in data["metadata"]["existing_claims"]}
            for entry in entries:
                value = entry["payload"]
                if (
                    entry["ref"].startswith("stage1-reading-registry-")
                    and (value["work_id"], value["version_id"])
                    == (plan["proposal"]["work_id"], plan["proposal"]["version_id"])
                    and {c["claim_id"] for c in value["claims"]} == required
                ):
                    self.records._reading(context, value, sources)
                    prior = deepcopy(value["claims"])
            if prior is None:
                prior = self.records.derive_reading_payload(
                    ref,
                    data["metadata"]["work_id"],
                    classification=plan["proposal"]["reading"]["classification"],
                    findings=plan["proposal"]["reading"]["findings"],
                    roles=[],
                    expected_ledger_state_sha256=report["state_sha256"],
                )["claims"]
            prepared.append(
                dict(
                    data=data,
                    output_ref=body["output_ref"],
                    draft_sha256=body["draft_sha256"],
                    entries=entries,
                    facts=facts,
                    plan=plan,
                    previous=prior,
                    context=context,
                )
            )
            self._stable(actor, ref, state, ledger, prepared[0], check)
            self._preflight_publication(ledger, context, plan, data["metadata"], prior)

        def produce(state, run, ledger, digest, actor, check):
            item = prepared[0]
            self._stable(actor, ref, state, ledger, item, check)
            plan = item["plan"]
            self._preflight_publication(
                ledger,
                item["context"],
                plan,
                item["data"]["metadata"],
                item["previous"],
            )
            decision = ledger.decide(**plan["decision_arguments"])
            actual = ledger.event(decision, "DecisionEvent")
            args = plan["decision_arguments"]
            _check(
                actual["subject_id"] == args["work_id"]
                and actual["new_decision"] == args["decision"]
                and actual["rationale"] == args["rationale"]
                and actual["reason_code"] == args["reason"]
                and actual["evidence_refs"] == args["evidence_refs"]
                and actual["actor_type"] == "agent"
                and actual["authorization"] is None,
                "stage1-agent-analysis-decision-differs",
            )
            claims = {}
            for row in plan["claims"]:
                check()
                event = ledger.claim(**row["arguments"])
                _check(
                    all(
                        ledger.event(event).get(k) == v
                        for k, v in row["arguments"].items()
                    ),
                    "stage1-agent-analysis-claim-differs",
                )
                claims[row["claim_key"]] = event
            review = (
                ledger.coverage_state()
                .evidence.current()
                .get(plan["proposal"]["work_id"])
            )
            reading = prepare_reading_record(
                plan,
                item["data"]["metadata"],
                decision_event_id=decision,
                claim_event_ids=claims,
                previous_claim_spans=item["previous"],
                review_event_id=None if review is None else review["event_id"],
            )
            self._publication(item["context"], reading)
            self._stable(actor, ref, state, ledger, item, check)
            return dict(
                output_ref=body["output_ref"],
                draft_sha256=body["draft_sha256"],
                proposal_sha256=sha(item["data"]["raw"]),
                model_request_sha256=item["data"]["job"]["request_sha256"],
                model_job_sha256=sha(canonical(item["data"]["job"])),
                decision_event_id=decision,
                claim_event_ids=claims,
                analysis_plan_sha256=sha(canonical(plan)),
                reading=reading,
                reading_sha256=sha(canonical(reading)),
                ledger_state_sha256=ledger.state_hash(),
                actor_type="agent",
                human_per_action_confirmation=False,
                scientific_acceptance=False,
                stage1_complete=False,
                reading_registration_complete=False,
            )

        return mutate_agent(
            self.stage1,
            credential,
            ref,
            body,
            produce,
            run_authorization=run_authorization,
            kind="stage1-agent-analysis",
            fields={"output_ref", "draft_sha256"},
            preflight=preflight,
            check_deadline=check_deadline,
        )

    def register(
        self, credential, ref, body, *, run_authorization, check_deadline=None
    ):
        return self._register_adoption(
            credential,
            ref,
            body,
            adoption_kind="stage1-agent-analysis",
            run_authorization=run_authorization,
            check_deadline=check_deadline,
        )

    def _register_adoption(
        self,
        credential,
        ref,
        body,
        *,
        adoption_kind,
        run_authorization,
        check_deadline=None,
    ):
        # Only trusted Python services select the durable receipt kind; the
        # caller body and typed run authority remain exact and unchanged.
        _check(
            adoption_kind in {"stage1-agent-analysis", "stage1-agent-coverage"},
            "stage1-agent-adoption-kind-invalid",
        )
        # A separate action after adoption commit; never nest intake transactions.
        _fields(
            body,
            BOUND_FIELDS
            | {
                "confirmed",
                "ledger_state_sha256",
                "adoption_key",
                "adoption_request_sha256",
                "reading_sha256",
            },
        )
        actor = self.intake._principal(credential)
        guard = RunActionGuard(
            self.intake,
            actor,
            ref,
            body,
            run_authorization,
            operation="records",
            action="stage1-agent-reading",
        )
        check = guard.deadline_check(check_deadline)
        with self.intake._lock:
            row = self.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (actor, ref, body["adoption_key"]),
            ).fetchone()
            _check(
                row is not None and row[0] == body["adoption_request_sha256"],
                "stage1-agent-adoption-missing",
            )
            saved = decode(row[1].encode(), "saved analysis adoption")
            _check(
                saved["kind"] == adoption_kind
                and saved["status"] == "saved"
                and saved["request_sha256"]
                == row[0]
                == sha(canonical({"kind": saved["kind"], "body": saved["request"]}))
                and saved["reading_sha256"]
                == body["reading_sha256"]
                == sha(canonical(saved["reading"]))
                and saved["ledger_state_sha256"] == body["ledger_state_sha256"],
                "stage1-agent-adoption-binding-differs",
            )

            def recheck():
                check()
                self._idle(credential, ref)
                current = self.intake._load(actor, ref)
                data = self._job(
                    actor, ref, current, saved["output_ref"], saved["draft_sha256"]
                )
                _check(
                    sha(canonical(data["job"])) == saved["model_job_sha256"]
                    and sha(data["raw"]) == saved["proposal_sha256"],
                    "stage1-agent-adoption-job-changed",
                )
                check()

            # register_reading revalidates every physical source, all claims and
            # the exact post-adoption frontier before its own durable publication.
            result = self.records.register_reading(
                ref,
                reading=saved["reading"],
                expected_ledger_state_sha256=body["ledger_state_sha256"],
                check_current=recheck,
            )
            return dict(
                registry_entry=result,
                adoption_key=body["adoption_key"],
                authority=deepcopy(guard.request["run_authority"]),
                actor_type="agent",
                scientific_acceptance=False,
                stage1_complete=False,
            )
