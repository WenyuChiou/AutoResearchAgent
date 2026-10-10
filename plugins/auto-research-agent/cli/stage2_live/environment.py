"""Bind each native execution to its own authenticated functional preflight."""

import json
import copy
from pathlib import Path
from datetime import datetime

from stage2_common import Stage2Error, canonical_hash
from .native import verify_capture, codex_runtime_sha, _path_binding
from .preflight import (
    verify_preflight,
    PreflightError,
    require_matching_preflight_contract,
    _actual_runtime,
    _load_jsonl,
    _session_identity,
    _turn_context,
    _inventory,
)
from .native_policy import (
    CAPTURE_ROOT_POLICY_VERSION,
    NAMED_POLICY_KIND,
    NamedPolicyError,
    named_policy_args,
    verify_named_runtime,
)
from .session_selection import select_production_session

CONTROLLER_ROLE_POLICY_VERSIONS = frozenset({"1.1.0", "1.2.0"})


def environment_key(home, workspace):
    return canonical_hash(
        {"home": str(Path(home).resolve()), "workspace": str(Path(workspace).resolve())}
    )


def native_for_environment(spec, home, workspace):
    """Resolve a frozen per-role policy only in explicit role-policy controllers."""
    native = copy.deepcopy(spec["native"])
    if spec.get("schema_version") not in CONTROLLER_ROLE_POLICY_VERSIONS:
        return native
    policy = spec.get("execution_policies", {}).get(environment_key(home, workspace))
    if (
        not isinstance(policy, dict)
        or policy.get("kind") != NAMED_POLICY_KIND
        or policy.get("schema_version") != CAPTURE_ROOT_POLICY_VERSION
    ):
        raise Stage2Error("execution-specific-named-policy-required")
    native["policy_bindings"] = copy.deepcopy(policy)
    binding = {
        **native,
        "codex_home": str(Path(home).resolve()),
        "workspace": str(Path(workspace).resolve()),
        "codex_profile_config": _path_binding(Path(home) / "config.toml"),
    }
    try:
        named_policy_args(
            binding,
            (Path(home) / "config.toml").read_bytes(),
            Path(policy["capture_root"]) / "contract-check",
        )
    except (NamedPolicyError, OSError, KeyError) as error:
        raise Stage2Error(f"execution-named-policy-invalid: {error}") from error
    return native


def preflight_for_environment(spec, home, workspace):
    key = environment_key(home, workspace)
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
    require_matching_preflight_contract(report, preflight["probe_spec"])
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
    """Require actual turn permissions and the inventory appropriate to scope.

    RPC bytes must be in the authenticated subject archive, not copied from a
    differently configured preflight. Missing inventory blocks formal admission;
    ordinary production preserves it as an explicit unknown observation.
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
    require_matching_preflight_contract(report, preflight["probe_spec"])
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
    production = report.get("validation_scope") == "production-single"
    root = Path(capture_dir)
    if production:
        try:
            primary = select_production_session(
                root, record["event_summary"]["thread_id"]
            )
        except PreflightError as error:
            if "primary session is not unique" in str(error):
                raise Stage2Error("execution-primary-session-not-unique") from error
            raise
    else:
        sessions = [
            _load_jsonl(p) for p in (root / "archive/native-sessions").rglob("*.jsonl")
        ]
        primary_matches = [
            rows
            for rows in sessions
            if _session_identity(rows, False) == record["event_summary"]["thread_id"]
        ]
        if len(primary_matches) != 1:
            raise Stage2Error("execution-primary-session-not-unique")
        primary = primary_matches[0]
    context = _turn_context(primary)
    try:
        verify_named_runtime(stable, context or {})
    except NamedPolicyError as error:
        raise Stage2Error(
            f"execution-effective-named-policy-invalid: {error}"
        ) from error
    if (
        not context
        or _actual_runtime(context, stable["workspace"]) != report["actual_runtime"]
    ):
        raise Stage2Error("execution-effective-policy-differs-from-preflight")
    if inventory_receipt is None and production:
        return {
            "status": "verified",
            "thread_id": record["event_summary"]["thread_id"],
            "inventory_sha256": None,
            "inventory_status": "not-captured",
        }
    if not isinstance(inventory_receipt, dict):
        raise Stage2Error("execution-inventory-not-captured")
    thread_id = record["event_summary"]["thread_id"]
    try:
        inventory, _ = _inventory(
            context,
            root.resolve(),
            inventory_receipt,
            [],
            thread_id,
            require_session_owner=production,
        )
    except PreflightError as error:
        code = (
            "execution-inventory-thread-mismatch"
            if "thread mismatch" in str(error)
            else "execution-inventory-invalid"
        )
        raise Stage2Error(f"{code}: {error}") from error
    entries = inventory_receipt.get("entries", {})
    for name, item in entries.items():
        if (
            not production or inventory.get(name, {}).get("status") == "present"
        ) and record["archived_files"].get(item.get("path")) != item.get("sha256"):
            raise Stage2Error("execution-inventory-not-in-native-archive")
    # Even optional production evidence must belong to this actual session.
    instruction = entries.get("instructions", {})
    if inventory.get("instructions", {}).get("status") == "present":
        raw = json.loads((root / instruction["path"]).read_text(encoding="utf-8"))
        result = raw.get("result", raw)
        if result.get("thread", {}).get("id") != thread_id:
            raise Stage2Error("execution-inventory-thread-mismatch")
    if production:
        statuses = {name: row["status"] for name, row in inventory.items()}
        return {
            "status": "verified",
            "thread_id": record["event_summary"]["thread_id"],
            "inventory_sha256": canonical_hash(
                {name: row["value"] for name, row in inventory.items()}
            ),
            "inventory_status": (
                "complete"
                if all(status == "present" for status in statuses.values())
                else "incomplete"
            ),
            "inventory_observations": [
                f"inventory-{name}-{status}"
                for name, status in sorted(statuses.items())
                if status != "present"
            ],
        }
    # The raw thread/start response must identify this actual subject session.
    raw = json.loads((root / instruction["path"]).read_text(encoding="utf-8"))
    result = raw.get("result", raw)
    if result.get("thread", {}).get("id") != record["event_summary"]["thread_id"]:
        raise Stage2Error("execution-inventory-thread-mismatch")
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
