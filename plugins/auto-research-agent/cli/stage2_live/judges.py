"""Callable, isolated Stage 2 v2 judge adapter with append-only evidence."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from stage1_eval.common import EvaluationError, canonical, read_json
from stage1_eval.model import _api_schema
from stage1_eval.model_calls import (
    _normalize_policy,
    _request_config,
    call_model_v31,
    replay_native_model_call_archive,
)
from .native import codex_runtime_sha
import stage2_common
import stage2_eval.evaluation
from . import judge_schemas
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval import (
    merge_judgments,
    prepare_action_view,
    prepare_content_view,
    validate_action_record,
    validate_content_assessment,
    validate_judge_output,
)
from stage2_eval.evaluation import RUBRIC_PATH

from .judge_schemas import content_assessment_schema, judge_assessment_schema

GUIDANCE_PATH = RUBRIC_PATH.with_name("stage2-judge-guidance.v1.json")


def _write_new_or_equal(path, value):
    path = Path(path)
    raw = canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise EvaluationError(f"saved Stage 2 judge artifact changed: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _read_rubric():
    try:
        return json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 rubric: {error}") from error


def _read_guidance():
    try:
        value = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 judge guidance: {error}") from error
    keys = {
        "kind",
        "schema_version",
        "rubric_id",
        "purpose",
        "observation_statuses",
        "major_error_rules",
        "decision_order",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("kind") != "Stage2JudgeGuidance"
        or value.get("schema_version") != "1.0.0"
        or value.get("rubric_id") != "stage2-general-v2"
    ):
        raise Stage2Error("invalid Stage 2 judge guidance contract")
    statuses, rules, order = (
        value["observation_statuses"],
        value["major_error_rules"],
        value["decision_order"],
    )
    if (
        not isinstance(statuses, dict)
        or set(statuses) != {"observed", "unavailable", "verified-absent"}
        or not isinstance(rules, dict)
        or set(rules) != set(_read_rubric()["major_error_ids"])
        or not isinstance(order, list)
        or not order
    ):
        raise Stage2Error("invalid Stage 2 judge guidance rules")
    texts = [value["purpose"], *statuses.values(), *rules.values(), *order]
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise Stage2Error("empty Stage 2 judge guidance rule")
    return value


def _code_binding():
    _read_guidance()
    paths = [Path(__file__), Path(judge_schemas.__file__), Path(stage2_common.__file__)]
    paths.append(GUIDANCE_PATH)
    paths.append(Path(__file__).with_name("native.py"))
    paths.extend(sorted(Path(stage2_eval.evaluation.__file__).parent.glob("*.py")))
    import hashlib

    return canonical_hash(
        [
            {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in paths
        ]
    )


def _execution_policy(value):
    policy = _normalize_policy(value, 600)
    policy.setdefault("max_semantic_corrections_per_unit", 1)
    if policy["max_semantic_corrections_per_unit"] != 1:
        raise EvaluationError(
            "Stage 2 judge calls require one semantic correction per unit"
        )
    return policy


def _unique_homes(r1_home, r2_home, adj_home):
    homes = {
        role: Path(path).resolve()
        for role, path in (("R1", r1_home), ("R2", r2_home), ("ADJ", adj_home))
    }
    if len(set(homes.values())) != 3:
        raise EvaluationError("R1, R2, and ADJ evaluator homes must resolve uniquely")
    for role, path in homes.items():
        if not path.is_dir():
            raise EvaluationError(f"{role} evaluator home does not exist")
    return homes


def _resume_receipts(output, result_name, resume, receipt):
    """Trust a caller-retained receipt, never a receipt read from the same bundle."""
    if not resume:
        if receipt is not None:
            raise EvaluationError("replay receipt is only valid for resume")
        return {}
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"result_sha256", "unit_receipts"}
        or not isinstance(receipt["unit_receipts"], dict)
    ):
        raise EvaluationError("resume requires an externally retained replay receipt")
    for digest in receipt["unit_receipts"].values():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise EvaluationError("invalid retained model-unit receipt")
    result_path = Path(output) / result_name
    if result_path.exists():
        if (
            hashlib.sha256(result_path.read_bytes()).hexdigest()
            != receipt["result_sha256"]
        ):
            raise EvaluationError("saved result differs from external replay receipt")
    elif receipt["result_sha256"] is not None:
        raise EvaluationError("externally receipted result is missing")
    return dict(receipt["unit_receipts"])


def _finish_result(output, result_name, result, receipts):
    result = {**result, "unit_receipts": dict(receipts)}
    path = Path(output) / result_name
    _write_new_or_equal(path, result)
    return {
        **result,
        "replay_receipt": {
            "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "unit_receipts": dict(receipts),
        },
    }


def _call_options(
    codex, home, model, reasoning, policy, resume, unit_receipts=None, receipt_sink=None
):
    return {
        "codex": codex,
        "evaluator_home": home,
        "model": model,
        "reasoning": reasoning,
        "timeout": 600,
        "execution_policy": policy,
        "resume_verified": resume,
        "api_schema": lambda value: _api_schema(value, preserve_constraints=True),
        "unit_receipts": unit_receipts or {},
        "receipt_sink": receipt_sink,
    }


def _obtain(
    call_adapter,
    prompt,
    schema_path,
    output_dir,
    label,
    options,
    semantic_validator,
):
    archive = Path(output_dir).resolve() / f"{label}.model-call"
    if archive.exists():
        raise EvaluationError(
            "existing model archive requires externally receipted replay"
        )
    try:
        return call_adapter(
            prompt,
            schema_path,
            output_dir,
            label,
            **options,
            semantic_validator=semantic_validator,
        )
    except EvaluationError:
        if not archive.is_dir() or not (archive / "request.json").is_file():
            raise
        return replay_native_model_call_archive(
            archive,
            expected_prompt=prompt,
            expected_schema=schema_path,
            expected_config=_request_config(
                options["codex"],
                options["evaluator_home"],
                options["model"],
                options["reasoning"],
            ),
            expected_policy=options["execution_policy"],
            for_correction=True,
        )


def _run_unit(
    *,
    call_adapter,
    prompt,
    schema,
    output_dir,
    label,
    options,
    validate,
):
    options = dict(options)
    receipts = options.pop("unit_receipts", {})
    receipt_sink = options.pop("receipt_sink", None)
    schema_path = Path(output_dir) / f"{label}.schema.json"
    _write_new_or_equal(schema_path, schema)
    unit_path = Path(output_dir) / f"{label}.unit.json"
    if not options["resume_verified"] and unit_path.exists():
        raise EvaluationError(
            "existing model unit requires externally receipted resume"
        )
    if options["resume_verified"] and unit_path.is_file():
        if hashlib.sha256(unit_path.read_bytes()).hexdigest() != receipts.get(label):
            raise EvaluationError("model unit differs from external replay receipt")
        saved = read_json(unit_path)
        config = _request_config(
            options["codex"],
            options["evaluator_home"],
            options["model"],
            options["reasoning"],
        )
        raw, initial = replay_native_model_call_archive(
            Path(output_dir) / f"{label}.model-call",
            expected_prompt=prompt,
            expected_schema=schema_path,
            expected_config=config,
            expected_policy=options["execution_policy"],
            for_correction=True,
        )
        try:
            validate(deepcopy(raw))
            value = raw
            provenance = {"initial": initial, "correction": None}
        except (EvaluationError, Stage2Error, KeyError, TypeError, ValueError) as error:
            correction_prompt = _correction_prompt(prompt, raw, error)
            value, correction = replay_native_model_call_archive(
                Path(output_dir) / f"{label}-correction.model-call",
                expected_prompt=correction_prompt,
                expected_schema=schema_path,
                expected_config=config,
                expected_policy=options["execution_policy"],
            )
            validate(deepcopy(value))
            provenance = {
                "initial": initial,
                "correction": correction,
                "correction_reason": str(error),
            }
        if saved.get("label") != label or saved.get("value") != value:
            raise EvaluationError(
                "saved Stage 2 unit differs from verified native generation"
            )
        _verify_provenance(saved.get("provenance"), provenance)
        if receipt_sink is not None:
            receipt_sink[label] = receipts[label]
        return value, saved["provenance"]
    if options["resume_verified"]:
        if (Path(output_dir) / f"{label}.model-call").exists() or label in receipts:
            raise EvaluationError("incomplete or missing model unit cannot be replayed")
        options["resume_verified"] = False
    raw, initial = _obtain(
        call_adapter,
        prompt,
        schema_path,
        output_dir,
        label,
        options,
        validate,
    )
    try:
        validate(deepcopy(raw))
        value = raw
        provenance = {"initial": initial, "correction": None}
    except (EvaluationError, Stage2Error, KeyError, TypeError, ValueError) as error:
        correction_prompt = _correction_prompt(prompt, raw, error)
        value, correction = _obtain(
            call_adapter,
            correction_prompt,
            schema_path,
            output_dir,
            label + "-correction",
            options,
            validate,
        )
        validate(deepcopy(value))
        provenance = {
            "initial": initial,
            "correction": correction,
            "correction_reason": str(error),
        }
    receipt = {"label": label, "value": value, "provenance": provenance}
    _write_new_or_equal(Path(output_dir) / f"{label}.unit.json", receipt)
    if receipt_sink is not None:
        receipt_sink[label] = hashlib.sha256(unit_path.read_bytes()).hexdigest()
    return value, provenance


def _verify_provenance(saved, replayed):
    """Compare immutable execution evidence, allowing only replay status to differ."""
    if not isinstance(saved, dict) or set(saved) != set(replayed):
        raise EvaluationError("saved unit provenance shape changed")
    for name, actual in replayed.items():
        claimed = saved[name]
        if name == "correction_reason" or actual is None:
            if claimed != actual:
                raise EvaluationError("saved unit correction provenance changed")
            continue
        if not isinstance(claimed, dict):
            raise EvaluationError("saved unit call provenance is missing")
        for key, value in actual.items():
            if key not in {"execution_status", "reused_completed_generation"}:
                if claimed.get(key) != value:
                    raise EvaluationError(f"saved unit call provenance changed: {key}")


def _correction_prompt(prompt, raw, error):
    return (
        prompt
        + "\nThe output below failed the unchanged Stage 2 v2 validator. Correct this unit once using only the supplied evidence. Preserve unknowns and do not invent sources, scores, audits, or approvals.\n"
        + json.dumps(
            {"validation_error": str(error), "rejected_output": raw},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _content_prompt(content_view, rubric):
    return (
        "Independently assess the scientific content below before seeing any action, "
        "disposition, score, other reviewer output, or experimental identity. Use only "
        "the admitted evidence IDs. Return the required Stage2ContentAssessment JSON.\n"
        + json.dumps(
            {
                "rubric": rubric,
                "judge_guidance": _read_guidance(),
                "content_view": content_view,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _judge_prompt(role, content_view, action_view, rubric, prior=None):
    instruction = (
        "Apply all seven frozen Stage 2 v2 criteria. A score of 0 is an observed "
        "subject deficiency; missing evidence or evaluator failure stays unknown/null. "
        "Never invent a human audit. Return the required Stage2JudgeAssessment JSON."
    )
    payload = {
        "assigned_role": role,
        "rubric": rubric,
        "judge_guidance": _read_guidance(),
        "content_view": content_view,
        "action_view": action_view,
    }
    if prior is not None:
        instruction += " Resolve only the recorded R1/R2 disagreement after your own independent content assessment."
        payload["disagreement"] = prior
    return instruction + "\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _disagreed(r1, r2):
    def signature(value):
        return (
            tuple(
                (row["criterion_id"], row["status"], row["score"])
                for row in value["criteria"]
            ),
            tuple(sorted(value["major_error_ids"])),
        )

    return signature(r1) != signature(r2)


def _result(
    request_sha256, *, status, r1=None, r2=None, adj=None, bundle=None, error=None
):
    return {
        "kind": "Stage2IsolatedJudgeRun",
        "schema_version": "1.0.0",
        "request_sha256": request_sha256,
        "status": status,
        "evaluator_status": "complete"
        if status in {"complete", "audit-required"}
        else "evaluator_failure",
        "error": error,
        "judgments": {"R1": r1, "R2": r2, "ADJ": adj},
        "bundle": bundle,
        "diagnostic_only": True,
        "external_claim_ready": False,
        "formal_claim_ready": False,
        "claim_gates": {
            "external_runtime_attested": False,
            "evaluation_frozen": False,
            "required_audit_accepted": bool(bundle and bundle.get("audit_accepted")),
        },
    }


def run_stage2_judges(
    packet,
    source_root,
    subject_id,
    input_sha256,
    config_sha256,
    action_record,
    *,
    r1_home,
    r2_home,
    adj_home,
    codex,
    model,
    reasoning,
    execution_policy,
    output_dir,
    resume=False,
    resume_receipt=None,
    call_adapter=None,
):
    """Run isolated R1/R2 and conditional ADJ with immutable evidence archives.

    A disagreement is adjudicated by ADJ, but the result remains ``audit-required``
    because the existing v2 merger requires a real named human audit. This adapter
    never manufactures that record.
    """

    validate_packet(packet, source_root)
    validate_action_record(action_record, packet)
    homes = _unique_homes(r1_home, r2_home, adj_home)
    policy = _execution_policy(execution_policy)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "kind": "Stage2IsolatedJudgeRequest",
        "schema_version": "1.0.0",
        "subject_id": subject_id,
        "packet_sha256": canonical_hash(packet),
        "source_bindings": [
            {
                key: row[key]
                for key in ("source_id", "work_id", "version_id", "path", "sha256")
            }
            for row in packet["sources"]
        ],
        "input_sha256": input_sha256,
        "config_sha256": config_sha256,
        "action_record_sha256": canonical_hash(action_record),
        "reviewer_homes": {role: str(path) for role, path in homes.items()},
        "codex": str(Path(codex).resolve()),
        "runtime_sha256": codex_runtime_sha(codex),
        "judge_code_sha256": _code_binding(),
        "rubric_sha256": canonical_hash(_read_rubric()),
        "adapter_mode": "native" if call_adapter is None else "injected-test",
        "model": model,
        "reasoning": reasoning,
        "execution_policy": policy,
    }
    request_sha256 = canonical_hash(request)
    request_path = output_dir / "request.json"
    if request_path.exists():
        if not resume:
            raise EvaluationError(
                "Stage 2 judge output already exists; use verified resume"
            )
        if read_json(request_path) != request:
            raise EvaluationError("Stage 2 judge resume input or configuration changed")
        result_path = output_dir / "result.json"
        if result_path.is_file():
            result = read_json(result_path)
            if result.get("request_sha256") != request_sha256:
                raise EvaluationError("saved Stage 2 judge result binding changed")
            if result.get("status") == "evaluator-failure":
                raise EvaluationError(
                    "failed Stage 2 judge attempt is retained; diagnose before a new attempt"
                )
            if call_adapter is not None:
                raise EvaluationError(
                    "injected test adapter cannot prove native resume"
                )
    else:
        if resume:
            raise EvaluationError("Stage 2 judge resume requires a saved request")
        if any(output_dir.iterdir()):
            raise EvaluationError("Stage 2 judge output directory is not empty")
        _write_new_or_equal(request_path, request)

    content_view = prepare_content_view(packet, subject_id, input_sha256, config_sha256)
    _write_new_or_equal(output_dir / "content-view.json", content_view)
    rubric = _read_rubric()
    adapter = call_model_v31 if call_adapter is None else call_adapter

    judgments = {}
    action_views = {}
    receipts = _resume_receipts(output_dir, "result.json", resume, resume_receipt)
    collected_receipts = {}
    try:
        for role in ("R1", "R2"):
            options = _call_options(
                codex,
                homes[role],
                model,
                reasoning,
                policy,
                resume,
                receipts,
                collected_receipts,
            )
            assessment, _ = _run_unit(
                call_adapter=adapter,
                prompt=_content_prompt(content_view, rubric),
                schema=content_assessment_schema(content_view, packet),
                output_dir=output_dir,
                label=f"{role.lower()}-content",
                options=options,
                validate=lambda value: validate_content_assessment(
                    value, content_view, packet
                ),
            )
            action_view = prepare_action_view(
                packet, content_view, assessment, action_record
            )
            action_views[role] = action_view
            _write_new_or_equal(
                output_dir / f"{role.lower()}-action-view.json", action_view
            )
            judgment, _ = _run_unit(
                call_adapter=adapter,
                prompt=_judge_prompt(role, content_view, action_view, rubric),
                schema=judge_assessment_schema(
                    role, content_view, action_view, packet, rubric
                ),
                output_dir=output_dir,
                label=f"{role.lower()}-judge",
                options=options,
                validate=lambda value, action_view=action_view: validate_judge_output(
                    value, content_view, action_view, packet
                ),
            )
            judgments[role] = judgment

        adj = None
        if (
            judgments["R1"]["evaluator_status"] == "complete"
            and judgments["R2"]["evaluator_status"] == "complete"
            and _disagreed(judgments["R1"], judgments["R2"])
        ):
            options = _call_options(
                codex,
                homes["ADJ"],
                model,
                reasoning,
                policy,
                resume,
                receipts,
                collected_receipts,
            )
            assessment, _ = _run_unit(
                call_adapter=adapter,
                prompt=_content_prompt(content_view, rubric),
                schema=content_assessment_schema(content_view, packet),
                output_dir=output_dir,
                label="adj-content",
                options=options,
                validate=lambda value: validate_content_assessment(
                    value, content_view, packet
                ),
            )
            action_view = prepare_action_view(
                packet, content_view, assessment, action_record
            )
            action_views["ADJ"] = action_view
            _write_new_or_equal(output_dir / "adj-action-view.json", action_view)
            disagreement = {
                "R1": judgments["R1"],
                "R2": judgments["R2"],
            }
            adj, _ = _run_unit(
                call_adapter=adapter,
                prompt=_judge_prompt(
                    "ADJ", content_view, action_view, rubric, disagreement
                ),
                schema=judge_assessment_schema(
                    "ADJ", content_view, action_view, packet, rubric
                ),
                output_dir=output_dir,
                label="adj-judge",
                options=options,
                validate=lambda value: validate_judge_output(
                    value, content_view, action_view, packet
                ),
            )
            judgments["ADJ"] = adj

        try:
            bundle = merge_judgments(
                judgments["R1"],
                judgments["R2"],
                content_view,
                action_views["R1"],
                packet,
                action_view_r2=action_views["R2"],
                adj=adj,
                action_view_adj=action_views.get("ADJ"),
            )
            result = _result(
                request_sha256,
                status="evaluator-failure"
                if bundle.get("evaluator_status") == "technical-failure"
                else "complete",
                r1=judgments["R1"],
                r2=judgments["R2"],
                adj=adj,
                bundle=bundle,
            )
        except Stage2Error as error:
            if "named audit" not in str(error):
                raise
            result = _result(
                request_sha256,
                status="audit-required",
                r1=judgments["R1"],
                r2=judgments["R2"],
                adj=adj,
                error=str(error),
            )
    except (
        EvaluationError,
        Stage2Error,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as error:
        result = _result(
            request_sha256,
            status="evaluator-failure",
            r1=judgments.get("R1"),
            r2=judgments.get("R2"),
            adj=judgments.get("ADJ"),
            error=str(error),
        )
    return _finish_result(output_dir, "result.json", result, collected_receipts)


__all__ = ["run_stage2_judges"]
