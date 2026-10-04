"""Read-only admission of a completed native rubric-quality calibration."""

import hashlib
from pathlib import Path

from stage1_eval.common import EvaluationError
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.evaluation import RUBRIC_PATH, _load_rubric
from stage2_eval.rubric_quality import (
    evaluate_quality,
    validate_dataset,
    validate_reference,
)
from stage2_live.native import codex_runtime_sha
from stage2_live.rubric_adjudication import _read_base, _replay_base
from stage2_live.rubric_quality import _load_guidance

_NATIVE_REPLAY_BASE = _replay_base
_REPLAY_BASE = _NATIVE_REPLAY_BASE


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _verification_code_sha256():
    live = Path(__file__).resolve().parents[1] / "stage2_live"
    return canonical_hash(
        {
            "admission_sha256": _file_sha(__file__),
            "deterministic_quality_sha256": _file_sha(
                Path(__file__).with_name("rubric_quality.py")
            ),
            "native_replay_sha256": _file_sha(live / "rubric_adjudication.py"),
            "live_quality_sha256": _file_sha(live / "rubric_quality.py"),
        }
    )


def _reject_linked_root(run_dir):
    root = Path(run_dir)
    try:
        linked = root.is_symlink() or (
            hasattr(root, "is_junction") and root.is_junction()
        )
        attributes = getattr(root.lstat(), "st_file_attributes", 0)
    except OSError as error:
        raise Stage2Error(f"cannot inspect rubric-quality run root: {error}") from error
    _require(not linked and not attributes & 0x400, "linked run root is forbidden")
    _require(root.is_dir(), "rubric-quality run root is missing")


def _reasons(report, native_replay):
    reasons = []
    if not native_replay:
        reasons.append("synthetic-test-only replay cannot establish admission")
    if not report["complete"]:
        reasons.append("quality report is incomplete")
    if report["missing"]:
        reasons.append("evaluator judgments are missing")
    if report["evaluator_failures"]:
        reasons.append("evaluator failures are present")
    if report["critical_mismatches"]:
        reasons.append("critical reference mismatches are present")
    if report["significant_disagreements"]:
        reasons.append("significant reviewer disagreements require adjudication")
    if report["major_error_invariance_mismatches"]:
        reasons.append("major-error presentation invariance failed")
    for metric, threshold in report["thresholds"].items():
        if report["rates"][metric] < threshold:
            reasons.append(f"{metric} is below its frozen threshold")
    if report["counts"].get("within_range_total") != 112:
        reasons.append("within-range denominator is not 112")
    if report["counts"].get("agreement_total") != 56:
        reasons.append("agreement denominator is not 56")
    if report["counts"].get("invariant_total") != 56:
        reasons.append("presentation-invariance denominator is not 56")
    if not report["passed"] and not reasons:
        reasons.append("raw rubric-quality gate did not pass")
    return reasons


def verify_rubric_quality_admission(
    dataset,
    reference,
    *,
    dataset_sha256,
    reference_sha256,
    run_dir,
    run_result_sha256,
    codex,
):
    """Replay and recompute a native QA run without dispatching or writing."""
    cases = validate_dataset(dataset, dataset_sha256)
    validate_reference(reference, reference_sha256, cases)
    _reject_linked_root(run_dir)
    try:
        root, request, result, policy = _read_base(
            run_dir, run_result_sha256, dataset_sha256, reference_sha256
        )
        rubric, rubric_sha256 = _load_rubric(RUBRIC_PATH)
        guidance, guidance_sha256 = _load_guidance(rubric)
        _require(
            request.get("rubric_sha256") == rubric_sha256,
            "base rubric differs from current rubric",
        )
        _require(
            request.get("guidance_sha256") == guidance_sha256,
            "base guidance differs from current guidance",
        )
        runtime_sha256 = codex_runtime_sha(codex)
        _require(
            request.get("runtime_sha256") == runtime_sha256,
            "base runtime differs from current runtime",
        )
        native_replay = _REPLAY_BASE is _NATIVE_REPLAY_BASE
        roles = _REPLAY_BASE(
            dataset,
            cases,
            root,
            request,
            result,
            policy,
            codex,
            rubric,
            guidance,
        )
        bindings = {
            key: value
            for key, value in result["bindings"].items()
            if key != "dataset_sha256"
        }
        report = evaluate_quality(
            dataset,
            reference,
            roles["R1"],
            roles["R2"],
            dataset_sha256=dataset_sha256,
            reference_sha256=reference_sha256,
            bindings=bindings,
        )
        report["native_qa_pass"] = report["passed"]
        _require(
            report == result.get("quality_report"),
            "base quality report differs from deterministic replay",
        )
    except Stage2Error:
        raise
    except (
        EvaluationError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as error:
        raise Stage2Error(
            f"rubric-quality admission verification failed: {error}"
        ) from error

    reasons = _reasons(report, native_replay)
    verification_code_sha256 = _verification_code_sha256()
    admission_bindings = {
        "verification_code_sha256": verification_code_sha256,
        "model": request["model"],
        "reasoning": request["reasoning"],
        "runtime_sha256": runtime_sha256,
        "rubric_sha256": rubric_sha256,
        "guidance_sha256": guidance_sha256,
        "base_code_sha256": request["code_sha256"],
        "execution_policy_sha256": canonical_hash(policy),
    }
    return {
        "kind": "Stage2RubricQualityAdmission",
        "schema_version": "1.0.0",
        "evidence_class": (
            "native-readonly-replay" if native_replay else "synthetic-test-only"
        ),
        "dataset_sha256": dataset_sha256,
        "reference_sha256": reference_sha256,
        "base_run_result_sha256": run_result_sha256,
        "base_request_sha256": result["request_sha256"],
        "base_code_sha256": request["code_sha256"],
        "verification_code_sha256": verification_code_sha256,
        "rubric_sha256": rubric_sha256,
        "guidance_sha256": guidance_sha256,
        "runtime_sha256": runtime_sha256,
        "execution_policy_sha256": canonical_hash(policy),
        "model": request["model"],
        "reasoning": request["reasoning"],
        "bindings": admission_bindings,
        "counts": report["counts"],
        "rates": report["rates"],
        "thresholds": report["thresholds"],
        "accepted": native_replay and not reasons,
        "reasons": reasons,
        "formal_ready": False,
        "replayed_model_units": 16,
        "new_model_calls": 0,
    }


__all__ = ["verify_rubric_quality_admission"]
