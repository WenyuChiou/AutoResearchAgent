"""Agent coverage observations from a saved canonical analysis, never acceptance."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha
from stage1_ledger.journal import decode

from .project_agent_analysis import ProjectStage1AnalysisService
from .project_agent_mutation import mutate_agent
from .project_analysis_events import prepare_agent_events
from .project_stage1_coverage import offers, prepare
from .session_api import _check, _hash


class ProjectAgentCoverageService:
    def __init__(self, analysis):
        _check(
            type(analysis) is ProjectStage1AnalysisService,
            "stage1-agent-coverage-composition-differs",
        )
        self.analysis = analysis
        self.stage1, self.intake = analysis.stage1, analysis.intake
        self.models, self.records = analysis.models, analysis.records

    def _prepare(self, actor, ref, state, run, ledger, report, body, check):
        _check(
            type(body["adoption_key"]) is str
            and _hash(body["adoption_request_sha256"]),
            "stage1-agent-coverage-adoption-invalid",
            400,
        )
        row = self.intake.db.execute(
            "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
            (actor, ref, body["adoption_key"]),
        ).fetchone()
        _check(
            row is not None and row[0] == body["adoption_request_sha256"],
            "stage1-agent-adoption-missing",
        )
        saved = decode(row[1].encode(), "saved canonical adoption")
        _check(
            saved["kind"] == "stage1-agent-analysis"
            and saved["status"] == "saved"
            and saved["request_sha256"]
            == row[0]
            == sha(canonical(dict(kind=saved["kind"], body=saved["request"])))
            and saved["reading_sha256"] == sha(canonical(saved["reading"])),
            "stage1-agent-adoption-binding-differs",
        )
        data = self.analysis._job(
            actor, ref, state, saved["output_ref"], saved["draft_sha256"]
        )
        _check(
            data["snapshot"]["schema_version"] == "1.1.0"
            and data["proposal"]["schema_version"] == "1.1.0"
            and sha(canonical(data["job"])) == saved["model_job_sha256"]
            and sha(data["raw"]) == saved["proposal_sha256"],
            "stage1-agent-coverage-analysis-version-differs",
        )
        context = self.records._context(ref, report["state_sha256"])
        entries = self.records._entries(context)
        facts = self.analysis._sources(ledger, entries, data["metadata"])
        plan = prepare_agent_events(
            data["raw"],
            data["snapshot"],
            facts,
            actor=actor,
            method="saved-full-source-analysis-1.1",
            source_evidence=True,
        )
        _check(
            sha(canonical(plan)) == saved["analysis_plan_sha256"]
            and set(saved["claim_event_ids"])
            == {r["claim_key"] for r in plan["claims"]},
            "stage1-agent-coverage-adoption-plan-differs",
        )
        decision = ledger.event(saved["decision_event_id"], "DecisionEvent")
        args = plan["decision_arguments"]
        _check(
            decision["subject_id"] == args["work_id"]
            and decision["new_decision"] == args["decision"] == "include"
            and decision["rationale"] == args["rationale"]
            and decision["reason_code"] == args["reason"]
            and decision["evidence_refs"] == args["evidence_refs"]
            and decision["actor_type"] == "agent"
            and decision["authorization"] is None,
            "stage1-agent-coverage-decision-differs",
        )
        ids = saved["claim_event_ids"]
        for claim in plan["claims"]:
            event = ledger.event(ids[claim["claim_key"]], "ClaimEvidence")
            _check(
                all(event.get(k) == v for k, v in claim["arguments"].items()),
                "stage1-agent-coverage-claim-differs",
            )
        offered = [
            r
            for r in offers(ledger, self.intake.binding(ref), run, report)["offers"]
            if r["operation"] == "review-work"
            and r["document"]["work_ref"] == plan["proposal"]["work_id"]
        ]
        _check(len(offered) == 1, "stage1-agent-coverage-work-not-offered")
        offered = offered[0]
        document = offered["document"]
        companion = data["snapshot"]["coverage_context"]
        _check(
            document["clusters"] == companion["clusters"]
            and document["decision_event_id"] == saved["decision_event_id"]
            and document["candidate_event_id"] == data["metadata"]["candidate_event_id"]
            and document["version_id"] == data["metadata"]["version_id"]
            and ledger.candidates()[document["work_ref"]]["identity_status"]
            == companion["candidate_identity_status"],
            "stage1-agent-coverage-current-context-differs",
        )
        coverage = data["proposal"]["coverage"]
        review = dict(
            cluster_claims={
                cluster: ids[key]
                for cluster, key in coverage["cluster_claim_keys"].items()
            },
            identity_status=coverage["identity_status"],
            identity_claims={
                field: ids[c["claim_key"]] if c["status"] == "match" else None
                for field, c in coverage["identity_comparisons"].items()
            },
            closest=coverage["closest"],
            rationale=coverage["rationale"],
        )
        # Original Core replay verifies current decision, source claims, clusters,
        # identity and closest-work rules. The assessor explicitly remains agent.
        method, arguments, expected = prepare(
            ledger,
            self.intake.binding(ref),
            run,
            report,
            dict(
                operation="review-work",
                offer_ref=offered["offer_ref"],
                offer_sha256=offered["offer_sha256"],
                review=review,
            ),
            "agent:" + actor,
        )
        reading = deepcopy(saved["reading"])
        projected = 10 ** max(6, len(str(len(ledger.events()) + 1)))
        reading["review_event_id"] = f"e{projected}"
        self.analysis._publication(context, reading)
        item = dict(
            data=data,
            output_ref=saved["output_ref"],
            draft_sha256=saved["draft_sha256"],
            entries=entries,
            facts=facts,
            saved=saved,
            context=context,
            method=method,
            arguments=arguments,
            expected=expected,
        )
        self.analysis._stable(actor, ref, state, ledger, item, check)
        return item

    def review(self, credential, ref, body, *, run_authorization, check_deadline=None):
        self.analysis._idle(credential, ref)
        prepared = []

        def preflight(state, run, ledger, report, actor, check):
            prior = self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                (actor, ref),
            ).fetchall()
            _check(
                not any(
                    (r := decode(row[0].encode(), "agent coverage"))["kind"]
                    == "stage1-agent-coverage"
                    and r["status"] == "saved"
                    and r["request"].get("adoption_key") == body["adoption_key"]
                    for row in prior
                ),
                "stage1-agent-coverage-already-recorded",
            )
            prepared.append(
                self._prepare(actor, ref, state, run, ledger, report, body, check)
            )

        def produce(state, run, ledger, digest, actor, check):
            # Recompute the actual current offer under the original mutation owner.
            report = self.records._context(ref, body["ledger_state_sha256"])[5]
            item = self._prepare(actor, ref, state, run, ledger, report, body, check)
            _check(
                all(
                    item[field] == prepared[0][field]
                    for field in ("data", "saved", "facts", "arguments", "expected")
                ),
                "stage1-agent-coverage-preflight-changed",
            )
            event = getattr(ledger, item["method"])(**item["arguments"])
            _check(
                all(event.get(k) == v for k, v in item["expected"].items()),
                "stage1-agent-coverage-result-differs",
            )
            reading = deepcopy(item["saved"]["reading"])
            reading["review_event_id"] = event["event_id"]
            self.analysis._publication(item["context"], reading)
            self.analysis._stable(actor, ref, state, ledger, item, check)
            return dict(
                adoption_key=body["adoption_key"],
                adoption_request_sha256=body["adoption_request_sha256"],
                output_ref=item["output_ref"],
                draft_sha256=item["draft_sha256"],
                proposal_sha256=sha(item["data"]["raw"]),
                model_job_sha256=sha(canonical(item["data"]["job"])),
                event_id=event["event_id"],
                reading=reading,
                reading_sha256=sha(canonical(reading)),
                ledger_state_sha256=ledger.state_hash(),
                actor_type="agent",
                human_per_action_confirmation=False,
                scientific_acceptance=False,
                stage1_complete=False,
            )

        return mutate_agent(
            self.stage1,
            credential,
            ref,
            body,
            produce,
            run_authorization=run_authorization,
            kind="stage1-agent-coverage",
            fields={"adoption_key", "adoption_request_sha256"},
            preflight=preflight,
            check_deadline=check_deadline,
        )

    def register(
        self, credential, ref, body, *, run_authorization, check_deadline=None
    ):
        return self.analysis._register_adoption(
            credential,
            ref,
            body,
            adoption_kind="stage1-agent-coverage",
            run_authorization=run_authorization,
            check_deadline=check_deadline,
        )
