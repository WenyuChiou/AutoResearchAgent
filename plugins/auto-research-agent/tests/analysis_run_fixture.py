"""Actual saved queue/Core/SQLite analysis fixture with synthetic I/O seams."""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from research_workspace_native.model_input_profile import turn_input
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_run_authority import action_identity
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body
import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as package_fixture


LONG_QUOTE = "Q" * 8192


def analysis_proposal(
    context,
    *,
    quote=None,
    claim_count=1,
    classification=None,
    findings=None,
):
    """Build a source-bound proposal accepted by the saved model-job parser."""
    reading = context["saved_reading"]["reading_input"]
    source = reading["full_source"]["sources"][0]
    text = source["text"]
    quote = text[-32:] if quote is None else quote
    raw = text.encode("utf8")
    start = raw.index(quote.encode("utf8"))
    return dict(
        kind="Stage1FullSourceAnalysisProposal",
        schema_version="1.0.0",
        reading=dict(
            summary="Synthetic saved source only; semantic support Unknown.",
            classification=classification
            if classification is not None
            else {key: "Unknown" for key in CLASSIFICATION},
            findings=findings
            if findings is not None
            else {key: "Unknown" for key in FINDINGS},
            limitations=["Support unassessed."],
            open_questions=["Relevance Unknown."],
            evidence=[
                dict(
                    source_id=source["source_id"],
                    text_sha256=source["text_sha256"],
                    start_byte=start,
                    end_byte=start + len(quote.encode("utf8")),
                    quote=quote,
                    claim_id=None,
                )
            ],
        ),
        screening=dict(
            decision="pending",
            need_ids=[reading["brief"]["needs"][0]["need_id"]],
            reason_code="needs-independent-review",
            rationale="This authored source was mechanically read; relevance to the confirmed need remains Unknown.",
            missing_information=["Scientific relevance."],
        ),
        claims=[
            dict(
                claim_key=f"synthetic-tail-{index:02d}",
                claim_text=f"The authored source contains passage {index:02d}.",
                relation="unclear",
                evidence_index=0,
                section="Unknown",
                assessment=dict(
                    reason_code="support-unassessed",
                    rationale="Exact passage retained; meaning remains unassessed.",
                ),
            )
            for index in range(claim_count)
        ],
    )


@contextmanager
def analysis_run_fixture(
    *,
    proposal_builder=analysis_proposal,
    long_source=False,
    analysis_coverage=False,
):
    """Yield one completed saved job plus its real adoption/authority services."""
    original_submit = delivery_fixture.submit_body
    original_records = package_fixture.ResearchDeliverableTests.make_records

    def funded(view):
        body = original_submit(view)
        body["budgets"].update(model_calls=2, seconds=120)
        return body

    def long_records(case, raw=package_fixture.HTML, **kwargs):
        raw = raw.replace(
            b"</article>", b"<p>" + LONG_QUOTE.encode() + b"</p></article>"
        )
        return original_records(case, raw=raw, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(delivery_fixture, "submit_body", side_effect=funded)
        )
        if long_source:
            stack.enter_context(
                patch.object(
                    package_fixture.ResearchDeliverableTests,
                    "make_records",
                    new=long_records,
                )
            )
        case, fixture = stack.enter_context(saved_stage1_case())
        ref, ledger = fixture["ref"], fixture["ledger"]
        work = fixture["records"]["papers"][0]["work_id"]
        calls = []

        def factory(*, context, admit, output_root):
            calls.append(context)
            answer = proposal_builder(context)

            class Reader:
                def run(self, key, prompt, deadline):
                    event = dict(
                        unit_key=key,
                        prompt_sha256=sha(prompt.encode()),
                        source_sha256=context["source_sha256"],
                        permit_sha256=context["permit_sha256"],
                        event={},
                    )
                    admit(dict(event, phase="reserve"))
                    admit(dict(event, phase="spawn"))
                    admit(
                        dict(
                            event,
                            phase="action",
                            event=dict(
                                action=dict(
                                    method="turn/start",
                                    payload=dict(
                                        model=context["model"],
                                        **turn_input(prompt, context["input_profile"]),
                                    ),
                                )
                            ),
                        )
                    )
                    return dict(
                        status="completed",
                        prompt_sha256=event["prompt_sha256"],
                        source_sha256=event["source_sha256"],
                        final_text=canonical(answer).decode(),
                        synthetic=True,
                    )

                def verify_receipt(self, receipt, **expected):
                    return receipt

            return Reader()

        model = ProjectModelService(
            case.intake,
            provider_factory=factory,
            model="synthetic-analysis",
            local_cap_seconds=30,
            clock=lambda: 1_900_000_000,
            reading_records=case.producer,
            analysis_coverage=analysis_coverage,
        )
        try:

            def run_job(key, user_input):
                view = case.intake.read("alice-token", ref)
                preview = model.full_analysis_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=view["input_version"],
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
                if not preview["available"]:
                    raise AssertionError(preview)
                offer = model.authorize(
                    "alice-token",
                    ref,
                    {
                        **bound_body(view, key + "-auth"),
                        "operation": "analyze-full-paper",
                        "work_ref": work,
                        "snapshot_sha256": preview["snapshot_sha256"],
                        "confirmed": True,
                        "user_input": user_input,
                    },
                )["offer"]
                model.execute(
                    "alice-token",
                    ref,
                    {
                        **bound_body(case.intake.read("alice-token", ref), key),
                        "confirmed": True,
                        "offer_ref": offer["offer_ref"],
                        "offer_sha256": offer["offer_sha256"],
                    },
                )
                worker = model._workers[(ref, key)]
                worker.join(90)
                if worker.is_alive():
                    raise AssertionError("saved analysis worker did not finish")
                job = model._job("alice", ref, key)
                if job["status"] != "content-review-pending":
                    raise AssertionError(job)
                return job

            job = run_job("analysis", "Analyze this authored fixture once.")
            grant_service = ProjectStage1RunGrantService(
                case.intake, runtime_sha256="a" * 64, clock=lambda: 1_900_000_000
            )
            grant = grant_service.authorize(
                "alice-token",
                ref,
                {
                    **bound_body(case.intake.read("alice-token", ref), "run-consent"),
                    "confirmed": True,
                    "user_input": "Adopt saved synthetic analysis as agent observations; stop before science acceptance.",
                    "scope": SCOPE,
                    "operations": ["agent-adoption", "records"],
                    "max_seconds": 100,
                    "max_actions": 8,
                },
            )

            def derived(action, operation, extra):
                body = {
                    **bound_body(case.intake.read("alice-token", ref), "draft"),
                    "confirmed": False,
                    "ledger_state_sha256": ledger.state_hash(),
                    **extra,
                }
                token = grant_service.derive(
                    "alice-token",
                    ref,
                    grant_ref=grant["grant_ref"],
                    grant_sha256=grant["grant_sha256"],
                    operation=operation,
                    identity=action_identity(action, body),
                )
                body.update(
                    key=token.key + "-work",
                    revision=case.intake.read("alice-token", ref)["revision"],
                )
                return body, token

            yield SimpleNamespace(
                case=case,
                fixture=fixture,
                ref=ref,
                ledger=ledger,
                work=work,
                calls=calls,
                model=model,
                job=job,
                run_job=run_job,
                derived=derived,
            )
        finally:
            model.close()
