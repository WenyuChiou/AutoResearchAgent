"""Apply the frozen three-pair A/B decision rule without a composite score."""

import argparse
from datetime import datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .evaluation_plan import validate_plan
    from .holdout_manifest import canonical_sha256
    from .judge_bundle import (
        EVAL_ROOT,
        _load_json_artifact,
        _safe_relative_path,
        validate_bundle,
    )
except ImportError:  # Direct script execution.
    from evaluation_plan import validate_plan
    from holdout_manifest import canonical_sha256
    from judge_bundle import (
        EVAL_ROOT,
        _load_json_artifact,
        _safe_relative_path,
        validate_bundle,
    )


SCHEMA_PATH = EVAL_ROOT / "schemas" / "paired-evaluation-request.v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
RESULT_SCHEMA = json.loads(
    (EVAL_ROOT / "schemas" / "paired-evaluation-decision.v1.schema.json").read_text(
        encoding="utf-8"
    )
)
RESULT_VALIDATOR = Draft202012Validator(RESULT_SCHEMA, format_checker=FormatChecker())


def _verify_bytes(binding, label, errors):
    if not _safe_relative_path(binding["path"]):
        errors.append(f"{label} path must be a normalized relative path")
        return
    path = EVAL_ROOT / binding["path"]
    if not path.is_file():
        errors.append(f"{label} artifact does not exist")
        return
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
        errors.append(f"{label} sha256 does not match artifact bytes")


def _selected_result(bundle, errors):
    selected_id = bundle["selected_evaluation_id"]
    for slot in ("auto_r1", "auto_r2", "auto_adj"):
        binding = bundle["artifacts"][slot]
        if binding is None:
            continue
        result = _load_json_artifact(binding, f"{bundle['bundle_id']}:{slot}", errors)
        if result is not None and result["evaluation_id"] == selected_id:
            return result
    errors.append(f"{bundle['bundle_id']} selected evaluation artifact is missing")
    return None


def _distribution(scores):
    if not scores:
        raise ValueError("distribution requires at least one score")
    count = len(scores)
    return {
        "minimum": min(scores),
        "scores_sorted": sorted(scores),
        "at_least_1": [sum(score >= 1 for score in scores), count],
        "at_least_2": [sum(score >= 2 for score in scores), count],
    }


def _metric_summary(result, metric_id):
    rows = [row for row in result["metric_results"] if row["metric_id"] == metric_id]
    if metric_id == "P1":
        row = next(row for row in rows if row["unit_type"] == "stage_summary")
        return {"score": row["score"]}
    if metric_id == "P5":
        return {"direction_distribution": _distribution([row["score"] for row in rows])}
    if metric_id == "P6":
        recommendation = next(
            row for row in rows if row["unit_type"] == "final_recommendation"
        )
        directions = [
            row["score"] for row in rows if row["unit_type"] == "research_direction"
        ]
        return {
            "final_recommendation": recommendation["score"],
            "direction_distribution": _distribution(directions),
        }
    if len(rows) != 1:
        raise ValueError(f"{metric_id} requires exactly one reporting row")
    return {"score": rows[0]["score"]}


def _flat_components(summary):
    components = []
    for key, value in summary.items():
        if isinstance(value, dict):
            components.append((f"{key}.minimum", Fraction(value["minimum"], 1)))
            components.append((f"{key}.at_least_1", Fraction(*value["at_least_1"])))
            components.append((f"{key}.at_least_2", Fraction(*value["at_least_2"])))
        else:
            components.append((key, Fraction(value, 1)))
    return components


def _compare(baseline, treatment):
    before = dict(_flat_components(baseline))
    after = dict(_flat_components(treatment))
    if set(before) != set(after):
        return "inconclusive"
    deltas = [after[key] - before[key] for key in before]
    if all(delta == 0 for delta in deltas):
        return "same"
    if any(delta < 0 for delta in deltas):
        return "regressed"
    return "improved"


def _close_ordinal(baseline, treatment):
    for key in set(baseline) & set(treatment):
        if isinstance(baseline[key], dict) and baseline[key] != treatment[key]:
            return True
    before = dict(_flat_components(baseline))
    after = dict(_flat_components(treatment))
    ordinal_keys = {
        key
        for key in before
        if key.endswith("score")
        or key.endswith("minimum")
        or key == "final_recommendation"
    }
    return any(abs(after[key] - before[key]) == 1 for key in ordinal_keys)


def _major_errors(result):
    return {
        error for row in result["metric_results"] for error in row["major_error_ids"]
    }


