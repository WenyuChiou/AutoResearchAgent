"""Prepare a fresh subject profile without modifying personal Codex settings."""

import hashlib
import json
from pathlib import Path
import sys

from .native import CaptureError


def prepare_profile(
    destination,
    skills_response,
    skills_response_sha256,
    *,
    platform=None,
    workspace=None,
):
    """Disable discovered personal skills equally for A and B; keep bundled skills.

    This is configuration preparation only. It neither establishes isolation nor
    permits a formal run. The native functional preflight remains mandatory.
    """
    source = Path(skills_response)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != skills_response_sha256:
        raise CaptureError("skills discovery response hash mismatch")
    response = json.loads(raw)
    result = response.get("result", response)
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows:
        raise CaptureError("native skills/list response is missing")
    disabled = set()
    for group in rows:
        if (
            not isinstance(group, dict)
            or group.get("errors")
            or not isinstance(group.get("skills"), list)
        ):
            raise CaptureError("skills discovery incomplete")
        for skill in group["skills"]:
            if not isinstance(skill, dict) or not isinstance(skill.get("path"), str):
                raise CaptureError("skill identity missing")
            if skill.get("scope") == "user" and skill.get("enabled") is True:
                disabled.add(skill["path"])
            elif skill.get("scope") not in {"user", "system", "repo", "admin"}:
                raise CaptureError(
                    "unrecognized skill scope; review inventory before preparation"
                )
    home = Path(destination)
    if home.exists():
        raise CaptureError(
            "profile destination must be new; personal profiles are never overwritten"
        )
    lines = [
        'model = "gpt-5.6-sol"',
        'model_reasoning_effort = "high"',
        'web_search = "live"',
    ]
    if workspace is not None:
        work = Path(workspace).resolve()
        if (
            not work.is_dir()
            or not (work / ".git").is_dir()
            or Path(workspace).is_symlink()
        ):
            raise CaptureError(
                "explicit workspace must be an existing Git-root directory"
            )
        if (
            work == home.resolve()
            or work in home.resolve().parents
            or home.resolve() in work.parents
        ):
            raise CaptureError("explicit workspace and profile must be separate")
        # Native Codex persists this same user-authorized project registration on
        # first use. Do it before byte-bound preflight, never relax sandbox policy.
        project = (
            str(work).lower() if (platform or sys.platform) == "win32" else str(work)
        )
        lines.extend(
            ["", "[projects." + json.dumps(project) + "]", 'trust_level = "trusted"']
        )
    if (platform or sys.platform) == "win32":
        # With the Windows sandbox disabled, native Codex downgrades an explicit
        # workspace-write request to read-only. Enable enforcement, never bypass it.
        lines.extend(["", "[windows]", 'sandbox = "unelevated"'])
    for path in sorted(disabled):
        lines.extend(
            ["", "[[skills.config]]", "path = " + json.dumps(path), "enabled = false"]
        )
    config = ("\n".join(lines) + "\n").encode("utf-8")
    home.mkdir(parents=True, exist_ok=False)
    (home / "config.toml").write_bytes(config)
    return {
        "kind": "Stage2ProfilePreparation",
        "schema_version": "1.0.0",
        "config_sha256": hashlib.sha256(config).hexdigest(),
        "skills_discovery_sha256": skills_response_sha256,
        "disabled_personal_skill_paths": sorted(disabled),
        "runtime_gate": False,
        "formal_ready": False,
        "next_step": "Create a separate Git-root workspace and perform native capability and isolation probes.",
        "limitation": "Windows unelevated sandbox cannot enforce deny-read; a supported isolated host is still required.",
    }
