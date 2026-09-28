"""Deterministic Stage 2 review coordination without native execution.

The functions in this module bind local records and expose pending work.  They
do not call tools or models, attest native sessions, rank candidates, or assign
scientific confidence.
"""

import copy

from stage2_check.contracts import latest_candidates
from stage2_common import Stage2Error, canonical_hash
from stage2_workflow.reviews import (
    ROLES,
    prepare_review,
    reconcile_reviews,
    select_excluded_audit,
)


_RESULT_STATUSES = {"complete", "empty", "failed", "interrupted", "unavailable"}
_ATTEMPT_STATUSES = {"success", "empty", "failed", "interrupted", "unavailable"}
_BATCH_KEYS = {
    "kind",
    "schema_version",
    "packet_sha256",
    "snapshot_sha256",
    "seed",
    "current_candidates",
    "screening",
    "audit",
    "main_candidate_count",
    "audited_excluded_count",
    "assignments",
    "batch_sha256",
}


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _sha256(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        f"{label}-sha256",
    )


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"{label}-required")


def _batch_payload(batch):
    return {key: value for key, value in batch.items() if key != "batch_sha256"}


def prepare_review_batch(packet, snapshot_sha256, screening, seed):
    """Prepare two isolated roles for every included or audited candidate.

    ``screening`` must contain exactly one current-version row per candidate.
    Its rows use the exact shape accepted by ``select_excluded_audit``.  Output
    ordering is canonical, so input ordering cannot alter the batch binding.
    """

    _sha256(snapshot_sha256, "snapshot")
    _, latest = latest_candidates(packet, [])
    audit = select_excluded_audit(screening, seed)
    ordered_screening = sorted(
        copy.deepcopy(screening), key=lambda row: row["candidate_id"]
    )
    screened = {row["candidate_id"]: row for row in ordered_screening}
    _require(set(screened) == set(latest), "screening-current-candidates-mismatch")
    for candidate_id, candidate in latest.items():
        _require(
            screened[candidate_id]["candidate_version"] == candidate["version"],
            f"screening-stale-candidate-version: {candidate_id}",
        )

    audited_ids = {row["candidate_id"] for row in audit["selected"]}
    included_ids = {row["candidate_id"] for row in ordered_screening if row["included"]}
    selected_ids = sorted(included_ids | audited_ids)
    assignments = []
    for candidate_id in selected_ids:
        cohort = "main" if candidate_id in included_ids else "audit"
        for role in ROLES:
            view = prepare_review(packet, candidate_id, snapshot_sha256, role)
            assignments.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_version": latest[candidate_id]["version"],
                    "cohort": cohort,
                    "role": role,
                    "view": view,
                    "view_sha256": canonical_hash(view),
                }
            )
    audit = copy.deepcopy(audit)
    audit["selected"] = sorted(audit["selected"], key=lambda row: row["candidate_id"])
    payload = {
        "kind": "Stage2ReviewBatch",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(packet),
        "snapshot_sha256": snapshot_sha256,
        "seed": seed,
        "current_candidates": [
            {
                "candidate_id": candidate_id,
                "candidate_version": latest[candidate_id]["version"],
            }
            for candidate_id in sorted(latest)
        ],
        "screening": ordered_screening,
        "audit": audit,
        "main_candidate_count": len(included_ids),
        "audited_excluded_count": len(audited_ids),
        "assignments": assignments,
    }
    return {**payload, "batch_sha256": canonical_hash(payload)}


def _validate_result_envelope(row):
    _require(
        isinstance(row, dict)
        and set(row)
        == {"candidate_id", "candidate_version", "role", "status", "review", "error"},
        "review-result-shape",
    )
    _text(row["candidate_id"], "review-result-candidate-id")
    _text(row["role"], "review-result-role")
    _require(
        type(row["candidate_version"]) is int and row["candidate_version"] > 0,
        "review-result-version",
    )
    _require(
        isinstance(row["status"], str) and row["status"] in _RESULT_STATUSES,
        "review-result-status",
    )
    if row["status"] == "complete":
        _require(isinstance(row["review"], dict), "complete-review-required")
        _require(
            isinstance(row["review"].get("assessment"), dict),
            "review-assessment-object-required",
        )
        _require(row["error"] is None, "complete-review-cannot-have-error")
    else:
        _require(row["review"] is None, "incomplete-review-must-be-empty")
        _text(row["error"], "review-result-error")


