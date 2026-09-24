"""Validate a frozen paired evaluation plan before any subject run begins."""

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator, FormatChecker

try:
    from .holdout_manifest import canonical_sha256, validate_manifest
    from .holdout_manifest_v2 import validate_manifest_v2
except ImportError:  # Direct script execution.
    from holdout_manifest import canonical_sha256, validate_manifest
    from holdout_manifest_v2 import validate_manifest_v2


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PLUGIN_ROOT / "evals"
SCHEMA_PATH = EVAL_ROOT / "schemas" / "evaluation-plan.v1.schema.json"
RUBRIC_PATH = EVAL_ROOT / "rubrics" / "aging-bidirectional-rubric.v1.json"
CAPABILITY_MAP_PATH = EVAL_ROOT / "capability-metric-map.v1.json"
STAGE_METRICS = {
    1: {"P1", "P2", "P3"},
    2: {"P4", "P5", "P6"},
    3: {"P7", "P8", "P9"},
}
AUDIT_TRIGGERS = {
    "major-error",
    "low-confidence",
    "evidence-unverifiable",
    "judge-disagreement",
    "close-paired-result",
    "external-claim",
}
EXPECTED_ORDERS = [
    ["baseline", "treatment"],
    ["treatment", "baseline"],
    ["baseline", "treatment"],
]


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
RUBRIC = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
CAPABILITY_MAP = json.loads(CAPABILITY_MAP_PATH.read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_plan(plan):
    errors = [
        f"schema:{'/'.join(map(str, error.absolute_path)) or '<root>'}:{error.message}"
        for error in sorted(SCHEMA_VALIDATOR.iter_errors(plan), key=str)
    ]
    if errors:
        return errors

    stage_metrics = STAGE_METRICS[plan["stage"]]
    if set(plan["metric_ids"]) != stage_metrics:
        errors.append("metric_ids must exactly match the selected stage")
    if not set(plan["target_metric_ids"]).issubset(stage_metrics):
        errors.append("target_metric_ids must be a nonempty subset of stage metrics")
    if plan["study_mode"] not in RUBRIC["case_scope"]["allowed_research_modes"]:
        errors.append("study_mode is not allowed by the frozen rubric")

    _validate_public_bindings(plan, errors)
    _validate_artifact_paths(plan, errors)
    _validate_builds(plan, errors)
    _validate_runtime(plan["subject_runtime"], errors)
    _validate_judges(plan["judge_configs"], errors)
    _validate_repeats(plan["paired_repeats"], errors)

    if set(plan["human_audit"]["trigger_ids"]) != AUDIT_TRIGGERS:
        errors.append("human_audit must contain all six frozen trigger IDs")

    if plan["status"] == "frozen":
        _validate_frozen_plan(plan, errors)
    elif plan["frozen_at"] is not None:
        errors.append("a draft evaluation plan must not set frozen_at")
    return errors


def _safe_relative_path(value):
    if not value or value.startswith("/") or "\\" in value:
        return False
    if len(value) >= 2 and value[1] == ":":
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    return all(part not in {"", ".", ".."} for part in value.split("/"))


def _is_private_path(value):
    return _safe_relative_path(value) and value.startswith("private/")


def _validate_public_bindings(plan, errors):
    bindings = plan["bindings"]
    rubric_binding = bindings["rubric"]
    if rubric_binding["path"] != "rubrics/aging-bidirectional-rubric.v1.json":
        errors.append("rubric path must name the repository frozen rubric")
    if rubric_binding["version"] != RUBRIC["rubric_version"]:
        errors.append("rubric version does not match the loaded rubric")
    if RUBRIC["status"] != "frozen":
        errors.append("evaluation plans require a frozen rubric")
    if rubric_binding["canonical_sha256"] != canonical_sha256(RUBRIC):
        errors.append("rubric canonical_sha256 does not match the loaded rubric")

    expected_catalog = RUBRIC["criterion_catalog"]
    catalog_binding = bindings["criterion_catalog"]
    for field in ("path", "sha256", "record_count"):
        if catalog_binding[field] != expected_catalog[field]:
            errors.append(f"criterion catalog {field} does not match the rubric")
    catalog_path = EVAL_ROOT / expected_catalog["path"]
    canonical_catalog = (
        catalog_path.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )
    if hashlib.sha256(canonical_catalog).hexdigest() != expected_catalog["sha256"]:
        errors.append("loaded criterion catalog bytes do not match the rubric")
    if (
        sum(bool(line.strip()) for line in canonical_catalog.decode().splitlines())
        != (expected_catalog["record_count"])
    ):
        errors.append("loaded criterion catalog count does not match the rubric")

    registry_binding = bindings["capability_registry"]
    if registry_binding["path"] != "capability-metric-map.v1.json":
        errors.append("capability registry path must name the frozen registry")
    if registry_binding["canonical_sha256"] != canonical_sha256(CAPABILITY_MAP):
        errors.append("capability registry hash does not match the loaded registry")

    holdout_binding = bindings["holdout"]
    if _safe_relative_path(holdout_binding["path"]):
        holdout_path = EVAL_ROOT / holdout_binding["path"]
        if not holdout_path.is_file():
            errors.append("bound holdout manifest does not exist")
        else:
            holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
            if holdout.get("manifest_id") != holdout_binding["manifest_id"]:
                errors.append("holdout manifest_id does not match the bound artifact")
            if holdout.get("use_class") != holdout_binding["use_class"]:
                errors.append("holdout use_class does not match the bound artifact")
            if canonical_sha256(holdout) != holdout_binding["canonical_sha256"]:
                errors.append(
                    "holdout canonical_sha256 does not match the bound artifact"
                )
            holdout_validator = {
                "1.0.0": validate_manifest,
                "2.0.0": validate_manifest_v2,
            }.get(holdout.get("schema_version"))
            if holdout_validator is None or holdout_validator(holdout):
                errors.append("bound holdout manifest fails its semantic contract")
            if holdout.get("status") != "frozen":
                errors.append("an evaluation plan requires a frozen holdout")
            if holdout.get("case_id") != plan["case_id"]:
                errors.append("holdout case_id must match the evaluation case")
            if holdout.get("cutoff_date") != plan["subject_runtime"]["data_cutoff"]:
                errors.append("holdout cutoff must match the subject data cutoff")
            if holdout.get("frozen_at") and datetime.fromisoformat(
                holdout["frozen_at"]
            ) > datetime.fromisoformat(plan["created_at"]):
                errors.append("holdout must be frozen before the plan is created")
            if (
                plan["execution_class"] == "formal"
                and holdout.get("use_class") != "scientific"
            ):
                errors.append("a formal plan requires a scientific-use holdout")


def _validate_artifact_paths(plan, errors):
    bindings = plan["bindings"]
    paths = {
        "rubric": bindings["rubric"]["path"],
        "criterion catalog": bindings["criterion_catalog"]["path"],
        "capability registry": bindings["capability_registry"]["path"],
        "holdout": bindings["holdout"]["path"],
        "prompt": bindings["prompt"]["artifact"]["path"],
        "condition map": bindings["condition_map"]["path"],
    }
    paths.update(
        {
            f"approval {index}": approval["artifact"]["path"]
            for index, approval in enumerate(plan["human_approvals"])
        }
    )
    for label, path in paths.items():
        if not _safe_relative_path(path):
            errors.append(f"{label} path must be a normalized relative path")
    if not _is_private_path(bindings["condition_map"]["path"]):
        errors.append("condition map must stay under private/")
    if plan["execution_class"] == "formal" and not _is_private_path(
        bindings["holdout"]["path"]
    ):
        errors.append("a formal plan requires a private holdout path")
    for index, approval in enumerate(plan["human_approvals"]):
        if not _is_private_path(approval["artifact"]["path"]):
            errors.append(f"approval {index} artifact must stay under private/")


def _validate_builds(plan, errors):
    bindings = plan["bindings"]
    baseline = bindings["baseline_build"]
    treatment = bindings["treatment_build"]
    if baseline["capability_ids"]:
        errors.append("baseline build must not load custom research capabilities")
    if not treatment["capability_ids"]:
        errors.append("treatment build must name at least one research capability")
    if baseline["extension_revision"] is not None or baseline["reviewed_diff_sha256"]:
        errors.append("baseline build must not contain a research extension revision")
    if baseline["changed_owner_paths"]:
        errors.append("baseline build must not contain changed capability owner paths")
    if not treatment["extension_revision"] or not treatment["reviewed_diff_sha256"]:
        errors.append("treatment build requires a reviewed extension diff")
    if baseline["core_revision"] != treatment["core_revision"]:
        errors.append("baseline and treatment must share the stock core revision")

    registry = {item["capability_id"]: item for item in CAPABILITY_MAP["capabilities"]}
    unknown = set(treatment["capability_ids"]) - set(registry)
    if unknown:
        errors.append("treatment build names an unknown capability")
        return
    inactive = {
        capability_id
        for capability_id in treatment["capability_ids"]
        if registry[capability_id]["status"] not in {"active", "experimental"}
    }
    if inactive:
        errors.append(
            "treatment capabilities must be active or reviewed Stage 1 experimental"
        )
    experimental = {
        capability_id
        for capability_id in treatment["capability_ids"]
        if registry[capability_id]["status"] == "experimental"
    }
    if experimental:
        readiness = bindings.get("stage1_readiness")
        if (
            plan["stage"] != 1
            or plan["execution_class"] != "formal"
            or readiness is None
        ):
            errors.append(
                "experimental treatment requires a formal Stage 1 readiness binding"
            )
        else:
            path = EVAL_ROOT / readiness["path"]
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != readiness["sha256"]
            ):
                errors.append("Stage 1 readiness manifest byte hash does not match")
            else:
                evidence = json.loads(path.read_text(encoding="utf-8"))
                if (
                    evidence.get("readiness"),
                    evidence.get("validator_status"),
                    evidence.get("resume_status"),
                ) != ("stage-executable", "passed", "passed"):
                    errors.append("Stage 1 readiness evidence is not passing")
                for artifact in evidence.get("artifacts", []):
                    artifact_path = PLUGIN_ROOT.parents[1] / artifact["path"]
                    if (
                        not artifact_path.is_file()
                        or hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                        != artifact["sha256"]
                    ):
                        errors.append(
                            f"Stage 1 readiness artifact byte hash does not match: {artifact['role']}"
                        )
    expected_paths = {
        registry[capability_id]["owner_path"]
        for capability_id in treatment["capability_ids"]
    }
    if set(treatment["changed_owner_paths"]) != expected_paths:
        errors.append(
            "changed_owner_paths must exactly match capability registry owners"
        )
    covered_metrics = {
        effect["metric_id"]
        for capability_id in treatment["capability_ids"]
        for effect in registry[capability_id]["metric_effects"]
    }
    if not set(plan["target_metric_ids"]).issubset(covered_metrics):
        errors.append("every target metric must be covered by a treatment capability")


