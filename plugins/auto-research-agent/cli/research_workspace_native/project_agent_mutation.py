"""Trusted agent mutations through the original intake and ledger owner."""

from .project_intake_contract import _fields, BOUND_FIELDS
from .project_run_authority import RunActionGuard
from .session_api import _check, _hash


def mutate_agent(
    stage1,
    credential,
    project_ref,
    body,
    producer,
    *,
    run_authorization,
    kind,
    fields,
    preflight=None,
    check_deadline=None,
):
    """No browser callbacks; the trusted caller supplies one bounded producer."""
    _fields(body, BOUND_FIELDS | {"confirmed", "ledger_state_sha256"} | set(fields))
    _check(_hash(body["ledger_state_sha256"]), "stage1-agent-ledger-hash-invalid")
    principal = stage1.intake._principal(credential)
    guard = RunActionGuard(
        stage1.intake,
        principal,
        project_ref,
        body,
        run_authorization,
        operation="agent-adoption",
        action=kind,
    )
    check = guard.deadline_check(check_deadline)

    def context(state):
        binding = stage1.intake.binding(project_ref)
        run, ledger, report = stage1._ledger(state, binding)
        _check(
            report["state_sha256"] == body["ledger_state_sha256"],
            "stage1-ledger-state-stale",
        )
        if run.get("query_owned"):
            _check(stage1.query_service is not None, "stage1-query-owner-unconnected")
            _check(
                stage1.query_service.saved_frontier(project_ref)["state_sha256"]
                == report["state_sha256"],
                "stage1-agent-owner-state-differs",
            )
        check()
        return run, ledger, report

    def reserve(state, digest, actor):
        from .project_stage1_coverage import unresolved

        _check(
            not unresolved(stage1, project_ref, actor, state["input_version"]),
            "stage1-coverage-write-outcome-unobserved",
        )
        run, ledger, report = context(state)
        if preflight is not None:
            preflight(state, run, ledger, report, actor, check)
        check()

    def work(state, digest, actor):
        run, ledger, _ = context(state)

        def produce(owned):
            check()
            result = producer(state, run, owned, digest, actor, check)
            check()
            return result

        if run.get("query_owned"):
            return stage1.query_service.mutate(
                credential, project_ref, state, run, ledger, digest, kind, produce
            )
        return produce(ledger)

    return stage1.intake._perform(
        principal,
        project_ref,
        kind,
        guard.request,
        work,
        reserve=reserve,
        check_deadline=check,
    )
