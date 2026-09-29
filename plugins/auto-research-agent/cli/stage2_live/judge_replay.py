"""Read-only authentication of isolated Stage 2 judge archives."""

import copy
import hashlib
import json
from pathlib import Path

from stage1_eval.common import canonical
from stage1_eval.model_calls import _request_config
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval import (
    merge_judgments,
    prepare_action_view,
    prepare_content_view,
    validate_action_record,
    validate_content_assessment,
    validate_judge_output,
)

from .judge_schemas import content_assessment_schema, judge_assessment_schema
from .judges import (
    _code_binding,
    _content_prompt,
    _disagreed,
    _execution_policy,
    _judge_prompt,
    _read_rubric,
    _result,
)
from .native import codex_runtime_sha
from .replay import replay_unit

_BASE_LABELS = {"r1-content", "r1-judge", "r2-content", "r2-judge"}
_ADJ_LABELS = {"adj-content", "adj-judge"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value, label):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise Stage2Error(f"invalid-{label}-sha256")


def _root(value):
    path = Path(value).resolve()
    if Path(value).is_symlink() or not path.is_dir():
        raise Stage2Error("judge-replay-root-must-be-regular-directory")
    return path


def _file(root, name):
    path = root / name
    if path.parent != root or path.is_symlink() or not path.is_file():
        raise Stage2Error(f"missing-or-unsafe-judge-replay-file: {name}")
    return path


def _json(path, label):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise Stage2Error(f"invalid-{label}: {error}") from error
    if not isinstance(value, dict):
        raise Stage2Error(f"invalid-{label}-shape")
    return value


def _same_saved(root, name, expected, label):
    path = _file(root, name)
    if path.read_bytes() != canonical(expected) + b"\n":
        raise Stage2Error(f"judge-replay-{label}-mismatch")


def _config(expected_config):
    fields = {
        "codex",
        "codex_executable_sha256",
        "model",
        "reasoning",
        "reviewer_homes",
    }
    if not isinstance(expected_config, dict) or set(expected_config) != fields:
        raise Stage2Error("judge-replay-expected-config-shape")
    homes_value = expected_config["reviewer_homes"]
    if not isinstance(homes_value, dict) or set(homes_value) != {"R1", "R2", "ADJ"}:
        raise Stage2Error("judge-replay-reviewer-homes-shape")
    homes = {role: Path(value).resolve() for role, value in homes_value.items()}
    if len(set(homes.values())) != 3 or any(
        not path.is_dir() for path in homes.values()
    ):
        raise Stage2Error("judge-replay-reviewer-homes-must-exist-and-be-distinct")
    codex = Path(expected_config["codex"]).resolve()
    _hash(expected_config["codex_executable_sha256"], "codex-executable")
    if codex_runtime_sha(codex) != expected_config["codex_executable_sha256"]:
        raise Stage2Error("judge-replay-runtime-sha256-mismatch")
    if not all(
        isinstance(expected_config[key], str) and expected_config[key].strip()
        for key in ("model", "reasoning")
    ):
        raise Stage2Error("judge-replay-model-or-reasoning-missing")
    return codex, homes


