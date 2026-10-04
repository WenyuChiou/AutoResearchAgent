"""Deterministic admission for the supplemental source-context QA bundle.

The 12 cases complement the historical 72-presentation v3 calibration. They do
not change its cases, denominators, or report, and they do not establish live or
formal readiness.
"""

from collections import Counter
from copy import deepcopy

from stage2_common import Stage2Error, canonical_hash

from .rubric_quality_v3 import evaluate_quality_v3, validate_quality_batch


FAMILY_CRITERIA = {
    "attribution": "P4V3.FIDELITY",
    "existence": "P4V3.FIDELITY",
    "policy-exception": "P6V3.FEASIBILITY",
}
POLARITIES = {"positive", "negative"}


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"missing {label}")


def _signature(row):
    return row["status"], row["score"], row["major_error"]


def validate_context_quality_inputs(dataset, reference):
    """Validate the fixed 12-case dataset and its separate answer reference."""

    _require(isinstance(dataset, dict), "context-quality-dataset-must-be-object")
    _require(
        set(dataset) == {"kind", "schema_version", "cases"},
        "context-quality-unexpected-dataset-fields",
    )
    _require(
        dataset.get("kind") == "Stage2SourceContextQualityDataset"
        and dataset.get("schema_version") == "1.0.0",
        "context-quality-dataset-version",
    )
    cases = dataset.get("cases")
    _require(
        isinstance(cases, list) and len(cases) == 12,
        "context-quality-requires-12-cases",
    )

    by_id = {}
    evidence_ids = set()
    family_polarities = Counter()
    for case in cases:
        _require(isinstance(case, dict), "context-quality-case-must-be-object")
        _require(
            set(case)
            == {
                "case_id",
                "family",
                "polarity",
                "criterion_id",
                "facts",
                "subject_record",
            },
            "context-quality-unexpected-case-fields",
        )
        case_id = case.get("case_id")
        _text(case_id, "context-quality case ID")
        _require(case_id not in by_id, "context-quality-duplicate-case")
        family = case.get("family")
        _require(
            isinstance(family, str) and family in FAMILY_CRITERIA,
            "context-quality-unknown-family",
        )
        polarity = case.get("polarity")
        _require(
            isinstance(polarity, str) and polarity in POLARITIES,
            "context-quality-unknown-polarity",
        )
        _require(
            case.get("criterion_id") == FAMILY_CRITERIA[family],
            "context-quality-family-criterion-mismatch",
        )
        facts = case.get("facts")
        _require(
            isinstance(facts, list) and bool(facts),
            "context-quality-facts-required",
        )
        local_ids = []
        for fact in facts:
            _require(
                isinstance(fact, dict) and set(fact) == {"evidence_id", "text"},
                "context-quality-invalid-fact",
            )
            _text(fact.get("evidence_id"), "context-quality evidence ID")
            _text(fact.get("text"), "context-quality fact text")
            local_ids.append(fact["evidence_id"])
        _require(
            len(local_ids) == len(set(local_ids)),
            "context-quality-duplicate-case-evidence",
        )
        _require(
            evidence_ids.isdisjoint(local_ids),
            "context-quality-duplicate-bundle-evidence",
        )
        evidence_ids.update(local_ids)
        _require(
            isinstance(case.get("subject_record"), dict)
            and set(case["subject_record"]) == {"text"},
            "context-quality-subject-record-content-fields-only",
        )
        _text(case["subject_record"]["text"], "context-quality subject text")
        _require(
            len(case["subject_record"]["text"]) <= 12000,
            "context-quality-subject-text-too-large",
        )
        canonical_hash(case["subject_record"])
        by_id[case_id] = case
        family_polarities[(family, polarity)] += 1

    _require(
        Counter(case["family"] for case in cases)
        == {family: 4 for family in FAMILY_CRITERIA},
        "context-quality-requires-four-cases-per-family",
    )
    _require(
        family_polarities
        == Counter(
            {
                (family, polarity): 2
                for family in FAMILY_CRITERIA
                for polarity in POLARITIES
            }
        ),
        "context-quality-requires-two-cases-per-family-polarity",
    )

    _require(isinstance(reference, dict), "context-quality-reference-must-be-object")
    _require(
        set(reference) == {"kind", "schema_version", "judgments"},
        "context-quality-unexpected-reference-fields",
    )
    _require(
        reference.get("kind") == "Stage2SourceContextQualityReference"
        and reference.get("schema_version") == "1.0.0",
        "context-quality-reference-version",
    )
    judgments = reference.get("judgments")
    _require(
        isinstance(judgments, list) and len(judgments) == 12,
        "context-quality-reference-requires-12-cases",
    )
    reference_by_id = {}
    for row in judgments:
        _require(isinstance(row, dict), "context-quality-reference-row-must-be-object")
        _require(
            set(row)
            == {
                "case_id",
                "status",
                "score",
                "major_error",
                "reason",
                "critical",
            },
            "context-quality-unexpected-reference-row-fields",
        )
        case_id = row.get("case_id")
        _require(
            isinstance(case_id, str)
            and case_id in by_id
            and case_id not in reference_by_id,
            "context-quality-reference-case-mismatch",
        )
        status = row.get("status")
        _require(
            isinstance(status, str) and status in {"scored", "unknown"},
            "context-quality-reference-status",
        )
        if status == "scored":
            _require(
                type(row.get("score")) is int and row["score"] in {0, 1, 2},
                "context-quality-reference-score",
            )
            _require(
                type(row.get("major_error")) is bool,
                "context-quality-reference-major-error",
            )
        else:
            _require(
                row.get("score") is None and row.get("major_error") is None,
                "context-quality-unknown-reference-must-be-null",
            )
        _text(row.get("reason"), "context-quality reference reason")
        _require(
            type(row.get("critical")) is bool,
            "context-quality-reference-critical-flag",
        )
        reference_by_id[case_id] = row
    _require(
        set(reference_by_id) == set(by_id),
        "context-quality-reference-case-mismatch",
    )
    return by_id, reference_by_id