def _validate_runtime(runtime, errors):
    if runtime["time_limit_policy"] == "fixed-limit":
        if runtime["fixed_limit_seconds"] is None:
            errors.append("fixed-limit runtime requires fixed_limit_seconds")
    elif runtime["fixed_limit_seconds"] is not None:
        errors.append("no-artificial-limit runtime must not set fixed_limit_seconds")


def _validate_judges(configs, errors):
    roles = [config["role"] for config in configs]
    config_ids = [config["config_id"] for config in configs]
    if set(roles) != {"auto-r1", "auto-r2", "auto-adj"}:
        errors.append("judge_configs must contain Auto-R1, Auto-R2, and Auto-ADJ")
    if len(config_ids) != len(set(config_ids)):
        errors.append("judge config IDs must be unique")
    if set(roles) == {"auto-r1", "auto-r2", "auto-adj"}:
        by_role = {config["role"]: config for config in configs}
        r1 = by_role["auto-r1"]
        r2 = by_role["auto-r2"]
        for field in ("model_id", "reasoning", "prompt_sha256"):
            if r1[field] != r2[field]:
                errors.append(f"Auto-R1 and Auto-R2 must share the same {field}")
        if by_role["auto-adj"]["prompt_sha256"] == r1["prompt_sha256"]:
            errors.append("Auto-ADJ must use its separately versioned prompt")
        if r1["evaluation_config_sha256"] != r2["evaluation_config_sha256"]:
            errors.append("Auto-R1 and Auto-R2 must share the evaluation config hash")
        if (
            by_role["auto-adj"]["evaluation_config_sha256"]
            == r1["evaluation_config_sha256"]
        ):
            errors.append("Auto-ADJ must use a separate evaluation config hash")
    contexts = [config["execution_context_id"] for config in configs]
    if len(contexts) != len(set(contexts)):
        errors.append("judge execution context IDs must be unique")


