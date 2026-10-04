"""Read-only authentication of native Stage 2 v3 quality archives.

This verifier never resumes a run, dispatches a model, or writes an artifact.
It is intentionally limited to the 18-unit calibration produced by
``run_quality_v3``. Ordinary daily-bundle replay needs shared prompt builders in
the producer before it can be added without duplicating security-sensitive
prompt construction. ``producer_binding`` is a narrow migration for preserved
pre-format producer bytes: it requires explicit paths and hashes, reason
``format-only``, and identical parsed ASTs. It never executes archived source
and is not a general stale-evidence allowance.
"""

import ast
import copy
import hashlib
import io
import json
import os
import stat
import tokenize
from pathlib import Path

from stage1_eval.common import canonical
from stage1_eval.model_calls import _request_config
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.rubric_quality_v3 import (
    evaluate_quality_v3,
    validate_quality_inputs,
)

from . import rubric_quality_v3 as live_quality
from .judges import _execution_policy
from .native import codex_runtime_sha
from .replay import _read_json, _require_sha, _safe_entry, _safe_root, replay_unit


_CONFIG_KEYS = {"codex", "runtime_sha256", "model", "reasoning", "homes", "policy"}
_RECEIPT_KEYS = {"result_sha256", "request_sha256", "unit_receipts"}
_PRODUCER_BINDING_KEYS = {
    "live_path",
    "evaluator_path",
    "live_sha256",
    "evaluator_sha256",
    "code_sha256",
    "reason",
}
_ROLES = ("R1", "R2")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _quality_code_sha():
    import stage2_eval.rubric_quality_v3 as evaluator

    return canonical_hash(
        {
            "live": _sha(Path(live_quality.__file__).read_bytes()),
            "evaluator": _sha(Path(evaluator.__file__).read_bytes()),
        }
    )


