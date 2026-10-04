"""Deterministic validation and scoring for private rubric-quality calibration."""

from copy import deepcopy

from stage2_common import Stage2Error, canonical_hash
from .evaluation import CRITERIA

TRANSFORMATIONS = ("order", "length", "prestige", "preference")


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _text(value, label):
    _require(isinstance(value, str) and value.strip(), f"missing {label}")


def _hash(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        f"invalid {label}",
    )


def validate_dataset(dataset, expected_sha256):
    """Validate the frozen 28-anchor/28-variant private dataset and its hash."""
    _require(isinstance(dataset, dict), "dataset must be an object")
    _hash(expected_sha256, "external dataset hash")
    _require(canonical_hash(dataset) == expected_sha256, "dataset hash mismatch")
    _require(
        set(dataset) == {"kind", "schema_version", "cases"}, "unexpected dataset fields"
    )
    _require(dataset.get("kind") == "Stage2RubricQualityDataset", "wrong dataset kind")
    version = dataset.get("schema_version")
    _require(isinstance(version, str), "wrong dataset version")
    _require(version in {"1.0.0", "1.1.0"}, "wrong dataset version")
    cases = dataset.get("cases")
    _require(isinstance(cases, list) and len(cases) == 56, "dataset needs 56 cases")
    by_id = {}
    anchors = []
    variants = []
    for case in cases:
        _require(isinstance(case, dict), "case must be an object")
        case_fields = {
            "case_id",
            "criterion_id",
            "base_case_id",
            "transformation",
            "facts",
            "presentation",
        }
        if version == "1.1.0":
            case_fields.add("observation")
        _require(set(case) == case_fields, "unexpected case fields")
        case_id = case.get("case_id")
        _text(case_id, "case ID")
        _require(case_id not in by_id, "duplicate case ID")
        _require(case.get("criterion_id") in CRITERIA, "unknown criterion ID")
        _text(case.get("presentation"), "case presentation")
        facts = case.get("facts")
        _require(isinstance(facts, list) and facts, "case facts missing")
        fact_ids = []
        for fact in facts:
            _require(isinstance(fact, dict), "fact must be an object")
            _require(set(fact) == {"evidence_id", "text"}, "unexpected fact fields")
            _text(fact.get("evidence_id"), "evidence ID")
            _text(fact.get("text"), "fact text")
            fact_ids.append(fact["evidence_id"])
        _require(len(fact_ids) == len(set(fact_ids)), "duplicate evidence ID")
        if version == "1.1.0":
            observation = case["observation"]
            _require(
                isinstance(observation, dict)
                and set(observation) == {"status", "record_ref"},
                "invalid observation",
            )
            _require(
                isinstance(observation.get("status"), str)
                and observation.get("status")
                in {"observed", "unavailable", "verified-absent"},
                "invalid observation status",
            )
            _text(observation.get("record_ref"), "observation record reference")
        base, transform = case.get("base_case_id"), case.get("transformation")
        if base is None:
            _require(transform is None, "anchor cannot have a transformation")
            anchors.append(case)
        else:
            _text(base, "variant base case ID")
            _require(transform in TRANSFORMATIONS, "invalid transformation")
            variants.append(case)
        by_id[case_id] = case
    _require(
        len(anchors) == len(variants) == 28, "dataset needs 28 anchors and variants"
    )
    for criterion in CRITERIA:
        _require(
            sum(row["criterion_id"] == criterion for row in anchors) == 4,
            "each criterion needs four anchors",
        )
    grouped = {}
    for row in variants:
        base = by_id.get(row["base_case_id"])
        _require(base in anchors, "variant base must be an anchor")
        _require(
            row["criterion_id"] == base["criterion_id"], "variant criterion changed"
        )
        _require(row["facts"] == base["facts"], "variant facts differ from anchor")
        if version == "1.1.0":
            _require(
                row["observation"] == base["observation"],
                "variant observation differs from anchor",
            )
        grouped.setdefault(base["case_id"], []).append(row["transformation"])
    _require(len(grouped) == 7, "variants must use exactly seven anchors")
    _require(
        all(sorted(value) == sorted(TRANSFORMATIONS) for value in grouped.values()),
        "each chosen anchor needs four different transformations",
    )
    _require(
        {by_id[key]["criterion_id"] for key in grouped} == set(CRITERIA),
        "chosen variant anchors must cover all criteria",
    )
    return by_id


