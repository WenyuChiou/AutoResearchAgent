"""Conservative offline readiness; the live coverage policy is a later slice."""


def coverage_text(checkpoint=None):
    if checkpoint is None:
        return "# Coverage and stop\n\nNo checkpoint yet; closest-work verification is incomplete.\n"
    result = checkpoint["stage_result"]
    text = "# Coverage and stop\n\n"
    text += f"Decision: {result['next_allowed_action']}\n\nClosest-work verification: incomplete.\n\n"
    text += "\n".join(f"- {reason}" for reason in result["gate"]["reasons"])
    text += f"\n\nCheckpoint: {checkpoint['event_id']}\nState SHA-256: {checkpoint['state_sha256']}\n"
    return text


def readiness(report):
    reasons = ["closest-work-unverified", "live-coverage-not-evaluated"]
    if not report["valid"]:
        reasons.insert(0, "validator-failed")
    if report["pending_actions"]:
        reasons.append("unfinished-actions")
    if report["missing_discoveries"]:
        reasons.append("extraction-incomplete")
    if report["counts"].get("backend_failures"):
        reasons.append("recorded-backend-failures-require-review")
    action = (
        "human-review"
        if not report["valid"]
        or report["counts"].get("backend_failures")
        or report["missing_discoveries"]
        else "continue"
    )
    return dict(
        kind="GateResult",
        schema_version="1.0.0",
        gate_name="stage1-offline-readiness",
        outcome="review-required",
        reasons=reasons,
        blocking_items=reasons.copy(),
        evidence_refs=[],
    ), action