def evaluate_context_quality(dataset, reference, r1, r2):
    """Assess 24 fixed judgments without shrinking any denominator."""

    cases, refs = validate_context_quality_inputs(dataset, reference)
    roles = {}
    ordered_cases = list(cases.values())
    for role, batch in (("R1", r1), ("R2", r2)):
        validate_quality_batch(batch, role, ordered_cases)
        roles[role] = {row["case_id"]: row for row in batch["judgments"]}

    family_hits = Counter()
    mismatches = []
    disagreements = []
    critical_errors = []
    unresolved_major_errors = []
    evaluator_failures = []
    for case_id, case in cases.items():
        expected = refs[case_id]
        for role in ("R1", "R2"):
            actual = roles[role][case_id]
            matches = _signature(actual) == _signature(expected)
            family_hits[case["family"]] += int(matches)
            if not matches:
                mismatches.append(
                    {
                        "case_id": case_id,
                        "role": role,
                        "family": case["family"],
                        "expected": deepcopy(expected),
                        "actual": deepcopy(actual),
                    }
                )
                if expected["critical"]:
                    critical_errors.append({"case_id": case_id, "role": role})
            if actual["status"] == "evaluator_failure":
                evaluator_failures.append({"case_id": case_id, "role": role})

        r1_row, r2_row = roles["R1"][case_id], roles["R2"][case_id]
        if _signature(r1_row) != _signature(r2_row):
            disagreements.append(case_id)
            if r1_row["major_error"] != r2_row["major_error"]:
                unresolved_major_errors.append(
                    {
                        "case_id": case_id,
                        "R1": r1_row["major_error"],
                        "R2": r2_row["major_error"],
                    }
                )

    per_family = {
        family: {
            "matched": family_hits[family],
            "required": 8,
            "percent": 100 * family_hits[family] / 8,
        }
        for family in FAMILY_CRITERIA
    }
    matched = sum(family_hits.values())
    agreement = sum(
        roles["R1"][case_id]["status"] != "evaluator_failure"
        and roles["R2"][case_id]["status"] != "evaluator_failure"
        and _signature(roles["R1"][case_id]) == _signature(roles["R2"][case_id])
        for case_id in cases
    )
    passed = (
        matched / 24 >= 0.90
        and all(row["percent"] >= 90 for row in per_family.values())
        and agreement / 12 >= 0.85
        and not critical_errors
        and not unresolved_major_errors
        and not evaluator_failures
    )
    return {
        "kind": "Stage2SourceContextQualityReport",
        "schema_version": "1.0.0",
        "dataset_sha256": canonical_hash(dataset),
        "reference_sha256": canonical_hash(reference),
        "r1_sha256": canonical_hash(r1),
        "r2_sha256": canonical_hash(r2),
        "cases": 12,
        "designated_judgments": 24,
        "overall": {
            "matched": matched,
            "required": 24,
            "percent": 100 * matched / 24,
        },
        "per_family": per_family,
        "agreement": {
            "matched": agreement,
            "required": 12,
            "percent": 100 * agreement / 12,
        },
        "mismatches": mismatches,
        "unresolved_disagreements": disagreements,
        "critical_errors": critical_errors,
        "unresolved_major_errors": unresolved_major_errors,
        "evaluator_failures": evaluator_failures,
        "reviewer_judgments": {
            "R1": deepcopy(r1["judgments"]),
            "R2": deepcopy(r2["judgments"]),
        },
        "passed": passed,
        "diagnostic_only": True,
    }


