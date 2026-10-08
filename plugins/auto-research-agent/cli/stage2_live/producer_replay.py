"""Read-only execution inventory from externally retained producer receipts."""

import os
from pathlib import Path

from . import native_policy, trace_capture, trace_observation, trace_producer
from .native import CaptureError, validate_timeout_seconds


REQUEST_FIELDS = frozenset(
    {
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
)


def verify_producer_inventory(telemetry_root, producer_receipt, *, capture_request):
    """Reconstruct captured attempts without environment mutation or dispatch.

    This is strict replay against the retained runtime, inputs and workspace,
    rather than a portable attestation or a formal-readiness decision. A caller
    must obtain ``capture_request`` and its receipt from its frozen plan.
    """
    return _verify_inventory(
        telemetry_root,
        producer_receipt,
        capture_request=capture_request,
        workspace_mode="current",
    )


def verify_historical_producer_inventory(
    telemetry_root, producer_receipt, *, capture_request
):
    """Verify completed archived evidence after the live workspace advances.

    Runtime, profile, input bytes, producer bytes and all archive receipts still
    match. Only equality of the current workspace with its archived end state is
    inapplicable. This API cannot dispatch or resume a subject.
    """
    return _verify_inventory(
        telemetry_root,
        producer_receipt,
        capture_request=capture_request,
        workspace_mode="archived",
    )


def _verify_inventory(
    telemetry_root, producer_receipt, *, capture_request, workspace_mode
):
    if (
        not isinstance(capture_request, dict)
        or not REQUEST_FIELDS <= set(capture_request)
        or not (set(capture_request) - REQUEST_FIELDS)
        <= {"timeout_seconds", "trace_root"}
    ):
        raise CaptureError("producer replay needs the exact frozen request fields")
    if "timeout_seconds" in capture_request:
        try:
            if capture_request["timeout_seconds"] is None:
                raise ValueError("declared timeout cannot be null")
            validate_timeout_seconds(capture_request["timeout_seconds"])
        except ValueError as error:
            raise CaptureError("producer replay timeout is invalid") from error
    root = trace_capture._absolute(telemetry_root)
    policy = capture_request["policy_bindings"]
    if (
        not isinstance(policy, dict)
        or policy.get("kind") != native_policy.NAMED_POLICY_KIND
    ):
        raise CaptureError("producer replay telemetry differs from the frozen policy")
    selected = capture_request.get("trace_root")
    if "trace_root" in capture_request:
        parent = policy.get("telemetry_path")
        if (
            policy.get("schema_version") != native_policy.CAPTURE_ROOT_POLICY_VERSION
            or not isinstance(selected, (str, os.PathLike))
            or not isinstance(parent, str)
            or not Path(parent).is_absolute()
            or str(Path(parent).resolve()) != parent
            or os.fspath(selected) != str(root)
            or root == Path(parent)
            or not root.is_relative_to(Path(parent))
        ):
            raise CaptureError(
                "producer replay action trace differs from the frozen policy"
            )
    elif policy.get("telemetry_path") != str(root):
        raise CaptureError("producer replay telemetry differs from the frozen policy")
    mode = {} if workspace_mode == "current" else {"workspace_mode": "archived"}
    record = trace_producer._verify(
        capture_request, root, producer_receipt, allow_synthetic=False, **mode
    )
    trace = record["trace"]
    # _verify has already authenticated this exact trace against the capture
    # and its external producer receipt; inspect it to project attempt counts.
    observed = trace_observation.inspect_native_trace(
        root / trace["root"], trace["inventory"], trace["receipt_sha256"]
    )
    inventory = trace_producer.observation.verify_runtime_observation(
        root / "bundle" / "inventory", record["runtime_observation_receipt"]
    )
    counts = observed["counts"]
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise CaptureError("producer replay counts must be nonnegative integers")
    # Unknown usage does not erase an attempted inference. It also cannot
    # establish compliance with a token budget or imply zero cost.
    usage_unknown = [
        item for item in observed["blockers"] if item.startswith("token-usage-unknown:")
    ]
    structural_blockers = [
        item for item in observed["blockers"] if item not in usage_unknown
    ]
    complete_calls = (
        not structural_blockers
        and counts["incomplete_inferences"] == 0
        and counts["incomplete_tool_calls"] == 0
    )
    return {
        "kind": "Stage2NativeExecutionInventory",
        "schema_version": "1.0.0" if workspace_mode == "current" else "1.1.0",
        "evidence_class": "host-observed-producer-replay",
        "formal_ready": False,
        "producer_receipt": producer_receipt,
        "native_capture_receipt": record["native_capture_receipt"],
        "runtime_observation_receipt": record["runtime_observation_receipt"],
        "root_thread_id": observed["root_thread_id"],
        "child_threads": counts["threads"] - 1 if counts["threads"] else None,
        "capture": record["capture"],
        "inventory_status": inventory["status"],
        "counts": counts,
        "call_accounting_complete": complete_calls,
        "token_usage_complete": (
            not usage_unknown
            and complete_calls
            and observed["token_usage_totals"] is not None
        ),
        "token_usage_totals": observed["token_usage_totals"],
        "cost": {"amount": None, "currency": None, "state": "unknown"},
        "blockers": observed["blockers"],
        "resume_action": "verified-replay-no-execution"
        if workspace_mode == "current"
        else "verified-history-no-execution",
        "limitations": [
            "retained-runtime replay; no provider acquisition attestation",
            "archived verification never authorizes resuming a changed workspace",
            "partial metadata cannot support a complete inventory claim",
            "unknown tokens cannot demonstrate token-budget compliance",
            "all-role preflights, pilots and calibration remain separate",
        ],
    }
