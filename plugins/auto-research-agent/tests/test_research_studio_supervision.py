"""Cgroup contract fixtures; these do not establish live host containment."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_studio import supervision  # noqa: E402
from research_studio.store import StudioError  # noqa: E402


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.cg, self.proc = self.root / "cgroup", self.root / "proc"
        self.scope = "/system.slice/research-studio.service"
        self.group = self.cg / self.scope.lstrip("/")
        self.group.mkdir(parents=True)
        (self.cg / "cgroup.controllers").write_text("pids", encoding="utf-8")
        (self.group / "cgroup.type").write_text("domain", encoding="utf-8")
        self.write_members([])
        self.write_scope("self", self.scope)
        for name, value in (("CGROUP_ROOT", self.cg), ("PROC_ROOT", self.proc)):
            replacement = patch.object(supervision, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.subject = supervision.Supervision()
        for target, name, value in (
            (os, "geteuid", lambda: 1000),
            (os, "statvfs", lambda _path: SimpleNamespace(f_flag=1)),
            (os, "ST_RDONLY", 1),
            (supervision.signal, "SIGKILL", 9),
        ):
            replacement = patch.object(target, name, value, create=True)
            replacement.start()
            self.addCleanup(replacement.stop)

    def tearDown(self):
        self.temp.cleanup()

    def write_members(self, values):
        (self.group / "cgroup.procs").write_text(
            "\n".join(map(str, [os.getpid(), *values])), encoding="utf-8"
        )

    def write_scope(self, pid, value):
        directory = self.proc / str(pid)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "cgroup").write_text("0::" + value, encoding="utf-8")

    def test_dedicated_scope_and_pidfd_cleanup(self):
        with (
            patch.object(os, "pidfd_open", return_value=42, create=True),
            patch.object(os, "close"),
            patch.object(
                supervision.signal,
                "pidfd_send_signal",
                side_effect=lambda *args: self.write_members([]),
                create=True,
            ) as kill,
        ):
            self.subject.preflight()
            self.write_scope(123456, self.scope)
            self.write_members([123456])
            self.subject.cleanup()
            self.assertEqual(kill.call_args.args, (42, supervision.signal.SIGKILL))
            self.assertEqual(self.subject.members(), set())

    def test_foreign_scope_and_pid_reuse_are_not_killed(self):
        self.write_scope("self", "/system.slice/unrelated.service")
        with self.assertRaisesRegex(StudioError, "dedicated"):
            self.subject.members()
        self.write_scope("self", self.scope)
        self.write_members([123456])
        self.write_scope(123456, "/system.slice/unrelated.service")
        with (
            patch.object(os, "pidfd_open", return_value=42, create=True),
            patch.object(os, "close"),
            patch.object(supervision.signal, "pidfd_send_signal", create=True) as kill,
        ):
            with self.assertRaisesRegex(StudioError, "escaped"):
                self.subject.cleanup()
            kill.assert_not_called()

    def test_nonempty_scope_and_cleanup_timeout_fail_closed(self):
        self.write_members([123456])
        with (
            patch.object(os, "pidfd_open", return_value=42, create=True),
            patch.object(os, "close"),
            patch.object(supervision.signal, "pidfd_send_signal", create=True),
        ):
            with self.assertRaisesRegex(StudioError, "another process"):
                self.subject.preflight()
            with patch.object(supervision.time, "monotonic", side_effect=[0, 10]):
                with self.assertRaisesRegex(StudioError, "reconciliation"):
                    self.subject.cleanup()


if __name__ == "__main__":
    unittest.main()
