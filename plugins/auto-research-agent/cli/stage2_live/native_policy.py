"""Validate an opt-in named native permission policy without weakening sandboxing."""

import hashlib
import json
import os
from pathlib import Path
import re
import tomllib


NAMED_POLICY_KIND = "Stage2NamedPermissionsPolicy"
NAMED_POLICY_VERSION = "1.0.0"


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
    _require(
        set(policy)
        == {"kind", "schema_version", "name", "config_sha256", "telemetry_path"},
        "named policy fields differ",
    )
    _require(
        policy["kind"] == NAMED_POLICY_KIND
        and policy["schema_version"] == NAMED_POLICY_VERSION,
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
    _require(
        all(
            isinstance(value, str) and Path(value).is_absolute()
            for value in (workspace, home, telemetry)
        ),
        "named policy paths must be absolute",
    )
    paths = [Path(value).resolve() for value in (workspace, home, telemetry, output)]
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
            output: "deny",
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
