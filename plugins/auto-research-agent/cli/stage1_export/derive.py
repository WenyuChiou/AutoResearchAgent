"""Count recorded facts; never infer scientific judgments or platform usage."""

from collections import Counter
from datetime import datetime
import re
from stage1_ledger.journal import decode


def ratio(n, total):
    return dict(
        n=n,
        N=total,
        ratio=n / total if total else None,
        status="recorded" if total else "not-applicable",
    )


def unavailable(reason, total=None):
    return dict(n=None, N=total, ratio=None, status="unavailable", reason=reason)


def derive(manifest, events, report, checkpoint, read_ref=None):
    works = {p["work_id"]: p for p in events if p["kind"] == "CandidateRevision"}
    decisions = [p for p in events if p["kind"] == "DecisionEvent"]
    latest = {p["subject_id"]: p for p in decisions}
    included = [
        work for work in works if latest.get(work, {}).get("new_decision") == "include"
    ]
    claims = [p for p in events if p["kind"] == "ClaimEvidence"]
    checkpoints = [p for p in events if p["kind"] == "Checkpoint"]
    queries = [p for p in events if p["kind"] == "QueryEvent"]
    finishes = [p for p in events if p["kind"] == "ActionFinished"]
    backends = [
        p
        for p in events
        if p["kind"] == "ActionStarted" and p["operation"] == "backend"
    ]
    coverage = report.get("coverage")
    # The plan's window is also encoded in each derived recent query's exact year.
    ranges = [
        q["arguments"]["year"]
        for q in queries
        if q["arguments"].get("year") is not None
    ]
    recent_ranges = (
        set(ranges) if all(isinstance(value, str) for value in ranges) else set()
    )
    window = next(iter(recent_ranges)) if len(recent_ranges) == 1 else None
    years = []
    for work in included:
        observed = {d["record"]["year"] for d in works[work]["discoveries"]}
        year = next(iter(observed)) if len(observed) == 1 else None
        years.append(dict(work_id=work, recorded_year=year))
    known = [row["recorded_year"] for row in years if row["recorded_year"] is not None]
    recent = unavailable("no-unambiguous-recorded-year-window", len(known))
    if (
        window
        and re.fullmatch(r"[0-9]{4}-[0-9]{4}", window)
        and int(window[:4]) <= int(window[5:])
    ):
        low, high = map(int, window.split("-"))
        recent = ratio(sum(low <= year <= high for year in known), len(known))
    screening_traced = sum(
        bool(p["reason_code"] and p["rationale"] and p["evidence_refs"])
        for p in decisions
    )
    checkpoint_traced = sum(
        bool(
            p["stage_result"]["gate"]["reasons"]
            and p["stage_result"]["validator_report"]
        )
        for p in checkpoints
    )
    base = dict(schema_version="1.0.0", source_state_sha256=report["state_sha256"])
    inputs = dict(
        base,
        kind="Stage1MetricInputs",
        population=dict(
            included_work_ids=included,
            candidate_work_ids=list(works),
            basis="latest ledger decisions; final answer and central-claim selection require external audit",
        ),
        P1=dict(
            candidate_event_ids=[p["event_id"] for p in works.values()],
            claim_event_ids=[p["event_id"] for p in claims],
            identity_comparison_event_ids=[
                p["event_id"] for p in events if p["kind"] == "IdentityComparison"
            ],
            coverage_review_event_ids=[
                p["event_id"] for p in events if p["kind"] == "CoverageWorkReview"
            ],
            central_claim_ids=None,
            audit_status="not-performed",
        ),
        P2=dict(
            operational_coverage=coverage,
            recorded_years=years,
            recorded_recent=recent,
            recorded_latest_year=max(known) if known else None,
            recent_window=window,
            core_recall=unavailable("private-anchor-matches-not-supplied"),
            must_have_recall=unavailable("private-anchor-matches-not-supplied"),
            scientific_coverage=unavailable(
                "requires-independent-source-and-relevance-audit"
            ),
        ),
        P3=dict(
            works_with_trace=ratio(
                sum(bool(works[w]["discoveries"]) for w in included), len(included)
            ),
            all_annotated_claims_with_locator=ratio(
                sum(p["locator"] is not None for p in claims), len(claims)
            ),
            central_claims_with_locator=unavailable(
                "central-claim-selection-not-supplied"
            ),
            decisions_with_reason=ratio(
                screening_traced + checkpoint_traced, len(decisions) + len(checkpoints)
            ),
            versions_with_access_date=unavailable(
                "source-save-time-is-not-source-access-date", len(included)
            ),
            checkpoint_event_id=checkpoint["event_id"],
            stop_action=checkpoint["stage_result"]["next_allowed_action"],
            coverage_rounds_recorded=bool(coverage and coverage["rounds"]),
            operational_stop_checks_satisfied=bool(
                coverage
                and not coverage["blockers"]
                and checkpoint["stage_result"]["next_allowed_action"]
                == "stop-sufficient"
            ),
        ),
        judgment_scores={
            metric: dict(R1=None, R2=None, ADJ=None, status="not_scored")
            for metric in ("P1", "P2", "P3")
        },
        major_error_gate=dict(status="not-assessed", issues=None),
        required_external_inputs=[
            "final-answer-and-central-claim-selection",
            "bibliographic-and-claim-audits",
            "private-anchor-matches",
            "source-access-dates",
            "native-runtime-and-usage",
            "blinded-judges-and-required-human-audits",
        ],
    )
    started = datetime.fromisoformat(
        manifest["research_run"]["created_at"].replace("Z", "+00:00")
    )
    ended = datetime.fromisoformat(events[-1]["created_at"].replace("Z", "+00:00"))
    completed_ids = {p["attempt_id"] for p in finishes}
    efficiency = dict(
        base,
        kind="Stage1EfficiencyInputs",
        source_mode=manifest["mode"],
        recorded_queries=len(queries),
        recorded_backend_attempts=len(backends),
        backend_outcomes=dict(sorted(Counter(p["outcome"] for p in finishes).items())),
        pending_backend_attempts=sum(
            p["event_id"] not in completed_ids for p in backends
        ),
        recorded_human_actions=sum(
            p["kind"] == "CoverageHumanAction"
            or (p["kind"] == "DecisionEvent" and p["actor_type"] == "human")
            for p in events
        ),
        observed_ledger_span_seconds=(ended - started).total_seconds(),
        elapsed_seconds=None,
        tool_calls=None,
        failed_tool_calls=None,
        model_calls=None,
        human_interventions=None,
        retries=None,
        tokens=None,
        cost=None,
        scope="recorded ledger activity; complete research time, host calls, retries and usage are unavailable",
    )
    if manifest["mode"] == "research-hub-cli":
        receipts = [
            decode(read_ref(p["execution_ref"]), "execution receipt") for p in finishes
        ]
        projections = [r["projection"] for r in receipts]
        efficiency["retrieval_usage"] = dict(
            completed_cli_invocations=len(receipts),
            provider_attempts=sum(p["provider_attempts"] for p in projections)
            if all(p["provider_attempts"] is not None for p in projections)
            else None,
            http_attempts=sum(p["http_attempts"] for p in projections)
            if all(p["http_attempts"] is not None for p in projections)
            else None,
            incomplete_captures=sum(
                p["provider_attempts"] is None for p in projections
            ),
            scope="saved public CLI attempts only; pending invocations and whole-stage model usage are separate",
        )
    return inputs, efficiency
