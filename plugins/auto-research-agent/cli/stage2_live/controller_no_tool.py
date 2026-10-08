import os
from pathlib import Path

from stage2_common import Stage2Error, canonical_hash

from .native_namespace import bind_namespace
from .no_tool_call import NoToolCallFailure, resume_no_tool_call, run_no_tool_call


_KIND = "Stage2ControllerNoToolExecution"
_STRICT_POLICY = "no-offered-tools-v1"
_EXECUTION_POLICY = "no-executed-tools-v1"
_POLICIES = {_STRICT_POLICY, _EXECUTION_POLICY}
_CONFIG_KEYS = {"model", "reasoning", "sandbox_mode", "approval_policy"}
_METADATA_KEYS_1_0 = {
    "kind",
    "schema_version",
    "controller_schema_version",
    "original_call_result_sha256",
    "output_dir",
    "evidence_dir",
    "namespace_binding",
    "expected_config",
    "seal_sha256",
    "capture",
}
_METADATA_KEYS_1_1 = _METADATA_KEYS_1_0 | {"execution_policy", "seal_receipt"}


def _fail(reason):
    raise Stage2Error("controller-no-tool-" + reason)


def _path(value):
    if not isinstance(value, (str, os.PathLike)):
        _fail("path-invalid")
    return Path(os.path.abspath(os.fspath(value)))


def _policy(value):
    if value not in _POLICIES:
        _fail("execution-policy-invalid")


def _context(spec, home, output_dir):
    if not isinstance(spec, dict) or spec.get("schema_version") != "1.2.0":
        _fail("controller-version-required")
    native = spec.get("native")
    if not isinstance(native, dict):
        _fail("native-settings-invalid")
    for key in ("codex", "model", "reasoning"):
        if not isinstance(native.get(key), str) or not native[key]:
            _fail("native-settings-invalid")
    binding = bind_namespace(native["codex"], home)
    if binding is None:
        _fail("namespace-required")
    scope = binding.get("scope") if isinstance(binding, dict) else None
    telemetry = scope.get("telemetry") if isinstance(scope, dict) else None
    if (
        not isinstance(binding.get("path"), str)
        or not isinstance(binding.get("sha256"), str)
        or not isinstance(binding.get("dispatcher_sha256"), str)
        or not isinstance(telemetry, str)
    ):
        _fail("namespace-binding-invalid")
    output = _path(output_dir)
    evidence = output.with_name(output.name + "-trace-evidence")
    expected = {
        "model": native["model"],
        "reasoning": native["reasoning"],
        "sandbox_mode": "read-only",
        "approval_policy": "never",
    }
    receipt = {
        "path": binding["path"],
        "sha256": binding["sha256"],
        "dispatcher_sha256": binding["dispatcher_sha256"],
        "telemetry": telemetry,
    }
    return output, evidence, expected, receipt


def _seals(capture):
    units = capture.get("units") if isinstance(capture, dict) else None
    if not isinstance(units, dict) or not units:
        _fail("capture-units-invalid")
    seals = {}
    for unit, record in units.items():
        if (
            not isinstance(unit, str)
            or not unit
            or not isinstance(record, dict)
            or not isinstance(record.get("seal_sha256"), str)
            or not record["seal_sha256"]
        ):
            _fail("capture-seal-invalid")
        seals[unit] = record["seal_sha256"]
    return seals


def _receipt(value, policy, seals):
    if not isinstance(value, dict) or set(value) != {
        "kind",
        "schema_version",
        "execution_policy",
        "seal_sha256",
        "receipt_sha256",
    }:
        _fail("seal-receipt-invalid")
    unsigned = dict(value)
    digest = unsigned.pop("receipt_sha256")
    if (
        value.get("kind") != "Stage2NoToolCallSealReceipt"
        or value.get("schema_version") != "1.0.0"
        or value.get("execution_policy") != policy
        or value.get("seal_sha256") != seals
        or digest != canonical_hash(unsigned)
    ):
        _fail("seal-receipt-invalid")
    return value


