"""Versioned authenticated messages for operator-controlled, single-slot guests."""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath

from . import runner

VERSION = "Stage1GuestTransport.v2"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(value):
    return runner.sha(canonical(value))


def binding():
    root = Path(__file__).parent
    names = (
        "vm_common.py",
        "vm_guest.py",
        "vm_controller.py",
        "vm_transport.py",
        "vm_subject.py",
        "vm_lifecycle.py",
        "vm_runtime.py",
        "runner.py",
        "sequence.py",
    )
    return {
        "version": VERSION,
        "files": {name: runner.sha((root / name).read_bytes()) for name in names},
    }


def require(condition, message):
    if not condition:
        raise runner.ExecutionBlocked(message)


def secret(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing or linked guest secret")
    if os.name != "nt":
        require(
            path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0,
            "guest secret must be operator-owned and mode 0600",
        )
    data = path.read_bytes()
    require(len(data) >= 32, "guest secret must contain at least 32 random bytes")
    return data


def sign(value, key):
    return {
        "body": value,
        "hmac_sha256": hmac.new(key, canonical(value), hashlib.sha256).hexdigest(),
    }


def authenticated(envelope, key):
    require(
        set(envelope) == {"body", "hmac_sha256"}, "unexpected transport envelope fields"
    )
    expected = sign(envelope["body"], key)["hmac_sha256"]
    require(
        isinstance(envelope["hmac_sha256"], str)
        and hmac.compare_digest(expected, envelope["hmac_sha256"]),
        "transport authentication failed",
    )
    return envelope["body"]


def safe_name(name):
    p = PurePosixPath(name)
    require(
        isinstance(name, str)
        and name
        and "\\" not in name
        and ":" not in name
        and not p.is_absolute()
        and all(v not in {"", ".", ".."} for v in name.split("/")),
        "unsafe transferred filename",
    )
    return p


def capture_files(directory):
    """Allowlist the exact existing capture, never a profile or arbitrary guest tree."""
    root = Path(directory).resolve()
    record = runner.read_json(root / "run.json")
    names = {"run.json"}
    for attempt in record["attempts"]:
        names.update(attempt["files"])
    files = {}
    for name in sorted(names):
        safe_name(name)
        p = root / name
        require(
            p.resolve().is_relative_to(root) and not p.is_symlink(),
            "capture transfer escapes root",
        )
        require(
            all(
                not parent.is_symlink() for parent in p.parents if parent != root.parent
            ),
            "linked capture transfer",
        )
        data = p.read_bytes()
        files[name] = {
            "sha256": runner.sha(data),
            "base64": base64.b64encode(data).decode("ascii"),
        }
    return files


def receive_capture(files, output):
    """Verify every transferred byte before creating an exclusive destination."""
    decoded = {}
    for name, row in files.items():
        safe_name(name)
        require(set(row) == {"sha256", "base64"}, "unexpected transferred metadata")
        data = base64.b64decode(row["base64"], validate=True)
        require(runner.sha(data) == row["sha256"], "transferred file hash differs")
        decoded[name] = data
    require("run.json" in decoded, "transferred capture lacks run.json")
    record = json.loads(decoded["run.json"])
    expected = {"run.json"}
    for attempt in record["attempts"]:
        for name, sha in attempt["files"].items():
            expected.add(name)
            require(
                name in decoded and runner.sha(decoded[name]) == sha,
                "capture manifest differs from transfer",
            )
    require(set(decoded) == expected, "transfer contains non-capture files")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, data in decoded.items():
        p = output / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("xb") as stream:
            stream.write(data)
    for number, attempt in enumerate(record["attempts"], 1):
        (output / "workspace" / f"{number:02d}").mkdir(parents=True, exist_ok=True)
        prefix = f"attempt-{number:02d}.observer/"
        if any(name.startswith(prefix) for name in attempt["files"]):
            (output / prefix / "blobs").mkdir(parents=True, exist_ok=True)
    return runner.verify_capture(output, verify_runtime=False)