def _validate_repeats(repeats, errors):
    if [repeat["repeat"] for repeat in repeats] != [1, 2, 3]:
        errors.append("paired repeats must be numbered 1, 2, 3 in order")
    if [repeat["order"] for repeat in repeats] != EXPECTED_ORDERS:
        errors.append("paired repeat order must alternate B-T, T-B, B-T")
    run_ids = []
    subject_ids = []
    for repeat in repeats:
        for condition in ("baseline", "treatment"):
            run = repeat[condition]
            run_ids.append(run["run_id"])
            subject_ids.append(run["subject_id"])
    if len(run_ids) != len(set(run_ids)):
        errors.append("all paired run IDs must be unique")
    if len(subject_ids) != len(set(subject_ids)):
        errors.append("all blinded subject IDs must be unique")
    if any(not re.fullmatch(r"subject-[0-9a-f]{16}", item) for item in subject_ids):
        errors.append("blinded subject IDs must use opaque random identifiers")


def _validate_frozen_plan(plan, errors):
    frozen_at = plan["frozen_at"]
    if frozen_at is None:
        errors.append("a frozen evaluation plan requires frozen_at")
        return
    approvals = plan["human_approvals"]
    approval_ids = [approval["actor_id"] for approval in approvals]
    if len(set(approval_ids)) < 2:
        errors.append("a frozen evaluation plan requires two human approvals")
    created = datetime.fromisoformat(plan["created_at"])
    frozen = datetime.fromisoformat(frozen_at)
    if frozen < created:
        errors.append("frozen_at must not precede created_at")
    if date.fromisoformat(plan["subject_runtime"]["data_cutoff"]) > frozen.date():
        errors.append("subject data_cutoff must not be later than frozen_at")
    for approval in approvals:
        approved = datetime.fromisoformat(approval["approved_at"])
        if not created <= approved <= frozen:
            errors.append(
                f"approval by {approval['actor_id']} must occur between creation and freeze"
            )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    errors = validate_plan(plan)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Evaluation plan is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