def run_controller_no_tool(
    callback,
    spec,
    home,
    output_dir,
    args=(),
    kwargs=None,
    *,
    execution_policy=_STRICT_POLICY,
):
    _policy(execution_policy)
    output, evidence, expected, namespace = _context(spec, home, output_dir)
    call = run_no_tool_call(
        callback,
        output_dir=output,
        evidence_dir=evidence,
        telemetry_root=namespace["telemetry"],
        expected_config=expected,
        callback_args=args,
        callback_kwargs=kwargs,
        execution_policy=execution_policy,
    )
    try:
        if not isinstance(call.result, dict) or "no_tool_execution" in call.result:
            _fail("canonical-result-invalid")
        capture = call.evidence
        seals = _seals(capture)
        if execution_policy == _STRICT_POLICY:
            capture = {
                key: value
                for key, value in capture.items()
                if key not in {"execution_policy", "seal_receipt"}
            }
        elif (
            capture.get("kind") != "Stage2NoExecutionTraceCapture"
            or capture.get("execution_policy") != execution_policy
        ):
            _fail("capture-policy-mismatch")
        metadata = {
            "kind": _KIND,
            "schema_version": "1.0.0"
            if execution_policy == _STRICT_POLICY
            else "1.1.0",
            "controller_schema_version": "1.2.0",
            "original_call_result_sha256": canonical_hash(call.result),
            "output_dir": str(output),
            "evidence_dir": str(evidence),
            "namespace_binding": namespace,
            "expected_config": expected,
            "seal_sha256": seals,
            "capture": capture,
        }
        if execution_policy == _EXECUTION_POLICY:
            metadata.update(
                execution_policy=execution_policy,
                seal_receipt=_receipt(
                    capture.get("seal_receipt"), execution_policy, seals
                ),
            )
        result = dict(call.result)
        result["no_tool_execution"] = metadata
        return result
    except Exception as error:
        # The caller has already sealed authentic attempts: never drop these
        # externally retainable receipts because downstream formatting failed.
        state = {
            "completed_call": call,
            "result": call.result,
            "evidence": call.evidence,
            "output_dir": str(output),
            "evidence_dir": str(evidence),
            "expected_config": expected,
            "execution_policy": execution_policy,
            "retained_seal_receipt": call.evidence.get("seal_receipt"),
        }
        raise NoToolCallFailure("controller-binding", state, error) from error


def verify_controller_no_tool_history(
    result,
    spec,
    home,
    output_dir,
    *,
    execution_policy=_STRICT_POLICY,
):
    _policy(execution_policy)
    metadata = result.get("no_tool_execution") if isinstance(result, dict) else None
    if not isinstance(metadata, dict):
        _fail("metadata-invalid")
    version = metadata.get("schema_version")
    if execution_policy == _STRICT_POLICY:
        if version != "1.0.0":
            _fail("history-policy-mismatch")
        keys = _METADATA_KEYS_1_0
    else:
        if version != "1.1.0" or metadata.get("execution_policy") != execution_policy:
            _fail("history-policy-mismatch")
        keys = _METADATA_KEYS_1_1
    if set(metadata) != keys:
        _fail("metadata-invalid")
    canonical_result = dict(result)
    canonical_result.pop("no_tool_execution")
    output, evidence, expected, namespace = _context(spec, home, output_dir)
    if (
        metadata.get("kind") != _KIND
        or metadata.get("controller_schema_version") != "1.2.0"
        or metadata.get("original_call_result_sha256")
        != canonical_hash(canonical_result)
        or metadata.get("output_dir") != str(output)
        or metadata.get("evidence_dir") != str(evidence)
        or metadata.get("namespace_binding") != namespace
        or metadata.get("expected_config") != expected
        or set(expected) != _CONFIG_KEYS
        or metadata.get("seal_sha256") != _seals(metadata.get("capture"))
    ):
        _fail("history-binding-mismatch")
    receipt = metadata["seal_sha256"]
    if execution_policy == _EXECUTION_POLICY:
        receipt = _receipt(
            metadata.get("seal_receipt"),
            execution_policy,
            metadata["seal_sha256"],
        )
        if metadata["capture"].get("seal_receipt") != receipt:
            _fail("history-binding-mismatch")
    return resume_no_tool_call(
        output,
        evidence,
        receipt,
        expected_config=expected,
        execution_policy=execution_policy,
    )
