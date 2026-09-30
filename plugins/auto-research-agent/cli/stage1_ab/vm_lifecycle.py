"""V2 lifecycle: one disposable diagnostic UID, a fresh subject, no copied history."""

import json
from pathlib import Path
import subprocess
import time

from . import runner, vm_subject
from .vm_common import authenticated, digest, require, secret, sign

MODE = "subject-non-model-v2"
DIAGNOSTIC_FIELDS = {"native_user", "profile", "workspace", "native_tmp"}
MATCH_FIELDS = (
    "codex_version",
    "model",
    "reasoning",
    "native_web_search",
    "native_capabilities_sha256",
    "native_config_sha256",
    "plugin_names",
    "installed_plugin_sha256",
)
TASK = "installed-stage1-skill-file-read-and-sha256-v1"


def account_paths(config):
    """Kernel identities and private, non-overlapping roots; no subject assertions."""
    from .vm_guest import native_options

    diagnostic = config["diagnostic"]
    require(
        set(diagnostic) == DIAGNOSTIC_FIELDS, "diagnostic configuration fields differ"
    )
    require(
        diagnostic["native_user"] != config["native_user"],
        "diagnostic reused subject account",
    )
    groups = []
    for item in (config, diagnostic):
        options, env = native_options(item["native_user"])
        home = Path(env["HOME"])
        paths = [home, *[Path(item[k]) for k in ("profile", "workspace", "native_tmp")]]
        require(
            Path(item["native_tmp"]) == home / "tmp",
            "diagnostic/subject tmp differs from private home",
        )
        for path in paths:
            require(path.is_absolute() and path.is_dir(), "lifecycle root missing")
            require(
                not any(p.is_symlink() for p in (path, *path.parents)),
                "linked lifecycle root",
            )
            require(
                path.stat().st_uid == options["user"]
                and path.stat().st_mode & 0o077 == 0,
                "lifecycle roots must be UID-owned mode 0700",
            )
            require(
                path == home or path.is_relative_to(home),
                "lifecycle root outside private home",
            )
        leaves = paths[1:]
        require(
            not any(
                a == b or a.is_relative_to(b)
                for i, a in enumerate(leaves)
                for j, b in enumerate(leaves)
                if i != j
            ),
            "lifecycle directories overlap",
        )
        groups.append((options["user"], home, paths))
    require(groups[0][0] != groups[1][0], "diagnostic reused subject UID")
    a, b = groups[0][1], groups[1][1]
    require(
        not (a.is_relative_to(b) or b.is_relative_to(a)),
        "diagnostic and subject homes overlap",
    )
    for field in ("state_root", "secret_file", "lock", "prompt", "instance_file"):
        if field in config:
            control = Path(config[field]).resolve()
            require(
                not any(
                    control.is_relative_to(home) or home.is_relative_to(control)
                    for home in (a, b)
                ),
                "operator control overlaps a native home",
            )
    # Mounts are checked in the broker namespace; trusted root must not hide host mounts.
    mounts = Path("/proc/mounts").read_text().splitlines()
    require(
        not any(
            row.split()[2] in {"9p", "virtiofs", "cifs", "smb3", "nfs", "nfs4"}
            for row in mounts
        ),
        "shared filesystem mounted in guest",
    )
    for actor, other in ((config, groups[1]), (diagnostic, groups[0])):
        access = vm_subject.call(
            actor["native_user"], "access", paths=[str(p) for p in other[2]]
        )
        require(
            set(access) == {str(p) for p in other[2]}
            and all(v is False for v in access.values()),
            "diagnostic/subject storage is accessible across UID boundary",
        )
    return groups


def initial_setup(config):
    from .vm_guest import native_options

    _, env = native_options(config["native_user"])
    accepted_plugin_files = {}
    if config["condition"] == "treatment":
        accepted_plugin_files = {
            p.relative_to(runner.PLUGIN_ROOT).as_posix(): runner.sha(p.read_bytes())
            for p in runner.PLUGIN_ROOT.rglob("*")
            if p.is_file()
            and not any(
                part in {"__pycache__", ".pytest_cache", "private"}
                for part in p.relative_to(runner.PLUGIN_ROOT).parts
            )
        }
    return vm_subject.call(
        config["native_user"],
        "initial_setup",
        home=env["HOME"],
        profile=config["profile"],
        workspace=config["workspace"],
        tmp=config["native_tmp"],
        treatment=config["condition"] == "treatment",
        accepted_plugin_files=accepted_plugin_files,
    )


def relevant(probe):
    return {key: probe[key] for key in MATCH_FIELDS}


def match_probe(lifecycle, probe, lock, identity):
    """Portable semantic binding; online admit also authenticates root-private HMAC."""
    body = lifecycle.get("diagnostic", {}).get("body", {})
    require(
        lifecycle.get("kind") == "Stage1GuestLifecycle.v2"
        and lifecycle.get("mode") == MODE
        and body.get("kind") == "Stage1DiagnosticReceipt.v2"
        and body.get("actual_subject") == identity
        and body.get("codex_runtime_sha256") == lock["codex_runtime_sha256"]
        and body.get("plugin_tree_sha256") == lock["plugin_tree_sha256"]
        and body.get("matching_probe") == relevant(probe)
        and probe.get("functional_skill_sha256") is None,
        "diagnostic/actual-subject runtime, plugin, config or identity differs",
    )
    treatment = identity["condition"] == "treatment"
    require(
        body.get("task") == (TASK if treatment else "native-discovery-only-v1")
        and body.get("model_calls") == int(treatment)
        and body.get("retired") is True
        and body.get("result") == "passed"
        and (
            not treatment
            or body.get("functional_skill_sha256")
            == probe.get("installed_skill_sha256")
        ),
        "diagnostic task/result not accepted",
    )
    require(
        lifecycle.get("initial_setup_sha256") == body.get("initial_setup_sha256"),
        "initial subject setup binding differs",
    )


