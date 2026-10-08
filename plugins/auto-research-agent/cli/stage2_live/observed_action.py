"""Sequential coordinator for one receipt-bound observed controller action."""

import os
from pathlib import Path

from . import execution_inventory, native, native_policy, trace_producer
from .native import CaptureError


_REQUIRED = {
    "codex",
    "codex_home",
    "workspace",
    "prompt",
    "model",
    "reasoning",
    "input_bindings",
    "config_bindings",
    "policy_bindings",
    "capture_dir",
}
_OPTIONAL = {"timeout_seconds", "trace_root"}


class ObservedActionVerificationError(CaptureError):
    """Post-producer verification failed with original receipts retained."""

    def __init__(self, message, receipts, failure_class):
        super().__init__(message)
        self.receipts = dict(receipts)
        self.failure_class = failure_class


def _action_root(request, *, resume):
    if not isinstance(request, dict) or set(request) - (_REQUIRED | _OPTIONAL):
        raise CaptureError("observed action capture request fields differ")
    if not _REQUIRED <= set(request):
        raise CaptureError("observed action capture request is incomplete")
    policy = request.get("policy_bindings")
    if (
        not isinstance(policy, dict)
        or policy.get("kind") != native_policy.NAMED_POLICY_KIND
        or policy.get("schema_version") != native_policy.CAPTURE_ROOT_POLICY_VERSION
    ):
        raise CaptureError("observed action requires named policy 1.1")
    selected = request.get("trace_root")
    if not isinstance(selected, (str, os.PathLike)):
        raise CaptureError("observed action requires an exact trace_root")
    selected = Path(selected)
    telemetry = Path(policy.get("telemetry_path", ""))
    if (
        not selected.is_absolute()
        or not telemetry.is_absolute()
        or str(selected.resolve()) != os.fspath(selected)
        or str(telemetry.resolve()) != os.fspath(telemetry)
        or selected == telemetry
        or not selected.is_relative_to(telemetry)
    ):
        raise CaptureError("observed action trace_root is not a canonical child")
    if resume:
        if selected.is_symlink() or not selected.is_dir():
            raise CaptureError("observed action resume trace_root is unavailable")
    else:
        try:
            selected.mkdir(mode=0o700)
        except OSError as error:
            raise CaptureError("observed action trace_root is not fresh") from error
        if selected.is_symlink() or not selected.is_dir():
            raise CaptureError("observed action trace_root is not a private directory")
    return selected


def capture_observed_action(capture_request, *, producer_receipt=None, resume=False):
    """Capture or replay one action, then authenticate its execution inventory."""
    if type(resume) is not bool:
        raise CaptureError("observed action resume flag must be boolean")
    if resume != isinstance(producer_receipt, str):
        raise CaptureError("observed action resume requires one retained receipt")
    request = (
        dict(capture_request) if isinstance(capture_request, dict) else capture_request
    )
    trace_root = _action_root(request, resume=resume)
    name = "CODEX_ROLLOUT_TRACE_ROOT"
    previous = os.environ.get(name)
    try:
        os.environ[name] = str(trace_root)
        producer = trace_producer.capture_observed_native(
            **request, producer_receipt=producer_receipt, resume=resume
        )
        receipt = producer.get("producer_receipt")
        if not isinstance(receipt, str):
            raise CaptureError("observed action producer receipt is missing")
        receipts = {
            "producer": receipt,
            "native_capture": producer.get("native_capture_receipt"),
            "runtime_observation": producer.get("runtime_observation_receipt"),
        }
        if any(not isinstance(value, str) for value in receipts.values()):
            raise CaptureError("observed action retained receipts are incomplete")
        phase = "native"
        try:
            native_record, _ = native.verify_capture(
                request["capture_dir"], receipts["native_capture"]
            )
            phase = "inventory"
            inventory = execution_inventory.inspect_execution_inventory(
                trace_root, receipt, capture_request=request
            )
        except Exception as error:
            raise ObservedActionVerificationError(
                f"observed action {phase} verification failed: {error}",
                receipts,
                type(error).__name__,
            ) from error
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous
    return {
        "kind": "Stage2ObservedAction",
        "schema_version": "1.0.0",
        "formal_ready": False,
        "trace_root": str(trace_root),
        "native_capture": native_record,
        "producer": producer,
        "inventory": inventory,
        "receipts": receipts,
        "resume_action": "verified-replay-no-execution" if resume else "captured",
        "limitations": [
            "sequential action evidence is non-formal and makes no readiness claim",
            "cost remains whatever the authenticated inventory reports; unknown is not zero",
        ],
    }
