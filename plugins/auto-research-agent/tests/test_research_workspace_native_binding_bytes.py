"""Physical-byte regressions using local synthetic Git objects and no models."""

from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace_native.binding import BindingError, BindingVerifier
from research_workspace_native.transport import JsonRpcTransport, TransportError
from stage1_ledger.journal import canonical, digest


class PhysicalDependencyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "dependency"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.file = self.repo / "tracked.py"
        self.file.write_bytes(b"approved code\n")
        self.commit()
        entry = self.root / "runtime.py"
        entry.write_bytes(b"# synthetic runtime\n")
        exe = str(Path(sys.executable).resolve())
        files = {
            exe: digest(Path(exe).read_bytes()),
            str(entry): digest(entry.read_bytes()),
        }
        argv = [exe, "-I", "-B", str(entry)]
        self.pin = dict(
            argv_prefix=argv,
            executable_sha256=files[exe],
            code_identity=dict(
                argv_prefix=argv,
                mode="script",
                entry=str(entry),
                absent_paths=[],
                roots={str(entry): True},
                files=files,
                files_sha256=digest(canonical(files)),
            ),
        )

    def git(self, *args, data=None):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=" + str(self.repo),
                "-C",
                str(self.repo),
                *args,
            ],
            input=data,
            timeout=10,
        )

    def commit(self):
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=f@invalid",
            "commit",
            "-qm",
            "neutral fixture",
        )
        self.sha = self.git("rev-parse", "HEAD").decode().strip()

    def guard(self):
        return BindingVerifier(self.pin, self.repo, self.sha)

    def mask(self):
        self.marker = self.root / "filter-observations"
        script = self.root / "mask.py"
        script.write_text(
            "import sys\nfrom pathlib import Path\n"
            f"p=Path({str(self.marker)!r})\np.write_bytes(p.read_bytes()+b'x' if p.exists() else b'x')\n"
            "sys.stdin.buffer.read()\nsys.stdout.buffer.write(b'approved code\\n')\n",
            encoding="utf-8",
        )
        command = shlex.join([Path(sys.executable).as_posix(), script.as_posix()])
        self.git("config", "filter.mask.clean", command)
        (self.repo / ".gitattributes").write_bytes(b"tracked.py filter=mask\n")
        self.commit()

    def test_clean_filter_cannot_hide_post_binding_physical_mutation(self):
        self.mask()
        guard = self.guard()
        self.file.write_bytes(b"unapproved physical code\n")
        self.git("add", "tracked.py")  # Clean filter retains the accepted index blob.
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertTrue(
            all(
                row[:1] == b"H"
                for row in self.git("ls-files", "-v", "-z").split(b"\0")
                if row
            )
        )
        before = self.marker.read_bytes()
        with self.assertRaises(BindingError):
            guard()
        self.assertEqual(
            self.marker.read_bytes(), before, "guard must not execute clean filters"
        )
        channel = Mock()
        transport = JsonRpcTransport(
            channel,
            connection_id="fixture",
            on_event=lambda event: None,
            verify_binding=guard,
        )
        self.addCleanup(transport.close)
        with self.assertRaises(TransportError):
            transport.send_request("turn/start", {}, request_id=1)
        channel.write.assert_not_called()

    def test_constructor_cannot_adopt_already_polluted_physical_bytes(self):
        self.mask()
        self.file.write_bytes(b"polluted before constructor\n")
        self.git("add", "tracked.py")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaises(BindingError):
            self.guard()()

    def test_literal_git_show_clean_filter_cannot_hide_physical_bytes(self):
        self.git("config", "filter.replay.clean", "git show HEAD:tracked.py")
        (self.repo / ".gitattributes").write_bytes(b"tracked.py filter=replay\n")
        self.commit()
        guard = self.guard()
        self.file.write_bytes(b"unreviewed physical implementation\n")
        self.git("add", "tracked.py")
        self.assertEqual(self.git("rev-parse", "HEAD").decode().strip(), self.sha)
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertTrue(
            all(
                row[:1] == b"H"
                for row in self.git("ls-files", "-v", "-z").split(b"\0")
                if row
            )
        )
        with self.assertRaises(BindingError):
            guard()

    def test_exact_bytes_rechecked_and_filter_is_never_executed(self):
        self.mask()
        before = self.marker.read_bytes()
        guard = self.guard()
        guard()
        self.assertEqual(self.marker.read_bytes(), before)
        self.file.write_bytes(b"different bytes\n")
        with self.assertRaises(BindingError):
            guard()

    def test_normalized_crlf_and_encoded_worktrees_fail_closed(self):
        attributes = self.repo / ".gitattributes"
        attributes.write_bytes(b"tracked.py text\n")
        self.commit()
        self.file.write_bytes(b"approved code\r\n")
        self.git("add", "tracked.py")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaises(BindingError):
            self.guard()()
        attributes.write_bytes(b"tracked.py text working-tree-encoding=UTF-16\n")
        self.file.write_bytes("approved code\n".encode("utf-16"))
        self.commit()
        self.assertEqual(self.git("status", "--porcelain"), b"")
        with self.assertRaises(BindingError):
            self.guard()()

    def test_symlink_and_submodule_git_modes_are_not_admitted(self):
        for mode, object_id in (
            (
                "120000",
                self.git("hash-object", "-w", "--stdin", data=b"outside")
                .decode()
                .strip(),
            ),
            ("160000", self.sha),
        ):
            tree = (
                self.git(
                    "mktree",
                    data=f"{mode} {'blob' if mode == '120000' else 'commit'} {object_id}\tentry\n".encode(),
                )
                .decode()
                .strip()
            )
            commit = (
                self.git(
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=f@invalid",
                    "commit-tree",
                    tree,
                    data=b"typed fixture\n",
                )
                .decode()
                .strip()
            )
            with self.assertRaisesRegex(BindingError, "mode"):
                BindingVerifier(self.pin, self.repo, commit)

    def test_index_flags_staging_and_untracked_files_remain_rejected(self):
        guard = self.guard()
        guard()
        for flag in ("assume-unchanged", "skip-worktree"):
            self.git("update-index", "--" + flag, "tracked.py")
            with self.assertRaises(BindingError):
                guard()
            self.git("update-index", "--no-" + flag, "tracked.py")
        (self.repo / "added.py").write_bytes(b"untracked")
        with self.assertRaises(BindingError):
            guard()
        (self.repo / "added.py").unlink()
        oid = (
            self.git("hash-object", "-w", "--stdin", data=b"staged difference")
            .decode()
            .strip()
        )
        self.git("update-index", "--cacheinfo", "100644," + oid + ",tracked.py")
        with self.assertRaises(BindingError):
            guard()

    def test_unsafe_and_case_colliding_tree_paths_fail_before_use(self):
        oid = self.git("rev-parse", "HEAD:tracked.py").decode().strip()
        for names in (("CON.py",), ("module.py", "MODULE.py")):
            tree = (
                self.git(
                    "mktree",
                    data="".join(
                        f"100644 blob {oid}\t{name}\n" for name in names
                    ).encode(),
                )
                .decode()
                .strip()
            )
            commit = (
                self.git(
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=f@invalid",
                    "commit-tree",
                    tree,
                    data=b"path fixture\n",
                )
                .decode()
                .strip()
            )
            with self.assertRaisesRegex(BindingError, "path"):
                BindingVerifier(self.pin, self.repo, commit)


if __name__ == "__main__":
    unittest.main()