def process_ids(uid):
    result = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if entry.stat().st_uid == uid:
                    result.append(int(entry.name))
            except FileNotFoundError:
                pass
    return result


def retire(uid):
    # Dedicated disposable UID only. Remove descendants/caches from availability,
    # never copy them into the actual subject; private artifacts remain preserved.
    result = subprocess.run(
        ["pkill", "-KILL", "-u", str(uid)], capture_output=True, timeout=10
    )
    require(result.returncode in {0, 1}, "diagnostic process retirement failed")
    until = time.monotonic() + 5
    while process_ids(uid) and time.monotonic() < until:
        time.sleep(0.05)
    require(not process_ids(uid), "diagnostic processes remain after retirement")


def run_diagnostic(config_path):
    """Explicit preparation command; the sole v2 functional model-call entry point."""
    from .vm_guest import configuration
    from .sequence import exclusive

    config, lock, identity, key = configuration(config_path)
    root = Path(config["state_root"])
    with exclusive(root / "diagnostic"):
        groups = account_paths(config)
        require(
            not process_ids(groups[0][0]) and not process_ids(groups[1][0]),
            "subject or diagnostic account already has running processes",
        )
        setup = initial_setup(config)
        diagnostic = config["diagnostic"]
        initial_setup({**config, **diagnostic})
        runner.write_json(root / "initial-setup.json", setup)
        runner.write_json(
            root / "diagnostic-start.json",
            {
                "actual_subject": identity,
                "started_at": runner.datetime.now(runner.timezone.utc).isoformat(),
            },
        )
        started = time.monotonic()
        probe = None
        try:
            probe = runner.probe_profile(
                config["codex"],
                diagnostic["profile"],
                diagnostic["workspace"],
                config["condition"] == "treatment",
                config["private_root"],
                probe_evidence_dir=root / "diagnostic-evidence",
                native_user=diagnostic["native_user"],
            )
        finally:
            try:
                runner.write_json(
                    root / "diagnostic-stop.json",
                    {
                        "completed_probe": probe is not None,
                        "duration_seconds": time.monotonic() - started,
                        "model_calls": int(config["condition"] == "treatment")
                        if probe is not None
                        else None,
                        "model_call_status": "confirmed"
                        if probe is not None
                        else "unknown-preserve-failure",
                        "cost": None,
                        "cost_status": "unavailable",
                    },
                )
            finally:
                retire(groups[1][0])
        account_paths(config)
        require(
            initial_setup(config) == setup, "diagnostic changed actual subject setup"
        )
        usage = []
        events = root / "diagnostic-evidence/skill-read.jsonl"
        if events.exists():
            usage = [
                row["usage"]
                for line in events.read_text(encoding="utf-8").splitlines()
                if (row := json.loads(line)).get("type") == "turn.completed"
                and "usage" in row
            ]
        treatment = config["condition"] == "treatment"
        body = {
            "kind": "Stage1DiagnosticReceipt.v2",
            "actual_subject": identity,
            "diagnostic_identity": {**diagnostic, "uid": groups[1][0]},
            "codex_runtime_sha256": runner.codex_runtime_sha(config["codex"]),
            "plugin_tree_sha256": lock["plugin_tree_sha256"],
            "matching_probe": relevant(probe),
            "initial_setup_sha256": digest(setup),
            "functional_skill_sha256": probe["functional_skill_sha256"],
            "task": TASK if treatment else "native-discovery-only-v1",
            "model_calls": int(treatment),
            "duration_seconds": time.monotonic() - started,
            "usage": usage,
            "cost": None,
            "cost_status": "unavailable",
            "retired": True,
            "result": "passed",
        }
        envelope = sign(body, key)
        runner.write_json(root / "diagnostic-receipt.json", envelope)
        return envelope


def admit(config, lock, identity):
    """Reverify storage, actual identity and signed diagnostic, without model calls."""
    groups = account_paths(config)
    require(not process_ids(groups[1][0]), "retired diagnostic account is active")
    root = Path(config["state_root"])
    envelope = runner.read_json(root / "diagnostic-receipt.json")
    body = authenticated(envelope, secret(config["secret_file"]))
    require(
        body["actual_subject"] == identity
        and body["diagnostic_identity"]
        == {**config["diagnostic"], "uid": groups[1][0]},
        "diagnostic receipt substituted actual or diagnostic profile",
    )
    setup = runner.read_json(root / "initial-setup.json")
    if not (root / "probe.json").exists():
        require(initial_setup(config) == setup, "actual profile no longer fresh")
    return {
        "kind": "Stage1GuestLifecycle.v2",
        "mode": MODE,
        "initial_setup_sha256": digest(setup),
        "diagnostic": envelope,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    args = parser.parse_args()
    run_diagnostic(args.config)
