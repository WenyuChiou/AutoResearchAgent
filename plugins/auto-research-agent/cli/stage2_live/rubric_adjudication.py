"""Replay-bound adjudication for a completed Stage 2 rubric-quality run."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from stage1_eval.common import EvaluationError, read_json
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
    _execution_policy,
    _finish_result,
    _run_unit,
    _write_new_or_equal,
)
from .native import codex_runtime_sha
from .rubric_quality import (
    _archived_native_attempts,
    _load_guidance,
    _prompt,
    _validate_batch,
    batch_schema,
)


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _sha(value, label):
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value),
        f"invalid {label}",
    )


def _base_labels():
    return [f"{role}-{number:02d}" for role in ("r1", "r2") for number in range(1, 9)]


def _read_base(run_dir, result_sha256, dataset_sha256, reference_sha256):
    run_dir = Path(run_dir).resolve()
    result_path, request_path = run_dir / "result.json", run_dir / "request.json"
    _sha(result_sha256, "base result hash")
    _require(
        result_path.is_file()
        and hashlib.sha256(result_path.read_bytes()).hexdigest() == result_sha256,
        "base result hash mismatch",
    )
    result, request = read_json(result_path), read_json(request_path)
    _require(
        result.get("kind") == "Stage2RubricQualityRun"
        and result.get("status") == "complete",
        "base run is incomplete",
    )
    _require(
        result.get("adapter_mode") == "native"
        and result.get("evidence_class") == "native-live-diagnostic",
        "base run is not native evidence",
    )
    _require(
        result.get("request_sha256") == canonical_hash(request),
        "base request binding mismatch",
    )
    _require(
        request.get("dataset_sha256") == dataset_sha256
        and request.get("reference_sha256") == reference_sha256,
        "base data binding mismatch",
    )
    bindings = result.get("bindings")
    _require(
        isinstance(bindings, dict)
        and all(bindings.get(key) == request.get(key) for key in bindings),
        "base configuration binding mismatch",
    )
    receipts = result.get("unit_receipts")
    _require(
        isinstance(receipts, dict) and set(receipts) == set(_base_labels()),
        "base unit receipts incomplete",
    )
    policies = []
    for label in _base_labels():
        for suffix in ("schema.json", "unit.json"):
            _require(
                (run_dir / f"{label}.{suffix}").is_file(),
                f"missing base {label} {suffix}",
            )
        archive = run_dir / f"{label}.model-call"
        _require(
            archive.is_dir() and (archive / "request.json").is_file(),
            f"missing base archive {label}",
        )
        policy = read_json(archive / "request.json").get("execution_policy")
        _require(isinstance(policy, dict), "base execution policy missing")
        policies.append(policy)
    _require(
        all(policy == policies[0] for policy in policies), "base unit policies differ"
    )
    _require(
        canonical_hash(policies[0]) == request.get("execution_policy_sha256"),
        "base policy hash mismatch",
    )
    _require(
        policies[0].get("evaluator_bundle_sha256") == request.get("code_sha256"),
        "base code binding mismatch",
    )
    return run_dir, request, result, policies[0]


def _forbid_dispatch(*args, **kwargs):
    raise EvaluationError("base replay attempted a new model dispatch")


def _replay_base(
    dataset, cases, run_dir, request, result, policy, codex, rubric, guidance
):
    receipts = result["unit_receipts"]
    rebuilt = {}
    ordered = [cases[row["case_id"]] for row in dataset["cases"]]
    for role in ("R1", "R2"):
        rows = []
        options = _call_options(
            codex,
            request["evaluator_homes"][role],
            request["model"],
            request["reasoning"],
            policy,
            True,
            unit_receipts=receipts,
        )
        for index in range(8):
            batch = ordered[index * 7 : (index + 1) * 7]
            value, _ = _run_unit(
                call_adapter=_forbid_dispatch,
                prompt=_prompt(role, batch, rubric, guidance),
                schema=batch_schema(role, batch),
                output_dir=run_dir,
                label=f"{role.lower()}-{index + 1:02d}",
                options=options,
                validate=lambda value, role=role, batch=batch: _validate_batch(
                    value, role, batch
                ),
            )
            rows.extend(value["judgments"])
        rebuilt[role] = {
            "role": role,
            "bindings": result["bindings"],
            "judgments": rows,
        }
    _require(
        rebuilt == result.get("roles"),
        "replayed roles differ from immutable base result",
    )
    return rebuilt


def _judgment_fields(case):
    ids = [fact["evidence_id"] for fact in case["facts"]]
    return {
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


def _initial_schema(case):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "kind": _const("Stage2RubricQualityAdjInitial"),
                "schema_version": _const("1.0.0"),
                **_judgment_fields(case),
            }
        ),
    }


def _resolution_schema(case):
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "kind": _const("Stage2RubricQualityAdjResolution"),
                "schema_version": _const("1.0.0"),
                **_judgment_fields(case),
                "change_explanation": {"type": ["string", "null"]},
            }
        ),
    }


def _case_payload(case, rubric, guidance):
    criterion = next(
        row for row in rubric["criteria"] if row["id"] == case["criterion_id"]
    )
    return {
        "guidance": guidance,
        "case": {
            key: deepcopy(case[key])
            for key in (
                "case_id",
                "criterion_id",
                "observation",
                "facts",
                "presentation",
            )
        },
        "criterion": {
            "question": criterion["question"],
            "anchors": criterion["anchors"],
        },
    }


def _initial_prompt(case, rubric, guidance):
    return (
        "Independently judge this one case before seeing other reviewers. Use only the supplied case facts, subject-record observation, criterion, and frozen guidance. Do not infer an answer key or human decision.\n"
        + json.dumps(
            _case_payload(case, rubric, guidance), ensure_ascii=False, sort_keys=True
        )
    )


def _resolution_prompt(case, rubric, guidance, initial, pair):
    anonymous = sorted(
        (deepcopy(pair[0]), deepcopy(pair[1])),
        key=lambda row: json.dumps(row, sort_keys=True),
    )
    payload = _case_payload(case, rubric, guidance)
    payload.update(
        {"own_initial": initial, "reviewer_a": anonymous[0], "reviewer_b": anonymous[1]}
    )
    return (
        "Resolve the one disagreement using the supplied evidence and guidance. Preserve your independent judgment unless evidence warrants a change. Cite case evidence and give change_explanation when your status, score, or major-error decision changes. No reference answer or human audit is supplied.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _validate_initial(value, case):
    _require(
        isinstance(value, dict)
        and value.get("kind") == "Stage2RubricQualityAdjInitial"
        and value.get("schema_version") == "1.0.0",
        "invalid ADJ initial envelope",
    )
    _require(
        set(value) == {"kind", "schema_version", *_judgment_fields(case)},
        "unexpected ADJ initial fields",
    )
    validate_judgment({key: value[key] for key in _judgment_fields(case)}, case)


def _validate_resolution(value, case, initial):
    _require(
        isinstance(value, dict)
        and value.get("kind") == "Stage2RubricQualityAdjResolution"
        and value.get("schema_version") == "1.0.0",
        "invalid ADJ resolution envelope",
    )
    _require(
        set(value)
        == {"kind", "schema_version", "change_explanation", *_judgment_fields(case)},
        "unexpected ADJ resolution fields",
    )
    row = {key: value[key] for key in _judgment_fields(case)}
    validate_judgment(row, case)
    changed = any(
        row[key] != initial[key] for key in ("status", "score", "major_error")
    )
    explanation = value.get("change_explanation")
    _require(
        (not changed and explanation is None)
        or (changed and isinstance(explanation, str) and explanation.strip()),
        "changed ADJ judgment needs change explanation",
    )


def _adj_code_binding(base_code, guidance_sha256):
    deterministic_quality = (
        Path(__file__).parents[1] / "stage2_eval" / "rubric_quality.py"
    )
    live_quality = Path(__file__).with_name("rubric_quality.py")
    return canonical_hash(
        {
            "base_code_sha256": base_code,
            "guidance_sha256": guidance_sha256,
            "adjudication_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "deterministic_quality_sha256": hashlib.sha256(
                deterministic_quality.read_bytes()
            ).hexdigest(),
            "live_quality_sha256": hashlib.sha256(
                live_quality.read_bytes()
            ).hexdigest(),
        }
    )


def _quality_acceptance(raw_report, resolved, refs, native):
    expected = set(raw_report["significant_disagreements"])
    resolved_ok = (
        len(resolved) == len(expected)
        and {item["case_id"] for item in resolved} == expected
    )
    for item in resolved:
        row, ref = item["resolution"], refs[item["case_id"]]
        resolved_ok = (
            resolved_ok
            and row["status"] == "scored"
            and row["status"] == ref["status"]
            and row["score"] in ref["allowed_scores"]
            and bool(row["evidence_ids"])
            and row["major_error"] == ref["major_error"]
        )
    base_ok = (
        raw_report["complete"]
        and not raw_report["critical_mismatches"]
        and not raw_report["major_error_invariance_mismatches"]
        and all(
            raw_report["rates"][key] >= value
            for key, value in raw_report["thresholds"].items()
        )
    )
    return native and base_ok and resolved_ok


def resolve_rubric_quality(
    dataset,
    reference,
    *,
    dataset_sha256,
    reference_sha256,
    run_dir,
    run_result_sha256,
    codex,
    adj_home,
    model,
    reasoning,
    execution_policy,
    output_dir,
    call_adapter=None,
):
    """Verify/replay the immutable base run, then adjudicate significant differences."""
    cases = validate_dataset(dataset, dataset_sha256)
    refs = validate_reference(reference, reference_sha256, cases)
    run_dir, base_request, base_result, base_policy = _read_base(
        run_dir, run_result_sha256, dataset_sha256, reference_sha256
    )
    rubric, rubric_sha256 = _load_rubric(RUBRIC_PATH)
    guidance, guidance_sha256 = _load_guidance(rubric)
    _require(
        base_request.get("rubric_sha256") == rubric_sha256
        and base_request.get("guidance_sha256") == guidance_sha256,
        "base rubric or guidance changed",
    )
    _require(
        codex_runtime_sha(codex) == base_request.get("runtime_sha256"),
        "base runtime changed",
    )
    _require(
        model == base_request.get("model")
        and reasoning == base_request.get("reasoning"),
        "ADJ model configuration differs from base",
    )
    homes = {Path(path).resolve() for path in base_request["evaluator_homes"].values()}
    adj_home = Path(adj_home).resolve()
    _require(
        adj_home.is_dir() and adj_home not in homes,
        "ADJ home must exist and be independent",
    )
    roles = _replay_base(
        dataset,
        cases,
        run_dir,
        base_request,
        base_result,
        base_policy,
        codex,
        rubric,
        guidance,
    )
    bindings = {
        key: value
        for key, value in base_result["bindings"].items()
        if key != "dataset_sha256"
    }
    recomputed = evaluate_quality(
        dataset,
        reference,
        roles["R1"],
        roles["R2"],
        dataset_sha256=dataset_sha256,
        reference_sha256=reference_sha256,
        bindings=bindings,
    )
    recomputed["native_qa_pass"] = recomputed["passed"]
    _require(
        recomputed == base_result.get("quality_report"),
        "base quality report was rewritten",
    )
    raw_report = deepcopy(base_result["quality_report"])
    output = Path(output_dir)
    _require(
        not output.exists() or not any(output.iterdir()),
        "resolution output directory must be empty",
    )
    output.mkdir(parents=True, exist_ok=True)
    policy_input = dict(execution_policy)
    policy_input["evaluator_bundle_sha256"] = _adj_code_binding(
        base_request["code_sha256"], guidance_sha256
    )
    policy = _execution_policy(policy_input)
    request = {
        "kind": "Stage2RubricQualityResolutionRequest",
        "schema_version": "1.0.0",
        "base_run_result_sha256": run_result_sha256,
        "base_request_sha256": base_result["request_sha256"],
        "dataset_sha256": dataset_sha256,
        "reference_sha256": reference_sha256,
        "rubric_sha256": rubric_sha256,
        "guidance_sha256": guidance_sha256,
        "base_code_sha256": base_request["code_sha256"],
        "adjudication_code_sha256": policy["evaluator_bundle_sha256"],
        "runtime_sha256": base_request["runtime_sha256"],
        "model": model,
        "reasoning": reasoning,
        "execution_policy_sha256": canonical_hash(policy),
        "adj_home": str(adj_home),
        "adapter_mode": "injected-test" if call_adapter else "native",
        "planned_calls": 2 * len(raw_report["significant_disagreements"]),
    }
    _write_new_or_equal(output / "request.json", request)
    adapter, receipts, resolved, completed = call_adapter or call_model_v31, {}, [], 0
    options = _call_options(
        codex, adj_home, model, reasoning, policy, False, receipt_sink=receipts
    )
    by_role = {
        role: {row["case_id"]: row for row in result["judgments"]}
        for role, result in roles.items()
    }
    try:
        for index, case_id in enumerate(raw_report["significant_disagreements"], 1):
            case, pair = (
                cases[case_id],
                (by_role["R1"][case_id], by_role["R2"][case_id]),
            )
            initial, initial_proof = _run_unit(
                call_adapter=adapter,
                prompt=_initial_prompt(case, rubric, guidance),
                schema=_initial_schema(case),
                output_dir=output,
                label=f"adj-{index:02d}-initial",
                options=options,
                validate=lambda value, case=case: _validate_initial(value, case),
            )
            completed += 1
            final, final_proof = _run_unit(
                call_adapter=adapter,
                prompt=_resolution_prompt(case, rubric, guidance, initial, pair),
                schema=_resolution_schema(case),
                output_dir=output,
                label=f"adj-{index:02d}-resolution",
                options=options,
                validate=lambda value, case=case, initial=initial: _validate_resolution(
                    value, case, initial
                ),
            )
            completed += 1
            resolved.append(
                {
                    "case_id": case_id,
                    "initial": initial,
                    "resolution": final,
                    "call_proof": {"initial": initial_proof, "resolution": final_proof},
                }
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
            "kind": "Stage2RubricQualityResolution",
            "schema_version": "1.0.0",
            "status": "evaluator-failure",
            "error": str(error),
            "request_sha256": canonical_hash(request),
            "raw_report": raw_report,
            "adjudications": resolved,
            "quality_accepted": False,
            "formal_ready": False,
            "human_audit": None,
            "execution": {
                "planned_units": request["planned_calls"],
                "completed_units": completed,
                "archived_native_attempts": _archived_native_attempts(
                    output, call_adapter is None
                ),
            },
        }
        return _finish_result(output, "result.json", failure, receipts)
    accepted = _quality_acceptance(raw_report, resolved, refs, call_adapter is None)
    result = {
        "kind": "Stage2RubricQualityResolution",
        "schema_version": "1.0.0",
        "status": "complete",
        "request_sha256": canonical_hash(request),
        "base_run_result_sha256": run_result_sha256,
        "dataset_sha256": dataset_sha256,
        "reference_sha256": reference_sha256,
        "raw_report": raw_report,
        "adjudications": resolved,
        "execution": {
            "planned_units": request["planned_calls"],
            "completed_units": completed,
            "archived_native_attempts": _archived_native_attempts(
                output, call_adapter is None
            ),
        },
        "quality_accepted": accepted,
        "evidence_class": "injected-fake-test-only"
        if call_adapter
        else "native-live-diagnostic",
        "formal_ready": False,
        "human_audit": None,
    }
    return _finish_result(output, "result.json", result, receipts)


__all__ = ["resolve_rubric_quality"]