def evaluate_request(request):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(request), key=str)
    ]
    if errors:
        return None, errors
    plan = _load_json_artifact(request["plan"], "plan", errors)
    if plan is None or validate_plan(plan):
        errors.append("bound evaluation plan is missing or invalid")
        return None, errors
    if plan["status"] != "frozen" or plan["frozen_at"] is None:
        errors.append("paired evaluation requires a frozen plan")
        return None, errors

    bundles = []
    for index, binding in enumerate(request["bundles"]):
        bundle = _load_json_artifact(binding, f"bundle[{index}]", errors)
        if bundle is not None:
            bundle_errors = validate_bundle(bundle)
            errors.extend(f"bundle[{index}]:{error}" for error in bundle_errors)
            bundles.append(bundle)
    if errors:
        return None, errors
    if len({bundle["bundle_id"] for bundle in bundles}) != 6:
        errors.append("six unique bundle IDs are required")

    run_map = {bundle["run_id"]: bundle for bundle in bundles}
    expected_runs = {
        item["run_id"]
        for repeat in plan["paired_repeats"]
        for item in (repeat["baseline"], repeat["treatment"])
    }
    if set(run_map) != expected_runs:
        errors.append("bundle run IDs must exactly match the frozen three pairs")
    for bundle in bundles:
        if (
            bundle["plan"]["plan_id"] != plan["plan_id"]
            or bundle["plan"]["artifact"]["canonical_sha256"]
            != request["plan"]["canonical_sha256"]
        ):
            errors.append(f"{bundle['bundle_id']} does not bind the requested plan")
        if not bundle["usable_for_pairing"]:
            errors.append(f"{bundle['bundle_id']} is not usable for pairing")
    if plan["execution_class"] == "formal" and any(
        not binding["path"].startswith("private/") for binding in request["bundles"]
    ):
        errors.append("formal judge-bundle artifacts must stay under private/")

    costs = {item["run_id"]: item for item in request["run_costs"]}
    if set(costs) != expected_runs or len(costs) != 6:
        errors.append("run_costs must contain every frozen run exactly once")
    expected_run_state = {}
    for repeat in plan["paired_repeats"]:
        for condition in ("baseline", "treatment"):
            expected_run_state[repeat[condition]["run_id"]] = (
                condition,
                repeat[condition]["subject_id"],
                plan["bindings"][f"{condition}_build"],
            )
    attestations = {item["run_id"]: item for item in request["run_attestations"]}
    if set(attestations) != expected_runs or len(attestations) != 6:
        errors.append("run_attestations must contain every frozen run exactly once")
    runtime_hash = canonical_sha256(plan["subject_runtime"])
    frozen_at = datetime.fromisoformat(plan["frozen_at"])
    for run_id, attestation in attestations.items():
        if run_id not in expected_run_state:
            continue
        condition, subject_id, build = expected_run_state[run_id]
        expected = {
            "subject_id": subject_id,
            "condition": condition,
            "build_version_id": build["version_id"],
            "core_revision": build["core_revision"],
            "extension_revision": build["extension_revision"],
            "reviewed_diff_sha256": build["reviewed_diff_sha256"],
            "runtime_profile_sha256": runtime_hash,
            "prompt_sha256": plan["bindings"]["prompt"]["artifact"]["sha256"],
            "condition_map_sha256": plan["bindings"]["condition_map"]["sha256"],
            "subject_artifact": run_map[run_id]["subject_artifact"],
        }
        for field, value in expected.items():
            if attestation[field] != value:
                errors.append(
                    f"{run_id} attestation {field} does not match the frozen plan or bundle"
                )
        _verify_bytes(
            attestation["attestation_artifact"],
            f"{run_id} execution attestation",
            errors,
        )
        if plan["execution_class"] == "formal" and not attestation[
            "attestation_artifact"
        ]["path"].startswith("private/"):
            errors.append(f"{run_id} formal execution attestation must stay private")
        attested_at = datetime.fromisoformat(attestation["created_at"])
        if (
            not frozen_at
            <= attested_at
            <= datetime.fromisoformat(run_map[run_id]["created_at"])
        ):
            errors.append(f"{run_id} execution attestation timestamp is out of order")
    if errors:
        return None, errors

    results = {
        run_id: _selected_result(bundle, errors) for run_id, bundle in run_map.items()
    }
    if errors:
        return None, errors

    audits = {
        (item["repeat"], item["metric_id"]): item for item in request["pair_audits"]
    }
    if len(audits) != len(request["pair_audits"]):
        errors.append("pair audits must be unique per repeat and metric")
    pair_rows = []
    added_major_errors = []
    used_audits = set()
    for repeat in plan["paired_repeats"]:
        number = repeat["repeat"]
        baseline_run = repeat["baseline"]["run_id"]
        treatment_run = repeat["treatment"]["run_id"]
        baseline_result = results[baseline_run]
        treatment_result = results[treatment_run]
        added = sorted(_major_errors(treatment_result) - _major_errors(baseline_result))
        if added:
            added_major_errors.append({"repeat": number, "ids": added})
        for metric_id in plan["metric_ids"]:
            before = _metric_summary(baseline_result, metric_id)
            after = _metric_summary(treatment_result, metric_id)
            direction = _compare(before, after)
            audit_state = "not-required"
            if _close_ordinal(before, after):
                audit = audits.get((number, metric_id))
                if audit is None:
                    direction, audit_state = "audit-required", "missing"
                else:
                    used_audits.add((number, metric_id))
                    expected_bundle_ids = {
                        run_map[baseline_run]["bundle_id"],
                        run_map[treatment_run]["bundle_id"],
                    }
                    if set(audit["reviewed_bundle_ids"]) != expected_bundle_ids:
                        errors.append(
                            f"repeat {number} {metric_id} audit reviews the wrong bundles"
                        )
                    _verify_bytes(
                        audit["artifact"], f"repeat {number} {metric_id} audit", errors
                    )
                    if plan["execution_class"] == "formal" and not audit["artifact"][
                        "path"
                    ].startswith("private/"):
                        errors.append(
                            f"repeat {number} {metric_id} formal audit must stay private"
                        )
                    bundle_time = max(
                        datetime.fromisoformat(run_map[baseline_run]["created_at"]),
                        datetime.fromisoformat(run_map[treatment_run]["created_at"]),
                    )
                    if datetime.fromisoformat(audit["completed_at"]) < bundle_time:
                        errors.append(
                            f"repeat {number} {metric_id} audit predates its bundles"
                        )
                    audit_state = audit["decision"]
                    if audit["decision"] != "accept-comparison":
                        direction = "inconclusive"
            pair_rows.append(
                {
                    "repeat": number,
                    "metric_id": metric_id,
                    "baseline": before,
                    "treatment": after,
                    "direction": direction,
                    "audit_state": audit_state,
                }
            )
    unused_audits = set(audits) - used_audits
    if unused_audits:
        errors.append(
            f"pair audits supplied without a close comparison: {sorted(unused_audits)}"
        )
    request_time = datetime.fromisoformat(request["created_at"])
    latest_bundle_time = max(
        datetime.fromisoformat(bundle["created_at"]) for bundle in bundles
    )
    latest_audit_time = max(
        (
            datetime.fromisoformat(audit["completed_at"])
            for audit in request["pair_audits"]
        ),
        default=latest_bundle_time,
    )
    if request_time < max(latest_bundle_time, latest_audit_time):
        errors.append(
            "paired request must be created after every bundle and pair audit"
        )
    if errors:
        return None, errors

    metric_decisions = []
    incomplete = False
    for metric_id in plan["metric_ids"]:
        rows = [row for row in pair_rows if row["metric_id"] == metric_id]
        counts = {
            state: sum(row["direction"] == state for row in rows)
            for state in (
                "improved",
                "same",
                "regressed",
                "inconclusive",
                "audit-required",
            )
        }
        is_target = metric_id in plan["target_metric_ids"]
        if counts["audit-required"] or counts["inconclusive"]:
            decision = "inconclusive"
            incomplete = True
        elif counts["regressed"]:
            decision = "failed"
        elif (
            is_target
            and counts["improved"]
            >= plan["decision_rule"]["minimum_pairs_improved_per_target"]
        ):
            decision = "passed"
        elif not is_target:
            decision = "passed"
        else:
            decision = "failed"
        metric_decisions.append(
            {
                "metric_id": metric_id,
                "is_target": is_target,
                "pair_counts": counts,
                "decision": decision,
            }
        )

    if incomplete:
        overall = "inconclusive"
    elif added_major_errors or any(
        item["decision"] != "passed" for item in metric_decisions
    ):
        overall = "not-improved"
    else:
        overall = "improved"
    result = {
        "kind": "PairedEvaluationDecision",
        "schema_version": "1.0.0",
        "request_id": request["request_id"],
        "plan_id": plan["plan_id"],
        "request_canonical_sha256": canonical_sha256(request),
        "bundle_bindings": request["bundles"],
        "stage": plan["stage"],
        "decision": overall,
        "metric_decisions": metric_decisions,
        "pair_results": pair_rows,
        "added_major_errors": added_major_errors,
        "run_costs": request["run_costs"],
        "no_composite_total": True,
        "external_claim_ready": False,
        "created_at": request["created_at"],
    }
    RESULT_VALIDATOR.validate(result)
    return result, []


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    result, errors = evaluate_request(request)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
