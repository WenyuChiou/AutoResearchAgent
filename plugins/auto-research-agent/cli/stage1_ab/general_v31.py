"""Replay every v3.1 scoring unit before deciding a frozen paired comparison."""

import json
from pathlib import Path
from types import SimpleNamespace

from stage1_eval.common import canonical, read_json, validate_schema
from stage1_eval.pipeline_v31 import bundle_sha_v31, evaluate_v31, execution_policy

from . import runner, sequence
from .general import _check_result_scores, _paired_decision


def _replay_result(result_path, capture_dir, lock_path, background_path, lock):
    path = Path(result_path).resolve()
    if path.name != "result.json":
        raise runner.ExecutionBlocked(
            "v3.1 result must be its complete evaluator archive"
        )
    result = read_json(path)
    validate_schema(result, "stage-evaluation-result.v3_1.schema.json")
    if (
        result["execution_class"] != "formal"
        or result["evidence_mode"] != "evidence-audited"
    ):
        raise runner.ExecutionBlocked(
            "diagnostic or pilot evidence cannot enter formal pairs"
        )
    root = path.parent
    value = read_json(root / "evaluation-input.json")
    config = value["model_config"]
    if (
        result["evaluation_input_sha256"] != runner.sha(canonical(value))
        or value["execution_class"] != "formal"
        or value["policy"] != execution_policy()
        or result["rubric_sha256"] != lock["rubric_sha256"]
        or result["spec_sha256"] != lock["spec_sha256"]
        or value["identity"]["model"] != lock["evaluator_runtime"]["model"]
        or value["identity"]["reasoning"] != lock["evaluator_runtime"]["reasoning"]
    ):
        raise runner.ExecutionBlocked(
            "v3.1 result binding differs from the frozen experiment"
        )
    args = SimpleNamespace(
        output=str(root),
        resume_verified=True,
        task=str(root / "task.txt"),
        spec=str(root / "spec.json"),
        hub=None,
        hub_command_json=json.dumps(["@python", "-m", "research_hub"]),
        artifact=[],
        saved_extraction=None,
        resume_pilot=False,
        execution_class="formal",
        portable_diagnostic=False,
        capture=str(capture_dir),
        lock=str(lock_path),
        codex=config["codex"],
        evaluator_home=config["evaluator_home"],
        model=config["model"],
        reasoning=config["reasoning"],
        mode="evidence-audited",
        background=str(background_path),
        background_sha256=lock["background_sha256"],
    )
    replay = evaluate_v31(args, replay_only=True)
    if canonical(replay) != canonical(result):
        raise runner.ExecutionBlocked(
            "v3.1 result differs from complete offline replay"
        )
    _check_result_scores(result)
    return result


def paired_v31(lock_path, background_path, result_paths, capture_dirs, output):
    raw = Path(lock_path).read_bytes()
    lock = json.loads(raw)
    if (
        lock.get("kind") != "Stage1ABPublicLockV3"
        or lock.get("schema_version") != "3.1.0"
        or lock.get("execution_class") != "formal"
        or lock.get("evaluator_bundle_sha256") != bundle_sha_v31()
        or lock.get("evaluator_execution_policy") != execution_policy()
        or lock.get("plugin_tree_sha256") != runner.tree_sha(runner.PLUGIN_ROOT)
        or runner.sha(Path(background_path).read_bytes())
        != lock.get("background_sha256")
    ):
        raise runner.ExecutionBlocked("v3.1 paired lock or frozen bytes changed")
    expected = sequence.expected_runs(lock)
    if len(expected) != 6 or len(result_paths) != 6 or len(capture_dirs) != 6:
        raise runner.ExecutionBlocked(
            "v3.1 paired evaluation requires exactly six runs"
        )
    by_run = {}
    for result_path, capture_dir in zip(result_paths, capture_dirs, strict=True):
        record = runner.verify_capture(capture_dir, verify_runtime=True)
        if (
            record.get("status") != "complete"
            or record.get("lock_kind") != "Stage1ABPublicLockV3"
            or record.get("stage1_receipt_error")
            or record.get("lock_sha256") != runner.sha(raw)
            or (
                record.get("condition") == "treatment"
                and not record.get("stage1_receipt")
            )
            or record["run_id"] in by_run
        ):
            raise runner.ExecutionBlocked(
                "v3.1 capture is incomplete, duplicated or unbound"
            )
        result = _replay_result(
            result_path, capture_dir, lock_path, background_path, lock
        )
        if result["formal_capture"]["run_id"] != record["run_id"]:
            raise runner.ExecutionBlocked("v3.1 result belongs to another subject")
        by_run[record["run_id"]] = {
            "result": result,
            "capture": record,
            "result_sha256": runner.sha(Path(result_path).read_bytes()),
        }
    if (
        set(by_run) != {row["run_id"] for row in expected}
        or len({row["capture"]["series_id"] for row in by_run.values()}) != 1
    ):
        raise runner.ExecutionBlocked("v3.1 results mix runs or execution series")
    return _paired_decision(lock, by_run, runner.sha(raw), output)
