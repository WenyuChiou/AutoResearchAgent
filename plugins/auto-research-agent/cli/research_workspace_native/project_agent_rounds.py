"""Agent-only round bookkeeping through the unchanged Core coverage contract."""

from stage1_ledger.validation import validate_run

from .project_agent_mutation import mutate_agent
from .project_stage1_coverage import FIELDS, prepare
from .session_api import _check


def record_round(
    stage1, credential, ref, body, *, run_authorization, check_deadline=None
):
    """Record observed query metadata, never a human stop or scientific decision."""
    _check(
        type(body) is dict
        and type(body.get("operation")) is str
        and body["operation"] in {"open-round", "receipt", "close-round"}
        and type(body.get("review")) is dict,
        "stage1-agent-round-operation-invalid",
        400,
    )

    def checked(run, ledger, report):
        return prepare(
            ledger,
            stage1.intake.binding(ref),
            run,
            report,
            body,
            "agent:" + stage1.intake._principal(credential),
        )

    def preflight(state, run, ledger, report, actor, check):
        checked(run, ledger, report)
        check()

    def produce(state, run, ledger, digest, actor, check):
        method, arguments, expected = checked(run, ledger, validate_run(ledger.root))
        check()
        event = getattr(ledger, method)(**arguments)
        _check(
            all(event.get(key) == value for key, value in expected.items()),
            "stage1-agent-round-core-result-differs",
        )
        check()
        return dict(
            operation=body["operation"],
            event_id=event["event_id"],
            ledger_state_sha256=ledger.state_hash(),
            automated_actor="agent",
            human_per_action_confirmation=False,
            scientific_acceptance=False,
            stage1_complete=False,
            grants_external_permission=False,
        )

    return mutate_agent(
        stage1,
        credential,
        ref,
        body,
        produce,
        run_authorization=run_authorization,
        kind="stage1-coverage",
        fields=FIELDS,
        preflight=preflight,
        check_deadline=check_deadline,
    )
