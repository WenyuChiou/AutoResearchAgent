"""Fail-closed semantic validation for aging-bidirectional rubric judgments."""

import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
RUBRIC_PATH = EVAL_ROOT / "rubrics" / "aging-bidirectional-rubric.v1.json"
SCHEMA_PATH = EVAL_ROOT / "schemas" / "rubric-judge-result.v1.schema.json"


def _load_contract():
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    catalog_path = EVAL_ROOT / rubric["criterion_catalog"]["path"]
    catalog = [
        json.loads(line)
        for line in catalog_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    canonical_catalog = (
        catalog_path.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )
    catalog_binding = rubric["criterion_catalog"]
    if hashlib.sha256(canonical_catalog).hexdigest() != catalog_binding["sha256"]:
        raise RuntimeError("criterion catalog hash does not match the frozen rubric")
    if len(catalog) != catalog_binding["record_count"]:
        raise RuntimeError("criterion catalog count does not match the frozen rubric")
    criteria = {
        metric["id"]: set(metric["criterion_ids"]) for metric in rubric["metrics"]
    }
    major_errors = {
        metric["id"]: set(metric["major_error_ids"]) for metric in rubric["metrics"]
    }
    units = {
        metric["id"]: {
            unit["unit_type"]: unit["cardinality"]
            for unit in metric["evaluation_units"]
        }
        for metric in rubric["metrics"]
    }
    catalog_ids = {row["id"] for row in catalog}
    return schema, criteria, major_errors, units, catalog_ids, catalog_binding["sha256"]


SCHEMA, CRITERIA, MAJOR_ERRORS, UNITS, CATALOG_IDS, CATALOG_SHA256 = _load_contract()
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
STAGE_METRICS = {1: {"P1", "P2", "P3"}, 2: {"P4", "P5", "P6"}, 3: {"P7", "P8", "P9"}}
AUDIT_TRIGGERS = {
    "major-error",
    "low-confidence",
    "evidence-unverifiable",
    "judge-disagreement",
    "close-paired-result",
    "external-claim",
}


def validate_result(result):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(result), key=str)
    ]
    if errors:
        return errors

    role = result["judge"]["role"]
    if role.startswith("auto-") and not result["judge"]["condition_blinded"]:
        errors.append(f"{role} must be condition-blinded")
    adjudicates = result.get("adjudicates_evaluation_ids", [])
    if role == "auto-adj" and len(adjudicates) < 2:
        errors.append("auto-adj must name at least two adjudicated evaluation IDs")
    if role != "auto-adj" and adjudicates:
        errors.append("only auto-adj may set adjudicates_evaluation_ids")

    rows = result["metric_results"]
    stage = result["stage"]
    if result["catalog_sha256"] != CATALOG_SHA256:
        errors.append("catalog_sha256 does not match the loaded frozen catalog")
    observed_metrics = {row["metric_id"] for row in rows}
    if observed_metrics != STAGE_METRICS[stage]:
        errors.append(
            f"stage {stage} requires metrics {sorted(STAGE_METRICS[stage])}, got {sorted(observed_metrics)}"
        )

    keys = [(row["metric_id"], row["unit_type"], row["unit_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        errors.append("duplicate metric_id/unit_type/unit_id result")

    expected_units = result["expected_units"]
    if set(expected_units) != STAGE_METRICS[stage]:
        errors.append("expected_units must declare exactly the stage metrics")

    for metric_id in observed_metrics:
        metric_rows = [row for row in rows if row["metric_id"] == metric_id]
        allowed_units = UNITS[metric_id]
        declared_units = expected_units.get(metric_id, {})
        if set(declared_units) != set(allowed_units):
            errors.append(
                f"{metric_id} expected_units must declare exactly {sorted(allowed_units)}"
            )
        for row in metric_rows:
            if row["unit_type"] not in allowed_units:
                errors.append(
                    f"{metric_id} does not allow unit_type {row['unit_type']}"
                )
            _validate_metric_row(row, errors)
        for unit_type, cardinality in allowed_units.items():
            actual_ids = {
                row["unit_id"] for row in metric_rows if row["unit_type"] == unit_type
            }
            declared_ids = set(declared_units.get(unit_type, []))
            if actual_ids != declared_ids:
                errors.append(
                    f"{metric_id}/{unit_type} results must exactly match expected unit IDs"
                )
            if cardinality == "exactly-one" and len(declared_ids) != 1:
                errors.append(
                    f"{metric_id}/{unit_type} requires exactly one expected unit"
                )
            if cardinality.startswith("one-per-") and not declared_ids:
                errors.append(
                    f"{metric_id}/{unit_type} requires at least one expected unit"
                )

    if stage == 1:
        _validate_p1_summary(rows, errors)
    if stage == 2:
        p5_ids = {
            row["unit_id"]
            for row in rows
            if row["metric_id"] == "P5" and row["unit_type"] == "research_direction"
        }
        p6_ids = {
            row["unit_id"]
            for row in rows
            if row["metric_id"] == "P6" and row["unit_type"] == "research_direction"
        }
        if p5_ids != p6_ids:
            errors.append(
                "P5 and P6 must evaluate the same research_direction unit_ids"
            )
        if len(p5_ids) < 2:
            errors.append("Stage 2 requires at least two research directions")
        recommendation = next(
            (
                row
                for row in rows
                if row["metric_id"] == "P6"
                and row["unit_type"] == "final_recommendation"
            ),
            None,
        )
        direction_scores = [
            row["score"]
            for row in rows
            if row["metric_id"] == "P6" and row["unit_type"] == "research_direction"
        ]
        if recommendation and direction_scores:
            if recommendation["score"] > min(direction_scores):
                errors.append(
                    "P6 final recommendation cannot exceed the lowest direction score"
                )

    triggers = set(result["audit_trigger_ids"])
    unknown_triggers = triggers - AUDIT_TRIGGERS
    if unknown_triggers:
        errors.append(f"unknown audit trigger IDs: {sorted(unknown_triggers)}")
    row_review_required = any(row["needs_human_review"] for row in rows)
    audit_required = row_review_required or bool(triggers)
    if result["requires_human_audit"] != audit_required:
        errors.append("requires_human_audit must match result and trigger state")
    if role == "auto-adj" and "judge-disagreement" not in triggers:
        errors.append("auto-adj requires the judge-disagreement audit trigger")
    if row_review_required and not triggers:
        errors.append("audit_trigger_ids must identify why human review is required")
    if any(row["major_error_ids"] for row in rows) and "major-error" not in triggers:
        errors.append("major-error trigger is required")
    if (
        any(row["confidence"] == "low" for row in rows)
        and "low-confidence" not in triggers
    ):
        errors.append("low-confidence trigger is required")
    if (
        any(
            row["hard_fact_status"] == "unverifiable"
            or row["missing_evidence"]
            or any(
                item["outcome"] == "unverifiable" for item in row["criterion_results"]
            )
            for row in rows
        )
        and "evidence-unverifiable" not in triggers
    ):
        errors.append("evidence-unverifiable trigger is required")
    return errors


def _validate_metric_row(row, errors):
    metric_id = row["metric_id"]
    criterion_rows = row["criterion_results"]
    criterion_ids = [item["criterion_id"] for item in criterion_rows]
    if len(criterion_ids) != len(set(criterion_ids)):
        errors.append(f"{metric_id}/{row['unit_id']} has duplicate criterion IDs")
    if set(criterion_ids) != CRITERIA[metric_id]:
        errors.append(
            f"{metric_id}/{row['unit_id']} criterion IDs must exactly match the frozen rubric"
        )
    invalid_errors = set(row["major_error_ids"]) - MAJOR_ERRORS[metric_id]
    if invalid_errors or not set(row["major_error_ids"]).issubset(CATALOG_IDS):
        errors.append(
            f"{metric_id}/{row['unit_id']} has unknown or cross-metric major error IDs"
        )

    outcomes = {item["outcome"] for item in criterion_rows}
    for item in criterion_rows:
        if item["outcome"] in {"pass", "partial", "fail"} and not item["evidence_ids"]:
            errors.append(
                f"{metric_id}/{row['unit_id']}/{item['criterion_id']} requires evidence_ids"
            )

    must_review = bool(row["major_error_ids"] or row["missing_evidence"])
    must_review |= row["confidence"] == "low"
    must_review |= row["hard_fact_status"] == "unverifiable"
    must_review |= "unverifiable" in outcomes
    if must_review and not row["needs_human_review"]:
        errors.append(f"{metric_id}/{row['unit_id']} must request human review")

    if row["major_error_ids"] and row["score"] != 0:
        errors.append(f"{metric_id}/{row['unit_id']} major errors force score 0")
    if row["hard_fact_status"] == "fail" and row["score"] != 0:
        errors.append(f"{metric_id}/{row['unit_id']} hard-fact failure forces score 0")
    if (
        row["hard_fact_status"] == "unverifiable"
        or row["missing_evidence"]
        or "unverifiable" in outcomes
    ) and row["score"] > 1:
        errors.append(
            f"{metric_id}/{row['unit_id']} unverifiable evidence caps score at 1"
        )

    if row["score"] == 2:
        if row["hard_fact_status"] != "pass" or row["missing_evidence"]:
            errors.append(
                f"{metric_id}/{row['unit_id']} score 2 requires complete hard evidence"
            )
        if outcomes - {"pass", "not-applicable"}:
            errors.append(
                f"{metric_id}/{row['unit_id']} score 2 requires all applicable criteria to pass"
            )
        if "pass" not in outcomes:
            errors.append(
                f"{metric_id}/{row['unit_id']} score 2 requires at least one applicable passing criterion"
            )
    if "fail" in outcomes and row["score"] != 0:
        errors.append(f"{metric_id}/{row['unit_id']} failed criterion forces score 0")
    if row["score"] == 0 and not (
        row["major_error_ids"]
        or row["hard_fact_status"] == "fail"
        or "fail" in outcomes
    ):
        errors.append(f"{metric_id}/{row['unit_id']} score 0 needs a recorded failure")
    if row["score"] == 1 and not (
        row["hard_fact_status"] == "unverifiable"
        or row["missing_evidence"]
        or outcomes.intersection({"partial", "unverifiable"})
    ):
        errors.append(
            f"{metric_id}/{row['unit_id']} score 1 needs a partial or unverifiable result"
        )


def _validate_p1_summary(rows, errors):
    p1_rows = [row for row in rows if row["metric_id"] == "P1"]
    summary = next(
        (row for row in p1_rows if row["unit_type"] == "stage_summary"), None
    )
    items = [row for row in p1_rows if row["unit_type"] != "stage_summary"]
    if summary is None or not items:
        return
    if summary["score"] > min(row["score"] for row in items):
        errors.append("P1 stage_summary cannot exceed its lowest central item score")
    if any(row["major_error_ids"] for row in items) and summary["score"] != 0:
        errors.append(
            "P1 stage_summary must be 0 when a central item has a major error"
        )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: rubric_judge_result.py RESULT.json", file=sys.stderr)
        return 2
    result = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    errors = validate_result(result)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Rubric judge result is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
