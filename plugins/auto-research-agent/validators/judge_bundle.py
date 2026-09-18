"""Reconcile two blinded rubric judges and fail closed around adjudication."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .evaluation_plan import validate_plan
    from .holdout_manifest import canonical_sha256
    from .rubric_judge_result import validate_result
except ImportError:  # Direct script execution.
    from evaluation_plan import validate_plan
    from holdout_manifest import canonical_sha256
    from rubric_judge_result import validate_result


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
SCHEMA_PATH = EVAL_ROOT / "schemas" / "judge-bundle.v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _safe_relative_path(value):
    if not value or value.startswith("/") or "\\" in value:
        return False
    if len(value) >= 2 and value[1] == ":":
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _load_json_artifact(binding, label, errors):
    path_text = binding["path"]
    if not _safe_relative_path(path_text):
        errors.append(f"{label} path must be a normalized relative path")
        return None
    path = EVAL_ROOT / path_text
    if not path.is_file():
        errors.append(f"{label} artifact does not exist")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} artifact is not readable JSON: {exc}")
        return None
    if canonical_sha256(value) != binding["canonical_sha256"]:
        errors.append(f"{label} canonical_sha256 does not match artifact bytes")
        return None
    return value


def _verify_byte_artifact(binding, label, errors):
    path_text = binding["path"]
    if not _safe_relative_path(path_text):
        errors.append(f"{label} path must be a normalized relative path")
        return False
    path = EVAL_ROOT / path_text
    if not path.is_file():
        errors.append(f"{label} artifact does not exist")
        return False
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"{label} artifact is not readable: {exc}")
        return False
    if digest != binding["sha256"]:
        errors.append(f"{label} sha256 does not match artifact bytes")
        return False
    return True


def _is_private_path(value):
    return _safe_relative_path(value) and value.startswith("private/")


def _result_signature(result):
    return {
        (row["metric_id"], row["unit_type"], row["unit_id"]): (
            row["score"],
            tuple(sorted(row["major_error_ids"])),
        )
        for row in result["metric_results"]
    }


def _same_subject(left, right):
    fields = (
        "run_id",
        "case_id",
        "rubric_version",
        "catalog_sha256",
        "stage",
        "study_mode",
        "expected_units",
        "subject_artifact",
    )
    return all(left[field] == right[field] for field in fields)


def validate_bundle(bundle):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(bundle), key=str)
    ]
    if errors:
        return errors

    plan = _load_json_artifact(bundle["plan"]["artifact"], "plan", errors)
    if plan is None:
        return errors
    if validate_plan(plan):
        errors.append("bound evaluation plan fails its semantic contract")
        return errors
    if plan["plan_id"] != bundle["plan"]["plan_id"]:
        errors.append("plan_id does not match the bound evaluation plan")
    if plan["status"] != "frozen" or plan["frozen_at"] is None:
        errors.append("judge bundles require a frozen evaluation plan")
        return errors

    known_runs = {
        run["run_id"]: run["subject_id"]
        for repeat in plan["paired_repeats"]
        for run in (repeat["baseline"], repeat["treatment"])
    }
    if known_runs.get(bundle["run_id"]) != bundle["subject_id"]:
        errors.append("run_id and subject_id are not a frozen plan pair")
    _verify_byte_artifact(bundle["subject_artifact"], "subject", errors)

    loaded = {}
    for slot in ("auto_r1", "auto_r2", "auto_adj"):
        binding = bundle["artifacts"][slot]
        if binding is not None:
            loaded[slot] = _load_json_artifact(binding, slot, errors)
    if errors or any(value is None for value in loaded.values()):
        return errors

    expected_roles = {
        "auto_r1": "auto-r1",
        "auto_r2": "auto-r2",
        "auto_adj": "auto-adj",
    }
    plan_judges = {item["role"]: item for item in plan["judge_configs"]}
    for slot, result in loaded.items():
        result_errors = validate_result(result)
        errors.extend(f"{slot}:{error}" for error in result_errors)
        if result_errors:
            continue
        role = expected_roles[slot]
        if result["judge"]["role"] != role:
            errors.append(f"{slot} artifact must use judge role {role}")
        config = plan_judges[role]
        if result["judge"]["config_id"] != config["config_id"]:
            errors.append(f"{slot} config_id does not match the frozen plan")
        result_judge = result["judge"]
        plan_fields = {
            "model": "model_id",
            "reasoning": "reasoning",
            "prompt_sha256": "prompt_sha256",
            "evaluation_config_sha256": "evaluation_config_sha256",
            "execution_context_id": "execution_context_id",
            "condition_blinded": "condition_blinded",
        }
        missing_provenance = set(plan_fields) - set(result_judge)
        if missing_provenance:
            errors.append(
                f"{slot} lacks frozen-plan provenance fields: "
                f"{sorted(missing_provenance)}"
            )
            continue
        for result_field, plan_field in plan_fields.items():
            if result_judge[result_field] != config[plan_field]:
                errors.append(f"{slot} {result_field} does not match the frozen plan")
        if result["run_id"] != bundle["run_id"]:
            errors.append(f"{slot} run_id does not match the bundle")
        if (
            result["case_id"] != plan["case_id"]
            or result["stage"] != plan["stage"]
            or result["study_mode"] != plan["study_mode"]
        ):
            errors.append(
                f"{slot} case, stage, or study_mode does not match the frozen plan"
            )
        if result["subject_artifact"] != bundle["subject_artifact"]:
            errors.append(f"{slot} subject artifact does not match the bundle")

    if errors:
        return errors

    r1 = loaded["auto_r1"]
    r2 = loaded["auto_r2"]
    if not _same_subject(r1, r2):
        errors.append("Auto-R1 and Auto-R2 must judge the exact same subject")
    evaluation_ids = [result["evaluation_id"] for result in loaded.values()]
    if len(evaluation_ids) != len(set(evaluation_ids)):
        errors.append("judge evaluation IDs must be unique")

    disagreement = _result_signature(r1) != _result_signature(r2)
    adjudication = loaded.get("auto_adj")
    if disagreement and adjudication is None:
        errors.append("judge disagreement requires Auto-ADJ")
    if not disagreement and adjudication is not None:
        errors.append("Auto-ADJ must not run when R1 and R2 agree")
    if adjudication is not None:
        if not _same_subject(r1, adjudication):
            errors.append("Auto-ADJ must judge the exact same subject")
        if set(adjudication.get("adjudicates_evaluation_ids", [])) != {
            r1["evaluation_id"],
            r2["evaluation_id"],
        }:
            errors.append("Auto-ADJ must name exactly the R1 and R2 evaluation IDs")

    frozen_at = datetime.fromisoformat(plan["frozen_at"])
    r1_time = datetime.fromisoformat(r1["created_at"])
    r2_time = datetime.fromisoformat(r2["created_at"])
    if r1_time < frozen_at or r2_time < frozen_at:
        errors.append("R1 and R2 must be created after the evaluation plan is frozen")
    if adjudication is not None and datetime.fromisoformat(
        adjudication["created_at"]
    ) < max(r1_time, r2_time):
        errors.append("Auto-ADJ must be created after both R1 and R2")

    if plan["execution_class"] == "formal":
        private_paths = [
            bundle["subject_artifact"]["path"],
            *(
                binding["path"]
                for binding in bundle["artifacts"].values()
                if isinstance(binding, dict) and "canonical_sha256" in binding
            ),
        ]
        if not all(_is_private_path(path) for path in private_paths):
            errors.append("formal subject and judge artifacts must stay under private/")

    automatic_results = list(loaded.values())
    audit_required = any(result["requires_human_audit"] for result in automatic_results)
    selected = adjudication or r1
    audit = bundle["artifacts"]["human_audit"]
    if audit_required and audit is None:
        expected_status, expected_selected, expected_usable = (
            "audit-required",
            None,
            False,
        )
    elif audit_required:
        reviewed = set(audit["reviewed_evaluation_ids"])
        if reviewed != set(evaluation_ids):
            errors.append(
                "human audit must review every automatic evaluation in the bundle"
            )
        _verify_byte_artifact(audit["artifact"], "human audit", errors)
        if plan["execution_class"] == "formal" and not _is_private_path(
            audit["artifact"]["path"]
        ):
            errors.append("formal human audit artifacts must stay under private/")
        evaluation_times = [
            datetime.fromisoformat(result["created_at"]) for result in automatic_results
        ]
        if datetime.fromisoformat(audit["completed_at"]) < max(evaluation_times):
            errors.append(
                "human audit must be completed after every reviewed evaluation"
            )
        if audit["decision"] == "accept-selected":
            expected_selected, expected_usable = selected["evaluation_id"], True
        else:
            expected_selected, expected_usable = None, False
        expected_status = "completed"
    else:
        if audit is not None:
            errors.append(
                "human audit must not be added without a frozen audit trigger"
            )
        expected_status = "agreed"
        expected_selected, expected_usable = r1["evaluation_id"], True

    bundle_time = datetime.fromisoformat(bundle["created_at"])
    latest_input_time = max(
        datetime.fromisoformat(result["created_at"]) for result in automatic_results
    )
    if audit is not None:
        latest_input_time = max(
            latest_input_time, datetime.fromisoformat(audit["completed_at"])
        )
    if bundle_time < latest_input_time:
        errors.append("judge bundle must be created after all judge and audit inputs")

    if bundle["status"] != expected_status:
        errors.append(f"status must be {expected_status} for the observed judge state")
    if bundle["selected_evaluation_id"] != expected_selected:
        errors.append("selected_evaluation_id does not match the resolved judge state")
    if bundle["usable_for_pairing"] != expected_usable:
        errors.append("usable_for_pairing does not match the resolved judge state")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    errors = validate_bundle(bundle)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Judge bundle is valid and reconciled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
