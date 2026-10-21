"""Stage1 delivery explanations from saved records, without inventing reviews."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha

from .academic_screening import academic_screening_files, derive_academic_screening

CONTRACT = "S1-DELIVERY-REVIEW-1.0.0"
FILES = frozenset(
    "literature/" + name
    for name in (
        "academic_screening.json",
        "academic_screening.csv",
        "academic_screening.md",
        "academic_screening.xlsx",
        "academic_screening_history.csv",
        "claim_verification.json",
        "delivery_review.json",
    )
)


def derive_delivery_review(index):
    screening = derive_academic_screening(index)
    claims = []
    for position, claim in enumerate(index["claims"]):
        event = (claim.get("core_event") or {}).get("payload", {})
        assessment = event.get("assessment")
        relation = claim.get("relation", claim.get("support", "Unknown"))
        claims.append(
            dict(
                claim_id=claim.get("claim_id"),
                work_id=claim.get("work_id"),
                version_id=claim.get("version_id"),
                relation=relation,
                assessment=deepcopy(assessment),
                reason_state="recorded" if assessment else "not-recorded",
                reason_code=assessment["reason_code"]
                if assessment
                else "assessment-reason-not-recorded",
                explanation=assessment["rationale"]
                if assessment
                else "The saved claim has no assessment rationale. Its unresolved cause cannot be inferred from a quote, readable source or parser status; review the assertion against its exact source.",
                provenance=dict(
                    records_sha256=index["provenance"]["records_sha256"],
                    pointer=f"/claims/{position}/core_event/payload/assessment"
                    if assessment
                    else f"/claims/{position}",
                ),
                source_observations=[
                    dict(
                        source_id=s.get("source_id"),
                        receipt=deepcopy(s.get("receipt")),
                        reading=deepcopy(s.get("reading")),
                    )
                    for s in index["sources"]
                    if s.get("source_id") == claim.get("source_id")
                ],
                source_observation_is_not_assessment_reason=True,
            )
        )
    issues = []
    if screening["count_scope"] != "bound-run":
        issues.append("complete-candidate-history-not-bound")
    if any(r["reason_review_required"] for r in screening["rows"]):
        issues.append("per-work-screening-reason-review-required")
    if any(r["reason_state"] == "not-recorded" for r in claims):
        issues.append("claim-assessment-reasons-missing")
    return dict(
        kind="Stage1DeliveryReview",
        schema_version="1.0.0",
        contract_version=CONTRACT,
        input_canonical_sha256=sha(canonical(index)),
        records_sha256=index["provenance"]["records_sha256"],
        screening=screening,
        claims=claims,
        repair_required=issues,
        review_complete=False,
        scientific_assessment=False,
        stage1_completed=False,
        official_stage2_import_eligible=False,
    )


def delivery_review_files(index):
    result = derive_delivery_review(index)
    summary = {k: v for k, v in result.items() if k not in {"screening", "claims"}}
    summary.update(
        screening_counts=result["screening"]["counts"],
        count_scope=result["screening"]["count_scope"],
        library_counts=result["screening"]["library_counts"],
        claim_count=len(result["claims"]),
        missing_claim_reason_count=sum(
            r["reason_state"] == "not-recorded" for r in result["claims"]
        ),
    )
    return {
        **academic_screening_files(index),
        "literature/claim_verification.json": canonical(
            dict(
                contract_version=CONTRACT,
                input_canonical_sha256=result["input_canonical_sha256"],
                rows=result["claims"],
            )
        ),
        "literature/delivery_review.json": canonical(summary),
    }
