"""Synthetic runtime pins and Git checkouts; no Codex or model execution."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test_retrieval_execution import runtime
from research_workspace_native.binding import BindingError, BindingVerifier
from stage1_ledger.journal import LedgerError


class WorkspaceNativeBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.code = self.root / "runtime"
        self.code.mkdir()
        pin = runtime(self.code)
        self.entry = Path(pin["argv_prefix"][-1])
        self.dependency = self.root / "dependency"
        self.dependency.mkdir()
        self.git("init", "-q")
        (self.dependency / "tracked.py").write_bytes(b"approved code")
        self.git("add", "tracked.py")
        self.commit("synthetic accepted dependency")
        self.guard = BindingVerifier(
            pin, self.dependency, self.git("rev-parse", "HEAD").strip()
        )

    def git(self, *args):
        prefix = ["git", "-c", "safe.directory=" + str(self.dependency)]
        return subprocess.check_output(
            prefix + ["-C", str(self.dependency), *args], text=True, timeout=10
        )

    def commit(self, message):
        config = ["-c", "user.name=Fixture", "-c", "user.email=f@invalid"]
        self.git(*config, "commit", "--allow-empty", "-qm", message)

    def test_runtime_bytes_bound_including_added_cached_bytecode(self):
        self.guard()
        original = self.entry.read_bytes()
        self.entry.write_bytes(b"changed synthetic runtime")
        with self.assertRaisesRegex(LedgerError, "runtime-code-changed"):
            self.guard()
        self.entry.write_bytes(original)
        cache = self.code / "__pycache__"
        cache.mkdir()
        (cache / "fake.cpython-311.pyc").write_bytes(b"unbound stale bytecode")
        with self.assertRaisesRegex(BindingError, "cached bytecode"):
            self.guard()

    def test_dependency_sha_bound_and_changed_checkout_rejected(self):
        self.guard()
        self.git("update-index", "--assume-unchanged", "tracked.py")
        (self.dependency / "tracked.py").write_bytes(b"unapproved code")
        self.assertEqual(self.git("status", "--porcelain"), "")
        with self.assertRaises(BindingError):
            self.guard()
        self.git("update-index", "--no-assume-unchanged", "tracked.py")
        with self.assertRaises(BindingError):
            self.guard()
        self.git("checkout", "--", "tracked.py")
        self.commit("changed dependency")
        with self.assertRaisesRegex(BindingError, "dependency SHA or checkout"):
            self.guard()
