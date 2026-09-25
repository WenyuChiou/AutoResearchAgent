"""Compute Stage 1 dimension scores from validated atomic judgments."""

from datetime import datetime, timezone

from .common import EvaluationError, canonical, load_rubric, sha


def aggregate(packet, judgment, *, evaluator_identity, costs=None):
    rubric, rubric_sha = load_rubric()
    rows = (
        judgment["selected"]["content"]["criteria"]
        + judgment["selected"]["process"]["criteria"]
    )
    row_by_id = {row["criterion_id"]: row for row in rows}
    if set(row_by_id) != {row["id"] for row in rubric["criteria"]} or len(rows) != len(
        row_by_id
    ):
        raise EvaluationError("aggregation requires complete atomic rubric")
    issues = (
        judgment["selected"]["content"]["major_issues"]
        + judgment["selected"]["process"]["major_issues"]
    )
    dimensions = {}
    for dimension in rubric["dimensions"]:
        dimension_id = dimension["id"]
        subset = [
            row_by_id[criterion["id"]]
            for criterion in rubric["criteria"]
            if criterion["dimension"] == dimension_id
        ]
        applicable = [row for row in subset if row["status"] != "not-applicable"]
        scored = [row for row in applicable if row["status"] == "scored"]
        unknown = len(applicable) - len(scored)
        known_points = sum(row["score"] for row in scored)
        denominator = 2 * len(applicable)
        dimensions[dimension_id] = {
            "name": dimension["name"],
            "criteria": subset,
            "applicable_count": len(applicable),
            "scored_count": len(scored),
            "unknown_count": unknown,
            "not_applicable_count": len(subset) - len(applicable),
            "assessed_fraction": len(scored) / len(applicable) if applicable else None,
            "observed_score_100": round(100 * known_points / (2 * len(scored)), 2)
            if scored
            else None,
            "lower_bound_100": round(100 * known_points / denominator, 2)
            if denominator
            else None,
            "upper_bound_100": round(
                100 * (known_points + 2 * unknown) / denominator, 2
            )
            if denominator
            else None,
            "confirmed_major_issue_ids": [
                row["issue_id"]
                for row in issues
                if row["dimension"] == dimension_id and row["status"] == "confirmed"
            ],
            "unresolved_major_issue_ids": [
                row["issue_id"]
                for row in issues
                if row["dimension"] == dimension_id and row["status"] == "unresolved"
            ],
        }
    challenge_complete = packet["mode"] == "evidence-audited" and all(
        row["status"] in {"results", "zero-results"}
        for row in packet["challenge_receipts"]
    )
    critical_unknown = any(
        criterion["critical"] and row_by_id[criterion["id"]]["status"] != "scored"
        for criterion in rubric["criteria"]
    )
    confirmed = any(row["status"] == "confirmed" for row in issues)
    unresolved = any(row["status"] == "unresolved" for row in issues)
    if confirmed:
        readiness = "fail-confirmed-major-issue"
    elif (
        not challenge_complete
        or critical_unknown
        or unresolved
        or not packet["extraction"]["extraction_complete"]
        or any(row["unknown_count"] for row in dimensions.values())
        or packet["subject_status"] != "complete"
    ):
        readiness = "inconclusive"
    else:
        readiness = "evidence-assessed"
    result = {
        "kind": "StageEvaluationResult",
        "schema_version": "3.0.0",
        "stage_id": "stage1",
        "evaluation_mode": "rubric-evidence",
        "rubric_id": rubric["rubric_id"],
        "rubric_sha256": rubric_sha,
        "topic_id": packet["spec"]["topic_id"],
        "spec_sha256": sha(canonical(packet["spec"])),
        "packet_sha256": sha(canonical(packet)),
        "subject_sha256": packet["content_evidence"]["answer"]["sha256"],
        "evidence_mode": packet["mode"],
        "subject_status": packet["subject_status"],
        "extraction_status": "complete"
        if packet["extraction"]["extraction_complete"]
        else "partial",
        # A complete evaluator run may conclude that the subject is inadequate.
        # Scientific readiness and evaluator execution are separate states.
        "evaluator_status": "complete",
        "scientific_readiness_status": readiness,
        "claimed_scope": "Rubric adequacy within frozen task, accessible sources, and bounded search; not field-wide core recall.",
        "dimensions": dimensions,
        "core_assessments": judgment["selected"]["content"]["core_assessments"],
        "omission_assessments": judgment["selected"]["content"]["omission_assessments"],
        "major_issues": issues,
        "adjudicated_phases": judgment["adjudicated_phases"],
        "evaluator_identity": evaluator_identity,
        "costs": costs
        or {
            "evaluator_model_completed_turns": None,
            "evaluator_tokens": {
                key: None
                for key in (
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )
            },
            "source_acquisition_calls": None,
            "source_acquisition_failures": None,
            "evaluator_elapsed_seconds_this_attempt": None,
            "subject_tokens": None,
            "currency_cost": None,
        },
        "authorization": {
            "publication_approved": False,
            "external_improvement_claim_approved": False,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return result