def _resolution_map(resolutions, expected_ids):
    _require(
        isinstance(resolutions, dict)
        and set(resolutions) == {"candidate_resolutions", "next_step"},
        "batch-resolutions-shape",
    )
    rows = resolutions["candidate_resolutions"]
    _require(isinstance(rows, list), "candidate-resolutions-must-be-list")
    result = {}
    for row in rows:
        _require(
            isinstance(row, dict) and set(row) == {"candidate_id", "resolution"},
            "candidate-resolution-shape",
        )
        candidate_id = row["candidate_id"]
        _text(candidate_id, "resolution-candidate-id")
        _require(candidate_id in expected_ids, "foreign-candidate-resolution")
        _require(candidate_id not in result, "duplicate-candidate-resolution")
        resolution = row["resolution"]
        _require(isinstance(resolution, dict), "resolution-object-required")
        for field in (
            "review_sha256s",
            "addressed",
            "evidence_ids",
            "substantive_disagreements",
        ):
            _require(
                isinstance(resolution.get(field), list)
                and all(isinstance(item, str) for item in resolution[field]),
                f"resolution-{field}-text-list-required",
            )
        _text(resolution.get("method"), "resolution-method")
        _require(
            isinstance(resolution.get("assessment"), dict),
            "resolution-assessment-object-required",
        )
        result[candidate_id] = resolution
    if resolutions["next_step"] is not None:
        _text(resolutions["next_step"], "next-step")
    return result


def reconcile_batch(packet, batch, reviews, resolutions):
    """Reconcile a fully reconstructed batch from explicit result envelopes.

    A review result envelope has ``candidate_id``, ``candidate_version``,
    ``role``, ``status``, ``review`` and ``error``.  Non-complete results keep
    their distinct status and leave that candidate pending.  ``resolutions`` is
    ``{"candidate_resolutions": [{"candidate_id", "resolution"}],
    "next_step": str | None}``.
    """

    _require(isinstance(batch, dict) and set(batch) == _BATCH_KEYS, "batch-shape")
    _require(
        batch["batch_sha256"] == canonical_hash(_batch_payload(batch)),
        "batch-hash-mismatch",
    )
    expected = prepare_review_batch(
        packet, batch["snapshot_sha256"], batch["screening"], batch["seed"]
    )
    _require(batch == expected, "batch-reconstruction-mismatch")
    _require(isinstance(reviews, list), "review-results-must-be-list")

    assignments = {
        (row["candidate_id"], row["role"]): row for row in batch["assignments"]
    }
    results = {}
    for row in reviews:
        _validate_result_envelope(row)
        key = (row["candidate_id"], row["role"])
        _require(key in assignments, "foreign-review-result")
        _require(key not in results, "duplicate-review-result")
        _require(
            row["candidate_version"] == assignments[key]["candidate_version"],
            "review-result-candidate-version-mismatch",
        )
        if row["status"] == "complete":
            review = row["review"]
            _require(
                review.get("candidate_id") == row["candidate_id"]
                and review.get("candidate_version") == row["candidate_version"]
                and review.get("role") == row["role"],
                "review-result-binding-mismatch",
            )
        results[key] = copy.deepcopy(row)

    candidate_ids = sorted({key[0] for key in assignments})
    resolution_by_id = _resolution_map(resolutions, set(candidate_ids))
    candidate_rows = []
    recommendations = []
    for candidate_id in candidate_ids:
        assignment = assignments[(candidate_id, ROLES[0])]
        role_rows = {role: results.get((candidate_id, role)) for role in ROLES}
        complete = [
            role_rows[role]["review"]
            for role in ROLES
            if role_rows[role] and role_rows[role]["status"] == "complete"
        ]
        incomplete = {
            role: "missing" if role_rows[role] is None else role_rows[role]["status"]
            for role in ROLES
            if role_rows[role] is None or role_rows[role]["status"] != "complete"
        }
        resolution = resolution_by_id.get(candidate_id)
        _require(
            not (incomplete and resolution is not None),
            "resolution-before-complete-reviews",
        )
        reconciled = reconcile_reviews(
            packet,
            candidate_id,
            batch["snapshot_sha256"],
            complete,
            resolution,
        )
        assessment = reconciled.get("assessment")
        blocked_unknown = bool(
            assessment
            and any(
                finding["status"] == "unknown" and finding["blocking"]
                for finding in assessment["checks"].values()
            )
        )
        recommendation_eligible = bool(
            reconciled["recommendation_eligible"] and not blocked_unknown
        )
        if recommendation_eligible:
            recommendations.append(candidate_id)
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_version": assignment["candidate_version"],
                "cohort": assignment["cohort"],
                "result_states": incomplete,
                "key_prerequisite_unknown": blocked_unknown,
                "recommendation_eligible": recommendation_eligible,
                "reconciliation": reconciled,
            }
        )

    next_step = resolutions["next_step"]
    if not recommendations:
        _text(next_step, "zero-recommendation-next-step")
    review_counts = {status: 0 for status in sorted(_RESULT_STATUSES)}
    review_counts["missing"] = len(assignments) - len(results)
    for row in results.values():
        review_counts[row["status"]] += 1
    local_ready = all(
        row["reconciliation"]["status"] == "resolved" for row in candidate_rows
    )
    return {
        "kind": "Stage2ReviewBatchReconciliation",
        "schema_version": "1.0.0",
        "packet_sha256": batch["packet_sha256"],
        "snapshot_sha256": batch["snapshot_sha256"],
        "batch_sha256": batch["batch_sha256"],
        "candidate_counts": {
            "main": batch["main_candidate_count"],
            "audit": batch["audited_excluded_count"],
        },
        "review_counts": review_counts,
        "candidates": candidate_rows,
        "recommendations": recommendations,
        "next_step": next_step,
        "local_reconciliation_ready": local_ready,
        "actual_execution_attested": False,
    }