def verify_judges(
    root,
    external_receipt,
    *,
    packet,
    source_root,
    subject_id,
    input_sha256,
    config_sha256,
    action_record,
    expected_config,
    expected_policy,
    named_audit=None,
):
    """Authenticate a completed judge run and optionally apply a real named audit.

    The archive is never changed.  ``saved_result`` is the exact unaudited result;
    ``bundle`` is present only when that result was complete or ``named_audit``
    validates against the independently replayed selected assessment.
    """

    root = _root(root)
    validate_packet(packet, source_root)
    validate_action_record(action_record, packet)
    codex, homes = _config(expected_config)
    policy = _execution_policy(expected_policy)
    if not isinstance(external_receipt, dict) or set(external_receipt) != {
        "result_sha256",
        "unit_receipts",
    }:
        raise Stage2Error("judge-replay-external-receipt-shape")
    receipts = external_receipt["unit_receipts"]
    if not isinstance(receipts, dict) or set(receipts) not in (
        _BASE_LABELS,
        _BASE_LABELS | _ADJ_LABELS,
    ):
        raise Stage2Error("judge-replay-unit-receipt-set")
    _hash(external_receipt["result_sha256"], "result")
    for value in receipts.values():
        _hash(value, "unit")
    result_path = _file(root, "result.json")
    if _sha(result_path.read_bytes()) != external_receipt["result_sha256"]:
        raise Stage2Error("judge-replay-result-receipt-mismatch")

    rubric = _read_rubric()
    content_view = prepare_content_view(packet, subject_id, input_sha256, config_sha256)
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
        "codex": str(codex),
        "runtime_sha256": expected_config["codex_executable_sha256"],
        "judge_code_sha256": _code_binding(),
        "rubric_sha256": canonical_hash(rubric),
        "adapter_mode": "native",
        "model": expected_config["model"],
        "reasoning": expected_config["reasoning"],
        "execution_policy": policy,
    }
    _same_saved(root, "request.json", request, "request")
    _same_saved(root, "content-view.json", content_view, "content-view")

    replays = {}
    judgments = {}
    action_views = {}

    def run(label, role, prompt, schema, validate):
        role_config = _request_config(
            codex,
            homes[role],
            expected_config["model"],
            expected_config["reasoning"],
        )
        if (
            role_config["codex_executable_sha256"]
            != expected_config["codex_executable_sha256"]
        ):
            raise Stage2Error("judge-replay-role-runtime-mismatch")
        replays[label] = replay_unit(
            root,
            label,
            receipts[label],
            prompt=prompt,
            schema=schema,
            config=role_config,
            policy=policy,
            validate=validate,
        )
        return replays[label]["value"]

    for role in ("R1", "R2"):
        prefix = role.lower()
        assessment = run(
            f"{prefix}-content",
            role,
            _content_prompt(content_view, rubric),
            content_assessment_schema(content_view, packet),
            lambda value: validate_content_assessment(value, content_view, packet),
        )
        action_view = prepare_action_view(
            packet, content_view, assessment, action_record
        )
        action_views[role] = action_view
        _same_saved(
            root, f"{prefix}-action-view.json", action_view, f"{prefix}-action-view"
        )
        judgments[role] = run(
            f"{prefix}-judge",
            role,
            _judge_prompt(role, content_view, action_view, rubric),
            judge_assessment_schema(role, content_view, action_view, packet, rubric),
            lambda value, action_view=action_view: validate_judge_output(
                value, content_view, action_view, packet
            ),
        )

    needs_adj = (
        judgments["R1"]["evaluator_status"] == "complete"
        and judgments["R2"]["evaluator_status"] == "complete"
        and _disagreed(judgments["R1"], judgments["R2"])
    )
    expected_labels = _BASE_LABELS | (_ADJ_LABELS if needs_adj else set())
    if set(receipts) != expected_labels:
        raise Stage2Error("judge-replay-adjudicator-receipt-set-mismatch")
    adj = None
    if needs_adj:
        assessment = run(
            "adj-content",
            "ADJ",
            _content_prompt(content_view, rubric),
            content_assessment_schema(content_view, packet),
            lambda value: validate_content_assessment(value, content_view, packet),
        )
        action_view = prepare_action_view(
            packet, content_view, assessment, action_record
        )
        action_views["ADJ"] = action_view
        _same_saved(root, "adj-action-view.json", action_view, "adj-action-view")
        adj = run(
            "adj-judge",
            "ADJ",
            _judge_prompt(
                "ADJ",
                content_view,
                action_view,
                rubric,
                {"R1": judgments["R1"], "R2": judgments["R2"]},
            ),
            judge_assessment_schema("ADJ", content_view, action_view, packet, rubric),
            lambda value: validate_judge_output(
                value, content_view, action_view, packet
            ),
        )

    merge_args = (
        judgments["R1"],
        judgments["R2"],
        content_view,
        action_views["R1"],
        packet,
    )
    merge_kwargs = {
        "action_view_r2": action_views["R2"],
        "adj": adj,
        "action_view_adj": action_views.get("ADJ"),
    }
    try:
        saved_bundle = merge_judgments(*merge_args, **merge_kwargs)
        expected_result = _result(
            canonical_hash(request),
            status=(
                "evaluator-failure"
                if saved_bundle["evaluator_status"] == "technical-failure"
                else "complete"
            ),
            r1=judgments["R1"],
            r2=judgments["R2"],
            adj=adj,
            bundle=saved_bundle,
        )
        audit_required = False
    except Stage2Error as error:
        if "named audit" not in str(error):
            raise
        saved_bundle = None
        audit_required = True
        expected_result = _result(
            canonical_hash(request),
            status="audit-required",
            r1=judgments["R1"],
            r2=judgments["R2"],
            adj=adj,
            error=str(error),
        )
    expected_result["unit_receipts"] = dict(receipts)
    saved_result = _json(result_path, "judge-result")
    if saved_result != expected_result:
        raise Stage2Error("judge-replay-saved-result-mismatch")

    bundle = saved_bundle
    if named_audit is not None:
        bundle = merge_judgments(
            *merge_args, **merge_kwargs, audit=copy.deepcopy(named_audit)
        )
    return {
        "saved_result": copy.deepcopy(saved_result),
        "bundle": copy.deepcopy(bundle),
        "status": "verified" if bundle is not None else "audit-required",
        "audit_required": audit_required,
        "named_audit_applied": named_audit is not None,
        "actual_call_count": sum(row["actual_call_count"] for row in replays.values()),
        "archive_sha256s": {
            label: copy.deepcopy(row["archive_sha256s"])
            for label, row in replays.items()
        },
        "unit_sha256s": dict(receipts),
        "scientific_approval": False,
        "portable_path_limitation": next(iter(replays.values()))[
            "portable_path_limitation"
        ],
    }


__all__ = ["verify_judges"]