def validate_reference(reference, expected_sha256, cases):
    """Validate the private answer key separately from promptable case data."""
    _require(isinstance(reference, dict), "reference must be an object")
    _hash(expected_sha256, "external reference hash")
    _require(canonical_hash(reference) == expected_sha256, "reference hash mismatch")
    _require(
        set(reference) == {"kind", "schema_version", "rows"},
        "unexpected reference fields",
    )
    _require(
        reference.get("kind") == "Stage2RubricQualityReference", "wrong reference kind"
    )
    _require(reference.get("schema_version") == "1.0.0", "wrong reference version")
    rows = reference.get("rows")
    _require(isinstance(rows, list) and len(rows) == 56, "reference needs 56 rows")
    by_id = {}
    for row in rows:
        case_id = row.get("case_id") if isinstance(row, dict) else None
        _require(isinstance(case_id, str), "reference invalid case ID")
        _require(
            isinstance(row, dict)
            and set(row)
            == {"case_id", "status", "allowed_scores", "major_error", "critical"},
            "unexpected reference row fields",
        )
        _require(
            isinstance(case_id, str) and case_id in cases and case_id not in by_id,
            "unknown or duplicate reference case",
        )
        status, scores, major = (
            row.get("status"),
            row.get("allowed_scores"),
            row.get("major_error"),
        )
        _require(
            isinstance(status, str) and status in {"scored", "unknown"},
            "invalid reference status",
        )
        _require(isinstance(scores, list) and scores, "allowed scores missing")
        if status == "scored":
            _require(
                all(type(score) is int and score in {0, 1, 2} for score in scores),
                "invalid scored reference",
            )
            _require(len(scores) == len(set(scores)), "duplicate allowed score")
            _require(type(major) is bool, "scored reference needs major-error truth")
        else:
            _require(
                scores == [None] and major is None, "unknown reference must be null"
            )
        _require(type(row.get("critical")) is bool, "critical flag missing")
        by_id[case_id] = row
    _require(set(by_id) == set(cases), "reference cases do not match dataset")
    expected_anchors = {
        ("scored", (0,)),
        ("scored", (1,)),
        ("scored", (2,)),
        ("unknown", (None,)),
    }
    for criterion in CRITERIA:
        anchor_rows = [
            by_id[case_id]
            for case_id, case in cases.items()
            if case["criterion_id"] == criterion and case["base_case_id"] is None
        ]
        coverage = {
            (row["status"], tuple(row["allowed_scores"])) for row in anchor_rows
        }
        _require(
            len(anchor_rows) == 4 and coverage == expected_anchors,
            "each criterion needs exact 0/1/2/unknown anchor references",
        )
    for case_id, case in cases.items():
        base_id = case.get("base_case_id")
        if base_id is not None:
            base, variant = by_id[base_id], by_id[case_id]
            _require(
                (variant["status"], variant["allowed_scores"], variant["major_error"])
                == (base["status"], base["allowed_scores"], base["major_error"]),
                "variant reference differs from anchor",
            )
    return by_id


def validate_judgment(row, case):
    _require(
        isinstance(row, dict) and row.get("case_id") == case["case_id"],
        "judgment case mismatch",
    )
    _require(
        set(row)
        == {"case_id", "status", "score", "evidence_ids", "reason", "major_error"},
        "unexpected judgment fields",
    )
    status = row.get("status")
    _require(
        isinstance(status, str)
        and status in {"scored", "unknown", "evaluator_failure"},
        "invalid judgment status",
    )
    _text(row.get("reason"), "judgment reason")
    evidence = row.get("evidence_ids")
    allowed = {fact["evidence_id"] for fact in case["facts"]}
    _require(
        isinstance(evidence, list) and all(isinstance(item, str) for item in evidence),
        "invalid evidence IDs",
    )
    _require(len(evidence) == len(set(evidence)), "invalid evidence IDs")
    _require(set(evidence).issubset(allowed), "judgment cites another case")
    if status == "scored":
        _require(
            type(row.get("score")) is int and row["score"] in {0, 1, 2},
            "scored judgment needs 0-2",
        )
        _require(bool(evidence), "scored judgment needs evidence")
        _require(
            type(row.get("major_error")) is bool,
            "scored judgment needs major-error decision",
        )
    else:
        _require(
            row.get("score") is None and row.get("major_error") is None,
            "unscored judgment must be null",
        )
    if case.get("observation", {}).get("status") == "unavailable":
        _require(status == "unknown", "unavailable subject record must remain unknown")
    return None


def _role_rows(result, role, cases, expected_bindings):
    _require(
        isinstance(result, dict) and result.get("role") == role,
        f"invalid {role} result",
    )
    _require(result.get("bindings") == expected_bindings, f"{role} bindings mismatch")
    rows = result.get("judgments")
    _require(isinstance(rows, list), f"{role} judgments missing")
    by_id = {}
    for row in rows:
        case_id = row.get("case_id") if isinstance(row, dict) else None
        _require(isinstance(case_id, str), f"{role} invalid case ID")
        _require(
            case_id in cases and case_id not in by_id,
            f"{role} duplicate or unknown case",
        )
        validate_judgment(row, cases[case_id])
        by_id[case_id] = row
    return by_id


