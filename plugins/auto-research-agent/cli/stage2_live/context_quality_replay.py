"""Read-only authentication of supplemental native context-quality QA."""

import copy
import hashlib
import json
from pathlib import Path

from stage1_eval.common import canonical
from stage1_eval.model_calls import _attempt_files, _request_config
from stage2_common import Stage2Error, canonical_hash
from stage2_eval.source_context_quality import evaluate_context_quality

from .context_quality_v3 import (
    _code_binding,
    _independent_homes,
    _plans,
    _restore_batch,
)
from .judges import _execution_policy
from .native import codex_runtime_sha
from .replay import _read_json, _require_sha, _safe_entry, _safe_root, replay_unit
from .rubric_quality_v3 import RUBRIC_PATH


_CONFIG_KEYS = {"codex", "runtime_sha256", "model", "reasoning", "homes", "policy"}
_RECEIPT_KEYS = {"result_sha256", "unit_receipts"}
_ROLES = ("R1", "R2")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _rubric():
    try:
        value = json.loads(RUBRIC_PATH.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(
            f"context-quality-replay-rubric-unreadable: {error}"
        ) from error
    if not isinstance(value, dict):
        raise Stage2Error("context-quality-replay-rubric-shape")
    return value


def _config(value, code_sha):
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
        raise Stage2Error("context-quality-replay-config-shape")
    if (
        not isinstance(value["codex"], (str, Path))
        or not isinstance(value["model"], str)
        or not value["model"]
        or not isinstance(value["reasoning"], str)
        or not value["reasoning"]
        or not isinstance(value["policy"], dict)
        or not isinstance(value["homes"], dict)
        or set(value["homes"]) != set(_ROLES)
        or not all(isinstance(value["homes"][role], (str, Path)) for role in _ROLES)
    ):
        raise Stage2Error("context-quality-replay-config-values")
    _require_sha(value["runtime_sha256"], "runtime")
    homes = _independent_homes(value["homes"]["R1"], value["homes"]["R2"])
    runtime_sha = codex_runtime_sha(value["codex"])
    if runtime_sha != value["runtime_sha256"]:
        raise Stage2Error("context-quality-replay-runtime-mismatch")
    configs = {
        role: _request_config(
            value["codex"], homes[role], value["model"], value["reasoning"]
        )
        for role in _ROLES
    }
    if any(row["codex_executable_sha256"] != runtime_sha for row in configs.values()):
        raise Stage2Error("context-quality-replay-config-runtime-mismatch")
    policy = _execution_policy({**value["policy"], "evaluator_bundle_sha256": code_sha})
    return configs, {role: str(homes[role]) for role in _ROLES}, policy, runtime_sha


def _receipt(root, value, labels):
    if (
        not isinstance(value, dict)
        or set(value) != _RECEIPT_KEYS
        or not isinstance(value["unit_receipts"], dict)
        or set(value["unit_receipts"]) != set(labels)
    ):
        raise Stage2Error("context-quality-replay-receipt-shape")
    _require_sha(value["result_sha256"], "result")
    for digest in value["unit_receipts"].values():
        _require_sha(digest, "unit")
    result = _safe_entry(root, "result.json")
    if _sha(result.read_bytes()) != value["result_sha256"]:
        raise Stage2Error("context-quality-replay-result-receipt-mismatch")
    return result


def _sidecars(root, label, provenance):
    """Bind redundant public call files to the already authenticated last attempt."""

    files = _attempt_files(root / f"{label}.model-call", provenance["attempt"])
    record = _read_json(files["record"], "context-quality attempt")
    expected = set()
    for suffix, key in (
        ("json", "output"),
        ("jsonl", "stdout"),
        ("stderr.txt", "stderr"),
    ):
        name = f"{label}.{suffix}"
        if record["status"] == "completed":
            path = _safe_entry(root, name)
            if path.read_bytes() != files[key].read_bytes():
                raise Stage2Error("context-quality-replay-sidecar-mismatch")
            expected.add(name)
        elif (root / name).exists():
            raise Stage2Error("context-quality-replay-unexpected-sidecar")
    return expected


def verify_context_quality_v3(
    root, external_receipt, *, dataset, reference, expected_config
):
    """Authenticate one current-format native context-quality result without writes."""

    root = _safe_root(root)
    rubric = _rubric()
    aliases, plans = _plans(dataset, reference, rubric)
    code_sha = _code_binding()
    configs, homes, policy, runtime_sha = _config(expected_config, code_sha)
    labels = [plan["label"] for role in _ROLES for plan in plans[role]]
    result_path = _receipt(root, external_receipt, labels)
    request = {
        "kind": "Stage2SourceContextQualityRequestV3",
        "schema_version": "1.0.0",
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
        "units": [
            {
                "label": plan["label"],
                "criterion_id": plan["criterion_id"],
                "prompt_sha256": plan["prompt_sha256"],
                "schema_sha256": plan["schema_sha256"],
            }
            for role in _ROLES
            for plan in plans[role]
        ],
    }
    request_path = _safe_entry(root, "request.json")
    if request_path.read_bytes() != canonical(request) + b"\n":
        raise Stage2Error("context-quality-replay-request-bytes-mismatch")
    request_sha = canonical_hash(request)

    roles = {}
    completed = []
    attempts = 0
    archive_sha256s = {}
    top_level = {"request.json", "result.json"}
    for role in _ROLES:
        judgments = []
        for plan in plans[role]:
            label = plan["label"]
            chunk_aliases = {
                row["case_id"]: aliases[role][row["case_id"]] for row in plan["cases"]
            }

            def validate(value, plan=plan, role=role, mapping=chunk_aliases):
                return _restore_batch(
                    value, role, plan["cases"], mapping, plan["original"]
                )

            replay = replay_unit(
                root,
                label,
                external_receipt["unit_receipts"][label],
                prompt=plan["prompt"],
                schema=plan["schema"],
                config=configs[role],
                policy=policy,
                validate=validate,
            )
            restored = validate(replay["value"])
            judgments.extend(copy.deepcopy(restored["judgments"]))
            completed.append(
                {
                    "role": role,
                    "label": label,
                    "provenance": copy.deepcopy(replay["provenance"]),
                }
            )
            if type(replay["actual_call_count"]) is not int:
                raise Stage2Error("context-quality-replay-attempt-count-unavailable")
            attempts += replay["actual_call_count"]
            archive_sha256s[label] = copy.deepcopy(replay["archive_sha256s"])
            top_level.update(_sidecars(root, label, replay["provenance"]["initial"]))
            top_level.update(
                {f"{label}.schema.json", f"{label}.unit.json", f"{label}.model-call"}
            )
            if "correction" in replay["archive_sha256s"]:
                top_level.add(f"{label}-correction.model-call")
                top_level.update(
                    _sidecars(
                        root, label + "-correction", replay["provenance"]["correction"]
                    )
                )
        roles[role] = {
            "kind": "Stage2RubricQualityBatchV3",
            "role": role,
            "judgments": judgments,
        }
    if {item.name for item in root.iterdir()} != top_level:
        raise Stage2Error("context-quality-replay-artifact-inventory-mismatch")

    report = evaluate_context_quality(dataset, reference, roles["R1"], roles["R2"])
    expected_result = {
        "kind": "Stage2SourceContextQualityNativeResultV3",
        "schema_version": "1.0.0",
        "request_sha256": request_sha,
        "status": "complete",
        "reviewer_status": {role: "complete" for role in _ROLES},
        "roles": roles,
        "quality_report": report,
        "completed_units": completed,
        "failures": [],
        "native_qa_pass": bool(report["passed"]),
        "formal_ready": False,
        "formal_quality_admission": False,
        "evidence_class": "host-native-context-qa",
        "actual_native_attempt_count": attempts,
        "cost": "unknown",
        "unit_receipts": dict(external_receipt["unit_receipts"]),
    }
    saved_result = _read_json(result_path, "context-quality replay result")
    if canonical_hash(saved_result) != canonical_hash(expected_result):
        raise Stage2Error("context-quality-replay-result-recomputation-mismatch")
    return {
        "authenticated": True,
        "qa_pass": report["passed"],
        "quality_report": copy.deepcopy(report),
        "roles": copy.deepcopy(roles),
        "actual_model_attempts": attempts,
        "archive_sha256s": archive_sha256s,
        "request_sha256": request_sha,
        "result_sha256": external_receipt["result_sha256"],
        "formal_ready": False,
        "cost": "unknown",
        "portable_path_limitation": (
            "Native executable and reviewer-home paths must match the retained host config; "
            "this replay does not join nested inference or tool-call inventories."
        ),
    }


__all__ = ["verify_context_quality_v3"]
