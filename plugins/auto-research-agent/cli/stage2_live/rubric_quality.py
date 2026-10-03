"""Native, isolated batch adapter for Stage 2 rubric-quality calibration."""

import hashlib
import json
from pathlib import Path

from stage1_eval.common import EvaluationError
from stage1_eval.model_calls import call_model_v31
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.evaluation import RUBRIC_PATH, _load_rubric
from stage2_eval.rubric_quality import (
    evaluate_quality,
    validate_dataset,
    validate_judgment,
    validate_reference,
)
from .judge_schemas import _const, _object, _text
from .judges import (
    _call_options,
    _code_binding,
    _execution_policy,
    _finish_result,
    _run_unit,
    _write_new_or_equal,
)
from .native import codex_runtime_sha

GUIDANCE_PATH = (
    Path(__file__).resolve().parents[2] / "evals/rubrics/stage2-judge-guidance.v1.json"
)


def _load_guidance(rubric):
    try:
        guidance = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 judge guidance: {error}") from error
    expected = {
        "kind",
        "schema_version",
        "rubric_id",
        "purpose",
        "observation_statuses",
        "major_error_rules",
        "decision_order",
    }
    if not isinstance(guidance, dict) or set(guidance) != expected:
        raise Stage2Error("unexpected Stage 2 judge guidance shape")
    if (
        guidance["kind"] != "Stage2JudgeGuidance"
        or guidance["schema_version"] != "1.0.0"
        or guidance["rubric_id"] != rubric["rubric_id"]
    ):
        raise Stage2Error("wrong Stage 2 judge guidance binding")
    statuses, errors = guidance["observation_statuses"], guidance["major_error_rules"]
    if not isinstance(statuses, dict) or set(statuses) != {
        "observed",
        "unavailable",
        "verified-absent",
    }:
        raise Stage2Error("judge guidance observation statuses changed")
    if not isinstance(errors, dict) or set(errors) != set(rubric["major_error_ids"]):
        raise Stage2Error("judge guidance major-error rules changed")
    order = guidance.get("decision_order")
    if not isinstance(order, list) or len(order) != 4:
        raise Stage2Error("judge guidance decision order changed")
    strings = [guidance["purpose"], *statuses.values(), *errors.values(), *order]
    if not all(isinstance(value, str) and value.strip() for value in strings):
        raise Stage2Error("judge guidance text is incomplete")
    return guidance, canonical_hash(guidance)


def _quality_code_binding(guidance_sha256):
    from stage2_eval import rubric_quality as evaluator

    return canonical_hash(
        {
            "shared": _code_binding(),
            "evaluation": hashlib.sha256(
                Path(evaluator.__file__).read_bytes()
            ).hexdigest(),
            "adapter": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "guidance_sha256": guidance_sha256,
        }
    )


def _homes(r1_home, r2_home):
    homes = {"R1": Path(r1_home).resolve(), "R2": Path(r2_home).resolve()}
    if len(set(homes.values())) != 2:
        raise Stage2Error("R1 and R2 evaluator homes must resolve uniquely")
    if any(not path.is_dir() for path in homes.values()):
        raise Stage2Error("evaluator home does not exist")
    return homes


def _archived_native_attempts(output, native):
    if not native:
        return 0
    records = list(Path(output).glob("*.model-call/attempt-*.record.json"))
    return len(records) if records else "unknown"


def batch_schema(role, cases):
    def row_schema(case):
        ids = [fact["evidence_id"] for fact in case["facts"]]
        return _object(
            {
                "case_id": _const(case["case_id"]),
                "status": {
                    "type": "string",
                    "enum": ["scored", "unknown", "evaluator_failure"],
                },
                "score": {"type": ["integer", "null"], "enum": [0, 1, 2, None]},
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": ids},
                    "uniqueItems": True,
                },
                "reason": _text(),
                "major_error": {"type": ["boolean", "null"]},
            }
        )

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "kind": _const("Stage2RubricQualityBatch"),
                "schema_version": _const("1.0.0"),
                "role": _const(role),
                "judgments": {
                    "type": "array",
                    "items": {"anyOf": [row_schema(case) for case in cases]},
                    "minItems": 7,
                    "maxItems": 7,
                },
            }
        ),
    }


def _validate_batch(value, role, cases):
    if (
        not isinstance(value, dict)
        or value.get("kind") != "Stage2RubricQualityBatch"
        or value.get("schema_version") != "1.0.0"
        or value.get("role") != role
    ):
        raise Stage2Error("invalid rubric-quality batch envelope")
    rows = value.get("judgments")
    expected = {case["case_id"]: case for case in cases}
    if (
        not isinstance(rows, list)
        or len(rows) != 7
        or {row.get("case_id") for row in rows if isinstance(row, dict)}
        != set(expected)
    ):
        raise Stage2Error("batch must return the seven actual case IDs once")
    for row in rows:
        validate_judgment(row, expected[row["case_id"]])


def _prompt(role, cases, rubric, guidance):
    criteria = {row["id"]: row for row in rubric["criteria"]}
    payload = []
    for case in cases:
        rule = criteria[case["criterion_id"]]
        facts = [
            {"evidence_id": fact["evidence_id"], "text": fact["text"]}
            for fact in case["facts"]
        ]
        payload.append(
            {
                "case_id": case["case_id"],
                "criterion_id": case["criterion_id"],
                "criterion_question": rule["question"],
                "anchors": rule["anchors"],
                "observation": case.get("observation"),
                "facts": facts,
                "presentation": case["presentation"],
            }
        )
    return (
        f"Act as independent {role}. Judge each supplied case only from its facts and the frozen criterion. "
        "The observation status describes the evaluated subject record. Unavailable means that record could not be obtained: return unknown/null, because background facts do not prove what the subject said. Verified-absent means a completed deliverable was inspected and the criterion-specific omission may warrant 0; observed records are judged normally. Return every actual case ID once. Use evaluator_failure only for your technical failure. Do not infer an answer key, other reviewer result, or human decision.\n"
        + json.dumps(
            {"guidance": guidance, "cases": payload}, ensure_ascii=False, sort_keys=True
        )
    )


