"""Supplied-fact calibration, separate from production and formal A/B runs."""

import copy
import hashlib
import json
from pathlib import Path

from stage1_eval.model_calls import call_model_v31
from stage2_common import canonical_hash
from stage2_eval.diagnostics import (
    CHECK_NAMES,
    DiagnosticError,
    _validate_cases,
    prepare_diagnostic_prompt,
    validate_diagnostic_output,
)

from .judge_schemas import _object, _text
from .native import codex_runtime_sha
from .judges import (
    _call_options,
    _code_binding,
    _execution_policy,
    _finish_result,
    _resume_receipts,
    _run_unit,
    _write_new_or_equal,
)


def diagnostic_schema(*, source_ids=False, output_version="2.0.0"):
    if not isinstance(output_version, str) or output_version not in {"2.0.0", "2.1.0"}:
        raise DiagnosticError("unsupported diagnostic output version")
    evidence = {
        "type": "array",
        "items": _object(
            {"evidence_id": _text()}
            if source_ids
            else {"evidence_id": _text(), "exact_quote": _text()}
        ),
    }
    check_fields = {
        "status": {
            "type": "string",
            "enum": ["assessed", "unknown", "not-applicable"],
        },
        "score": {"type": ["integer", "null"], "enum": [0, 1, 2, None]},
        "rationale": _text(),
        "evidence_refs": evidence,
    }
    if output_version == "2.1.0":
        check_fields.update(
            {
                "judgment_basis": {
                    "type": "string",
                    "enum": [
                        "demonstrated-incompatibility",
                        "partial-support",
                        "sufficient-support",
                        "evidence-not-established",
                        "not-applicable",
                    ],
                },
                "negative_evidence_ids": {"type": "array", "items": _text()},
            }
        )
    check = _object(check_fields)
    return _object(
        {
            "kind": {"type": "string", "enum": ["Stage2DiagnosticOutput"]},
            "schema_version": {"type": "string", "enum": [output_version]},
            "results": {
                "type": "array",
                "items": _object(
                    {
                        "case_id": _text(),
                        "case_sha256": _text(),
                        "disposition_target": _object(
                            {
                                "kind": {
                                    "type": "string",
                                    "enum": ["candidate", "claim", "screening-action"],
                                },
                                "id": _text(),
                                "version": {"type": ["integer", "null"]},
                            }
                        ),
                        "disposition": {
                            "type": "string",
                            "enum": ["recommend", "revise", "park", "reject"],
                        },
                        "rationale": _text(),
                        "evidence_refs": evidence,
                        "next_step": _text(),
                        "checks": _object(
                            {name: copy.deepcopy(check) for name in CHECK_NAMES}
                        ),
                        "unsupported_assumptions": {"type": "array", "items": _text()},
                    }
                ),
            },
        }
    )


def expand_source_ids(value, cases, *, output_version=None):
    """Restore a selected frozen fact verbatim, never repair a model-written quote."""
    _validate_cases(cases)
    expanded = copy.deepcopy(value)
    index = {
        case["case_id"]: {fact["evidence_id"]: fact for fact in case["source_facts"]}
        for case in cases
    }
    try:
        for row in expanded["results"]:
            facts = index[row["case_id"]]
            groups = [
                row["evidence_refs"],
                *(check["evidence_refs"] for check in row["checks"].values()),
            ]
            for refs in groups:
                for ref in refs:
                    if not isinstance(ref, dict) or set(ref) != {"evidence_id"}:
                        raise DiagnosticError(
                            "source-id transport must not supply a quote"
                        )
                    ref["exact_quote"] = facts[ref["evidence_id"]]["text"]
    except (KeyError, TypeError) as error:
        raise DiagnosticError(
            "source-id transport references unknown case or source"
        ) from error
    validate_diagnostic_output(expanded, cases, output_version=output_version)
    return expanded


