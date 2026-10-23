"""Initial pending observations; these never classify a work as included."""

from stage1_deliverable.common import identifier

from .project_agent_mutation import mutate_agent
from .session_api import _check


def initialize_pending(
    stage1, credential, ref, body, *, run_authorization, check_deadline=None
):
    works = body.get("work_refs") if type(body) is dict else None
    _check(
        type(works) is list
        and 0 < len(works) <= 64
        and all(type(work) is str for work in works)
        and len(set(works)) == len(works),
        "stage1-agent-pending-work-set-invalid",
        400,
    )
    for work in works:
        identifier(work)

    def selected(ledger):
        candidates = ledger.candidates()
        decided = {
            row["payload"]["subject_id"]
            for row in ledger.events()
            if row["payload"]["kind"] == "DecisionEvent"
        }
        for work in works:
            _check(
                work in candidates and work not in decided,
                "stage1-agent-pending-work-stale",
            )
        return candidates

    def preflight(state, run, ledger, report, actor, check):
        selected(ledger)

    def produce(state, run, ledger, digest, actor, check):
        candidates = selected(ledger)
        events = {}
        for work in works:
            check()
            discovery = candidates[work]["discoveries"][-1]
            # This is an explicit unassessed observation, never a semantic
            # inclusion reason or a claim of source/identity verification.
            events[work] = ledger.decide(
                work,
                "pending",
                reason="agent-source-review-required",
                rationale=(
                    "Unassessed discovery "
                    + work
                    + " / "
                    + discovery["version_id"]
                    + "; full-source evidence and relevance to the confirmed needs "
                    "remain Unknown. This observation only queues source review."
                ),
                evidence_refs=[discovery["source_ref"]],
                actor="agent",
                authorization=None,
            )
        return dict(
            work_decision_events=events,
            actor_type="agent",
            included_count=0,
            ledger_state_sha256=ledger.state_hash(),
            human_per_action_confirmation=False,
            scientific_acceptance=False,
        )

    return mutate_agent(
        stage1,
        credential,
        ref,
        body,
        produce,
        run_authorization=run_authorization,
        kind="stage1-agent-pending",
        fields={"work_refs"},
        preflight=preflight,
        check_deadline=check_deadline,
    )
