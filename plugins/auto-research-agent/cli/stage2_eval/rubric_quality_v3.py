"""Fixed-denominator v3 calibration; designated judgments are not independent trials."""

from collections import Counter

from stage2_common import Stage2Error, canonical_hash


def validate_quality_inputs(dataset, reference, rubric):
    ids = [row["id"] for row in rubric["criteria"]]
    if len(ids) != 9 or Counter(row["dimension"] for row in rubric["criteria"]) != {
        "P4": 3,
        "P5": 3,
        "P6": 3,
    }:
        raise Stage2Error("quality-v3-requires-balanced-nine-criteria")
    cases = dataset.get("cases", [])
    refs = reference.get("judgments", [])
    if len(cases) != 72 or len(refs) != 72:
        raise Stage2Error("quality-v3-requires-72-presentations")
    by_id = {row["case_id"]: row for row in cases}
    reference_by_id = {row["case_id"]: row for row in refs}
    if len(by_id) != 72 or set(by_id) != set(reference_by_id):
        raise Stage2Error("quality-v3-duplicate-or-missing-case")
    if Counter(row["criterion_id"] for row in cases) != {key: 8 for key in ids}:
        raise Stage2Error("quality-v3-must-assess-each-criterion-eight-times")
    for criterion in ids:
        anchors = [
            row
            for row in cases
            if row["criterion_id"] == criterion and row["variant"] == "anchor"
        ]
        if len(anchors) != 4 or {
            reference_by_id[row["case_id"]]["score"] for row in anchors
        } != {0, 1, 2, None}:
            raise Stage2Error("quality-v3-anchor-coverage")
        variants = [
            row
            for row in cases
            if row["criterion_id"] == criterion and row["variant"] != "anchor"
        ]
        if {row["variant"] for row in variants} != {
            "order",
            "length",
            "prestige",
            "preference",
        }:
            raise Stage2Error("quality-v3-equivalent-variant-coverage")
        for row in variants:
            parent = by_id.get(row.get("base_case_id"))
            if (
                parent not in anchors
                or row["facts"] != parent["facts"]
                or row["semantic_sha256"] != parent["semantic_sha256"]
            ):
                raise Stage2Error("quality-v3-variant-facts-changed")
            if (
                reference_by_id[row["case_id"]] | {"case_id": parent["case_id"]}
                != reference_by_id[parent["case_id"]]
            ):
                raise Stage2Error("quality-v3-variant-reference-changed")
    return by_id, reference_by_id


def validate_quality_batch(value, role, cases):
    if value.get("kind") != "Stage2RubricQualityBatchV3" or value.get("role") != role:
        raise Stage2Error("quality-v3-batch-role")
    rows = value.get("judgments", [])
    if len(rows) != len(cases) or {row.get("case_id") for row in rows} != {
        case["case_id"] for case in cases
    }:
        raise Stage2Error("quality-v3-batch-missing-or-duplicate")
    by_id = {row["case_id"]: row for row in cases}
    for row in rows:
        if row.get("status") not in {"scored", "unknown", "evaluator_failure"}:
            raise Stage2Error("quality-v3-judgment-status")
        score = row.get("score")
        if row["status"] == "scored":
            if (
                type(score) is not int
                or score not in {0, 1, 2}
                or type(row.get("major_error")) is not bool
            ):
                raise Stage2Error("quality-v3-scored-judgment-shape")
        elif score is not None or row.get("major_error") is not None:
            raise Stage2Error("quality-v3-unknown-cannot-be-zero")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise Stage2Error("quality-v3-missing-reason")
        evidence = row.get("evidence_ids")
        known = {fact["evidence_id"] for fact in by_id[row["case_id"]]["facts"]}
        if (
            not isinstance(evidence, list)
            or len(set(evidence)) != len(evidence)
            or not set(evidence).issubset(known)
        ):
            raise Stage2Error("quality-v3-unknown-evidence")
        if row["status"] == "scored" and not evidence:
            raise Stage2Error("quality-v3-scored-evidence-required")
    return value


def evaluate_quality_v3(dataset, reference, rubric, r1, r2):
    cases, refs = validate_quality_inputs(dataset, reference, rubric)
    scores = {}
    for role, value in (("R1", r1), ("R2", r2)):
        validate_quality_batch(value, role, list(cases.values()))
        scores[role] = {row["case_id"]: row for row in value["judgments"]}
    range_hits = Counter()
    mismatches, disagreements, critical_errors, failures = [], [], [], []

    def signatures(row):
        return row["status"], row["score"], row["major_error"]

    invariance_hits = 0
    for case_id, case in cases.items():
        expected = refs[case_id]
        for role in ("R1", "R2"):
            actual = scores[role][case_id]
            matches = signatures(actual) == (
                expected["status"],
                expected["score"],
                expected["major_error"],
            )
            range_hits[case["criterion_id"]] += int(matches)
            if not matches:
                mismatches.append(
                    {
                        "case_id": case_id,
                        "role": role,
                        "criterion_id": case["criterion_id"],
                        "expected": expected,
                        "actual": actual,
                    }
                )
            if expected.get("critical") and not matches:
                critical_errors.append({"case_id": case_id, "role": role})
            if actual["status"] == "evaluator_failure":
                failures.append({"case_id": case_id, "role": role})
            if case["variant"] != "anchor":
                invariance_hits += int(
                    signatures(actual) == signatures(scores[role][case["base_case_id"]])
                )
        if signatures(scores["R1"][case_id]) != signatures(scores["R2"][case_id]):
            disagreements.append(case_id)
    per_criterion = {
        criterion["id"]: {
            "matched": range_hits[criterion["id"]],
            "required": 16,
            "percent": 100 * range_hits[criterion["id"]] / 16,
        }
        for criterion in rubric["criteria"]
    }
    total = sum(range_hits.values())
    agreement = 72 - len(disagreements)
    passed = (
        total / 144 >= 0.9
        and all(row["percent"] >= 90 for row in per_criterion.values())
        and agreement / 72 >= 0.85
        and invariance_hits / 72 >= 0.9
        and not critical_errors
        and not failures
        and not disagreements
    )
    return {
        "kind": "Stage2RubricQualityReportV3",
        "schema_version": "3.0.0",
        "dataset_sha256": canonical_hash(dataset),
        "reference_sha256": canonical_hash(reference),
        "rubric_sha256": canonical_hash(rubric),
        "presentations": 72,
        "designated_judgments": 144,
        "range": {"matched": total, "required": 144, "percent": 100 * total / 144},
        "per_criterion": per_criterion,
        "agreement": {
            "matched": agreement,
            "required": 72,
            "percent": 100 * agreement / 72,
        },
        "invariance": {
            "matched": invariance_hits,
            "required": 72,
            "percent": 100 * invariance_hits / 72,
        },
        "mismatches": mismatches,
        "unresolved_disagreements": disagreements,
        "critical_errors": critical_errors,
        "evaluator_failures": failures,
        "passed": passed,
        "formal_ready": False,
        "independent_trials_claimed": False,
    }
