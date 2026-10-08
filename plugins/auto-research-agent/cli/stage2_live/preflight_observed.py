"""Production capability proof from an externally receipted native trace.

This is not formal A/B admission or an isolation attestation. Unlike historical
wrapper witnesses, v1.2 uses typed native invocation/runtime payloads. It never
evaluates JavaScript or executes a subject command while checking evidence.
"""

import copy
from pathlib import Path

from . import trace_observation, trace_producer
from .native import verify_capture
from .native_policy import verify_named_runtime
from .preflight import (
    PreflightError,
    _actual_runtime,
    _archive_hash,
    _canonical_hash,
    _context_inventory,
    _load_jsonl,
    _session_identity,
    _turn_context,
    _validate_probe_spec,
)
from .preflight_trace_witnesses import (
    _trace_events,
    project_tool_witness as project_tool_witness,
)
from .trace_files import _load_inventory
from .preflight_native_witnesses import (
    _check_child as _check_child,
    _check_witnesses,
    _require,
)


def _verify_child_session(sessions, child_id, stable, expected, raw):
    child = [rows for rows in sessions if _session_identity(rows, True) == child_id]
    _require(len(child) == 1, "observed-child-native-session-ambiguous")
    turns = [
        row["payload"]
        for row in _trace_events(raw)
        if row["payload"]["type"] == "codex_turn_started"
    ]
    child_turns = {
        turn.get("codex_turn_id") for turn in turns if turn.get("thread_id") == child_id
    }
    _require(
        bool(child_turns)
        and all(isinstance(turn, str) and turn for turn in child_turns),
        "observed-child-native-turn-missing",
    )
    allowed = {turn.get("codex_turn_id") for turn in turns}
    contexts = {}
    for row in child[0]:
        if row.get("type") != "turn_context":
            continue
        context = row.get("payload")
        _require(isinstance(context, dict), "observed-child-native-context-missing")
        turn = context.get("turn_id")
        _require(
            isinstance(turn, str) and turn in allowed and turn not in contexts,
            "observed-child-native-context-binding-mismatch",
        )
        verify_named_runtime(stable, context)
        actual = _actual_runtime(context, stable["workspace"])
        _require(
            all(actual.get(key) == value for key, value in expected.items())
            and actual["permission_workspace_write"] is True
            and actual["approval_policy"] == "never",
            "observed-child-native-policy-mismatch",
        )
        contexts[turn] = actual
    _require(child_turns <= contexts.keys(), "observed-child-native-context-missing")
    ordered = sorted(child_turns)
    return {**contexts[ordered[-1]], "native_turn_ids": ordered}


def inspect_observed_preflight(capture_dir, receipt, probe_spec):
    """Recompute an ordinary production gate from actual archived evidence."""
    _require(
        isinstance(probe_spec, dict)
        and set(probe_spec)
        == {"kind", "schema_version", "executor", "expected", "probes", "observation"}
        and probe_spec.get("kind") == "Stage2ProductionRuntimeProbeSpec"
        and probe_spec.get("schema_version") == "1.2.0",
        "observed-probe-contract-invalid",
    )
    legacy = copy.deepcopy(probe_spec)
    observation = legacy.pop("observation")
    legacy["schema_version"] = "1.1.0"
    _validate_probe_spec(legacy)
    _require(
        probe_spec["executor"]["family"] == "posix",
        "observed-probe-executor-unsupported",
    )
    _require(
        isinstance(observation, dict)
        and set(observation)
        == {"telemetry_root", "producer_receipt", "capture_request"},
        "observed-probe-observation-invalid",
    )
    capture, request = Path(capture_dir).resolve(), observation["capture_request"]
    _require(
        isinstance(request, dict)
        and str(Path(request.get("capture_dir", "")).resolve()) == str(capture),
        "observed-probe-capture-mismatch",
    )
    _require(
        request.get("trace_root") == observation["telemetry_root"],
        "observed-probe-trace-root-mismatch",
    )
    root = Path(observation["telemetry_root"])
    try:
        producer = trace_producer._verify(
            request,
            root,
            observation["producer_receipt"],
            allow_synthetic=False,
            workspace_mode="archived",
        )
        _require(
            producer["native_capture_receipt"] == receipt,
            "observed-probe-receipt-mismatch",
        )
        record, _ = verify_capture(capture, receipt)
        trace = producer["trace"]
        raw = _load_inventory(
            root / trace["root"], trace["inventory"], trace["receipt_sha256"]
        )
        observed = trace_observation.inspect_native_trace(
            root / trace["root"], trace["inventory"], trace["receipt_sha256"]
        )
        _require(not observed["blockers"], "observed-probe-incomplete-trace")
        thread_id = record["event_summary"]["thread_id"]
        _require(
            observed["root_thread_id"] == thread_id, "observed-probe-root-mismatch"
        )
        sessions = [
            _load_jsonl(p)
            for p in (capture / "archive/native-sessions").rglob("*.jsonl")
        ]
        primary = [s for s in sessions if _session_identity(s, True) == thread_id]
        _require(len(primary) == 1, "observed-probe-primary-session-ambiguous")
        context = _turn_context(primary[0])
        _require(isinstance(context, dict), "observed-probe-context-missing")
        stable = record["stable_request_binding"]
        _require(
            probe_spec["executor"]["working_directory"] == stable["workspace"],
            "observed-probe-executor-workspace-mismatch",
        )
        verify_named_runtime(stable, context)
        actual = _actual_runtime(context, stable["workspace"])
        expected = probe_spec["expected"]
        _require(
            all(actual.get(k) == v for k, v in expected.items()),
            "observed-probe-effective-runtime-mismatch",
        )
        _require(
            actual["permission_workspace_write"] is True
            and actual["approval_policy"] == "never",
            "observed-probe-effective-policy-invalid",
        )
        shell = stable["config_bindings"].get("probe_shell")
        _require(
            isinstance(shell, dict)
            and shell.get("path") == probe_spec["executor"]["shell_path"]
            and shell.get("sha256") == probe_spec["executor"]["shell_sha256"],
            "observed-probe-shell-binding-mismatch",
        )
        capabilities = _check_witnesses(raw, thread_id, probe_spec, capture)
        child_runtime = _verify_child_session(
            sessions,
            probe_spec["probes"]["child"]["child_thread_id"],
            stable,
            expected,
            raw,
        )
    except PreflightError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise PreflightError(f"observed-probe-evidence-invalid: {error}") from error
    return {
        "kind": "Stage2ProductionRuntimePreflight",
        "schema_version": "1.2.0",
        "status": "passed",
        "runtime_gate": True,
        "formal_ready": False,
        "scientific_improvement": False,
        "validation_scope": "production-single",
        "filesystem_read_isolation": "not-assessed",
        "quality_improvement": "not-established",
        "capture_record_sha256_receipt": receipt,
        "probe_spec_sha256": _canonical_hash(probe_spec),
        "inventory_receipt_sha256": None,
        "primary_thread_id": thread_id,
        "requested_runtime": expected,
        "actual_runtime": actual,
        "child_runtime": child_runtime,
        "inventory": _context_inventory(context),
        "capabilities": capabilities,
        "blockers": [],
        "observations": ["formal-isolation-and-inventory-admission-not-assessed"],
        "archive_files": [
            _archive_hash(capture / name, capture)
            for name in sorted(record["archived_files"])
        ],
        "observation_binding": {
            "producer_receipt": observation["producer_receipt"],
            "trace_receipt": trace["receipt_sha256"],
            "runtime_observation_receipt": producer["runtime_observation_receipt"],
        },
    }
