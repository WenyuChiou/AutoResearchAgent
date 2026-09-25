"""Bind a factual result to a condition-free judge input."""

import json
from pathlib import Path
import re
import secrets

from .runner import ExecutionBlocked, PLUGIN_ROOT, read_json, sha, write_json


def _reject_leak(model_input, plan):
    rendered = json.dumps(model_input, sort_keys=True).casefold()
    if re.search(r"\b(baseline|treatment)\b", rendered):
        raise ExecutionBlocked("judge input contains a condition label")
    for pair in plan["paired_repeats"]:
        for condition in ("baseline", "treatment"):
            run = pair[condition]
            for key in ("run_id", "subject_id"):
                if run[key].casefold() in rendered:
                    raise ExecutionBlocked(
                        "judge input contains a frozen subject identifier"
                    )


def make_packet(result_path, plan_path, evidence_path, output):
    from validators.holdout_manifest import canonical_sha256
    from validators.stage1_evaluation_result_v2 import validate_result_v2

    eval_root = (PLUGIN_ROOT / "evals").resolve()
    result_path = Path(result_path).resolve()
    evidence_path = Path(evidence_path).resolve()
    output = Path(output).resolve()
    if not result_path.is_relative_to(eval_root) or not result_path.relative_to(
        eval_root
    ).as_posix().startswith("private/"):
        raise ExecutionBlocked("factual result must stay private")
    if any(
        not path.is_relative_to(eval_root)
        or not path.relative_to(eval_root).as_posix().startswith("private/")
        for path in (evidence_path, output)
    ):
        raise ExecutionBlocked("judge source excerpts and packet must stay private")
    plan = read_json(plan_path)
    holdout_path = (eval_root / plan["bindings"]["holdout"]["path"]).resolve()
    if not holdout_path.is_relative_to(eval_root):
        raise ExecutionBlocked("holdout path escapes evaluator")
    holdout = read_json(holdout_path)
    result = read_json(result_path)
    errors = validate_result_v2(result, holdout, plan)
    if errors:
        raise ExecutionBlocked("factual result invalid: " + "; ".join(errors))
    evidence = read_json(evidence_path)
    if not isinstance(evidence, dict) or not isinstance(
        evidence.get("evidence_ids"), list
    ):
        raise ExecutionBlocked("judge evidence packet requires evidence IDs")
    real_subject_id = next(
        run["subject_id"]
        for pair in plan["paired_repeats"]
        for run in (pair["baseline"], pair["treatment"])
        if run["run_id"] == result["run_id"]
    )
    model_input = {
        "run_id": "blind-run-" + secrets.token_hex(16),
        "subject_id": "blind-subject-" + secrets.token_hex(16),
        "factual_result_sha256": canonical_sha256(result),
        "hard_facts": result["fact_metrics"],
        "major_issues": result["major_issues"],
        "evidence_ids": evidence["evidence_ids"],
        "source_excerpts": evidence.get("source_excerpts", []),
    }
    _reject_leak(model_input, plan)
    packet = {
        "kind": "Stage1BlindJudgePacket",
        "schema_version": "1.0.0",
        "factual_result_artifact": {
            "path": result_path.relative_to(eval_root).as_posix(),
            "canonical_sha256": canonical_sha256(result),
        },
        "evidence_artifact": {
            "path": evidence_path.relative_to(eval_root).as_posix(),
            "sha256": sha(evidence_path.read_bytes()),
        },
        "evaluator_mapping": {
            "run_id": result["run_id"],
            "subject_id": real_subject_id,
        },
        "model_input": model_input,
    }
    write_json(output, packet)
    return packet


def verify_packet(packet, plan):
    from validators.holdout_manifest import canonical_sha256
    from validators.stage1_evaluation_result_v2 import validate_result_v2

    eval_root = (PLUGIN_ROOT / "evals").resolve()
    binding = packet["factual_result_artifact"]
    result_path = (eval_root / binding["path"]).resolve()
    if not result_path.is_relative_to(eval_root) or not binding["path"].startswith(
        "private/"
    ):
        raise ExecutionBlocked("judge factual-result binding escapes evaluator")
    result = read_json(result_path)
    if canonical_sha256(result) != binding["canonical_sha256"]:
        raise ExecutionBlocked("judge factual-result hash differs")
    holdout_path = (eval_root / plan["bindings"]["holdout"]["path"]).resolve()
    if not holdout_path.is_relative_to(eval_root):
        raise ExecutionBlocked("holdout path escapes evaluator")
    holdout = read_json(holdout_path)
    errors = validate_result_v2(result, holdout, plan)
    if errors:
        raise ExecutionBlocked(
            "judge factual-result contract fails: " + "; ".join(errors)
        )
    model_input = packet["model_input"]
    if model_input.get("factual_result_sha256") != canonical_sha256(result):
        raise ExecutionBlocked("judge packet factual result hash differs")
    evidence_binding = packet["evidence_artifact"]
    evidence_path = (eval_root / evidence_binding["path"]).resolve()
    if (
        not evidence_path.is_relative_to(eval_root)
        or not evidence_binding["path"].startswith("private/")
        or sha(evidence_path.read_bytes()) != evidence_binding["sha256"]
    ):
        raise ExecutionBlocked("judge source-excerpt bytes differ")
    evidence = read_json(evidence_path)
    if model_input["evidence_ids"] != evidence["evidence_ids"] or model_input[
        "source_excerpts"
    ] != evidence.get("source_excerpts", []):
        raise ExecutionBlocked("judge evidence differs from bound source excerpts")
    expected_subject = next(
        run["subject_id"]
        for pair in plan["paired_repeats"]
        for run in (pair["baseline"], pair["treatment"])
        if run["run_id"] == result["run_id"]
    )
    if (
        packet.get("evaluator_mapping")
        != {"run_id": result["run_id"], "subject_id": expected_subject}
        or not re.fullmatch(r"blind-run-[0-9a-f]{32}", model_input["run_id"])
        or not re.fullmatch(r"blind-subject-[0-9a-f]{32}", model_input["subject_id"])
        or model_input["hard_facts"] != result["fact_metrics"]
        or model_input["major_issues"] != result["major_issues"]
    ):
        raise ExecutionBlocked("judge packet hard facts differ from v2 result")
    _reject_leak(model_input, plan)
    return model_input
