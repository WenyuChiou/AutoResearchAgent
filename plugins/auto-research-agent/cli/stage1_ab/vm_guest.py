"""Single-guest collection and capture. No controller registry or prior arm data."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from . import runner, sequence
from .vm_common import (
    VERSION,
    authenticated,
    binding,
    capture_files,
    digest,
    require,
    secret,
    sign,
)

CONFIG_FIELDS = {
    "kind",
    "guest_id",
    "condition",
    "repeat",
    "instance_file",
    "machine_id_file",
    "profile",
    "workspace",
    "codex",
    "lock",
    "prompt",
    "private_root",
    "runtime_pin",
    "state_root",
    "secret_file",
    "native_user",
    "native_tmp",
    "diagnostic",
}


def _sudo_policy_denies_all(result, username, hostname):
    """A successful policy listing can report no grants with exit status zero."""
    if (
        result.returncode not in {0, 1}
        or result.stderr != b""
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", hostname)
    ):
        return False
    # sudo prints its short run-host name; permit the measured kernel name too.
    # Never resolve DNS or accept a denial for an arbitrary other host/account.
    hosts = {hostname, hostname.split(".", 1)[0]}
    pattern = (
        rb"User "
        + re.escape(username.encode("utf-8"))
        + rb" is not allowed to run sudo on (?:"
        + b"|".join(re.escape(host.encode("ascii")) for host in sorted(hosts))
        + rb")\.\n?"
    )
    return re.fullmatch(pattern, result.stdout) is not None


def native_options(username):
    require(
        os.name == "posix" and os.geteuid() == 0,
        "guest broker must run as root and drop native privileges",
    )
    import pwd

    account = pwd.getpwnam(username)
    require(
        account.pw_uid != 0 and account.pw_name == username,
        "native subject must be the named unprivileged account",
    )
    options = {"user": account.pw_uid, "group": account.pw_gid, "extra_groups": []}
    sudo = subprocess.run(
        ["sudo", "-n", "-l", "-U", username],
        capture_output=True,
        timeout=15,
        env=dict(os.environ, LC_ALL="C"),
    )
    require(
        _sudo_policy_denies_all(sudo, account.pw_name, os.uname().nodename),
        "native subject has sudo grants or sudo policy could not be verified",
    )
    return (
        options,
        {
            "HOME": account.pw_dir,
            "USER": account.pw_name,
            "LOGNAME": account.pw_name,
            "TMPDIR": str(Path(account.pw_dir) / "tmp"),
            "TEMP": str(Path(account.pw_dir) / "tmp"),
            "TMP": str(Path(account.pw_dir) / "tmp"),
        },
    )


def configuration(path):
    path = Path(path).resolve()
    config = runner.read_json(path)
    require(
        set(config) == CONFIG_FIELDS and config["kind"] == "Stage1GuestConfig.v2",
        "guest config fields differ",
    )
    require(
        config["condition"] in {"baseline", "treatment"}
        and type(config["repeat"]) is int,
        "invalid guest slot",
    )
    options, native_env = native_options(config["native_user"])
    # Every broker/helper import and interpreter ancestor must resist subject writes.
    for target in (Path(__file__).resolve().parents[1], Path(sys.executable).resolve()):
        for item in (target, *target.parents):
            require(
                item.stat().st_uid == 0 and item.stat().st_mode & 0o022 == 0,
                "guest broker code/interpreter ancestry must be root-owned and non-writable",
            )
        if target.is_dir():
            require(
                all(
                    not item.is_symlink()
                    and item.stat().st_uid == 0
                    and item.stat().st_mode & 0o022 == 0
                    for item in target.rglob("*")
                ),
                "guest broker source must be root-owned and non-writable",
            )
    tmp = Path(config["native_tmp"])
    require(
        tmp.is_dir() and not tmp.is_symlink() and tmp.stat().st_uid == options["user"],
        "native scratch must belong to the isolated subject",
    )
    require(
        tmp.resolve() == Path(native_env["TMPDIR"]).resolve(),
        "native scratch differs from subject home tmp",
    )
    require(
        config["condition"] == "treatment" or config["runtime_pin"] is None,
        "baseline must not receive treatment runtime pin",
    )
    subject = [Path(config[k]).resolve() for k in ("profile", "workspace")]
    require(
        all(p.is_dir() and p.stat().st_uid == options["user"] for p in subject),
        "profile and workspace must belong to the isolated subject",
    )
    control = [
        path,
        *[
            Path(config[k]).resolve()
            for k in ("state_root", "secret_file", "instance_file", "lock", "prompt")
        ],
    ]
    require(
        subject[0] != subject[1]
        and not any(a.is_relative_to(b) for a in subject for b in subject if a != b),
        "subject profile/workspace overlap",
    )
    require(
        not any(
            a.is_relative_to(b) or b.is_relative_to(a) for a in control for b in subject
        ),
        "operator control material overlaps subject environment",
    )
    require(
        not Path(config["private_root"]).exists(),
        "private evaluator root is present on guest",
    )
    if os.name != "nt":
        # Provision each guest's independent operator home as 0700, as in the VM runbook.
        for value in (path, Path(config["secret_file"]), Path(config["instance_file"])):
            require(
                value.stat().st_uid == os.getuid()
                and value.parent.stat().st_uid == os.getuid()
                and value.parent.stat().st_mode & 0o077 == 0,
                "guest authority requires an operator-owned private directory",
            )
    lock = runner.read_json(config["lock"])
    require(
        lock.get("guest_adapter") == binding(),
        "guest adapter is not frozen at current bytes",
    )
    require(
        lock.get("kind") == "Stage1ABPublicLockV3"
        and lock.get("schema_version") == "3.1.0",
        "guest adapter requires a v3.1 public lock",
    )
    require(
        lock.get("execution_policy") == runner.SUBJECT_EXECUTION_POLICY,
        "guest sandbox/network policy differs",
    )
    require(
        lock["prompt_sha256"] == runner.sha(Path(config["prompt"]).read_bytes()),
        "guest prompt differs",
    )
    require(
        runner.codex_runtime_sha(config["codex"]) == lock["codex_runtime_sha256"],
        "guest Codex bytes differ",
    )
    slot = next(
        (
            r
            for r in sequence.expected_runs(lock)
            if (r["condition"], r["repeat"]) == (config["condition"], config["repeat"])
        ),
        None,
    )
    require(slot is not None, "guest slot absent from lock")
    identity = {
        "guest_id": config["guest_id"],
        "config_sha256": runner.sha(path.read_bytes()),
        "instance_sha256": runner.sha(Path(config["instance_file"]).read_bytes()),
        "machine_id_sha256": runner.sha(Path(config["machine_id_file"]).read_bytes()),
        "lock_sha256": runner.sha(Path(config["lock"]).read_bytes()),
        **slot,
    }
    require(
        Path(config["instance_file"]).stat().st_size >= 32,
        "guest instance identifier is missing",
    )
    root = Path(config["state_root"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(
        root.stat().st_uid == os.getuid() and root.stat().st_mode & 0o077 == 0,
        "guest state root must be operator-owned and mode 0700",
    )
    return config, lock, identity, secret(config["secret_file"])


def collect_probe(config, lock, identity):
    from . import vm_lifecycle

    lifecycle = vm_lifecycle.admit(config, lock, identity)
    condition, repeat = config["condition"], config["repeat"]
    probe = runner.probe_profile(
        config["codex"],
        config["profile"],
        config["workspace"],
        condition == "treatment",
        config["private_root"],
        probe_evidence_dir=Path(config["state_root"]) / "native-probe",
        native_user=config["native_user"],
        probe_mode="subject-non-model-v2",
    )
    require(
        probe["codex_version"] == lock["runtime"]["app_version"]
        and probe["model"] == lock["runtime"]["model_id"]
        and probe["reasoning"] == lock["runtime"]["reasoning"]
        and probe["native_capabilities_sha256"]
        == lock["runtime"]["tool_profile_sha256"],
        "guest probe differs from frozen runtime",
    )
    require(
        runner.tree_sha(runner.PLUGIN_ROOT) == lock["plugin_tree_sha256"],
        "guest adapter/plugin tree differs",
    )
    pin = {"sha256": runner._repeat_pin_sha(lock, repeat)}
    if condition == "treatment":
        pin["path"] = str(Path(config["runtime_pin"]).resolve())
        options, _ = native_options(config["native_user"])
        runner._runtime_pin(
            pin["path"],
            pin["sha256"],
            verify_host=True,
            workspace=config["workspace"],
            process_options=options,
        )
    vm_lifecycle.match_probe(lifecycle, probe, lock, identity)
    return {
        "kind": "Stage1GuestPreflight.v2",
        "lifecycle": lifecycle,
        "valid": True,
        "guest_binding": identity,
        "adapter": binding(),
        "lock_sha256": identity["lock_sha256"],
        "plugin_tree_sha256": lock["plugin_tree_sha256"],
        "research_hub_sha": lock["research_hub_sha"],
        "execution_policy": runner.SUBJECT_EXECUTION_POLICY,
        "binding": {
            "profiles": {condition: str(Path(config["profile"]).resolve())},
            "workspaces": {condition: str(Path(config["workspace"]).resolve())},
            "probes": {condition: probe},
            "treatment_runtime_pin": pin,
        },
    }


def verify_capture_binding(record, lock, preflight, *, verify_runtime=True):
    from .vm_lifecycle import match_probe

    identity = preflight.get("guest_binding", {})
    match_probe(
        preflight.get("lifecycle", {}),
        preflight["binding"]["probes"][record["condition"]],
        lock,
        identity,
    )
    require(
        preflight.get("kind") == "Stage1GuestPreflight.v2"
        and preflight.get("valid") is True
        and preflight.get("adapter") == lock.get("guest_adapter")
        and (not verify_runtime or preflight["adapter"] == binding()),
        "guest preflight adapter differs",
    )
    require(
        record.get("guest_binding") == identity
        and all(
            record.get(k) == identity.get(k)
            for k in ("run_id", "subject_id", "condition", "repeat")
        ),
        "guest capture identity or slot differs",
    )
    require(
        identity.get("lock_sha256") == record.get("lock_sha256"),
        "guest capture lock differs",
    )
    require(
        {k: identity[k] for k in ("repeat", "condition", "run_id", "subject_id")}
        in sequence.expected_runs(lock),
        "guest capture slot not frozen",
    )
    slot = record["condition"]
    for field in ("profiles", "workspaces", "probes"):
        require(
            set(preflight["binding"][field]) == {slot},
            "guest preflight contains another arm",
        )
    require(
        preflight["execution_policy"]
        == lock["execution_policy"]
        == runner.SUBJECT_EXECUTION_POLICY,
        "guest preflight execution policy differs",
    )


def verify_admission(context, lock_path, preflight_path, condition, repeat):
    """Validate a separately authenticated own-slot grant, never a copied registry."""
    config, lock, identity, key = configuration(context["config_path"])
    request = authenticated(context["envelope"], key)
    preflight = runner.read_json(preflight_path)
    require(
        context["config_path"] and request["action"] in {"capture", "resume"},
        "missing guest admission",
    )
    require(
        context["native_user"] == config["native_user"]
        and Path(context["native_final"]).parent.resolve()
        == Path(config["native_tmp"]).resolve(),
        "native execution identity differs from guest configuration",
    )
    require(
        request["identity"] == identity
        and (condition, repeat) == (identity["condition"], identity["repeat"])
        and Path(lock_path).resolve() == Path(config["lock"]).resolve(),
        "wrong guest admission",
    )
    require(
        request["preflight_sha256"] == runner.sha(Path(preflight_path).read_bytes()),
        "stale guest preflight",
    )
    state = runner.read_json(Path(config["state_root"]) / "admission.json")
    require(
        state["request_sha256"] == digest(request)
        and state["series_id"] == request["series_id"],
        "guest admission is not reserved",
    )
    verify_capture_binding({**identity, "guest_binding": identity}, lock, preflight)
    from .vm_lifecycle import admit

    require(
        admit(config, lock, identity) == preflight["lifecycle"],
        "guest lifecycle evidence changed",
    )


def execute(config_path, envelope):
    config, lock, identity, key = configuration(config_path)
    request = authenticated(envelope, key)
    require(
        set(request)
        == {"version", "action", "identity", "nonce", "series_id", "preflight_sha256"},
        "unexpected request fields: no file/path upload is accepted",
    )
    require(
        request["version"] == VERSION
        and request["identity"] == identity
        and isinstance(request["nonce"], str)
        and re.fullmatch(r"[0-9a-f]{64}", request["nonce"])
        and isinstance(request["series_id"], str)
        and re.fullmatch(r"[0-9a-f]{64}", request["series_id"]),
        "wrong guest or request version",
    )
    require(
        request["action"] in {"probe", "capture", "resume", "fetch"},
        "unsupported guest action",
    )
    root = Path(config["state_root"])
    with sequence.exclusive(root / "guest"):
        seen = root / ("request-" + request["nonce"] + ".json")
        runner.write_json(
            seen, envelope
        )  # Exclusive receipt; replay cannot launch twice.
        probe_path = root / "probe.json"
        state_path = root / "admission.json"
        output = root / "capture"
        action = request["action"]
        if action == "probe":
            require(
                request["preflight_sha256"] is None and not state_path.exists(),
                "probe after admission",
            )
            runner.write_json(probe_path, collect_probe(config, lock, identity))
        else:
            require(
                probe_path.is_file()
                and request["preflight_sha256"] == runner.sha(probe_path.read_bytes()),
                "stale guest probe receipt",
            )
            if action == "capture":
                require(not output.exists(), "guest output already exists")
                runner.write_json(
                    state_path,
                    {
                        "kind": "Stage1GuestAdmission.v2",
                        "request_sha256": digest(request),
                        "series_id": request["series_id"],
                        "active": None,
                    },
                )
            else:
                state = runner.read_json(state_path)
                require(
                    state["series_id"] == request["series_id"], "guest series changed"
                )
                if action == "resume":
                    record = runner.verify_capture(output)
                    require(
                        record["status"] != "complete" and record.get("thread_id"),
                        "no resumable guest capture",
                    )
                    state["request_sha256"] = digest(request)
                    sequence.save(state_path, state)
            if action in {"capture", "resume"}:
                state = runner.read_json(state_path)
                runner._capture_subject(
                    config["codex"],
                    config["lock"],
                    identity["condition"],
                    identity["repeat"],
                    config["profile"],
                    config["workspace"],
                    config["prompt"],
                    output,
                    config["private_root"],
                    probe_path,
                    resume=action == "resume",
                    registry=state,
                    registry_path=state_path,
                    guest_admission={
                        "config_path": str(config_path),
                        "envelope": envelope,
                        "native_user": config["native_user"],
                        "native_final": str(
                            Path(config["native_tmp"])
                            / (request["nonce"] + ".final.txt")
                        ),
                    },
                )
                runner.verify_capture(output)
        reply = {
            "version": VERSION,
            "request_sha256": digest(request),
            "identity": identity,
            "preflight": runner.read_json(probe_path),
            "preflight_sha256": runner.sha(probe_path.read_bytes()),
            "preflight_utf8": probe_path.read_bytes().decode("utf-8"),
            "files": None if action == "probe" else capture_files(output),
        }
        response = sign(reply, key)
        runner.write_json(root / ("response-" + request["nonce"] + ".json"), response)
        return response


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    args = parser.parse_args()
    result = execute(args.config, json.load(sys.stdin))
    print(json.dumps(result))