def run_rubric_quality(
    dataset,
    reference,
    *,
    dataset_sha256,
    reference_sha256,
    codex,
    r1_home,
    r2_home,
    model,
    reasoning,
    execution_policy,
    output_dir,
    call_adapter=None,
):
    """Run exactly 8 seven-case native units per independent role, without resume."""
    cases_by_id = validate_dataset(dataset, dataset_sha256)
    validate_reference(reference, reference_sha256, cases_by_id)
    rubric, rubric_sha256 = _load_rubric(RUBRIC_PATH)
    guidance, guidance_sha256 = _load_guidance(rubric)
    homes = _homes(r1_home, r2_home)
    runtime_sha256 = codex_runtime_sha(codex)
    policy_input = dict(execution_policy)
    policy_input["evaluator_bundle_sha256"] = _quality_code_binding(guidance_sha256)
    policy = _execution_policy(policy_input)
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise Stage2Error(
            "rubric-quality output directory must be empty; resume is unsupported"
        )
    output.mkdir(parents=True, exist_ok=True)
    bindings = {
        "dataset_sha256": dataset_sha256,
        "rubric_sha256": rubric_sha256,
        "guidance_sha256": guidance_sha256,
        "code_sha256": policy["evaluator_bundle_sha256"],
        "runtime_sha256": runtime_sha256,
        "model": model,
        "reasoning": reasoning,
        "execution_policy_sha256": canonical_hash(policy),
        "evaluator_homes": {role: str(path) for role, path in homes.items()},
    }
    request = {
        "kind": "Stage2RubricQualityRequest",
        "schema_version": "1.0.0",
        **bindings,
        "reference_sha256": reference_sha256,
        "adapter_mode": "injected-test" if call_adapter else "native",
        "batch_size": 7,
        "units_per_role": 8,
        "planned_units": 16,
        "cost": "unknown",
        "resume_supported": False,
    }
    _write_new_or_equal(output / "request.json", request)
    adapter = call_adapter or call_model_v31
    ordered = [cases_by_id[row["case_id"]] for row in dataset["cases"]]
    results, receipts, started, completed = {}, {}, 0, 0
    try:
        for role in ("R1", "R2"):
            results[role] = {"role": role, "bindings": bindings, "judgments": []}
            options = _call_options(
                codex,
                homes[role],
                model,
                reasoning,
                policy,
                False,
                receipt_sink=receipts,
            )
            for index in range(8):
                batch = ordered[index * 7 : (index + 1) * 7]
                started += 1
                value, _ = _run_unit(
                    call_adapter=adapter,
                    prompt=_prompt(role, batch, rubric, guidance),
                    schema=batch_schema(role, batch),
                    output_dir=output,
                    label=f"{role.lower()}-{index + 1:02d}",
                    options=options,
                    validate=lambda value, role=role, batch=batch: _validate_batch(
                        value, role, batch
                    ),
                )
                completed += 1
                results[role]["judgments"].extend(value["judgments"])
        report = evaluate_quality(
            dataset,
            reference,
            results["R1"],
            results["R2"],
            dataset_sha256=dataset_sha256,
            reference_sha256=reference_sha256,
            bindings={
                key: value for key, value in bindings.items() if key != "dataset_sha256"
            },
        )
    except (
        EvaluationError,
        Stage2Error,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as error:
        failure = {
            "kind": "Stage2RubricQualityRun",
            "schema_version": "1.0.0",
            "request_sha256": canonical_hash(request),
            "status": "evaluator-failure",
            "error": str(error),
            "bindings": bindings,
            "roles": results,
            "adapter_mode": request["adapter_mode"],
            "evidence_class": "injected-fake-test-only"
            if call_adapter
            else "native-live-diagnostic",
            "execution": {
                "planned_units": 16,
                "started_units": started,
                "completed_units": completed,
                "archived_native_attempts": _archived_native_attempts(
                    output, call_adapter is None
                ),
                "cost": "unknown",
            },
            "diagnostic_only": True,
            "formal_ready": False,
            "resume_supported": False,
        }
        return _finish_result(output, "result.json", failure, receipts)
    if call_adapter:
        report["passed"] = False
        report["native_qa_pass"] = False
        report["readiness_reason"] = (
            "injected fake adapters cannot establish native rubric quality"
        )
    else:
        report["native_qa_pass"] = report["passed"]
    result = {
        "kind": "Stage2RubricQualityRun",
        "schema_version": "1.0.0",
        "request_sha256": canonical_hash(request),
        "status": "complete",
        "adapter_mode": request["adapter_mode"],
        "evidence_class": "injected-fake-test-only"
        if call_adapter
        else "native-live-diagnostic",
        "execution": {
            "planned_units": 16,
            "started_units": started,
            "completed_units": completed,
            "archived_native_attempts": _archived_native_attempts(
                output, call_adapter is None
            ),
            "cost": "unknown",
        },
        "bindings": bindings,
        "roles": results,
        "quality_report": report,
        "diagnostic_only": True,
        "formal_ready": False,
        "resume_supported": False,
    }
    return _finish_result(output, "result.json", result, receipts)
