"""Read-only execution inventory from externally retained producer receipts."""

from . import trace_capture, trace_observation, trace_producer
from .native import CaptureError


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
    if not isinstance(capture_request, dict) or set(capture_request) != REQUEST_FIELDS:
        raise CaptureError("producer replay needs the exact frozen request fields")
    root = trace_capture._absolute(telemetry_root)
    policy = capture_request["policy_bindings"]
    if (
        not isinstance(policy, dict)
        or policy.get("kind") != "Stage2NamedPermissionsPolicy"
        or policy.get("telemetry_path") != str(root)
    ):
        raise CaptureError("producer replay telemetry differs from the frozen policy")
    record = trace_producer._verify(
        capture_request, root, producer_receipt, allow_synthetic=False
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
        "schema_version": "1.0.0",
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
        "resume_action": "verified-replay-no-execution",
        "limitations": [
            "strict retained-runtime replay; no provider acquisition attestation",
            "partial metadata cannot support a complete inventory claim",
            "unknown tokens cannot demonstrate token-budget compliance",
            "all-role preflights, pilots and calibration remain separate",
        ],
    }
