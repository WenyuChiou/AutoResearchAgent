"""Check six-cluster Stage 1 counts against a frozen versioned holdout."""

import argparse
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .evaluation_plan import validate_plan
    from .holdout_manifest import canonical_sha256
    from .holdout_manifest_v2 import EVAL_ROOT, validate_manifest_v2
    from .stage1_evaluation_result import count_semantic_errors
except ImportError:  # Direct script execution.
    from evaluation_plan import validate_plan
    from holdout_manifest import canonical_sha256
    from holdout_manifest_v2 import EVAL_ROOT, validate_manifest_v2
    from stage1_evaluation_result import count_semantic_errors


SCHEMA = json.loads(
    (EVAL_ROOT / "schemas" / "stage1-evaluation-result.v2.schema.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_result_v2(result, holdout, plan):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(result), key=str)
    ]
    if errors:
        return errors
    holdout_errors = validate_manifest_v2(holdout)
    if holdout_errors:
        return [f"holdout:{error}" for error in holdout_errors]
    expected_spec = (
        "stage1-primary-metrics-v2.1"
        if holdout["schema_version"] == "2.1.0"
        else "stage1-primary-metrics-v2"
    )
    if result["metric_spec_version"] != expected_spec:
        errors.append("metric_spec_version does not match the holdout protocol")
    plan_errors = validate_plan(plan)
    if plan_errors:
        return [f"plan:{error}" for error in plan_errors]
    if plan["status"] != "frozen":
        errors.append("a Stage 1 result requires a frozen evaluation plan")
    if plan["stage"] != 1:
        errors.append("a Stage 1 result requires a Stage 1 evaluation plan")
    if holdout["status"] != "frozen":
        errors.append("a Stage 1 evaluation requires a frozen holdout")
    if plan["case_id"] != holdout["case_id"]:
        errors.append("evaluation plan and holdout case IDs must match")
    plan_holdout = plan["bindings"]["holdout"]
    if plan_holdout["manifest_id"] != holdout["manifest_id"]:
        errors.append("evaluation plan must bind this holdout manifest ID")
    actual_holdout_sha256 = canonical_sha256(holdout)
    if plan_holdout["canonical_sha256"] != actual_holdout_sha256:
        errors.append("evaluation plan must bind these exact holdout bytes")
    if result["holdout_sha256"] != actual_holdout_sha256:
        errors.append("result holdout_sha256 must match these exact holdout bytes")
    if result["evaluation_plan_sha256"] != canonical_sha256(plan):
        errors.append("result evaluation_plan_sha256 must match the frozen plan")
    if result["prompt_sha256"] != plan["bindings"]["prompt"]["artifact"]["sha256"]:
        errors.append("result prompt_sha256 must match the frozen plan")
    expected_runs = {
        (item["run_id"], condition)
        for repeat in plan["paired_repeats"]
        for condition in ("baseline", "treatment")
        for item in (repeat[condition],)
    }
    if (result["run_id"], result["condition"]) not in expected_runs:
        errors.append("result run_id and condition must match a frozen plan run")
    if result["benchmark_version"] != holdout["manifest_id"]:
        errors.append("benchmark_version must match the bound holdout manifest_id")
    counts = result["fact_metrics"]["coverage"]
    core_total = sum(
        anchor["anchor_type"] in {"core", "core-and-must-have"}
        for anchor in holdout["anchors"]
    )
    must_have_total = sum(
        anchor["anchor_type"] in {"must-have", "core-and-must-have"}
        for anchor in holdout["anchors"]
    )
    if counts["core_total"] != core_total:
        errors.append("core_total must equal the frozen core-anchor count")
    if counts["must_have_total"] != must_have_total:
        errors.append("must_have_total must equal the frozen must-have count")
    return errors + count_semantic_errors(result)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args(argv)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    holdout = json.loads(args.holdout.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    errors = validate_result_v2(result, holdout, plan)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Six-cluster Stage 1 result is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