def _validate_bindings(bindings, *, guidance_required=False):
    _require(isinstance(bindings, dict), "quality bindings missing")
    for field in (
        "rubric_sha256",
        "code_sha256",
        "runtime_sha256",
        "execution_policy_sha256",
    ):
        _hash(bindings.get(field), field)
    if guidance_required:
        _hash(bindings.get("guidance_sha256"), "guidance_sha256")
    _text(bindings.get("model"), "model binding")
    _text(bindings.get("reasoning"), "reasoning binding")
    homes = bindings.get("evaluator_homes")
    _require(
        isinstance(homes, dict) and set(homes) == {"R1", "R2"},
        "evaluator-home bindings missing",
    )
    _require(
        all(isinstance(value, str) and value for value in homes.values()),
        "invalid evaluator-home binding",
    )
    _require(len(set(homes.values())) == 2, "evaluator homes are not independent")


def evaluate_quality(
    dataset, reference, r1, r2, *, dataset_sha256, reference_sha256, bindings
):
    """Compute fixed-denominator gates; incomplete outputs never shrink denominators."""
    cases = validate_dataset(dataset, dataset_sha256)
    refs = validate_reference(reference, reference_sha256, cases)
    expected = deepcopy(bindings)
    _validate_bindings(expected, guidance_required=dataset["schema_version"] == "1.1.0")
    expected["dataset_sha256"] = dataset_sha256
    roles = {
        "R1": _role_rows(r1, "R1", cases, expected),
        "R2": _role_rows(r2, "R2", cases, expected),
    }
    accurate = agreement = invariant = 0
    (
        failures,
        missing,
        disagreements,
        significant,
        minor,
        critical_mismatches,
        major_invariance,
    ) = [], [], [], [], [], [], []
    for case_id, ref in refs.items():
        pair = []
        for role, rows in roles.items():
            row = rows.get(case_id)
            if row is None:
                missing.append(f"{role}:{case_id}")
                pair.append(None)
                continue
            pair.append(row)
            if row["status"] == "evaluator_failure":
                failures.append(f"{role}:{case_id}")
            correct = (
                row["status"] == ref["status"] and row["score"] in ref["allowed_scores"]
            )
            accurate += int(correct)
            if ref["critical"] and (
                not correct or row["major_error"] != ref["major_error"]
            ):
                critical_mismatches.append(f"{role}:{case_id}")
        if (
            all(pair)
            and all(row["status"] != "evaluator_failure" for row in pair)
            and (pair[0]["status"], pair[0]["score"])
            == (pair[1]["status"], pair[1]["score"])
        ):
            agreement += 1
        if all(pair) and (
            pair[0]["status"],
            pair[0]["score"],
            pair[0]["major_error"],
        ) != (pair[1]["status"], pair[1]["score"], pair[1]["major_error"]):
            disagreements.append(case_id)
            status_diff = pair[0]["status"] != pair[1]["status"]
            major_diff = pair[0]["major_error"] != pair[1]["major_error"]
            two_point = (
                all(row["score"] is not None for row in pair)
                and abs(pair[0]["score"] - pair[1]["score"]) == 2
            )
            (
                significant
                if ref["critical"] or status_diff or major_diff or two_point
                else minor
            ).append(case_id)
    for role, rows in roles.items():
        for case_id, case in cases.items():
            if case["base_case_id"] is None:
                continue
            row, base = rows.get(case_id), rows.get(case["base_case_id"])
            if (
                row
                and base
                and row["status"] != "evaluator_failure"
                and base["status"] != "evaluator_failure"
                and (row["status"], row["score"]) == (base["status"], base["score"])
            ):
                invariant += 1
            if row and base and row["major_error"] != base["major_error"]:
                major_invariance.append(f"{role}:{case_id}")
    complete = (
        not missing and not failures and all(len(rows) == 56 for rows in roles.values())
    )
    rates = {
        "within_range_accuracy": accurate / 112,
        "r1_r2_agreement": agreement / 56,
        "presentation_invariance": invariant / 56,
    }
    thresholds = {
        "within_range_accuracy": 0.90,
        "r1_r2_agreement": 0.85,
        "presentation_invariance": 0.90,
    }
    passed = (
        complete
        and not significant
        and not critical_mismatches
        and not major_invariance
        and all(rates[key] >= value for key, value in thresholds.items())
    )
    return {
        "kind": "Stage2RubricQualityReport",
        "schema_version": "1.0.0",
        "bindings": {**expected, "reference_sha256": reference_sha256},
        "counts": {
            "within_range_correct": accurate,
            "within_range_total": 112,
            "agreement_exact": agreement,
            "agreement_total": 56,
            "invariant_exact": invariant,
            "invariant_total": 56,
        },
        "rates": rates,
        "thresholds": thresholds,
        "complete": complete,
        "missing": missing,
        "evaluator_failures": failures,
        "critical_mismatches": critical_mismatches,
        "major_error_invariance_mismatches": major_invariance,
        "unresolved_disagreements": disagreements,
        "significant_disagreements": significant,
        "minor_disagreements": minor,
        "passed": passed,
        "diagnostic_only": True,
        "formal_ready": False,
    }
