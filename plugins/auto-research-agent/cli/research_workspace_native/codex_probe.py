"""Bounded app-server handshake; no thread, turn, login or research dispatch.

Account reads can contact the authentication backend even with refresh disabled.
An executable hash and owned PID are observations, not process attestation or a
sandbox. Receipts exclude response bodies, account email, tokens and stderr.
"""

import hashlib
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import stat
import subprocess
import threading
import time


class ProbeError(ValueError):
    """A rejected or incomplete readiness observation."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while raw := stream.read(1024 * 1024):
            digest.update(raw)
    return digest.hexdigest()


def _path(value, *, directory=False):
    path = Path(value)
    if not path.is_absolute():
        raise ProbeError("absolute path required")
    for part in (path, *path.parents):
        reparse = os.name == "nt" and part.stat().st_file_attributes & 0x400
        if part.is_symlink() or reparse:
            raise ProbeError("linked path rejected")
    mode = path.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ProbeError("regular path required")
    return path.resolve(strict=True)


def _decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ProbeError("duplicate JSON field")
            value[key] = item
        return value

    def invalid(_):
        raise ProbeError("nonfinite JSON")

    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid
    )
    json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if not isinstance(value, dict):
        raise ProbeError("object frame required")
    return value


class _Receipt:
    def __init__(self, path):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.stream = os.fdopen(descriptor, "wb", buffering=0)
        self.sequence = 0

    def append(self, event, **fields):
        self.sequence += 1
        raw = json.dumps(
            dict(sequence=self.sequence, event=event, **fields), allow_nan=False
        )
        raw = (raw + "\n").encode("utf-8")
        if self.stream.write(raw) != len(raw):
            raise ProbeError("receipt write incomplete")
        os.fsync(self.stream.fileno())


class _Exchange:
    def __init__(self, process, receipt, deadline):
        self.process, self.receipt, self.deadline = process, receipt, deadline
        self.chunks, self.buffer, self.frames = queue.Queue(maxsize=16), b"", 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        total = 0
        try:
            while True:
                raw = self.process.stdout.read(4096)
                total += len(raw)
                if total > 1024 * 1024:
                    raise ProbeError("stream bound exceeded")
                self.chunks.put(raw, timeout=1)
                if not raw:
                    break
        except BaseException:
            try:
                self.chunks.put(None, timeout=1)
            except queue.Full:
                pass

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("probe deadline")
        return remaining

    def send(self, message):
        raw = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
        self.receipt.append("rpc-intent", method=message["method"], sha256=_sha(raw))
        done = queue.Queue(maxsize=1)

        def write():
            try:
                offset = 0
                while offset < len(raw):
                    self.remaining()
                    count = self.process.stdin.write(raw[offset:])
                    if type(count) is not int or not 0 < count <= len(raw) - offset:
                        raise ProbeError("invalid write count")
                    offset += count
                done.put(True)
            except BaseException:
                done.put(False)

        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        if not done.get(timeout=self.remaining()):
            raise ProbeError("write failed")
        self.receipt.append("rpc-write-observed", sha256=_sha(raw), byte_count=len(raw))

    def response(self, request_id):
        while True:
            self.remaining()
            while b"\n" not in self.buffer:
                if len(self.buffer) > 262144:
                    raise ProbeError("frame bound exceeded")
                raw = self.chunks.get(timeout=self.remaining())
                if raw is None or not raw:
                    raise ProbeError("output ended or reader failed")
                self.buffer += raw
            raw, self.buffer = self.buffer.split(b"\n", 1)
            self.frames += 1
            if len(raw) > 262144 or self.frames > 32:
                raise ProbeError("frame bound exceeded")
            value = _decode(raw)
            self.receipt.append(
                "rpc-frame-observed", sha256=_sha(raw), byte_count=len(raw)
            )
            if "method" in value:
                if (
                    not isinstance(value["method"], str)
                    or {"id", "result", "error"} & value.keys()
                ):
                    raise ProbeError("unexpected server request or ambiguous notice")
                continue
            if type(value.get("id")) is not int or value["id"] != request_id:
                raise ProbeError("unmatched response")
            if "error" in value or "result" not in value:
                raise ProbeError("RPC rejected")
            if not isinstance(value["result"], dict):
                raise ProbeError("object result required")
            return value["result"]


def _cleanup(process):
    report = dict(
        target_pid=process.pid,
        platform="windows" if os.name == "nt" else "posix",
        leader_reaped=False,
        tree_cleanup="not-required",
        process_tree_containment_verified=False,
        errors=[],
    )
    try:
        if process.poll() is None:
            if os.name == "nt":
                result = subprocess.run(
                    [
                        str(
                            Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
                        ),
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                report["tree_cleanup"] = "sent" if result.returncode == 0 else "failed"
            elif os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
                report["tree_cleanup"] = "sent"
            else:
                report["tree_cleanup"] = "ownership-unconfirmed"
        else:
            report["tree_cleanup"] = "unverified-leader-exited"
        process.wait(timeout=2)
        report["leader_reaped"] = True
        report["returncode"] = process.returncode
    except BaseException as error:
        report["errors"].append(type(error).__name__)
        try:
            process.kill()
            process.wait(timeout=1)
            report["leader_reaped"] = True
        except BaseException as error:
            report["errors"].append(type(error).__name__)
    for stream in (process.stdin, process.stdout):
        try:
            stream.close()
        except OSError:
            report["errors"].append("pipe-close-failed")
    return report


def run_probe(executable, expected_sha256, cwd, receipt_path, timeout=10):
    """Explicit one-shot readiness. Never called as a side effect of an HTTP GET."""
    executable, cwd = _path(executable), _path(cwd, directory=True)
    if (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or _file_sha(executable) != expected_sha256
    ):
        raise ProbeError("executable hash differs")
    if any(cwd.iterdir()) or any(
        (parent / ".git").exists() for parent in (cwd, *cwd.parents)
    ):
        raise ProbeError("empty private Git-external working directory required")
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 30
    ):
        raise ProbeError("deadline must be finite and within 30 seconds")
    receipt_path = Path(receipt_path)
    if not receipt_path.is_absolute():
        raise ProbeError("absolute receipt path required")
    _path(receipt_path.parent, directory=True)
    if receipt_path.parent.resolve() == cwd:
        raise ProbeError("receipt must be outside the empty working directory")
    receipt = _Receipt(receipt_path)
    process = None
    result = dict(
        status="check-failed",
        checked_at=datetime.now(timezone.utc).isoformat(),
        model_turn_tested=False,
        research_session_started=False,
        account_type=None,
        server_version=None,
    )
    try:
        receipt.append(
            "launch-intent",
            executable_sha256=expected_sha256,
            timeout_seconds=timeout,
            methods=["initialize", "initialized", "account/read"],
        )
        if _file_sha(executable) != expected_sha256:
            raise ProbeError("executable changed before launch")
        deadline = time.monotonic() + timeout
        options = dict(
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if os.name == "nt":
            options["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(
            [str(executable), "app-server", "--stdio"], **options
        )
        receipt.append("process-started", pid=process.pid)
        exchange = _Exchange(process, receipt, deadline)
        exchange.send(
            dict(
                id=1,
                method="initialize",
                params=dict(
                    clientInfo=dict(name="harness-workspace-readiness", version="1")
                ),
            )
        )
        hello = exchange.response(1)
        if (
            not isinstance(hello.get("userAgent"), str)
            or not 0 < len(hello["userAgent"]) <= 1024
        ):
            raise ProbeError("invalid initialization result")
        exchange.send(dict(method="initialized"))
        exchange.send(
            dict(id=2, method="account/read", params=dict(refreshToken=False))
        )
        account = exchange.response(2)
        requires_auth, entry = account.get("requiresOpenaiAuth"), account.get("account")
        if type(requires_auth) is not bool or not (
            entry is None or isinstance(entry, dict)
        ):
            raise ProbeError("invalid account result")
        kind = entry.get("type") if entry else None
        if (entry is not None and kind is None) or kind not in (
            None,
            "apiKey",
            "chatgpt",
            "amazonBedrock",
        ):
            raise ProbeError("unsupported account type")
        version = re.search(
            r"codex(?:-cli)?[ /]([0-9]+\.[0-9]+\.[0-9]+)",
            str(hello.get("userAgent", "")),
        )
        result.update(
            status="needs-login" if requires_auth and entry is None else "check-passed",
            account_type=kind,
            requires_openai_auth=requires_auth,
            server_version=version.group(1) if version else None,
            platform_os=hello.get("platformOs")
            if hello.get("platformOs") in ("windows", "linux", "macos")
            else "unknown",
        )
    except BaseException as error:
        result.update(status="check-failed", failure_type=type(error).__name__)
    finally:
        cleanup = _cleanup(process) if process is not None else dict(not_started=True)
        if process is not None and (
            not cleanup["leader_reaped"]
            or cleanup["errors"]
            or cleanup["tree_cleanup"]
            in ("failed", "ownership-unconfirmed", "unverified-leader-exited")
        ):
            result.update(status="check-failed", failure_type="CleanupIncomplete")
        result["cleanup"] = cleanup
        try:
            receipt.append("probe-completed", **result)
        finally:
            receipt.stream.close()
    return result
