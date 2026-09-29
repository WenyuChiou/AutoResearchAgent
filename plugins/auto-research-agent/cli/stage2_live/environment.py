"""Bind each native execution to its own authenticated functional preflight."""

import json
from pathlib import Path
from datetime import datetime

from stage2_common import Stage2Error, canonical_hash
from .native import verify_capture, codex_runtime_sha, _path_binding
from .preflight import (
    verify_preflight,
    _actual_runtime,
    _load_jsonl,
    _session_id,
    _turn_context,
    _inventory,
)


def preflight_for_environment(spec, home, workspace):
    key = canonical_hash(
        {"home": str(Path(home).resolve()), "workspace": str(Path(workspace).resolve())}
    )
    row = spec.get("execution_preflights", {}).get(key)
    if not isinstance(row, dict):
        raise Stage2Error("execution-specific-preflight-required")
    return row


def verify_environment_start(preflight, native, home, workspace):
    """Check the precise profile and working directory before any subject call."""
    report = verify_preflight(
        preflight["report"],
        preflight["capture_dir"],
        preflight["receipt"],
        preflight["probe_spec"],
        inventory_receipt=preflight["inventory_receipt"],
    )
    if report.get("runtime_gate") is not True or report.get("status") != "passed":
        raise Stage2Error("execution-preflight-not-passed")
    record, _ = verify_capture(preflight["capture_dir"], preflight["receipt"])
    stable = record["stable_request_binding"]
    for field, expected in [
        ("codex_home", str(Path(home).resolve())),
        ("workspace", str(Path(workspace).resolve())),
        ("codex_runtime_sha256", codex_runtime_sha(native["codex"])),
        ("model", native["model"]),
        ("reasoning", native["reasoning"]),
        ("policy_bindings", native["policy_bindings"]),
    ]:
        if stable.get(field) != expected:
            raise Stage2Error(f"execution-preflight-{field}-mismatch")
    profile = Path(home) / "config.toml"
    if stable.get("codex_profile_config") != (
        _path_binding(profile) if profile.is_file() else None
    ):
        raise Stage2Error("execution-preflight-profile-changed")
    expected_configs = {
        k: _path_binding(v) for k, v in native["config_bindings"].items()
    }
    captured_configs = {
        k: v for k, v in stable["config_bindings"].items() if k != "probe_shell"
    }
    if captured_configs != expected_configs:
        raise Stage2Error("execution-preflight-config-changed")
    return record, report


def verify_environment_capture(capture_dir, receipt, preflight, inventory_receipt):
    """Require actual turn permissions and a complete per-execution inventory.

    RPC bytes must be in the authenticated subject archive, not copied from a
    differently configured preflight. Missing inventory is an admission failure.
    """
    record, _ = verify_capture(capture_dir, receipt)
    stable = record["stable_request_binding"]
    report = verify_preflight(
        preflight["report"],
        preflight["capture_dir"],
        preflight["receipt"],
        preflight["probe_spec"],
        inventory_receipt=preflight["inventory_receipt"],
    )
    if report.get("runtime_gate") is not True:
        raise Stage2Error("execution-preflight-not-passed")
    prior, _ = verify_capture(preflight["capture_dir"], preflight["receipt"])
    previous = prior["stable_request_binding"]
    for name in (
        "codex_home",
        "workspace",
        "codex_runtime_sha256",
        "codex_profile_config",
        "model",
        "reasoning",
        "policy_bindings",
    ):
        if stable.get(name) != previous.get(name):
            raise Stage2Error(f"execution-environment-{name}-mismatch")
    configs = {
        k: v for k, v in previous["config_bindings"].items() if k != "probe_shell"
    }
    if stable["config_bindings"] != configs:
        raise Stage2Error("execution-environment-config-mismatch")
    if datetime.fromisoformat(prior["ended_at"]) > datetime.fromisoformat(
        record["started_at"]
    ):
        raise Stage2Error("execution-preflight-after-subject")
    root = Path(capture_dir)
    sessions = [
        _load_jsonl(p) for p in (root / "archive/native-sessions").rglob("*.jsonl")
    ]
    primary = [
        rows
        for rows in sessions
        if _session_id(rows) == record["event_summary"]["thread_id"]
    ]
    if len(primary) != 1:
        raise Stage2Error("execution-primary-session-not-unique")
    context = _turn_context(primary[0])
    if (
        not context
        or _actual_runtime(context, stable["workspace"]) != report["actual_runtime"]
    ):
        raise Stage2Error("execution-effective-policy-differs-from-preflight")
    if not isinstance(inventory_receipt, dict):
        raise Stage2Error("execution-inventory-not-captured")
    entries = inventory_receipt.get("entries", {})
    for item in entries.values():
        if record["archived_files"].get(item.get("path")) != item.get("sha256"):
            raise Stage2Error("execution-inventory-not-in-native-archive")
    # The raw thread/start response must identify this actual subject session.
    instruction = entries.get("instructions", {})
    raw = json.loads((root / instruction["path"]).read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    if result.get("thread", {}).get("id") != record["event_summary"]["thread_id"]:
        raise Stage2Error("execution-inventory-thread-mismatch")
    inventory, _ = _inventory(context, root.resolve(), inventory_receipt, [])
    if any(x["status"] != "present" for x in inventory.values()) or {
        k: v["value"] for k, v in inventory.items()
    } != {k: v["value"] for k, v in report["inventory"].items()}:
        raise Stage2Error("execution-inventory-differs-from-preflight")
    return {
        "status": "verified",
        "thread_id": record["event_summary"]["thread_id"],
        "inventory_sha256": canonical_hash(
            {k: v["value"] for k, v in inventory.items()}
        ),
    }