def make_followup(
    packet,
    snapshot_sha256,
    candidate_id,
    question,
    decision_at_risk,
    needed_evidence,
    prior_attempts,
    next_action,
    policy_ref,
):
    """Bind one material follow-up and derive whether unchanged work must stop.

    ``decision_at_risk`` is an exact object with ``kind`` (``scientific``,
    ``scope`` or ``resource``), ``description``, ``material`` and ``changeable``.
    Each prior attempt binds candidate/version/snapshot and preserves its action,
    status, evidence references and failure text.  ``next_action`` is text or
    ``None``; repeating an equivalent action is not a new feasible action.
    """

    _sha256(snapshot_sha256, "snapshot")
    _, latest = latest_candidates(packet, [])
    _require(candidate_id in latest, "unknown-followup-candidate")
    _text(question, "followup-question")
    _require(
        isinstance(decision_at_risk, dict)
        and set(decision_at_risk) == {"kind", "description", "material", "changeable"},
        "decision-at-risk-shape",
    )
    _require(
        decision_at_risk["kind"] in {"scientific", "scope", "resource"},
        "decision-at-risk-kind",
    )
    _text(decision_at_risk["description"], "decision-at-risk-description")
    _require(decision_at_risk["material"] is True, "material-decision-required")
    _require(decision_at_risk["changeable"] is True, "changeable-decision-required")
    _require(
        isinstance(needed_evidence, list)
        and needed_evidence
        and len(needed_evidence) == len(set(needed_evidence)),
        "needed-evidence-required",
    )
    for item in needed_evidence:
        _text(item, "needed-evidence-item")
    _require(isinstance(prior_attempts, list), "prior-attempts-must-be-list")
    _require(
        isinstance(policy_ref, dict) and set(policy_ref) == {"path", "sha256"},
        "policy-ref-shape",
    )
    _text(policy_ref["path"], "policy-ref-path")
    _sha256(policy_ref["sha256"], "policy-ref")
    if next_action is not None:
        _text(next_action, "next-action")

    current_version = latest[candidate_id]["version"]
    seen_ids = set()
    equivalent = []
    attempts = []
    attempt_shape = {
        "attempt_id",
        "candidate_id",
        "candidate_version",
        "snapshot_sha256",
        "question",
        "decision_at_risk",
        "needed_evidence",
        "action",
        "status",
        "evidence_refs",
        "failure",
    }
    for attempt in prior_attempts:
        _require(
            isinstance(attempt, dict) and set(attempt) == attempt_shape,
            "prior-attempt-shape",
        )
        _text(attempt["attempt_id"], "attempt-id")
        _require(attempt["attempt_id"] not in seen_ids, "duplicate-attempt-id")
        seen_ids.add(attempt["attempt_id"])
        _require(
            attempt["candidate_id"] == candidate_id, "prior-attempt-candidate-mismatch"
        )
        _require(
            type(attempt["candidate_version"]) is int
            and attempt["candidate_version"] > 0,
            "prior-attempt-version",
        )
        _sha256(attempt["snapshot_sha256"], "prior-attempt-snapshot")
        _text(attempt["question"], "prior-attempt-question")
        _text(attempt["action"], "prior-attempt-action")
        _require(attempt["status"] in _ATTEMPT_STATUSES, "prior-attempt-status")
        _require(
            isinstance(attempt["evidence_refs"], list), "prior-attempt-evidence-refs"
        )
        for ref in attempt["evidence_refs"]:
            _text(ref, "prior-attempt-evidence-ref")
        if attempt["status"] == "success":
            _require(
                attempt["evidence_refs"] and attempt["failure"] is None,
                "successful-attempt-evidence-required",
            )
        elif attempt["status"] == "empty":
            _require(
                not attempt["evidence_refs"] and attempt["failure"] is None,
                "empty-attempt-shape",
            )
        else:
            _text(attempt["failure"], "attempt-failure")
        attempts.append(copy.deepcopy(attempt))
        if (
            attempt["candidate_version"] == current_version
            and attempt["snapshot_sha256"] == snapshot_sha256
            and attempt["question"] == question
            and attempt["decision_at_risk"] == decision_at_risk
            and attempt["needed_evidence"] == needed_evidence
        ):
            equivalent.append(attempt)

    # Only the latest attempt can advance the evidence; an old success cannot
    # excuse later unchanged failures. Incorporation requires a new snapshot
    # or a distinct next action, not another execution of the same lookup.
    earlier_refs = {
        ref for attempt in equivalent[:-1] for ref in attempt["evidence_refs"]
    }
    new_evidence = bool(
        equivalent
        and equivalent[-1]["status"] == "success"
        and set(equivalent[-1]["evidence_refs"]) - earlier_refs
    )
    prior_actions = {attempt["action"] for attempt in equivalent}
    feasible_new_action = next_action is not None and next_action not in prior_actions
    stop = bool(equivalent and not feasible_new_action)
    _require(stop or next_action is not None, "next-action-required-unless-stopped")
    return {
        "kind": "Stage2Followup",
        "schema_version": "1.0.0",
        "packet_sha256": canonical_hash(packet),
        "snapshot_sha256": snapshot_sha256,
        "candidate_id": candidate_id,
        "candidate_version": current_version,
        "question": question,
        "decision_at_risk": copy.deepcopy(decision_at_risk),
        "needed_evidence": copy.deepcopy(needed_evidence),
        "prior_attempts": attempts,
        "next_action": next_action,
        "policy_ref": copy.deepcopy(policy_ref),
        "policy_ref_sha256": canonical_hash(policy_ref),
        "equivalent_prior_attempts": len(equivalent),
        "new_evidence_available": new_evidence,
        "feasible_new_action": feasible_new_action,
        "stop": stop,
        "human_decision_required": decision_at_risk["kind"] in {"scope", "resource"},
        "model_or_tool_success_proves_scientific_claim": False,
    }
