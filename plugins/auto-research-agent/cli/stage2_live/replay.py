"""Read-only Stage 2 native model-call archive verification.

These functions never resume a unit, dispatch a model, or write into an archive.
The underlying native replay deliberately retains exact executable and evaluator
home paths, so archives remain same-host unless the frozen config itself matches.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

from stage1_eval.common import EvaluationError, canonical
from stage1_eval.model_calls import replay_native_model_call_archive
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval.diagnostics import DiagnosticError, _validate_cases
from stage2_ideation import build_extraction_task, validate_extraction
from stage2_ideation.integration import build_next_packet

from stage2_live.calibration import (
    diagnostic_schema,
    expand_source_ids,
    validate_calibration_unit,
)
from stage2_live.extraction import (
    _prompt,
    _request,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_live.native import codex_runtime_sha
from stage2_live.judges import (
    _correction_prompt,
    _execution_policy,
    _verify_provenance,
)

_SAFE_LABEL = re.compile(r"[A-Za-z0-9_.-]+")
_VALIDATION_ERRORS = (
    DiagnosticError,
    EvaluationError,
    KeyError,
    Stage2Error,
    TypeError,
    ValueError,
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value, label):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise Stage2Error(f"invalid-{label}-sha256")


def _safe_root(root):
    path = Path(root).resolve()
    if Path(root).is_symlink() or not path.is_dir():
        raise Stage2Error("replay-root-must-be-regular-directory")
    return path


def _safe_entry(root, name, *, directory=False):
    path = root / name
    if path.parent != root or path.is_symlink():
        raise Stage2Error(f"unsafe-replay-path: {name}")
    if directory:
        if not path.is_dir():
            raise Stage2Error(f"missing-replay-directory: {name}")
        for item in path.rglob("*"):
            if item.is_symlink():
                raise Stage2Error(f"replay-archive-symlink: {item.name}")
    elif not path.is_file():
        raise Stage2Error(f"missing-replay-file: {name}")
    return path


def _read_json(path, label):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"invalid-{label}: {error}") from error
    if not isinstance(value, dict):
        raise Stage2Error(f"invalid-{label}-shape")
    return value


def _archive_sha(path):
    rows = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink():
            raise Stage2Error(f"replay-archive-symlink: {item.name}")
        if item.is_file():
            rows.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "sha256": _sha(item.read_bytes()),
                }
            )
    return canonical_hash(rows)


def _semantic_validate(validate, value):
    verdict = validate(copy.deepcopy(value))
    if verdict is False:
        raise Stage2Error("replay-semantic-validator-rejected-output")


def replay_unit(
    root,
    label,
    external_unit_sha256,
    *,
    prompt,
    schema,
    config,
    policy,
    validate,
):
    """Authenticate one saved Stage 2 unit without writing or dispatching."""

    root = _safe_root(root)
    if not isinstance(label, str) or not _SAFE_LABEL.fullmatch(label):
        raise Stage2Error("unsafe-replay-label")
    if not callable(validate):
        raise Stage2Error("replay-validator-required")
    _require_sha(external_unit_sha256, "unit")
    unit_path = _safe_entry(root, f"{label}.unit.json")
    schema_path = _safe_entry(root, f"{label}.schema.json")
    if _sha(unit_path.read_bytes()) != external_unit_sha256:
        raise Stage2Error("replay-unit-receipt-mismatch")
    expected_schema = canonical(schema) + b"\n"
    if schema_path.read_bytes() != expected_schema:
        raise Stage2Error("replay-schema-bytes-mismatch")
    saved = _read_json(unit_path, "replay-unit")
    if set(saved) != {"label", "value", "provenance"} or saved["label"] != label:
        raise Stage2Error("replay-unit-shape")
    initial_archive = _safe_entry(root, f"{label}.model-call", directory=True)
    raw, initial = replay_native_model_call_archive(
        initial_archive,
        expected_prompt=prompt,
        expected_schema=schema_path,
        expected_config=config,
        expected_policy=policy,
        for_correction=True,
    )
    correction = None
    correction_reason = None
    archives = {"initial": _archive_sha(initial_archive)}
    try:
        _semantic_validate(validate, raw)
        value = raw
    except _VALIDATION_ERRORS as error:
        allowed = policy.get("max_semantic_corrections_per_unit", 0)
        if allowed != 1:
            raise Stage2Error("replay-correction-not-allowed-by-policy") from error
        correction_reason = str(error)
        correction_archive = _safe_entry(
            root, f"{label}-correction.model-call", directory=True
        )
        value, correction = replay_native_model_call_archive(
            correction_archive,
            expected_prompt=_correction_prompt(prompt, raw, error),
            expected_schema=schema_path,
            expected_config=config,
            expected_policy=policy,
        )
        _semantic_validate(validate, value)
        archives["correction"] = _archive_sha(correction_archive)
    else:
        if (root / f"{label}-correction.model-call").exists():
            raise Stage2Error("unexpected-replay-correction-archive")
    replayed_provenance = {
        "initial": initial,
        "correction": correction,
    }
    if correction_reason is not None:
        replayed_provenance["correction_reason"] = correction_reason
    if saved["value"] != value:
        raise Stage2Error("replay-unit-value-mismatch")
    _verify_provenance(saved["provenance"], replayed_provenance)
    return {
        "value": copy.deepcopy(saved["value"]),
        "provenance": copy.deepcopy(saved["provenance"]),
        "actual_call_count": sum(
            p["attempt"] for p in (initial, correction) if p is not None
        )
        if all(
            type(p.get("attempt")) is int
            for p in (initial, correction)
            if p is not None
        )
        else None,
        "archive_sha256s": archives,
        "unit_sha256": external_unit_sha256,
        "portable_path_limitation": (
            "Native command, executable, and evaluator-home paths must match the "
            "host-frozen expected_config."
        ),
    }


def _receipt(root, external_receipt, result_name, label):
    if (
        not isinstance(external_receipt, dict)
        or set(external_receipt) != {"result_sha256", "unit_receipts"}
        or not isinstance(external_receipt["unit_receipts"], dict)
        or set(external_receipt["unit_receipts"]) != {label}
    ):
        raise Stage2Error("replay-external-receipt-shape")
    _require_sha(external_receipt["result_sha256"], "result")
    _require_sha(external_receipt["unit_receipts"][label], "unit")
    result_path = _safe_entry(root, result_name)
    if _sha(result_path.read_bytes()) != external_receipt["result_sha256"]:
        raise Stage2Error("replay-result-receipt-mismatch")
    return result_path, external_receipt["unit_receipts"][label]


def verify_calibration_unit(
    root,
    external_receipt,
    *,
    frozen_unit,
    expected_config,
    expected_policy,
    legacy_recipe=None,
):
    """Read-only verification of one supplied-fact calibration unit."""

    root = _safe_root(root)
    result_path, unit_receipt = _receipt(
        root, external_receipt, "calibration-result.json", "diagnostic"
    )
    frozen_path = _safe_entry(root, "frozen-unit.json")
    if frozen_path.read_bytes() != canonical(frozen_unit) + b"\n":
        raise Stage2Error("replay-frozen-calibration-unit-mismatch")
    _validate_cases(frozen_unit.get("cases"))
    validate_calibration_unit(frozen_unit, legacy_recipe=legacy_recipe)
    if (
        codex_runtime_sha(expected_config["codex"])
        != expected_config["codex_executable_sha256"]
    ):
        raise Stage2Error("replay-calibration-runtime-mismatch")
    if _sha(frozen_unit.get("prompt", "").encode("utf-8")) != frozen_unit.get(
        "prompt_sha256"
    ):
        raise Stage2Error("replay-calibration-prompt-hash-mismatch")
    source_ids = frozen_unit.get("evidence_transport") == "source-id-v1"

    def validate(value):
        if source_ids:
            expand_source_ids(value, frozen_unit["cases"])
        else:
            from stage2_eval.diagnostics import validate_diagnostic_output

            validate_diagnostic_output(value, frozen_unit["cases"])

    replay = replay_unit(
        root,
        "diagnostic",
        unit_receipt,
        prompt=frozen_unit["prompt"],
        schema=diagnostic_schema(source_ids=source_ids),
        config=expected_config,
        policy=expected_policy,
        validate=validate,
    )
    normalized = (
        expand_source_ids(replay["value"], frozen_unit["cases"])
        if source_ids
        else copy.deepcopy(replay["value"])
    )
    result = _read_json(result_path, "calibration-result")
    if (
        result.get("kind") != "Stage2CalibrationUnit"
        or result.get("schema_version") not in {"2.1.0", "2.2.0"}
        or result.get("variant") != frozen_unit.get("variant")
        or result.get("unit_sha256") != canonical_hash(frozen_unit)
        or result.get("case_outputs") != len(normalized["results"])
        or result.get("value") != normalized
        or result.get("provenance") != replay["provenance"]
        or result.get("unit_receipts") != external_receipt["unit_receipts"]
        or result.get("evidence_class") != "supplied-fact-live-diagnostic"
        or result.get("formal_ready") is not False
        or result.get("improvement_established") is not False
        or result.get("semantic_validation") != "pending-independent-review"
    ):
        raise Stage2Error("replay-calibration-result-mismatch")
    if result["schema_version"] == "2.2.0":
        expected_runtime = {
            "native_runtime_sha256": expected_config["codex_executable_sha256"]
        }
        if (
            result.get("native_runtime_sha256")
            != expected_runtime["native_runtime_sha256"]
            or _read_json(_safe_entry(root, "runtime-binding.json"), "runtime binding")
            != expected_runtime
        ):
            raise Stage2Error("replay-calibration-runtime-binding-mismatch")
    return {
        "result": result,
        "actual_call_count": replay["actual_call_count"],
        "archive_sha256s": replay["archive_sha256s"],
        "scientific_approval": False,
        "portable_path_limitation": replay["portable_path_limitation"],
    }


def verify_extraction(
    root,
    external_receipt,
    *,
    raw_proposal,
    packet,
    source_root,
    snapshot_sha256,
    expected_config,
    expected_policy,
):
    """Read-only verification of an ideation extraction and next packet."""

    root = _safe_root(root)
    validate_packet(packet, source_root)
    result_path, unit_receipt = _receipt(
        root, external_receipt, "result.json", "extraction"
    )
    task = build_extraction_task(raw_proposal, packet, snapshot_sha256)
    spans = build_span_index(raw_proposal)
    schema = generation_schema(spans, packet)
    prompt = _prompt(task, packet, spans, schema)

    def validate(value):
        expanded = expand_span_ids(value, raw_proposal, spans, packet)
        validate_extraction(raw_proposal, expanded, packet, snapshot_sha256)

    replay = replay_unit(
        root,
        "extraction",
        unit_receipt,
        prompt=prompt,
        schema=schema,
        config=expected_config,
        policy=expected_policy,
        validate=validate,
    )
    expanded = expand_span_ids(replay["value"], raw_proposal, spans, packet)
    validated = validate_extraction(raw_proposal, expanded, packet, snapshot_sha256)
    next_packet = build_next_packet(
        packet, source_root, raw_proposal, validated, snapshot_sha256
    )
    policy = _execution_policy(expected_policy)
    expected_request = _request(
        task,
        packet,
        source_root,
        spans,
        schema,
        prompt,
        expected_config["codex"],
        expected_config["evaluator_home"],
        expected_config["model"],
        expected_config["reasoning"],
        policy,
        "native",
    )
    request_path = _safe_entry(root, "request.json")
    if _read_json(request_path, "extraction-request") != expected_request:
        raise Stage2Error("replay-extraction-request-mismatch")
    if _safe_entry(root, "raw-proposal.bin").read_bytes() != raw_proposal.encode():
        raise Stage2Error("replay-raw-proposal-mismatch")
    if _safe_entry(root, "input-packet.json").read_bytes() != canonical(packet) + b"\n":
        raise Stage2Error("replay-input-packet-mismatch")
    if _safe_entry(root, "span-index.json").read_bytes() != canonical(spans) + b"\n":
        raise Stage2Error("replay-span-index-mismatch")
    normalization = {
        "kind": "Stage2ExtractionNormalizationReceipt",
        "schema_version": "1.0.0",
        "input_encoding": "utf-8",
        "normalization_applied": False,
        "raw_before_sha256": _sha(raw_proposal.encode("utf-8")),
        "raw_after_sha256": _sha(raw_proposal.encode("utf-8")),
        "packet_canonical_sha256": canonical_hash(packet),
        "source_bindings": expected_request["source_bindings"],
    }
    if (
        _read_json(
            _safe_entry(root, "normalization-receipt.json"),
            "normalization-receipt",
        )
        != normalization
    ):
        raise Stage2Error("replay-normalization-receipt-mismatch")
    result = _read_json(result_path, "extraction-result")
    if (
        result.get("kind") != "Stage2LiveExtractionResult"
        or result.get("schema_version") != "1.0.0"
        or result.get("status") != "passed"
        or result.get("request_sha256") != canonical_hash(expected_request)
        or result.get("extraction") != validated
        or result.get("next_packet") != next_packet
        or result.get("model_call_provenance") != replay["provenance"]
        or result.get("unit_receipts") != external_receipt["unit_receipts"]
        or result.get("native_execution_verified") is not True
        or result.get("scientific_approval") is not None
    ):
        raise Stage2Error("replay-extraction-result-mismatch")
    return {
        "result": result,
        "actual_call_count": replay["actual_call_count"],
        "archive_sha256s": replay["archive_sha256s"],
        "scientific_approval": False,
        "portable_path_limitation": replay["portable_path_limitation"],
    }
