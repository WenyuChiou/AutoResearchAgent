"""Operational coverage gate with a conservative fallback for unplanned runs."""


def coverage_text(checkpoint=None):
    if checkpoint is None:
        return "# Coverage and stop\n\nNo checkpoint yet; closest-work verification is incomplete.\n"
    result = checkpoint["stage_result"]
    text = "# Coverage and stop\n\n"
    text += f"Decision: {result['next_allowed_action']}\n\n"
    if result["gate"]["gate_name"] == "stage1-coverage-readiness":
        text += "Operational coverage is based on recorded source reviews; scientific truth is not evaluated.\n\n"
        text += f"Details: {result['validator_report']['path']}\n\n"
    else:
        text += "Closest-work verification: incomplete.\n\n"
    text += "\n".join(f"- {reason}" for reason in result["gate"]["reasons"])
    text += f"\n\nCheckpoint: {checkpoint['event_id']}\nState SHA-256: {checkpoint['state_sha256']}\n"
    return text


def readiness(report):
    if report["valid"] and report.get("coverage") is not None:
        coverage = report["coverage"]
        reasons = list(coverage["blockers"])
        if report["pending_actions"]:
            reasons.append("unfinished-actions")
        if report["missing_discoveries"] and "extraction-incomplete" not in reasons:
            reasons.append("extraction-incomplete")
        action = (
            "stop-sufficient"
            if not reasons
            else "human-review"
            if coverage["budget_exhausted"]
            else "continue"
        )
        return dict(
            kind="GateResult",
            schema_version="1.0.0",
            gate_name="stage1-coverage-readiness",
            outcome="review-required" if reasons else "pass",
            blocking_items=reasons,
            reasons=reasons
            or [
                "coverage-obligations-satisfied",
                "complete-rounds-show-zero-marginal-yield",
                "operational-stop-not-exhaustive-literature-proof",
            ],
            evidence_refs=coverage["evidence_refs"],
        ), action
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
