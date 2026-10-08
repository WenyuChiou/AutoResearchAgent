"""Compose canonical v3.1 calls with capture-time no-tool trace evidence."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

from stage1_eval.model_calls import replay_native_model_call_archive
from stage2_common import Stage2Error, canonical_hash

from .judge_trace_replay import _path
from .no_tool_trace_capture import (
    NoToolTraceCaptureFailure,
    begin_no_tool_trace_capture,
    finish_no_execution_trace_capture,
    finish_no_tool_trace_capture,
)
from .no_execution_trace_evidence import verify_no_execution_trace_evidence
from .no_tool_trace_evidence import verify_no_tool_trace_evidence


_EXECUTION_POLICIES = {"no-offered-tools-v1", "no-executed-tools-v1"}


def _fail(reason):
    raise Stage2Error("no-tool-call-" + reason)


def _fresh(value, reason):
    path = Path(os.path.abspath(os.fspath(value)))
    _path(path.parent, directory=True)
    if os.path.lexists(path):
        _fail(reason)
    return path


def _overlap(first, second):
    return (
        first == second or first.is_relative_to(second) or second.is_relative_to(first)
    )


def _expected(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"model", "reasoning", "sandbox_mode", "approval_policy"}
        or not isinstance(value.get("model"), str)
        or not value["model"]
        or not isinstance(value.get("reasoning"), str)
        or not value["reasoning"]
        or value.get("sandbox_mode") != "read-only"
        or value.get("approval_policy") != "never"
    ):
        _fail("expected-config-invalid")


def _execution_policy(value):
    if value not in _EXECUTION_POLICIES:
        _fail("execution-policy-invalid")


def _seal_receipt(policy, seals):
    value = {
        "kind": "Stage2NoToolCallSealReceipt",
        "schema_version": "1.0.0",
        "execution_policy": policy,
        "seal_sha256": seals,
    }
    return {**value, "receipt_sha256": canonical_hash(value)}


def _resume_seals(value, policy):
    if isinstance(value, dict) and set(value) == {
        "kind",
        "schema_version",
        "execution_policy",
        "seal_sha256",
        "receipt_sha256",
    }:
        unsigned = dict(value)
        receipt = unsigned.pop("receipt_sha256")
        if (
            value.get("kind") != "Stage2NoToolCallSealReceipt"
            or value.get("schema_version") != "1.0.0"
            or value.get("execution_policy") != policy
            or receipt != canonical_hash(unsigned)
        ):
            _fail("seal-receipt-policy-mismatch")
        return value.get("seal_sha256")
    if policy != "no-offered-tools-v1":
        _fail("seal-receipt-policy-unbound")
    return value


def _json(path, reason):
    try:
        value = json.loads(_path(path).read_bytes())
    except (UnicodeDecodeError, ValueError) as error:
        raise Stage2Error("no-tool-call-" + reason) from error
    if not isinstance(value, dict):
        _fail(reason)
    return value


def _unit_name(output, archive):
    relative = archive.relative_to(output).as_posix()
    if not relative.endswith(".model-call"):
        _fail("archive-name-invalid")
    value = relative[: -len(".model-call")].replace("/", "__")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        _fail("archive-name-invalid")
    return value


def _authenticate(output_dir, expected_config):
    output = _path(output_dir, directory=True)
    archives = sorted(output.rglob("*.model-call"), key=lambda item: item.as_posix())
    if not archives:
        _fail("model-call-archive-missing")
    provenances = {}
    for archive in archives:
        archive = _path(archive, directory=True)
        request = _json(archive / "request.json", "archive-request-invalid")
        config, policy = request.get("config"), request.get("execution_policy")
        if (
            not isinstance(config, dict)
            or config.get("model") != expected_config["model"]
            or config.get("reasoning") != expected_config["reasoning"]
            or not isinstance(policy, dict)
        ):
            _fail("archive-settings-mismatch")
        try:
            prompt = _path(archive / "prompt.txt").read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise Stage2Error("no-tool-call-prompt-invalid") from error
        records = sorted(archive.glob("attempt-*.record.json"))
        if not records:
            _fail("attempt-record-missing")
        final = _json(records[-1], "attempt-record-invalid")
        correction_input = (
            final.get("generation_status") == "completed"
            and final.get("semantic_status") == "rejected"
            and final.get("failure_class") == "schema-mismatch"
        )
        _, provenance = replay_native_model_call_archive(
            archive,
            expected_prompt=prompt,
            expected_schema=archive / "schema.json",
            expected_config=config,
            expected_policy=policy,
            for_correction=correction_input,
        )
        unit = _unit_name(output, archive)
        if unit in provenances:
            _fail("archive-unit-duplicate")
        provenances[unit] = provenance
    return provenances


@dataclass(frozen=True)
class NoToolCallResult:
    result: object
    evidence: dict


class NoToolCallFailure(Stage2Error):
    def __init__(self, phase, state, cause):
        super().__init__(f"no-tool-call-{phase}-failed: {cause}")
        self.phase = phase
        self.state = state


def run_no_tool_call(
    callback,
    *,
    output_dir,
    evidence_dir,
    telemetry_root,
    expected_config,
    callback_args=(),
    callback_kwargs=None,
    execution_policy="no-offered-tools-v1",
):
    """Invoke one canonical caller, then authenticate and seal its new traces."""
    if not callable(callback):
        _fail("callback-invalid")
    _expected(expected_config)
    _execution_policy(execution_policy)
    output = _fresh(output_dir, "output-already-exists")
    token = begin_no_tool_trace_capture(evidence_dir, telemetry_root)
    if (
        _overlap(output, token.output)
        or _overlap(output, token.telemetry)
        or _overlap(token.output, token.telemetry)
    ):
        _fail("path-overlap")
    state = {
        "output_dir": str(output),
        "evidence_dir": str(token.output),
        "capture_token": token,
        "phase": "call",
        "execution_policy": execution_policy,
    }
    try:
        result = callback(*(callback_args or ()), **(callback_kwargs or {}))
    except BaseException as error:
        raise NoToolCallFailure("call", state, error) from error
    state = {**state, "phase": "authentication", "result": result}
    try:
        provenances = _authenticate(output, expected_config)
    except BaseException as error:
        raise NoToolCallFailure("authentication", state, error) from error
    state = {**state, "phase": "capture", "authenticated_provenances": provenances}
    try:
        finish = (
            finish_no_tool_trace_capture
            if execution_policy == "no-offered-tools-v1"
            else finish_no_execution_trace_capture
        )
        evidence = finish(token, provenances, expected_config=expected_config)
    except NoToolTraceCaptureFailure as error:
        retained = {
            **state,
            "retained_seal_receipts": error.retained_seal_receipts,
            "completed_units": error.completed_units,
        }
        raise NoToolCallFailure("capture", retained, error) from error
    except BaseException as error:
        raise NoToolCallFailure("capture", state, error) from error
    seals = {unit: value["seal_sha256"] for unit, value in evidence["units"].items()}
    evidence = {
        **evidence,
        "execution_policy": execution_policy,
        "seal_receipt": _seal_receipt(execution_policy, seals),
    }
    return NoToolCallResult(result=result, evidence=evidence)


def resume_no_tool_call(
    output_dir,
    evidence_dir,
    externally_retained_seal_sha256,
    *,
    expected_config,
    execution_policy="no-offered-tools-v1",
):
    """Authenticate saved archives and seals without invoking a caller."""
    _expected(expected_config)
    _execution_policy(execution_policy)
    externally_retained_seal_sha256 = _resume_seals(
        externally_retained_seal_sha256, execution_policy
    )
    output = _path(output_dir, directory=True)
    evidence = _path(evidence_dir, directory=True) / "native-trace-evidence"
    provenances = _authenticate(output, expected_config)
    if not isinstance(externally_retained_seal_sha256, dict) or (
        set(externally_retained_seal_sha256) != set(provenances)
    ):
        _fail("seal-receipt-set-mismatch")
    proofs = {}
    verifier = (
        verify_no_tool_trace_evidence
        if execution_policy == "no-offered-tools-v1"
        else verify_no_execution_trace_evidence
    )
    for unit, provenance in provenances.items():
        unit_root = _path(evidence / unit, directory=True)
        proofs[unit] = verifier(
            provenance,
            unit_root / "traces",
            unit_root / "seal.json",
            externally_retained_seal_sha256[unit],
            expected_config=expected_config,
        )
    return {
        "kind": "Stage2NoToolCallResume",
        "schema_version": "1.0.0",
        "proofs": proofs,
        "execution_policy": execution_policy,
        "seal_receipt": _seal_receipt(
            execution_policy, externally_retained_seal_sha256
        ),
        "new_model_calls": 0,
        "new_tool_calls": 0,
        "resume_action": "verified-replay-no-execution",
    }
