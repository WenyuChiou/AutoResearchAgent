"""Private output admits only the native sandbox's inert Git placeholder."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(PLUGIN / "tests"))

from stage1_deliverable.common import DeliverableError, private_output  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow  # noqa: E402


class PrivateOutputSandboxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.marker = self.root / ".git"
        self.marker.mkdir()
        self.target = self.root / "private"
        clean = {
            k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")
        }
        self.environment = patch.dict(os.environ, clean, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @contextmanager
    def sandbox_mount(self, *, mounted=True, readonly=True):
        # Cross-platform fixture for OS observations; real sandbox acceptance
        # separately exercises an actual read-only mount with zero model calls.
        with (
            patch.object(
                type(self.marker),
                "is_mount",
                lambda path: mounted and path == self.marker,
            ),
            patch("stage1_deliverable.common.os.ST_RDONLY", 1, create=True),
            patch(
                "stage1_deliverable.common.os.statvfs",
                return_value=SimpleNamespace(f_flag=1 if readonly else 0),
                create=True,
            ),
        ):
            yield

    def test_readonly_empty_mount_allows_private_output_and_probes_git(self):
        with (
            self.sandbox_mount(),
            patch(
                "stage1_deliverable.common.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 128, b"", b"not a repository"
                ),
            ) as probe,
        ):
            self.assertEqual(private_output(self.target), self.target)
            probe.assert_called_once()

    def test_mutable_or_nonmount_empty_marker_remains_rejected(self):
        for mounted, readonly in ((False, True), (True, False), (False, False)):
            with self.subTest(mounted=mounted, readonly=readonly):
                with self.sandbox_mount(mounted=mounted, readonly=readonly):
                    with self.assertRaises(DeliverableError):
                        private_output(self.target)

    def test_populated_mount_and_gitfile_remain_rejected(self):
        (self.marker / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf8")
        with self.sandbox_mount():
            with self.assertRaises(DeliverableError):
                private_output(self.target)
        (self.marker / "HEAD").unlink()
        self.marker.rmdir()
        self.marker.write_text("gitdir: elsewhere\n", encoding="utf8")
        with self.sandbox_mount():
            with self.assertRaises(DeliverableError):
                private_output(self.target)

    def test_marker_inspection_failure_remains_rejected(self):
        with self.sandbox_mount():
            with patch(
                "stage1_deliverable.common.os.statvfs",
                side_effect=OSError("unreadable"),
            ):
                with self.assertRaises(DeliverableError):
                    private_output(self.target)

    def test_linked_or_reparse_metadata_remains_rejected(self):
        original = os.lstat
        for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFDIR, 0x400)):
            with self.subTest(mode=mode, attributes=attributes):

                def lstat(path, *args, **kwargs):
                    if Path(path) == self.marker:
                        return SimpleNamespace(
                            st_mode=mode, st_file_attributes=attributes
                        )
                    return original(path, *args, **kwargs)

                with (
                    self.sandbox_mount(),
                    patch("stage1_deliverable.common.os.lstat", side_effect=lstat),
                ):
                    with self.assertRaises(DeliverableError):
                        private_output(self.target)

    def test_unavailable_mount_support_remains_rejected(self):
        with (
            self.sandbox_mount(),
            patch.object(
                type(self.marker), "is_mount", side_effect=NotImplementedError
            ),
        ):
            with self.assertRaises(DeliverableError):
                private_output(self.target)

    def test_unreadable_mount_contents_remain_rejected(self):
        original = type(self.marker).iterdir

        def iterdir(path):
            if path == self.marker:
                raise PermissionError("unreadable marker")
            return original(path)

        with self.sandbox_mount(), patch.object(type(self.marker), "iterdir", iterdir):
            with self.assertRaises(DeliverableError):
                private_output(self.target)

    def test_real_git_probe_still_overrides_placeholder(self):
        with (
            self.sandbox_mount(),
            patch(
                "stage1_deliverable.common.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, b"repository", b""),
            ),
        ):
            with self.assertRaises(DeliverableError):
                private_output(self.target)

    def test_real_repository_below_placeholder_remains_rejected(self):
        repository = self.root / "repository"
        subprocess.run(
            ["git", "init", str(repository)], check=True, capture_output=True
        )
        with self.sandbox_mount():
            with self.assertRaises(DeliverableError):
                private_output(repository / "private")

    def test_stage2_initialization_and_replay_under_placeholder(self):
        from test_stage1_stage2_handoff import Stage1Stage2HandoffTests

        upstream = Stage1Stage2HandoffTests()
        upstream.setUp()
        self.addCleanup(upstream.doCleanups)
        receipt = upstream.build()
        with self.sandbox_mount():
            manifest = initialize_workflow(
                upstream.output / "packet.json",
                upstream.output,
                self.target,
                {"model": "test-model"},
                {"path": "policy.json", "sha256": "a" * 64},
                expected_packet_sha256=receipt["packet_sha256"],
            )
            self.assertEqual(inspect_workflow(self.target)["manifest"], manifest)


if __name__ == "__main__":
    unittest.main()
