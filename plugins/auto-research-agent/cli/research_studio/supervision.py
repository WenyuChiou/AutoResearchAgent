"""Fail closed unless the API owns an exclusive, non-delegated systemd cgroup."""

import os
from pathlib import Path, PurePosixPath
import signal
import time

from .store import StudioError, safe_path

CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")


def membership(pid):
    rows = (PROC_ROOT / str(pid) / "cgroup").read_text().strip().splitlines()
    if len(rows) != 1 or not rows[0].startswith("0::/"):
        raise StudioError("unified cgroup v2 membership required")
    value = rows[0][3:]
    if "//" in value or any(p in {".", ".."} for p in value.split("/")[1:]):
        raise StudioError("invalid cgroup membership")
    return value


class Supervision:
    def __init__(self):
        self.scope = None

    def locate(self):
        scope = membership("self")
        if (
            PurePosixPath(scope).name != "research-studio.service"
            or scope == "/research-studio.service"
        ):
            raise StudioError("a dedicated research-studio.service cgroup is required")
        root = safe_path(CGROUP_ROOT, scope.lstrip("/"))
        if (
            not (CGROUP_ROOT / "cgroup.controllers").is_file()
            or (root / "cgroup.type").read_text().strip() != "domain"
        ):
            raise StudioError("a cgroup v2 domain is required")
        if self.scope is not None and scope != self.scope:
            raise StudioError("service cgroup changed")
        self.scope = scope
        return root

    def members(self):
        root = self.locate()
        members = set()
        for path in [root / "cgroup.procs", *root.glob("**/cgroup.procs")]:
            safe_path(CGROUP_ROOT, path.relative_to(CGROUP_ROOT))
            for row in path.read_text().splitlines():
                if not row.isdecimal() or int(row) <= 0:
                    raise StudioError("invalid cgroup process inventory")
                members.add(int(row))
        return members - {os.getpid()}

    def preflight(self):
        if os.geteuid() == 0 or not os.statvfs(CGROUP_ROOT).f_flag & os.ST_RDONLY:
            raise StudioError(
                "unprivileged service with read-only cgroup protection required"
            )
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise StudioError("Linux pidfd process supervision required")
        descriptor = os.pidfd_open(os.getpid())
        os.close(descriptor)
        if self.members():
            raise StudioError("dedicated service cgroup contains another process")

    def cleanup(self):
        deadline = time.monotonic() + 5
        while True:
            members = self.members()
            if not members:
                return
            if time.monotonic() >= deadline:
                raise StudioError(
                    "worker processes remain; operator reconciliation required"
                )
            for pid in members:
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                try:
                    current = membership(pid)
                    if current != self.scope and not current.startswith(
                        self.scope + "/"
                    ):
                        raise StudioError(
                            "process escaped the dedicated service cgroup"
                        )
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                except (ProcessLookupError, FileNotFoundError):
                    pass
                finally:
                    os.close(descriptor)
            time.sleep(0.05)
