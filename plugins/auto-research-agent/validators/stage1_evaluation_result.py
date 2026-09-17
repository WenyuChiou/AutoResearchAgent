"""Semantic validation for a Stage 1 evaluation result."""

import argparse
import json
from pathlib import Path
import sys


def _sum_matches_total(record, parts):
    return sum(record[name] for name in parts) == record["total"]


def semantic_errors(result):
    """Return cross-field errors that JSON Schema cannot express."""
    errors = []
    facts = result["fact_metrics"]

    for name in ("bibliographic_identity", "identifier_or_link"):
        if not _sum_matches_total(
            facts[name], ("correct", "incorrect", "unverifiable")
        ):
            errors.append(f"fact_metrics.{name} parts must sum to total")

    if not _sum_matches_total(
        facts["claim_support"],
        ("supported", "partial", "contradicted", "unverifiable"),
    ):
        errors.append("fact_metrics.claim_support parts must sum to total")

    coverage = facts["coverage"]
    for numerator, denominator in (
        ("clusters_hit", "clusters_total"),
        ("core_hit", "core_total"),
        ("must_have_hit", "must_have_total"),
        ("recent_works", "year_confirmed_works"),
    ):
        if coverage[numerator] > coverage[denominator]:
            errors.append(
                f"fact_metrics.coverage.{numerator} must not exceed {denominator}"
            )
    if coverage["year_confirmed_works"] == 0 and coverage["latest_year"] is not None:
        errors.append(
            "fact_metrics.coverage.latest_year must be null when no work has a "
            "confirmed year"
        )
    if coverage["year_confirmed_works"] > 0 and coverage["latest_year"] is None:
        errors.append(
            "fact_metrics.coverage.latest_year is required when a work has a "
            "confirmed year"
        )

    auditability = facts["auditability"]
    for numerator, denominator in (
        ("works_with_trace", "works_total"),
        ("claims_with_locator", "claims_total"),
        ("decisions_with_reason", "decisions_total"),
        ("versions_with_access_date", "included_works_total"),
    ):
        if auditability[numerator] > auditability[denominator]:
            errors.append(
                f"fact_metrics.auditability.{numerator} must not exceed {denominator}"
            )

    efficiency = result["efficiency"]
    if (
        efficiency["tool_calls"] is not None
        and efficiency["failed_tool_calls"] is not None
        and efficiency["failed_tool_calls"] > efficiency["tool_calls"]
    ):
        errors.append("efficiency.failed_tool_calls must not exceed tool_calls")

    for metric_id, judgment in result["judgment_scores"].items():
        scores = [judgment["R1"], judgment["R2"], judgment["ADJ"]]
        if judgment["status"] == "adjudicated" and any(
            score is None for score in scores
        ):
            errors.append(
                f"judgment_scores.{metric_id} adjudicated status requires R1, R2, "
                "and ADJ scores"
            )
        if judgment["status"] == "pending" and judgment["ADJ"] is not None:
            errors.append(
                f"judgment_scores.{metric_id} pending status requires a null ADJ score"
            )
        if judgment["status"] == "not_scored" and any(
            score is not None for score in scores
        ):
            errors.append(
                f"judgment_scores.{metric_id} not_scored status requires null scores"
            )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    errors = semantic_errors(result)
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1
    print("Stage 1 evaluation result semantics passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
