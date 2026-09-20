"""Operational coverage stopping; scientific truth remains externally reviewed."""

from stage1_ledger.semantics import SUCCESS


def pending_reviews(state):
    evidence, current = state.evidence, state.evidence.current()
    return sorted(
        work
        for work in evidence.candidates
        if evidence.decisions.get(work, {}).get("new_decision")
        not in {"include", "exclude"}
        or (
            evidence.decisions[work]["new_decision"] == "include"
            and work not in current
        )
    )


def missing_extraction(state):
    expected = sum(q["result_count"] for q in state.completed.values())
    seen = {
        d["discovery_id"]
        for c in state.evidence.candidates.values()
        for d in c["discoveries"]
    }
    return expected - len(seen)


def record_round(state, payload):
    current = state.evidence.current()
    previous = {
        work for row in state.round_yields for work in row["qualified_work_ids"]
    }
    state.round_yields.append(
        dict(
            round_number=payload["round_number"],
            complete=payload["summary"]["complete"]
            and not pending_reviews(state)
            and missing_extraction(state) == 0,
            qualified_work_ids=sorted(current),
            new_qualified_work_ids=sorted(set(current) - previous),
            review_event_ids=sorted(r["event_id"] for r in current.values()),
        )
    )


def query_complete(state, query):
    return (
        query["outcome"] in SUCCESS
        and set(query["attempted_backends"])
        == set(state.backends_for(query["arguments"]))
        and state.receipts.get(query["event_id"], {}).get("truncated") is False
        and query["result_count"] < state.binding["limit"]
    )


def evaluate(state):
    if state.plan is None:
        return None
    proposal, current = state.plan["proposal"], state.evidence.current()
    policy = proposal["stop_policy"]
    blockers, coverage = [], {}
    if (state.manifest.get("research_hub_pin") or {}).get(
        "status"
    ) == "development-unmerged":
        blockers.append("development-dependency-unmerged")
    for cluster in proposal["clusters"]:
        cluster_id = cluster["cluster_id"]
        works = sorted(
            work
            for work, review in current.items()
            if cluster_id in review["cluster_claims"]
        )
        coverage[cluster_id] = dict(
            work_ids=works, required=cluster["min_included_works"]
        )
        if len(works) < cluster["min_included_works"]:
            blockers.append("cluster-incomplete:" + cluster_id)
    latest, expansions = {}, {}
    for query in state.completed.values():
        binding = query["arguments"].get("coverage", {})
        if "planned_query_id" in binding:
            latest[binding["planned_query_id"]] = query
        elif "seed_work_id" in binding:
            expansions[
                (
                    binding["seed_work_id"],
                    binding["seed_version_id"],
                    query["arguments"]["operation"],
                )
            ] = query
    recent = [key for key, q in state.queries.items() if q["purpose"] == "recent"]
    recent_complete = all(
        key in latest and query_complete(state, latest[key]) for key in recent
    )
    if not recent_complete:
        blockers.append("recent-sweep-incomplete")
    closest = {work: review for work, review in current.items() if review["closest"]}
    verified = sorted(
        work
        for work, review in closest.items()
        if review["identity_status"] == "verified"
    )
    if len(verified) < policy["closest_min_verified"] or len(verified) != len(closest):
        blockers.append("closest-work-unverified")
    for work, review in closest.items():
        for operation in ("references", "cited-by"):
            result = expansions.get((work, review["version_id"], operation))
            if result is None or not query_complete(state, result):
                blockers.append(f"closest-expansion-incomplete:{work}:{operation}")
    outstanding = []
    for action in state.human_actions:
        if action["action"] != "request-cluster":
            continue
        required = [
            key
            for key, q in state.queries.items()
            if q["cluster_id"] == action["cluster_id"]
        ]
        if not all(
            key in latest
            and latest[key]["query_id"] > action["event_id"]
            and query_complete(state, latest[key])
            for key in required
        ):
            outstanding.append(action["event_id"])
    if outstanding:
        blockers.append("human-request-outstanding")
    unreviewed = pending_reviews(state)
    if unreviewed:
        blockers.append("screening-or-evidence-review-incomplete")
    if missing_extraction(state):
        blockers.append("extraction-incomplete")
    if state.active is not None:
        blockers.append("round-still-open")
    if not state.closed or state.closed[-1]["summary"]["complete"] is not True:
        blockers.append("latest-round-incomplete")
    streak = 0
    for row in reversed(state.round_yields):
        if not row["complete"] or row["new_qualified_work_ids"]:
            break
        streak += 1
    if streak < policy["consecutive_zero_yield_rounds"]:
        blockers.append("marginal-yield-not-saturated")
    if not state.round_yields or state.round_yields[-1]["review_event_ids"] != sorted(
        r["event_id"] for r in current.values()
    ):
        blockers.append("coverage-changed-since-round-close")
    refs = {state.plan_ref["artifact_id"]: state.plan_ref}
    for review in current.values():
        for claim_id in list(review["cluster_claims"].values()) + list(
            review["identity_claims"].values()
        ):
            if claim_id is not None:
                ref = state.evidence.claims[claim_id]["source_ref"]
                refs[ref["artifact_id"]] = ref
    return dict(
        clusters=coverage,
        recent_complete=recent_complete,
        closest_verified_work_ids=verified,
        unreviewed_work_ids=unreviewed,
        outstanding_human_actions=outstanding,
        rounds=state.round_yields,
        consecutive_complete_zero_yield_rounds=streak,
        blockers=blockers,
        budget_exhausted=len(state.closed) >= policy["max_rounds"],
        evidence_refs=list(refs.values()),
        scope="operational-stop-based-on-recorded-reviews",
        scientific_truth="not-evaluated",
    )
