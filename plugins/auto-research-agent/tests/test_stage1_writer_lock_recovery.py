"""Windows kernel/CLI coverage for a recoverable Stage 1 coverage writer."""

# ruff: noqa: E402 -- load the authored local workspace fixture.
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from research_workspace_native.project_run_context import _tree
from stage1_coverage.run import CoverageLedger
from stage1_coverage import writer_lock
from stage1_ledger.journal import LedgerError, canonical, decode, digest
from stage1_ledger.store import Ledger


INTERRUPTED = r"""
from pathlib import Path
import sys
from unittest.mock import patch
from stage1_coverage.run import CoverageLedger
from stage1_ledger.store import Ledger
run = Path(sys.argv[1])
writer = CoverageLedger if sys.argv[2] == 'coverage' else Ledger
unlink = Path.unlink
def fail_release(path, *args, **kwargs):
    if path == run / '.writer-lock':
        raise OSError('authored normal process exit with a failed lock release')
    return unlink(path, *args, **kwargs)
try:
    with patch.object(Path, 'unlink', fail_release), writer(run).writing(repair=False):
        pass
except OSError as error:
    assert str(error) == 'authored normal process exit with a failed lock release'
assert (run / '.writer-lock').is_file()
"""


@unittest.skipUnless(os.name == "nt", "requires Windows lock and rename semantics")
class WindowsWriterLockRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wlr-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve() / "run"
        self.ledger = CoverageLedger.create(
            self.root, run_id="authored-lock-run", objective="Offline lock test"
        )
        self.lock = self.root / ".writer-lock"
        self.audit = self.root.parent / ".run.writer-lock-recovery"
        self.before = _tree(self.root)

    def invoke(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", *args],
            env={**os.environ, "PYTHONPATH": str(CLI)},
            capture_output=True,
            check=False,
        )

    def interrupt_release(self, kind="coverage"):
        result = self.invoke("-c", INTERRUPTED, str(self.root), kind)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return self.lock.read_bytes()

    def recover_cli(self, pin):
        result = self.invoke(
            "-m",
            "stage1_coverage.writer_lock",
            "--run",
            str(self.root),
            "--expect-lock-sha256",
            pin,
        )
        return result.returncode, json.loads(result.stdout)

    def test_supported_windows_cli_archives_failed_release_and_replays(self):
        raw = self.interrupt_release()
        self.assertEqual(decode(raw, "lock")["kind"], "Stage1CoverageWriterLock")
        held = self.invoke("-m", "stage1_ledger", "--run", str(self.root), "recover")
        self.assertEqual(held.returncode, 1)
        self.assertIn("writer-locked", json.loads(held.stdout)["error"])
        code, outcome = self.recover_cli(digest(raw))
        self.assertEqual(code, 0, outcome)
        self.assertEqual(outcome["status"], "recovered")
        self.assertEqual(outcome["automatic_retries"], 0)
        self.assertEqual(Path(outcome["archived_lock"]).read_bytes(), raw)
        proof = Path(outcome["receipt"]).read_bytes()
        self.assertEqual(json.loads(proof)["lock_sha256"], digest(raw))
        self.assertEqual(_tree(self.root), self.before)
        with self.ledger.writing(repair=False):
            current = self.lock.read_bytes()
            self.assertNotEqual(current, raw)
            code, again = self.recover_cli(digest(raw))
            self.assertEqual(code, 0, again)
            self.assertEqual(again["status"], "already-recovered")
            self.assertEqual(self.lock.read_bytes(), current)
        self.assertEqual(Path(outcome["receipt"]).read_bytes(), proof)
        self.assertEqual(_tree(self.root), self.before)
        projection = self.invoke(
            "-m", "stage1_ledger", "--run", str(self.root), "recover"
        )
        self.assertEqual(projection.returncode, 0, projection.stdout)
        self.assertEqual(json.loads(projection.stdout)["automatic_retries"], 0)

    def test_active_writer_keeps_delete_share_closed_and_refuses_recovery(self):
        with self.ledger.writing(repair=False):
            raw = self.lock.read_bytes()
            code, outcome = self.recover_cli(digest(raw))
            self.assertEqual((code, outcome["error"]), (1, "writer-lock-owner-active"))
            with self.assertRaises(PermissionError):
                os.rename(self.lock, self.root.parent / "forbidden-active-rename")
            self.assertEqual(self.lock.read_bytes(), raw)
            self.assertFalse(self.audit.exists())
        self.assertFalse(self.lock.exists())
        self.assertEqual(_tree(self.root), self.before)

    def test_legacy_and_wrong_sha_refuse_without_creating_receipt(self):
        legacy = self.interrupt_release("legacy")
        self.assertEqual(set(json.loads(legacy)), {"pid", "created_at"})
        code, _ = self.recover_cli("0" * 64)
        self.assertEqual(code, 1)
        code, outcome = self.recover_cli(digest(legacy))
        self.assertEqual(
            (code, outcome["error"]), (1, "writer-lock-owner-unverifiable")
        )
        self.assertEqual(self.lock.read_bytes(), legacy)
        self.assertFalse(self.audit.exists())

    def test_reused_pid_and_wrong_run_refuse(self):
        # Authored negative records, distinct from a live writer's actual file.
        record = writer_lock.owner_record(self.root, self.ledger.clock)
        record["owner_creation_filetime"] -= 1
        raw = canonical(record)
        self.lock.write_bytes(raw)
        code, outcome = self.recover_cli(digest(raw))
        self.assertEqual((code, outcome["error"]), (1, "writer-lock-owner-pid-reused"))
        other = self.root.parent / "other"
        Ledger.create(other, run_id="other-lock-fixture", objective="Test identity")
        (other / ".writer-lock").write_bytes(raw)
        with self.assertRaisesRegex(LedgerError, "writer-lock-run-or-boot-differs"):
            writer_lock.recover_writer_lock(other, digest(raw))
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertFalse(self.audit.exists())

    def test_prepared_receipt_survives_interruption_and_concurrent_recovery(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        rename = os.rename

        def interrupt(source, target):
            if source == self.lock:
                raise PermissionError("authored interruption after receipt publication")
            return rename(source, target)

        with patch.object(writer_lock.os, "rename", interrupt):
            with self.assertRaisesRegex(PermissionError, "after receipt publication"):
                writer_lock.recover_writer_lock(self.root, pin)
        receipt = self.audit / (pin + ".json")
        prepared = receipt.read_bytes()
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertFalse((self.audit / (pin + ".lock")).exists())
        with ThreadPoolExecutor(2) as pool:
            outcomes = [pool.submit(self.recover_cli, pin) for _ in range(2)]
            replies = [future.result() for future in outcomes]
        self.assertEqual([code for code, _ in replies], [0, 0], replies)
        self.assertEqual(
            {reply["status"] for _, reply in replies},
            {"recovered", "already-recovered"},
        )
        self.assertEqual(receipt.read_bytes(), prepared)
        self.assertEqual((self.audit / (pin + ".lock")).read_bytes(), raw)
        self.assertEqual(_tree(self.root), self.before)

    def test_receipt_not_published_leaves_original_lock_and_allows_retry(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        rename = os.rename

        def interrupt(source, target):
            if target.suffix == ".json":
                raise PermissionError(
                    "authored interruption before receipt publication"
                )
            return rename(source, target)

        with patch.object(writer_lock.os, "rename", interrupt):
            with self.assertRaisesRegex(PermissionError, "before receipt publication"):
                writer_lock.recover_writer_lock(self.root, pin)
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertEqual(list(self.audit.iterdir()), [])
        outcome = writer_lock.recover_writer_lock(self.root, pin)
        self.assertEqual(outcome["status"], "recovered")
        self.assertEqual(Path(outcome["archived_lock"]).read_bytes(), raw)

    def test_delayed_rename_cannot_move_a_new_generation(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        rename = os.rename
        observed = []

        def race(source, target):
            if source != self.lock:
                return rename(source, target)
            rename(source, target)
            # The next owner also exits normally after an injected I/O failure.
            # There is no active handle left to mask the no-replace guarantee.
            next_generation = self.interrupt_release()
            self.assertNotEqual(next_generation, raw)
            try:
                rename(source, target)
            except FileExistsError:
                self.assertEqual(self.lock.read_bytes(), next_generation)
                self.assertEqual(target.read_bytes(), raw)
                observed.append(next_generation)
                raise
            self.fail("delayed rename moved a later Windows writer's lock")

        with patch.object(writer_lock.os, "rename", race):
            outcome = writer_lock.recover_writer_lock(self.root, pin)
        self.assertEqual(outcome["status"], "already-recovered")
        self.assertEqual(len(observed), 1)
        self.assertEqual(self.lock.read_bytes(), observed[0])
        replacement = writer_lock.recover_writer_lock(self.root, digest(observed[0]))
        self.assertEqual(replacement["status"], "recovered")
        self.assertEqual(_tree(self.root), self.before)

    def test_junction_remote_provider_and_unsupported_platform_refuse(self):
        import _winapi

        raw = self.interrupt_release()
        link = self.root.parent / "through-junction"
        _winapi.CreateJunction(str(self.root), str(link))
        with self.assertRaisesRegex(ValueError, "link|reparse"):
            writer_lock.recover_writer_lock(link, digest(raw))
        with patch.object(writer_lock._windows(), "GetDriveTypeW", return_value=4):
            with self.assertRaisesRegex(LedgerError, "local-fixed-volume-required"):
                writer_lock.recover_writer_lock(self.root, digest(raw))
        with patch.object(writer_lock.os, "name", "posix"):
            with self.assertRaisesRegex(LedgerError, "recovery-windows-only"):
                writer_lock.recover_writer_lock(self.root, digest(raw))
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertFalse(self.audit.exists())

    def test_metadata_failure_preserves_normal_legacy_writing(self):
        with patch("stage1_coverage.run.owner_record", return_value=None):
            with self.ledger.writing(repair=False):
                self.assertEqual(
                    set(json.loads(self.lock.read_bytes())), {"pid", "created_at"}
                )
        self.assertFalse(self.lock.exists())
        self.assertEqual(_tree(self.root), self.before)

    def test_pinned_snapshot_never_includes_recovery_siblings(self):
        raw = self.interrupt_release()
        with self.assertRaisesRegex(ValueError, "ledger writer active"):
            _tree(self.root)
        result = writer_lock.recover_writer_lock(
            self.root, hashlib.sha256(raw).hexdigest()
        )
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(_tree(self.root), self.before)
