"""Stage1 delivery explanations from saved records, without inventing reviews."""

from copy import deepcopy

from stage1_deliverable.common import canonical, sha

from .academic_screening import (
    academic_screening_files,
    derive_academic_screening,
    rectangular_rows,
)

CONTRACT = "S1-DELIVERY-REVIEW-1.4.0"
COMPLETE_CONTRACT = "S1-DELIVERY-REVIEW-1.3.0"
PREVIOUS_CONTRACT = "S1-DELIVERY-REVIEW-1.2.0"
RECOVERY_CONTRACT = "S1-DELIVERY-REVIEW-1.1.0"
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
        "claim_assessments.csv",
        "candidate_screening.csv",
        "claim_assessments.md",
        "claim_assessments.xlsx",
    )
)


def derive_delivery_review(index, *, contract=CONTRACT):
    modern = contract != LEGACY_CONTRACT
    current = contract in {CONTRACT, COMPLETE_CONTRACT, PREVIOUS_CONTRACT}
    complete = contract in {CONTRACT, COMPLETE_CONTRACT}
    if contract not in {
        CONTRACT,
        COMPLETE_CONTRACT,
        PREVIOUS_CONTRACT,
        RECOVERY_CONTRACT,
        LEGACY_CONTRACT,
    }:
        raise ValueError("unknown delivery review contract")
    screening = derive_academic_screening(
        index,
        include_original_records=modern,
        include_new_reviews=current,
        include_retrieval_trace=contract == CONTRACT,
    )
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
            if (
                current
                and original_recovery
                and original_recovery.get("new_assessment")
            ):
                review = deepcopy(original_recovery["new_assessment"])
                row.update(
                    new_assessment=review,
                    current_relation=review["value"]["relation"],
                    historical_reason_state=row["reason_state"],
                    historical_explanation=row["explanation"],
                    reason_state="new-source-review",
                    reason_code=review["value"]["reason_code"],
                    explanation=review["value"]["rationale"],
                )
                if complete:
                    row["current_assertion"] = (
                        review["value"].get("revised_claim") or claim["text"]
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
    historical_gaps = []
    if complete and screening.get("new_candidate_screening"):
        historical_gaps.append("complete-candidate-history-not-bound")
    layout_claims = [
        r
        for r in recovery.get("claims", [])
        if any(s["state"] == "layout-reviewed-literal" for s in r["span_checks"])
    ]
    if (
        complete
        and layout_claims
        and all(r.get("new_assessment") for r in layout_claims)
    ):
        historical_gaps.append("original-note-citation-purpose-not-reestablished")
    issues = [issue for issue in issues if issue not in historical_gaps]
    return dict(
        kind="Stage1DeliveryReview",
        schema_version="1.4.0"
        if contract == CONTRACT
        else "1.3.0"
        if complete
        else "1.2.0"
        if current
        else "1.1.0"
        if modern
        else "1.0.0",
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
        **(
            dict(
                historical_gaps=historical_gaps,
                source_reassessment_complete=any("new_assessment" in c for c in claims)
                and not any(c["reason_state"] == "not-recorded" for c in claims),
                per_work_decisions_complete=bool(screening["rows"])
                and all("new_screening_review" in r for r in screening["rows"]),
                saved_observation_screening_complete=bool(
                    screening.get("new_candidate_screening")
                ),
                partial_claim_ids=[
                    c["claim_id"]
                    for c in claims
                    if c.get("current_relation") == "partial"
                ],
                independent_scientific_validation=False,
            )
            if complete
            else {}
        ),
        **(
            dict(
                new_source_review_count=sum("new_assessment" in c for c in claims),
                current_relation_counts={
                    r: sum(
                        c.get("current_relation", c["relation"]) == r for c in claims
                    )
                    for r in (
                        "supports",
                        "partial",
                        "contradicts",
                        "context",
                        "unverifiable",
                        "unverified",
                    )
                },
                new_reviews_are_historical=False,
            )
            if current
            else {}
        ),
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
            index,
            include_original_records=contract != LEGACY_CONTRACT,
            include_new_reviews=contract
            in {CONTRACT, COMPLETE_CONTRACT, PREVIOUS_CONTRACT},
            include_retrieval_trace=contract == CONTRACT,
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
    if contract != LEGACY_CONTRACT:
        files["literature/original_record_recovery.json"] = canonical(
            index.get(
                "original_record_recovery",
                dict(status="not-provided", scientific_assessment=False),
            )
        )
    if contract in {CONTRACT, COMPLETE_CONTRACT, PREVIOUS_CONTRACT}:
        from stage1_deliverable.views import csv_bytes
        from .literature_selection import _HeaderOnly

        files["literature/claim_assessments.csv"] = csv_bytes(
            "ClaimAssessments",
            rectangular_rows(result["claims"])
            or _HeaderOnly(("claim_id", "relation", "explanation")),
        )
        cohort = result["screening"].get("new_candidate_screening", {})
        files["literature/candidate_screening.csv"] = csv_bytes(
            "NewCandidateScreening",
            rectangular_rows(cohort.get("value", {}).get("rows", []))
            or _HeaderOnly(("observation_ref", "decision", "rationale")),
        )
    if contract in {CONTRACT, COMPLETE_CONTRACT}:
        from .reassessment_exports import claim_reports

        files.update(
            claim_reports(result["claims"], files["literature/claim_verification.json"])
        )
    return files
