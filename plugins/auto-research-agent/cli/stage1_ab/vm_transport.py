"""Pinned OpenSSH JSON transport; no broad filesystem upload or shell interpolation."""

import argparse
import base64
import json
from pathlib import Path
import re
import subprocess

from .vm_common import require


def ssh(endpoint, envelope):
    require(
        set(endpoint)
        == {
            "ssh",
            "host",
            "port",
            "user",
            "identity_file",
            "known_hosts",
            "guest_python",
            "guest_config",
        },
        "SSH endpoint fields differ",
    )
    require(
        endpoint["host"] in {"127.0.0.1", "localhost"}
        and type(endpoint["port"]) is int
        and 1024 <= endpoint["port"] <= 65535,
        "only local VM SSH forwarding is supported",
    )
    for key in ("user", "guest_python", "guest_config"):
        require(
            re.fullmatch(r"[A-Za-z0-9_./-]+", endpoint[key]) is not None
            and not endpoint[key].startswith("-"),
            "unsafe SSH remote token",
        )
    require(
        Path(endpoint["known_hosts"]).is_file()
        and Path(endpoint["identity_file"]).is_file(),
        "SSH requires pre-provisioned pinned host key and private identity",
    )
    argv = [
        endpoint["ssh"],
        "-F",
        "none",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "UserKnownHostsFile=" + endpoint["known_hosts"],
        "-i",
        endpoint["identity_file"],
        "-p",
        str(endpoint["port"]),
        endpoint["user"] + "@" + endpoint["host"],
        "sudo",
        "-n",
        endpoint["guest_python"],
        "-I",
        "-m",
        "stage1_ab.vm_guest",
        endpoint["guest_config"],
    ]
    # The accepted CLI must be installed in this guest interpreter. -I ignores ambient PYTHONPATH.
    result = subprocess.run(
        argv, input=json.dumps(envelope).encode(), capture_output=True, check=False
    )
    try:
        require(
            result.returncode == 0,
            "guest SSH operation failed; reservation retained; inspect guest receipts before recovery",
        )
        return json.loads(result.stdout)
    except ValueError as error:
        error.diagnostic = {
            "exit_code": result.returncode,
            "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(result.stderr).decode("ascii"),
        }
        raise


def main():
    from .vm_controller import advance, prepare

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "capture", "fetch", "resume"))
    parser.add_argument("plan")
    args = parser.parse_args()
    value = (
        str(prepare(args.plan, ssh))
        if args.action == "prepare"
        else advance(args.plan, ssh, action=args.action)
    )
    print(json.dumps(value))


if __name__ == "__main__":
    main()
