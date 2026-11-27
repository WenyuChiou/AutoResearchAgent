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
        self.assert_same_recovery(replies, pin)
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
        self.assertEqual([path.name for path in self.audit.iterdir()], ["owner.json"])
        outcome = writer_lock.recover_writer_lock(self.root, pin)
        self.assertEqual(outcome["status"], "recovered")
        self.assertEqual(Path(outcome["archived_lock"]).read_bytes(), raw)

    def test_audit_name_occupied_by_another_ledger_refuses_without_writes(self):
        Ledger.create(self.audit, run_id="other-ledger", objective="Separate run")
        other_before = _tree(self.audit)
        raw = self.interrupt_release()
        code, outcome = self.recover_cli(digest(raw))
        self.assertEqual(code, 1, outcome)
        self.assertEqual(outcome["error"], "writer-lock-audit-owner-differs")
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertEqual(_tree(self.audit), other_before)

    def test_wrong_audit_owner_refuses_new_archive_and_existing_archive_read(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        # Establish a genuine audit directory and preserve its original owner record.
        code, outcome = self.recover_cli(pin)
        self.assertEqual(code, 0, outcome)
        owner = self.audit / "owner.json"
        wrong = json.loads(owner.read_bytes())
        wrong["run_identity"]["directory_file_id"] += 1
        owner.write_bytes(canonical(wrong))
        new_lock = self.interrupt_release()
        for candidate in (pin, digest(new_lock)):
            code, outcome = self.recover_cli(candidate)
            self.assertEqual(code, 1, outcome)
            self.assertEqual(outcome["error"], "writer-lock-audit-owner-differs")
        self.assertEqual(self.lock.read_bytes(), new_lock)
        self.assertEqual((self.audit / (pin + ".lock")).read_bytes(), raw)
        self.assertFalse((self.audit / (digest(new_lock) + ".json")).exists())

    def test_two_cli_calls_publish_one_audit_for_the_same_run(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        self.assertFalse(self.audit.exists())
        with ThreadPoolExecutor(2) as pool:
            outcomes = [pool.submit(self.recover_cli, pin) for _ in range(2)]
            replies = [future.result() for future in outcomes]
        self.assertEqual([code for code, _ in replies], [0, 0], replies)
        self.assert_same_recovery(replies, pin)
        self.assertEqual(
            {path.name for path in self.audit.iterdir()},
            {"owner.json", pin + ".json", pin + ".lock"},
        )
        self.assertEqual((self.audit / (pin + ".lock")).read_bytes(), raw)
        self.assertEqual(_tree(self.root), self.before)
        code, replay = self.recover_cli(pin)
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay["status"], "already-recovered")

    def test_distinct_run_acl_refuses_new_and_existing_audit_without_writes(self):
        def change_fixture_acl(operation, principal):
            # The null SID never matches the test process. Change only the
            # temporary run's ACL to model an independently protected run.
            result = subprocess.run(
                ["icacls.exe", str(self.root), operation, principal],
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0,
                (result.stdout + result.stderr).decode(errors="replace"),
            )

        self.assertEqual(
            writer_lock._effective_acl(writer_lock._acl_descriptor(self.root))[1],
            writer_lock._effective_acl(writer_lock._acl_descriptor(self.root.parent))[1],
        )
        raw = self.interrupt_release()
        pin = digest(raw)
        change_fixture_acl("/deny", "*S-1-0-0:(OI)(CI)(R)")
        self.assertNotEqual(
            writer_lock._acl_descriptor(self.root), writer_lock._acl_descriptor(self.root.parent)
        )
        code, outcome = self.recover_cli(pin)
        self.assertEqual((code, outcome["error"]), (1, "writer-lock-audit-acl-differs"))
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertFalse(self.audit.exists())
        self.assertEqual(list(self.root.parent.glob(".writer-lock-audit-*")), [])

        change_fixture_acl("/remove:d", "*S-1-0-0")
        self.assertEqual(self.recover_cli(pin)[0], 0)
        before = _tree(self.audit)
        raw = self.interrupt_release()
        change_fixture_acl("/deny", "*S-1-0-0:(OI)(CI)(R)")
        code, outcome = self.recover_cli(digest(raw))
        self.assertEqual((code, outcome["error"]), (1, "writer-lock-audit-acl-differs"))
        self.assertEqual(self.lock.read_bytes(), raw)
        self.assertEqual(_tree(self.audit), before)

    def test_open_recovery_reader_does_not_block_offline_archive(self):
        raw = self.interrupt_release()
        pin = digest(raw)
        with writer_lock._open_read_lock(self.lock) as reader:
            code, outcome = self.recover_cli(pin)
            self.assertEqual(code, 0, outcome)
            self.assertEqual(outcome["status"], "recovered")
            self.assertEqual(reader.read(), raw)
        self.assertFalse(self.lock.exists())
        self.assertEqual((self.audit / (pin + ".lock")).read_bytes(), raw)

    def assert_same_recovery(self, replies, pin):
        statuses = {reply["status"] for _, reply in replies}
        self.assertIn("recovered", statuses, replies)
        self.assertLessEqual(statuses, {"recovered", "already-recovered"}, replies)
        self.assertEqual({reply["lock_sha256"] for _, reply in replies}, {pin})
        self.assertEqual(
            {Path(reply["archived_lock"]) for _, reply in replies},
            {self.audit / (pin + ".lock")},
        )
        self.assertEqual(
            {Path(reply["receipt"]) for _, reply in replies},
            {self.audit / (pin + ".json")},
        )

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

    def test_same_process_and_fixed_clock_stamp_distinct_generations(self):
        ledger = CoverageLedger(self.root, clock=lambda: "2026-11-26T12:00:00Z")
        locks = []
        for _ in range(2):
            with ledger.writing(repair=False):
                locks.append(json.loads(self.lock.read_bytes()))
            self.assertFalse(self.lock.exists())
        first, second = locks
        self.assertEqual(first["schema_version"], "1.0.0")
        self.assertEqual(first["pid"], os.getpid())
        self.assertNotEqual(first.pop("generation"), second.pop("generation"))
        self.assertEqual(first, second)
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
