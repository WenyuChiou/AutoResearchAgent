"""Validate an opt-in named native permission policy without weakening sandboxing."""

import hashlib
import json
import os
from pathlib import Path
import re
import tomllib


NAMED_POLICY_KIND = "Stage2NamedPermissionsPolicy"
NAMED_POLICY_VERSION = "1.0.0"
CAPTURE_ROOT_POLICY_VERSION = "1.1.0"


class NamedPolicyError(ValueError):
    """The requested named policy is not bound to a restrictive configuration."""


def _require(condition, message):
    if not condition:
        raise NamedPolicyError(message)


def _no_project_configs(workspace):
    root = Path(workspace).resolve()
    candidates = [root / "config.toml"] + [
        parent / ".codex/config.toml" for parent in (root, *root.parents)
    ]
    _require(
        not any(os.path.lexists(path) for path in candidates),
        "named capture rejects project or ancestor config layers",
    )


def named_policy_args(binding, config_bytes, output_dir):
    """Return native arguments only for an exact receipt-bound restrictive profile.

    This checks requested settings, not the effective runtime or role isolation.
    Functional preflight and raw execution evidence remain separately required.
    """
    policy = binding.get("policy_bindings")
    _require(isinstance(policy, dict), "named policy must be an object")
    root_bound = policy.get("schema_version") == CAPTURE_ROOT_POLICY_VERSION
    fields = {"kind", "schema_version", "name", "config_sha256", "telemetry_path"}
    if root_bound:
        fields.add("capture_root")
    _require(
        set(policy) == fields,
        "named policy fields differ",
    )
    _require(
        policy["kind"] == NAMED_POLICY_KIND
        and policy["schema_version"]
        in {NAMED_POLICY_VERSION, CAPTURE_ROOT_POLICY_VERSION},
        "named policy version is unsupported",
    )
    name = policy["name"]
    _require(
        isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name),
        "named permission name is invalid",
    )
    _require(isinstance(config_bytes, bytes), "named policy requires raw config bytes")
    digest = hashlib.sha256(config_bytes).hexdigest()
    profile = binding.get("codex_profile_config")
    _require(
        isinstance(profile, dict)
        and profile.get("kind") == "file"
        and profile.get("sha256") == digest == policy["config_sha256"],
        "named policy config bytes differ",
    )
    try:
        config = tomllib.loads(config_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise NamedPolicyError("named policy config is invalid UTF-8 TOML") from error
    _require(
        set(config)
        <= {
            "model",
            "model_reasoning_effort",
            "web_search",
            "approval_policy",
            "default_permissions",
            "features",
            "projects",
            "permissions",
        },
        "named policy contains unsupported configuration",
    )
    _require(
        config.get("default_permissions") == name
        and config.get("approval_policy") == "never"
        and config.get("model") == binding.get("model")
        and config.get("model_reasoning_effort") == binding.get("reasoning")
        and config.get("web_search") == "live",
        "named policy model, native search or selected permissions differ",
    )
    _require(
        config.get("features") == {"multi_agent_v2": True, "network_proxy": True},
        "named policy requires native children and managed network proxy",
    )
    _require(
        all(
            config["features"].get(key) is True
            for key in ("multi_agent_v2", "network_proxy")
        ),
        "named policy feature flags must be booleans",
    )
    workspace, home = binding.get("workspace"), binding.get("codex_home")
    telemetry = policy["telemetry_path"]
    output = str(Path(output_dir).resolve())
    denied_output = policy.get("capture_root", output)
    _require(
        all(
            isinstance(value, str) and Path(value).is_absolute()
            for value in (workspace, home, telemetry, denied_output)
        ),
        "named policy paths must be absolute",
    )
    if root_bound:
        _require(
            str(Path(denied_output).resolve()) == denied_output
            and Path(output) != Path(denied_output)
            and Path(output).is_relative_to(Path(denied_output)),
            "named capture output must remain inside frozen capture_root",
        )
    paths = [
        Path(value).resolve() for value in (workspace, home, telemetry, denied_output)
    ]
    _require(
        all(
            left != right
            and not left.is_relative_to(right)
            and not right.is_relative_to(left)
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ),
        "named policy role directories overlap",
    )
    expected = {
        "filesystem": {
            "/": "read",
            workspace: "write",
            home: "deny",
            telemetry: "deny",
            denied_output: "deny",
        },
        "network": {
            "enabled": True,
            "mode": "full",
            "allow_local_binding": False,
            "domains": {
                "*": "allow",
                "localhost": "deny",
                "127.0.0.1": "deny",
                "::1": "deny",
            },
        },
    }
    _require(
        config.get("permissions") == {name: expected},
        "named policy restrictions differ",
    )
    network = config["permissions"][name]["network"]
    _require(
        network["enabled"] is True and network["allow_local_binding"] is False,
        "named policy network flags must be booleans",
    )
    _require(
        config.get("projects") == {workspace: {"trust_level": "untrusted"}},
        "named policy project scope differs",
    )
    _no_project_configs(workspace)
    # Runtime trust participates in discovery before project layers are loaded.
    # Keep it pinned so a newly created local config cannot become active either.
    return [
        "-c",
        f"default_permissions={json.dumps(name)}",
        "-c",
        f'projects.{json.dumps(workspace)}.trust_level="untrusted"',
        "-c",
        "features.network_proxy=true",
        "-c",
        "features.multi_agent_v2=true",
    ]


def verify_named_runtime(binding, context):
    """Check observed permissions for v1.1, without promoting legacy evidence.

    A selected name or workspace-write label alone cannot establish the effective
    restrictions. Both native filesystem representations must match the profile.
    Missing fields remain a rejected, unknown observation.
    """
    policy = binding.get("policy_bindings", {})
    if (
        policy.get("kind") != NAMED_POLICY_KIND
        or policy.get("schema_version") != CAPTURE_ROOT_POLICY_VERSION
    ):
        return
    active = context.get("active_permission_profile")
    _require(
        isinstance(active, dict) and active.get("id") == policy["name"],
        "named active permission profile differs or is unknown",
    )
    permission = context.get("permission_profile")
    _require(
        isinstance(permission, dict)
        and permission.get("type") == "managed"
        and permission.get("network") == "enabled",
        "named effective permission profile differs or is unknown",
    )
    expected = {
        "/": "read",
        binding["workspace"]: "write",
        binding["codex_home"]: "deny",
        policy["telemetry_path"]: "deny",
        policy["capture_root"]: "deny",
    }
    for value, tag in (
        (permission.get("file_system"), "type"),
        (context.get("file_system_sandbox_policy"), "kind"),
    ):
        _require(
            isinstance(value, dict)
            and value.get(tag) == "restricted"
            and isinstance(value.get("entries"), list),
            "named restricted filesystem evidence is missing",
        )
        observed = {}
        for entry in value["entries"]:
            _require(
                isinstance(entry, dict) and set(entry) == {"path", "access"},
                "named filesystem entry differs",
            )
            path = entry["path"]
            _require(
                isinstance(path, dict)
                and set(path) == {"type", "path"}
                and path["type"] == "path",
                "named filesystem path is unknown",
            )
            name = path["path"]
            _require(
                isinstance(name, str) and name not in observed,
                "named filesystem path is duplicated",
            )
            observed[name] = entry["access"]
        _require(observed == expected, "named effective filesystem restrictions differ")
    sandbox = context.get("sandbox_policy")
    _require(
        isinstance(sandbox, dict)
        and sandbox.get("type") == "workspace-write"
        and sandbox.get("network_access") is True
        and context.get("approval_policy") == "never",
        "named effective sandbox or approval policy differs",
    )
