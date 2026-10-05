"""One native judge generation inside a caller-owned role namespace.

This endpoint does not create a namespace, grade an answer, restore aliases, or
promote a calibration. Those operations remain outside the role worker.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator, SchemaError

from stage1_eval.common import EvaluationError, canonical
from stage1_eval.model import _api_schema
from stage1_eval.model_calls import (
    _normalize_policy,
    _request_config,
    call_model_v31,
    replay_native_model_call_archive,
)
from stage2_common import Stage2Error

from .native import _assert_separate, codex_runtime_sha
from .replay import _archive_sha, _require_sha, _safe_root


def worker_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _inline_schema(value):
    if isinstance(value, dict):
        if {"$ref", "$dynamicRef", "$recursiveRef"} & set(value):
            raise Stage2Error("judge-worker-schema-references-unsupported")
        for item in value.values():
            _inline_schema(item)
    elif isinstance(value, list):
        for item in value:
            _inline_schema(item)


def _read_request(path, expected_sha256):
    _require_sha(expected_sha256, "judge-worker-request")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Stage2Error("judge-worker-request-not-regular")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Stage2Error("judge-worker-request-hash-mismatch")
    try:
        unit = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise Stage2Error("judge-worker-request-invalid-json") from error
    keys = {
        "kind",
        "schema_version",
        "role",
        "label",
        "prompt",
        "schema",
        "model",
        "reasoning",
        "runtime_sha256",
        "worker_sha256",
        "execution_policy",
    }
    if not isinstance(unit, dict) or set(unit) != keys:
        raise Stage2Error("judge-worker-request-shape")
    if (
        unit["kind"] != "Stage2NativeJudgeUnit"
        or unit["schema_version"] != "1.0.0"
        or unit["role"] not in ("R1", "R2", "ADJ")
        or not isinstance(unit["label"], str)
        or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", unit["label"])
        or not unit["label"].startswith(unit["role"].lower() + "-")
        or any(
            not isinstance(unit[key], str) or not unit[key].strip()
            for key in ("prompt", "model", "reasoning")
        )
        or not isinstance(unit["schema"], dict)
        or unit["schema"].get("type") != "object"
        or unit["worker_sha256"] != worker_sha256()
    ):
        raise Stage2Error("judge-worker-request-binding")
    _inline_schema(unit["schema"])
    try:
        Draft202012Validator.check_schema(unit["schema"])
    except SchemaError as error:
        raise Stage2Error("judge-worker-invalid-schema") from error
    _require_sha(unit["runtime_sha256"], "judge-worker-runtime")
    policy = _normalize_policy(unit["execution_policy"], None)
    if policy != unit["execution_policy"] or not math.isfinite(
        policy["timeout_seconds"]
    ):
        raise Stage2Error("judge-worker-policy-not-frozen")
    return unit, raw


def _config(unit, codex, home):
    if codex_runtime_sha(codex) != unit["runtime_sha256"]:
        raise Stage2Error("judge-worker-runtime-mismatch")
    return _request_config(codex, home, unit["model"], unit["reasoning"])


def _inventory(root, *, label=None, attempts=None):
    allowed = None
    if label is not None:
        allowed = {
            "worker-request.json",
            f"{label}.schema.json",
            f"{label}.json",
            f"{label}.jsonl",
            f"{label}.stderr.txt",
            *[
                f"{label}.model-call/{name}"
                for name in (
                    "prompt.txt",
                    "schema.json",
                    "generation-schema.json",
                    "request.json",
                )
            ],
        }
        for number in range(1, attempts + 1):
            allowed.update(
                f"{label}.model-call/attempt-{number:02d}.{suffix}"
                for suffix in (
                    "record.json",
                    "stdout.jsonl",
                    "stderr.txt",
                    "output.json",
                )
            )
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Stage2Error("judge-worker-output-symlink")
        if (
            allowed is not None
            and path.is_dir()
            and path != root / f"{label}.model-call"
        ):
            raise Stage2Error("judge-worker-unexpected-output-directory")
        if path.is_file() and path != root / "worker-result.json":
            name = path.relative_to(root).as_posix()
            if allowed is not None and name not in allowed:
                raise Stage2Error("judge-worker-unexpected-output-file")
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if allowed is not None and set(result) != allowed:
        raise Stage2Error("judge-worker-missing-output-file")
    return result


def _recompute(root, unit, request_sha256, config):
    label = unit["label"]
    schema = root / (label + ".schema.json")
    if schema.read_bytes() != canonical(unit["schema"]) + b"\n":
        raise Stage2Error("judge-worker-schema-mismatch")
    native_request = json.loads(
        (root / (label + ".model-call/request.json")).read_bytes()
    )
    if not isinstance(native_request, dict) or native_request.get("label") != label:
        raise Stage2Error("judge-worker-native-label-mismatch")
    value, provenance = replay_native_model_call_archive(
        root / (label + ".model-call"),
        expected_prompt=unit["prompt"],
        expected_schema=schema,
        expected_config=config,
        expected_policy=unit["execution_policy"],
    )
    archive = root / (label + ".model-call")
    records = sorted(archive.glob("attempt-*.record.json"))
    final = json.loads(records[-1].read_bytes())
    if any(
        type(json.loads(path.read_bytes()).get("attempt")) is not int
        for path in records
    ):
        raise Stage2Error("judge-worker-attempt-type")
    if (
        final.get("status") != "completed"
        or type(final.get("returncode")) is not int
        or final["returncode"] != 0
        or final.get("timed_out") is not False
    ):
        raise Stage2Error("judge-worker-generation-incomplete")
    for suffix, key in (
        ("json", "output"),
        ("jsonl", "stdout"),
        ("stderr.txt", "stderr"),
    ):
        if (root / f"{label}.{suffix}").read_bytes() != (
            archive / final["files"][key]["path"]
        ).read_bytes():
            raise Stage2Error("judge-worker-display-copy-mismatch")
    return {
        "kind": "Stage2NativeJudgeWorkerResult",
        "schema_version": "1.0.0",
        "status": "native-generation-replayed",
        "role": unit["role"],
        "label": label,
        "request_sha256": request_sha256,
        "value": value,
        "native_provenance": provenance,
        "archive_sha256": _archive_sha(archive),
        "actual_root_attempts": len(records),
        "files": _inventory(root, label=label, attempts=len(records)),
        "semantic_validation": "host-required",
        "tool_event_policy": "native-transcript-rejects-tool-events",
        "offered_tool_inventory": "external-attestation-required",
        "namespace_isolation": "external-attestation-required",
        "nested_usage_accounting": "not-attested",
        "cost": "unknown",
        "calibration_pass": None,
        "formal_ready": False,
    }


def verify_worker_output(
    output_dir, result_sha256, *, request_file, request_sha256, codex, evaluator_home
):
    """Read-only native replay; never use a saved PASS or dispatch another call."""
    _require_sha(result_sha256, "judge-worker-result")
    root = _safe_root(output_dir)
    unit, raw = _read_request(request_file, request_sha256)
    _assert_separate(root, evaluator_home, Path(request_file).resolve().parent)
    _inventory(root)
    result_path = root / "worker-result.json"
    if hashlib.sha256(result_path.read_bytes()).hexdigest() != result_sha256:
        raise Stage2Error("judge-worker-result-receipt-mismatch")
    if (root / "worker-request.json").read_bytes() != raw:
        raise Stage2Error("judge-worker-request-copy-mismatch")
    expected = _recompute(
        root, unit, request_sha256, _config(unit, codex, evaluator_home)
    )
    if result_path.read_bytes() != canonical(expected) + b"\n":
        raise Stage2Error("judge-worker-result-recomputation-mismatch")
    return expected


def execute_worker_unit(
    request_file, request_sha256, *, output_dir, codex, evaluator_home
):
    """Execute exactly one supplied unit; semantic corrections belong to the host."""
    unit, raw = _read_request(request_file, request_sha256)
    config = _config(unit, codex, evaluator_home)
    output = Path(output_dir)
    if output.is_symlink():
        raise Stage2Error("judge-worker-output-symlink")
    output = output.resolve()
    _assert_separate(output, evaluator_home, Path(request_file).resolve().parent)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise Stage2Error("judge-worker-output-not-fresh-use-readonly-replay")
    output.mkdir(parents=True, exist_ok=True)
    (output / "worker-request.json").write_bytes(raw)
    schema = output / (unit["label"] + ".schema.json")
    schema.write_bytes(canonical(unit["schema"]) + b"\n")
    try:
        call_model_v31(
            unit["prompt"],
            schema,
            output,
            unit["label"],
            codex=config["codex"],
            evaluator_home=config["evaluator_home"],
            model=unit["model"],
            reasoning=unit["reasoning"],
            timeout=unit["execution_policy"]["timeout_seconds"],
            execution_policy=unit["execution_policy"],
            resume_verified=False,
            semantic_validator=None,
            api_schema=lambda value: _api_schema(value, preserve_constraints=True),
        )
        result = _recompute(output, unit, request_sha256, config)
    except (EvaluationError, Stage2Error, OSError, ValueError) as error:
        failure = {
            "kind": "Stage2NativeJudgeWorkerFailure",
            "schema_version": "1.0.0",
            "role": unit["role"],
            "label": unit["label"],
            "request_sha256": request_sha256,
            "status": "evaluator_failure",
            "error": str(error),
            "formal_ready": False,
        }
        (output / "worker-failure.json").write_bytes(canonical(failure) + b"\n")
        raise
    path = output / "worker-result.json"
    path.write_bytes(canonical(result) + b"\n")
    receipt = hashlib.sha256(path.read_bytes()).hexdigest()
    verify_worker_output(
        output,
        receipt,
        request_file=request_file,
        request_sha256=request_sha256,
        codex=codex,
        evaluator_home=evaluator_home,
    )
    return {"result": result, "result_sha256": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--evaluator-home", required=True)
    args = parser.parse_args()
    try:
        result = execute_worker_unit(
            args.request_file,
            args.request_sha256,
            output_dir=args.output_dir,
            codex=args.codex,
            evaluator_home=args.evaluator_home,
        )
    except (EvaluationError, Stage2Error, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "evaluator_failure",
                    "error": str(error),
                    "formal_ready": False,
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": result["result"]["status"],
                "result_sha256": result["result_sha256"],
                "formal_ready": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