def _regular_file_without_reparse(path, label):
    """Return an absolute regular path after checking it and every parent."""

    candidate = Path(os.path.abspath(os.fspath(path)))
    chain = [candidate, *candidate.parents]
    for index, item in enumerate(chain):
        try:
            status = os.lstat(item)
        except OSError as error:
            raise Stage2Error(f"quality-v3-producer-{label}-path: {error}") from error
        attributes = getattr(status, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(status.st_mode) or (reparse and attributes & reparse):
            raise Stage2Error(f"quality-v3-producer-{label}-reparse-path")
        if index == 0 and not stat.S_ISREG(status.st_mode):
            raise Stage2Error(f"quality-v3-producer-{label}-not-regular-file")
        if index > 0 and not stat.S_ISDIR(status.st_mode):
            raise Stage2Error(f"quality-v3-producer-{label}-unsafe-parent")
    return candidate


def _ast_dump(raw, label):
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
        return ast.dump(ast.parse(source, filename=label), include_attributes=False)
    except (SyntaxError, UnicodeDecodeError, LookupError) as error:
        raise Stage2Error(f"quality-v3-producer-{label}-invalid-python") from error


def _resolve_producer_binding(producer_binding):
    import stage2_eval.rubric_quality_v3 as evaluator

    current_paths = {
        "live": Path(live_quality.__file__),
        "evaluator": Path(evaluator.__file__),
    }
    current_hashes = {
        name: _sha(path.read_bytes()) for name, path in current_paths.items()
    }
    current_code_sha = canonical_hash(current_hashes)
    if producer_binding is None:
        return {
            "request_code_sha256": current_code_sha,
            "current_code_sha256": current_code_sha,
            "producer_migration_status": "current-exact",
        }
    if (
        not isinstance(producer_binding, dict)
        or set(producer_binding) != _PRODUCER_BINDING_KEYS
        or producer_binding["reason"] != "format-only"
    ):
        raise Stage2Error("quality-v3-producer-binding-shape")
    archived_paths = {
        "live": _regular_file_without_reparse(producer_binding["live_path"], "live"),
        "evaluator": _regular_file_without_reparse(
            producer_binding["evaluator_path"], "evaluator"
        ),
    }
    archived_raw = {name: path.read_bytes() for name, path in archived_paths.items()}
    archived_hashes = {name: _sha(raw) for name, raw in archived_raw.items()}
    for name in ("live", "evaluator"):
        _require_sha(producer_binding[f"{name}_sha256"], f"producer-{name}")
        if archived_hashes[name] != producer_binding[f"{name}_sha256"]:
            raise Stage2Error(f"quality-v3-producer-{name}-sha256-mismatch")
        if _ast_dump(archived_raw[name], f"archived-{name}") != _ast_dump(
            current_paths[name].read_bytes(), f"current-{name}"
        ):
            raise Stage2Error(f"quality-v3-producer-{name}-ast-changed")
    producer_code_sha = canonical_hash(archived_hashes)
    _require_sha(producer_binding["code_sha256"], "producer-code")
    if producer_code_sha != producer_binding["code_sha256"]:
        raise Stage2Error("quality-v3-producer-code-sha256-mismatch")
    return {
        "request_code_sha256": producer_code_sha,
        "current_code_sha256": current_code_sha,
        "producer_migration_status": "format-only-ast-equivalent",
    }


def _load_rubric():
    try:
        rubric = json.loads(live_quality.RUBRIC_PATH.read_bytes())
    except (OSError, ValueError) as error:
        raise Stage2Error(f"quality-v3-rubric-unreadable: {error}") from error
    return rubric


def _validated_config(value, code_sha):
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
        raise Stage2Error("quality-v3-expected-config-shape")
    homes = value["homes"]
    if not isinstance(homes, dict) or set(homes) != set(_ROLES):
        raise Stage2Error("quality-v3-reviewer-homes-shape")
    resolved_homes = {role: str(Path(homes[role]).resolve()) for role in _ROLES}
    if len(set(resolved_homes.values())) != 2:
        raise Stage2Error("quality-v3-reviewer-homes-not-independent")
    configs = {
        role: _request_config(
            value["codex"], resolved_homes[role], value["model"], value["reasoning"]
        )
        for role in _ROLES
    }
    runtime_sha = codex_runtime_sha(value["codex"])
    _require_sha(value["runtime_sha256"], "runtime")
    if runtime_sha != value["runtime_sha256"]:
        raise Stage2Error("quality-v3-runtime-sha256-mismatch")
    if any(
        config["codex_executable_sha256"] != runtime_sha for config in configs.values()
    ):
        raise Stage2Error("quality-v3-model-config-runtime-mismatch")
    policy = _execution_policy({**value["policy"], "evaluator_bundle_sha256": code_sha})
    return configs, resolved_homes, policy, runtime_sha


def _expected_request(
    dataset,
    reference,
    rubric,
    expected_config,
    producer_binding=None,
    *,
    _resolved_binding=None,
):
    code_binding = _resolved_binding or _resolve_producer_binding(producer_binding)
    code_sha = code_binding["request_code_sha256"]
    configs, homes, policy, runtime_sha = _validated_config(expected_config, code_sha)
    request = {
        "kind": "Stage2RubricQualityRequestV3",
        "dataset_sha256": canonical_hash(dataset),
        "reference_sha256": canonical_hash(reference),
        "rubric_sha256": canonical_hash(rubric),
        "runtime_sha256": runtime_sha,
        "code_sha256": code_sha,
        "model": expected_config["model"],
        "reasoning": expected_config["reasoning"],
        "policy": policy,
        "homes": homes,
        "mode": "native",
        "planned_units": 18,
    }
    return request, configs, policy


def _validate_parent_freeze(root, dataset, reference, rubric):
    parent = root.parent
    disk_dataset = _read_json(_safe_entry(parent, "dataset.json"), "quality dataset")
    disk_reference = _read_json(
        _safe_entry(parent, "reference.json"), "quality reference"
    )
    if disk_dataset != dataset or disk_reference != reference:
        raise Stage2Error("quality-v3-parent-input-mismatch")
    freeze = _read_json(
        _safe_entry(parent, "pre_call_freeze.json"), "quality pre-call freeze"
    )
    required = {
        "dataset_sha256": canonical_hash(dataset),
        "reference_sha256": canonical_hash(reference),
        "rubric_sha256": canonical_hash(rubric),
        "presentations": 72,
        "designated_judgments": 144,
        "formal_ab": False,
        "human_approval_claimed": False,
    }
    if any(freeze.get(key) != value for key, value in required.items()):
        raise Stage2Error("quality-v3-pre-call-freeze-mismatch")


def _validate_receipt(root, receipt, labels):
    if (
        not isinstance(receipt, dict)
        or set(receipt) != _RECEIPT_KEYS
        or not isinstance(receipt["unit_receipts"], dict)
        or set(receipt["unit_receipts"]) != set(labels)
    ):
        raise Stage2Error("quality-v3-external-receipt-shape")
    _require_sha(receipt["result_sha256"], "result")
    _require_sha(receipt["request_sha256"], "request")
    for digest in receipt["unit_receipts"].values():
        _require_sha(digest, "unit")
    result_path = _safe_entry(root, "result.json")
    if _sha(result_path.read_bytes()) != receipt["result_sha256"]:
        raise Stage2Error("quality-v3-result-receipt-mismatch")
    return result_path


def verify_quality_v3(
    root,
    receipt,
    *,
    dataset,
    reference,
    expected_config,
    producer_binding=None,
):
    """Authenticate and recompute one saved native v3 calibration result.

    ``producer_binding`` may contain exactly ``live_path``, ``evaluator_path``,
    their two SHA-256 values, their canonical ``code_sha256``, and
    ``reason='format-only'``. Omitting it retains strict current-byte binding.
    """

    root = _safe_root(root)
    rubric = _load_rubric()
    validate_quality_inputs(dataset, reference, rubric)
    _validate_parent_freeze(root, dataset, reference, rubric)
    code_binding = _resolve_producer_binding(producer_binding)
    request, configs, policy = _expected_request(
        dataset,
        reference,
        rubric,
        expected_config,
        producer_binding,
        _resolved_binding=code_binding,
    )
    labels = [
        f"{role.lower()}-{index:02d}" for role in _ROLES for index in range(1, 10)
    ]
    result_path = _validate_receipt(root, receipt, labels)
    request_path = _safe_entry(root, "request.json")
    if request_path.read_bytes() != canonical(request) + b"\n":
        raise Stage2Error("quality-v3-request-bytes-mismatch")
    request_sha = canonical_hash(request)
    if receipt["request_sha256"] != request_sha:
        raise Stage2Error("quality-v3-request-receipt-mismatch")

    roles = {}
    attempts = 0
    archive_sha256s = {}
    for role in _ROLES:
        judgments = []
        for index, criterion in enumerate(rubric["criteria"], 1):
            cases = [
                row
                for row in dataset["cases"]
                if row["criterion_id"] == criterion["id"]
            ]
            label = f"{role.lower()}-{index:02d}"
            prepared = live_quality.prepare_quality_batch(role, cases, rubric)
            replay = replay_unit(
                root,
                label,
                receipt["unit_receipts"][label],
                prompt=prepared["prompt"],
                schema=prepared["schema"],
                config=configs[role],
                policy=policy,
                validate=lambda value, role=role, cases=cases, aliases=prepared["aliases"]: (
                    live_quality.restore_quality_batch(value, role, cases, aliases)
                ),
            )
            restored = live_quality.restore_quality_batch(
                replay["value"], role, cases, prepared["aliases"]
            )
            completed = _safe_entry(root, f"{label}.completed.json")
            if completed.read_bytes() != canonical(restored) + b"\n":
                raise Stage2Error("quality-v3-completed-row-mismatch")
            judgments.extend(copy.deepcopy(restored["judgments"]))
            if type(replay["actual_call_count"]) is not int:
                raise Stage2Error("quality-v3-model-attempt-count-unavailable")
            attempts += replay["actual_call_count"]
            archive_sha256s[label] = copy.deepcopy(replay["archive_sha256s"])
        roles[role] = {
            "kind": "Stage2RubricQualityBatchV3",
            "role": role,
            "judgments": judgments,
        }

    report = evaluate_quality_v3(dataset, reference, rubric, roles["R1"], roles["R2"])
    result = _read_json(result_path, "quality-v3 result")
    expected_keys = {
        "request_sha256",
        "roles",
        "quality_report",
        "unit_receipts",
        "native_qa_pass",
        "formal_ready",
        "actual_model_attempts",
        "cost",
    }
    if set(result) != expected_keys:
        raise Stage2Error("quality-v3-result-shape")
    if (
        result["request_sha256"] != request_sha
        or result["roles"] != roles
        or result["quality_report"] != report
        or result["unit_receipts"] != receipt["unit_receipts"]
        or result["actual_model_attempts"] != attempts
        or result["formal_ready"] is not False
        or result["cost"] != "unknown"
        or result["native_qa_pass"] is not report["passed"]
    ):
        raise Stage2Error("quality-v3-result-recomputation-mismatch")
    return {
        "authenticated": True,
        "qa_pass": report["passed"],
        "formal_ready": False,
        "actual_model_attempts": attempts,
        "request_sha256": request_sha,
        "quality_report": copy.deepcopy(report),
        "roles": copy.deepcopy(roles),
        "archive_sha256s": archive_sha256s,
        "producer_migration_status": code_binding["producer_migration_status"],
        "producer_code_sha256": code_binding["request_code_sha256"],
        "current_code_sha256": code_binding["current_code_sha256"],
        "portable_path_limitation": (
            "Native executable and reviewer-home paths must match the frozen host config."
        ),
    }