def prepare_context_quality_input(dataset, reference, role):
    """Return reviewer content separately from the private alias mapping.

    Reference scores, polarity, family and original identifiers never appear in
    the returned reviewer payload. The mapping stays at the evaluation host.
    This is context minimization, not proof of filesystem isolation.
    """
    cases, _ = validate_context_quality_inputs(dataset, reference)
    _require(role in ("R1", "R2"), "context-quality-reviewer-role")
    payload, mapping = [], {}
    for index, case in enumerate(cases.values(), 1):
        alias = f"case-{index:03d}"
        fact_mapping = {
            f"evidence-{number:03d}": fact["evidence_id"]
            for number, fact in enumerate(case["facts"], 1)
        }
        mapping[alias] = {"case_id": case["case_id"], "evidence_ids": fact_mapping}
        payload.append(
            {
                "case_id": alias,
                "criterion_id": case["criterion_id"],
                "facts": [
                    {"evidence_id": key, "text": fact["text"]}
                    for key, fact in zip(fact_mapping, case["facts"], strict=True)
                ],
                "subject_record": deepcopy(case["subject_record"]),
            }
        )
    return {"role": role, "cases": payload}, mapping


def _recompute_core(bundle):
    _require(isinstance(bundle, dict), "core-quality-bundle-must-be-object")
    _require(
        set(bundle) == {"dataset", "reference", "rubric", "r1", "r2", "report"},
        "core-quality-bundle-requires-original-inputs",
    )
    report = evaluate_quality_v3(
        bundle["dataset"],
        bundle["reference"],
        bundle["rubric"],
        bundle["r1"],
        bundle["r2"],
    )
    _require(
        bundle["report"] == report,
        "core-quality-report-does-not-match-recomputation",
    )
    return report


def _recompute_context(bundle):
    _require(isinstance(bundle, dict), "context-quality-bundle-must-be-object")
    _require(
        set(bundle) == {"dataset", "reference", "r1", "r2", "report"},
        "context-quality-bundle-requires-original-inputs",
    )
    report = evaluate_context_quality(
        bundle["dataset"], bundle["reference"], bundle["r1"], bundle["r2"]
    )
    _require(
        bundle["report"] == report,
        "context-quality-report-does-not-match-recomputation",
    )
    return report


def combine_quality_acceptance(core_result, context_result):
    """Replay and bind the historical and supplemental deterministic QA gates."""

    core = _recompute_core(core_result)
    context = _recompute_context(context_result)
    core_shape = (
        core.get("presentations") == 72 and core.get("designated_judgments") == 144
    )
    context_shape = (
        context.get("cases") == 12 and context.get("designated_judgments") == 24
    )
    context_thresholds = (
        context["overall"]["percent"] >= 90
        and all(row["percent"] >= 90 for row in context["per_family"].values())
        and context["agreement"]["percent"] >= 85
        and not context["critical_errors"]
        and not context["unresolved_major_errors"]
        and not context["evaluator_failures"]
    )
    qa_pass = (
        core_shape
        and context_shape
        and core["passed"]
        and context["passed"]
        and context_thresholds
    )
    return {
        "kind": "Stage2CombinedQualityAcceptance",
        "schema_version": "1.0.0",
        "evidence_class": "deterministic-mechanics-only",
        "core": {
            "report_sha256": canonical_hash(core),
            "dataset_sha256": core["dataset_sha256"],
            "reference_sha256": core["reference_sha256"],
            "r1_sha256": canonical_hash(core_result["r1"]),
            "r2_sha256": canonical_hash(core_result["r2"]),
            "status": "passed" if core["passed"] and core_shape else "failed",
            "presentations": 72,
            "designated_judgments": 144,
        },
        "context": {
            "report_sha256": canonical_hash(context),
            "dataset_sha256": context["dataset_sha256"],
            "reference_sha256": context["reference_sha256"],
            "r1_sha256": context["r1_sha256"],
            "r2_sha256": context["r2_sha256"],
            "status": (
                "passed"
                if context["passed"] and context_shape and context_thresholds
                else "failed"
            ),
            "cases": 12,
            "designated_judgments": 24,
        },
        "presentations": 84,
        "designated_judgments": 168,
        "qa_pass": qa_pass,
    }


__all__ = [
    "combine_quality_acceptance",
    "evaluate_context_quality",
    "prepare_context_quality_input",
    "validate_context_quality_inputs",
]