def prepare_calibration(cases, recipes, *, source_ids=True, output_version="2.0.0"):
    """Freeze prompts without supplying expected dispositions to the subject."""
    _validate_cases(cases)
    if not isinstance(recipes, dict) or recipes.get("schema_version") != "2.0.0":
        raise DiagnosticError("invalid presentation recipes")
    rows = recipes.get("recipes")
    names = ("base", "order", "verbosity", "prestige", "preference")
    if not isinstance(rows, list) or [row.get("recipe_id") for row in rows] != list(
        names
    ):
        raise DiagnosticError("calibration requires the five versioned variants")
    result = []
    for row in rows:
        if set(row) != {
            "recipe_id",
            "presentation_note",
            "case_order",
            "recipe_sha256",
        }:
            raise DiagnosticError("invalid recipe fields")
        payload = {key: value for key, value in row.items() if key != "recipe_sha256"}
        if canonical_hash(payload) != row["recipe_sha256"]:
            raise DiagnosticError("recipe hash mismatch")
        order = row["case_order"]
        if any(type(index) is not int for index in order) or sorted(order) != list(
            range(1, len(cases) + 1)
        ):
            raise DiagnosticError("recipe order must cover every case once")
        ordered = [copy.deepcopy(cases[index - 1]) for index in order]
        prompt = prepare_diagnostic_prompt(
            ordered, source_ids=source_ids, output_version=output_version
        )
        # Order is the only difference in the order variant. Other presentation
        # changes are explicit metadata; scientific source bytes never change.
        if row["recipe_id"] == "verbosity":
            prompt += "\n\nPRESENTATION NOTES:\n" + json.dumps(
                {
                    case["case_id"]: case["research_candidate"]["text"]
                    for case in ordered
                },
                ensure_ascii=False,
            )
        elif row["recipe_id"] in {"prestige", "preference"}:
            prompt += (
                "\n\nPRESENTATION NOTE FOR EACH CASE:\n" + row["presentation_note"]
            )
        unit = {
            "variant": row["recipe_id"],
            "cases": ordered,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "recipe_sha256": row["recipe_sha256"],
            "recipe": copy.deepcopy(row),
            "case_count": len(ordered),
            "evidence_transport": "source-id-v1" if source_ids else "verbatim-v1",
        }
        if output_version != "2.0.0":
            unit["diagnostic_output_version"] = output_version
        result.append(unit)
    return result


def validate_calibration_unit(unit, *, legacy_recipe=None, output_version=None):
    """Reconstruct a variant; old archives require a separately frozen recipe."""
    if not isinstance(unit, dict):
        raise DiagnosticError("calibration unit must be an object")
    frozen_output_version = unit.get("diagnostic_output_version", "2.0.0")
    if not isinstance(frozen_output_version, str) or frozen_output_version not in {
        "2.0.0",
        "2.1.0",
    }:
        raise DiagnosticError("unsupported diagnostic output version")
    if frozen_output_version == "2.1.0" and output_version != frozen_output_version:
        raise DiagnosticError("2.1 calibration requires a version-aware runtime")
    if output_version is not None and output_version != frozen_output_version:
        raise DiagnosticError("calibration output version mismatch")
    _validate_cases(unit.get("cases"))
    recipe = unit.get("recipe", legacy_recipe)
    if not isinstance(recipe, dict):
        raise DiagnosticError("calibration requires the frozen recipe payload")
    if unit.get("evidence_transport") not in {"source-id-v1", "verbatim-v1"}:
        raise DiagnosticError("unknown calibration evidence transport")
    count = len(unit["cases"])
    order = recipe.get("case_order")
    if (
        not isinstance(order, list)
        or any(type(i) is not int for i in order)
        or sorted(order) != list(range(1, count + 1))
    ):
        raise DiagnosticError("recipe order must cover every case once")
    original = [None] * count
    for case, position in zip(unit["cases"], order, strict=True):
        original[position - 1] = case
    # Reuse preparation, including its recipe-field and digest validation.
    recipes = []
    for name in ("base", "order", "verbosity", "prestige", "preference"):
        payload = dict(recipe, recipe_id=name)
        payload.pop("recipe_sha256", None)
        payload["recipe_sha256"] = canonical_hash(payload)
        recipes.append(payload)
    if unit.get("variant") not in {row["recipe_id"] for row in recipes} or recipe.get(
        "recipe_id"
    ) != unit.get("variant"):
        raise DiagnosticError("calibration variant differs from recipe")
    generated = prepare_calibration(
        original,
        {"schema_version": "2.0.0", "recipes": recipes},
        source_ids=unit["evidence_transport"] == "source-id-v1",
        output_version=frozen_output_version,
    )
    expected = next(row for row in generated if row["variant"] == unit["variant"])
    # The real recipe digest must match too; regenerating must not repair tamper.
    if expected["recipe"] != recipe:
        raise DiagnosticError("calibration recipe hash mismatch")
    if "recipe" not in unit and legacy_recipe is not None:
        expected.pop("recipe")
    if type(unit.get("case_count")) is not int or unit != expected:
        raise DiagnosticError("calibration variant, count, or prompt mismatch")
    return None


