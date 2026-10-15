"""Contained worker protocol around the unchanged public transport and resolver.

This has no server/project authority. Every transport gate needs a timely
parent acknowledgment; parent Job ownership supplies the outer cutoff. Typed
resolver/configuration hashes remain declarations, not authentication.
"""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time

from stage1_deliverable.common import canonical, sha
from .atlas_local_source import decode, pinned, read, require
from .bounded_public_source import (
    TypedBoundedResolver,
    acquire_public_source,
    request_binding,
)
from .bounded_source_resolver import ProcessBoundedResolver

MAX_FRAME = 16 * 1024


class _Gates:
    def __init__(self, launch):
        self.launch, self.sequence = launch, 0

    def frame(self, kind, **values):
        raw = canonical(
            dict(
                kind=kind,
                sequence=self.sequence,
                request_sha256=self.launch["request_sha256"],
                config_sha256=self.launch["config_sha256"],
                **values,
            )
        )
        require(len(raw) <= MAX_FRAME, "source-worker-frame-too-large")
        require(
            sys.stdout.buffer.write(raw + b"\n") == len(raw) + 1,
            "source-worker-frame-partial-write",
        )
        sys.stdout.buffer.flush()

    def gate(self, phase):
        self.frame("gate", phase=phase)
        raw = sys.stdin.buffer.readline(MAX_FRAME + 2)
        require(
            raw.endswith(b"\n") and len(raw) <= MAX_FRAME + 1,
            "source-worker-admission-frame-invalid",
        )
        response = decode(raw)
        require(
            response
            == dict(
                kind="admit",
                sequence=self.sequence,
                request_sha256=self.launch["request_sha256"],
                config_sha256=self.launch["config_sha256"],
            ),
            "source-worker-admission-differs",
        )
        self.sequence += 1


class _GuardedResolver(TypedBoundedResolver):
    def __init__(self, config, gates):
        self.resolver = ProcessBoundedResolver(
            config["resolver_sha256"],
            cleanup_seconds=min(1, config["cleanup_reserve_seconds"]),
        )
        self.gates = gates

    @property
    def binding_sha256(self):
        return self.resolver.binding_sha256

    def resolve(self, host, port, absolute_monotonic_deadline):
        self.gates.gate("before-dns")
        require(
            time.monotonic() < absolute_monotonic_deadline, "source-worker-dns-deadline"
        )
        addresses = self.resolver.resolve(host, port, absolute_monotonic_deadline)
        self.gates.gate("after-dns")
        require(
            time.monotonic() < absolute_monotonic_deadline, "source-worker-dns-deadline"
        )
        return addresses


class _ExactGitProbe:
    """Bind only the unchanged common.private_output rev-parse subprocess.

    This adapter replaces this one module's subprocess reference in the owned
    child, never the stdlib module or shared source. The real returncode flows
    through the unchanged outside-Git guard; no fake guard result is supplied.
    """

    def __init__(self, request, output_dir, config):
        self.expected = [
            "git",
            "-C",
            str(Path(output_dir).parent),
            "rev-parse",
            "--show-toplevel",
        ]
        self.config = config
        anchor = time.monotonic()
        deadline = datetime.fromisoformat(
            request["deadline_utc"].replace("Z", "+00:00")
        )
        self.end = anchor + min(
            (deadline - datetime.now(timezone.utc)).total_seconds(),
            request["total_timeout_seconds"],
        )

    def run(self, args, **kwargs):
        require(
            type(args) is list
            and args == self.expected
            and set(kwargs) == {"capture_output", "check"}
            and kwargs["capture_output"] is True
            and kwargs["check"] is False,
            "source-worker-git-probe-not-registered",
        )
        pinned(
            Path(self.config["git_executable"]),
            self.config["git_sha256"],
            64 * 1024 * 1024,
        )
        remaining = self.end - time.monotonic()
        require(remaining > 0, "source-worker-git-probe-expired")
        # CreateProcess receives an absolute exe via Python's real subprocess.
        # Captured stdout/stderr and exit status remain the actual Git result.
        result = subprocess.run(
            [self.config["git_executable"], *args[1:]], timeout=remaining, **kwargs
        )
        require(
            type(result.returncode) is int and type(result.stderr) is bytes,
            "source-worker-git-result-invalid",
        )
        error = result.stderr.lower()
        # A real rc=0 still reaches the unchanged Core rejection. Only the
        # specific real outside-repository result may pass as a nonzero probe;
        # permissions, invalid cwd and other errors cannot claim outside-Git.
        require(
            result.returncode == 0
            or (
                result.returncode == 128
                and b"not a git repository" in error
                and not any(
                    value in error
                    for value in (
                        b"permission denied",
                        b"cannot change to",
                        b"access is denied",
                    )
                )
            ),
            "source-worker-git-result-unverified",
        )
        require(time.monotonic() < self.end, "source-worker-git-result-late")
        return result


def run_worker(launch):
    request = request_binding(launch["request"])
    config, gates = launch["config"], _Gates(launch)
    require(
        request["runtime_sha256"] == config["runtime_sha256"]
        and request["resolver_sha256"] == config["resolver_sha256"],
        "source-worker-runtime-binding-differs",
    )
    gates.gate("before-transport")
    import stage1_deliverable.common as common

    require(
        common.subprocess is subprocess
        and common.private_output.__code__.co_filename
        == str(
            Path(config["repo"])
            / "plugins/auto-research-agent/cli/stage1_deliverable/common.py"
        ),
        "source-worker-git-guard-origin-differs",
    )
    common.subprocess = _ExactGitProbe(request, launch["output_dir"], config)
    try:
        # Original request and absolute UTC deadline are not shortened/rebuilt.
        acquire_public_source(
            request, launch["output_dir"], resolver=_GuardedResolver(config, gates)
        )
        receipt = Path(launch["output_dir"]) / "public-source-acquisition.json"
        require(
            not receipt.with_name("public-source-acquisition-failure.json").exists(),
            "source-worker-acquisition-late-failure",
        )
        digest = sha(read(receipt, 1024 * 1024))
        gates.frame(
            "terminal",
            status="receipt-observed",
            receipt_path=receipt.name,
            receipt_sha256=digest,
        )
    except BaseException:
        gates.frame("terminal", status="failed-or-unknown")
        raise
