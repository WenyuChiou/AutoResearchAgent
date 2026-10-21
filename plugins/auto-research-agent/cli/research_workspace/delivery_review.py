"""Stage1 delivery explanations from saved records, without inventing reviews."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha

from .academic_screening import academic_screening_files, derive_academic_screening

CONTRACT = "S1-DELIVERY-REVIEW-1.1.0"
LEGACY_CONTRACT = "S1-DELIVERY-REVIEW-1.0.0"
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
        "original_record_recovery.json",
    )
)


def derive_delivery_review(index, *, contract=CONTRACT):
    modern = contract == CONTRACT
    if contract not in {CONTRACT, LEGACY_CONTRACT}:
        raise ValueError("unknown delivery review contract")
    screening = derive_academic_screening(index, include_original_records=modern)
    recovery = index.get("original_record_recovery", {}).get("payload", {})
    recovered_claims = {r["claim_id"]: r for r in recovery.get("claims", [])}
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
        if modern:
            row = claims[-1]
            original_recovery = recovered_claims.get(claim.get("claim_id"))
            row.update(
                original_claim=deepcopy(claim),
                original_claim_pointer=f"/claims/{position}",
                historical_recovery=deepcopy(original_recovery),
            )
            if (
                not assessment
                and original_recovery
                and original_recovery["historical_reason"]
            ):
                row.update(
                    reason_state="recovered-record",
                    reason_code="saved-prior-assessment-reason",
                    explanation=original_recovery["historical_reason"]["value"],
                )
    issues = []
    if screening["count_scope"] != "bound-run":
        issues.append("complete-candidate-history-not-bound")
    if any(r["reason_review_required"] for r in screening["rows"]):
        issues.append("per-work-screening-reason-review-required")
    if any(r["reason_state"] == "not-recorded" for r in claims):
        issues.append("claim-assessment-reasons-missing")
    if modern and any(
        s["state"] in {"ambiguous", "quote-not-found"}
        for r in recovery.get("claims", [])
        for s in r["span_checks"]
    ):
        issues.append("saved-note-spans-unresolved")
    if modern and any(
        s["state"] == "layout-reviewed-literal"
        for r in recovery.get("claims", [])
        for s in r["span_checks"]
    ):
        issues.append("original-note-citation-purpose-not-reestablished")
    return dict(
        kind="Stage1DeliveryReview",
        schema_version="1.1.0" if modern else "1.0.0",
        contract_version=contract,
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


def delivery_review_files(index, *, contract=CONTRACT):
    result = derive_delivery_review(index, contract=contract)
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
    files = {
        **academic_screening_files(
            index, include_original_records=contract == CONTRACT
        ),
        "literature/claim_verification.json": canonical(
            dict(
                contract_version=contract,
                input_canonical_sha256=result["input_canonical_sha256"],
                rows=result["claims"],
            )
        ),
        "literature/delivery_review.json": canonical(summary),
    }
    if contract == CONTRACT:
        files["literature/original_record_recovery.json"] = canonical(
            index.get(
                "original_record_recovery",
                dict(status="not-provided", scientific_assessment=False),
            )
        )
    return files