def run_calibration_unit(
    unit,
    *,
    codex,
    evaluator_home,
    model,
    reasoning,
    execution_policy,
    output_dir,
    resume=False,
    resume_receipt=None,
    call_adapter=None,
):
    """One actual model unit, with one bounded semantic correction if needed."""
    if not isinstance(unit, dict):
        raise DiagnosticError("calibration unit must be an object")
    output_version = unit.get("diagnostic_output_version", "2.0.0")
    validate_calibration_unit(unit, output_version=output_version)
    runtime_sha256 = codex_runtime_sha(codex)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    policy_input = dict(execution_policy)
    policy_input["evaluator_bundle_sha256"] = canonical_hash(
        {
            "shared": _code_binding(),
            "calibration": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    policy = _execution_policy(policy_input)
    name = "calibration-result.json"
    receipts = _resume_receipts(output, name, resume, resume_receipt)
    _write_new_or_equal(output / "frozen-unit.json", unit)
    _write_new_or_equal(
        output / "runtime-binding.json", {"native_runtime_sha256": runtime_sha256}
    )
    sink = {}
    options = _call_options(
        codex,
        evaluator_home,
        model,
        reasoning,
        policy,
        resume,
        unit_receipts=receipts,
        receipt_sink=sink,
    )
    value, provenance = _run_unit(
        call_adapter=call_adapter or call_model_v31,
        prompt=unit["prompt"],
        schema=diagnostic_schema(
            source_ids=unit.get("evidence_transport") == "source-id-v1",
            output_version=output_version,
        ),
        output_dir=output,
        label="diagnostic",
        options=options,
        validate=lambda value: (
            expand_source_ids(value, unit["cases"], output_version=output_version)
            if unit.get("evidence_transport") == "source-id-v1"
            else validate_diagnostic_output(
                value, unit["cases"], output_version=output_version
            )
        ),
    )
    if unit.get("evidence_transport") == "source-id-v1":
        value = expand_source_ids(value, unit["cases"], output_version=output_version)
    return _finish_result(
        output,
        name,
        {
            "kind": "Stage2CalibrationUnit",
            "schema_version": "2.2.0",
            "native_runtime_sha256": runtime_sha256,
            "evidence_transport": unit.get("evidence_transport", "verbatim-v1"),
            "variant": unit["variant"],
            "unit_sha256": canonical_hash(unit),
            "case_outputs": len(value["results"]),
            "value": value,
            "provenance": provenance,
            "evidence_class": "synthetic-test-only"
            if call_adapter
            else "supplied-fact-live-diagnostic",
            "semantic_validation": "pending-independent-review",
            "formal_ready": False,
            "improvement_established": False,
        },
        sink,
    )
