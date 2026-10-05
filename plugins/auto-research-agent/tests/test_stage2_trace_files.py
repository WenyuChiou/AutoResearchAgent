"""Regression tests for private native telemetry byte and path boundaries."""

import hashlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live.trace_files import _json, _load_inventory, _ref, MAX_FILE_BYTES  # noqa: E402
from stage2_live.trace_handles import TraceRoot  # noqa: E402


class TraceFileBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "trace"
        (self.root / "payloads").mkdir(parents=True)
        (self.root / "manifest.json").write_bytes(b"{}")
        (self.root / "trace.jsonl").write_bytes(b"{}\n")
        (self.root / "payloads/1.json").write_bytes(b"{}")
        self.receipt = {
            p.relative_to(self.root).as_posix(): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in self.root.rglob("*")
            if p.is_file()
        }
        self.external = canonical_hash(self.receipt)

    def test_exact_bytes_and_rehash_do_not_replace_external_receipt(self):
        self.assertEqual(
            _load_inventory(self.root, self.receipt, self.external),
            {"manifest.json": b"{}", "trace.jsonl": b"{}\n", "payloads/1.json": b"{}"},
        )
        (self.root / "payloads/1.json").write_bytes(b"changed")
        with self.assertRaisesRegex(Stage2Error, "file-hash-mismatch"):
            _load_inventory(self.root, self.receipt, self.external)
        changed = dict(self.receipt)
        changed["payloads/1.json"] = hashlib.sha256(b"changed").hexdigest()
        with self.assertRaisesRegex(Stage2Error, "receipt-hash-mismatch"):
            _load_inventory(self.root, changed, self.external)

    def test_oversize_payload_is_rejected_before_read(self):
        oversized = self.root / "payloads/1.json"
        oversized.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        original = TraceRoot.open_file
        reads = []

        def observed(anchored, name):
            stream = original(anchored, name)
            if name == "payloads/1.json":

                class ObservedStream:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        stream.close()

                    def fileno(self):
                        return stream.fileno()

                    def read(self, amount):
                        reads.append(oversized)
                        return stream.read(amount)

                return ObservedStream()
            return stream

        with patch.object(TraceRoot, "open_file", observed):
            with self.assertRaisesRegex(Stage2Error, "file-size-limit"):
                _load_inventory(self.root, self.receipt, self.external)
        self.assertNotIn(oversized, reads)

    def test_growth_after_initial_stat_cannot_trigger_unbounded_read(self):
        original = os.fstat
        payload = self.root / "payloads/1.json"
        payload_inode = payload.stat().st_ino
        changed = False
        blocked = False

        def observed(fd):
            nonlocal changed, blocked
            value = original(fd)
            if value.st_ino == payload_inode and not changed:
                changed = True
                try:
                    payload.write_bytes(b"x" * (MAX_FILE_BYTES + 8))
                except PermissionError:
                    blocked = True
            return value

        with patch("stage2_live.trace_files.os.fstat", observed):
            if os.name == "nt":
                result = _load_inventory(self.root, self.receipt, self.external)
                self.assertTrue(blocked)
                self.assertEqual(result["payloads/1.json"], b"{}")
            else:
                with self.assertRaisesRegex(Stage2Error, "size-limit|changed"):
                    _load_inventory(self.root, self.receipt, self.external)
        self.assertTrue(changed)

    def test_directory_replacement_cannot_redirect_opened_trace(self):
        original = TraceRoot.open_file
        attempted, blocked = False, False
        retained = self.root.parent / "retained"
        foreign = self.root.parent / "foreign"
        foreign.mkdir()
        (foreign / "manifest.json").write_bytes(b"FOREIGN_DO_NOT_READ")

        def changed(anchored, name):
            nonlocal attempted, blocked
            if not attempted:
                attempted = True
                try:
                    self.root.rename(retained)
                except PermissionError:
                    blocked = True
                else:
                    self.root.symlink_to(foreign, target_is_directory=True)
            return original(anchored, name)

        with patch.object(TraceRoot, "open_file", changed):
            result = _load_inventory(self.root, self.receipt, self.external)
        self.assertTrue(attempted)
        self.assertEqual(result["manifest.json"], b"{}")
        if os.name == "nt":
            self.assertTrue(blocked)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO only")
    def test_fifo_replacement_is_rejected_without_blocking_open(self):
        original = TraceRoot.open_file

        def changed(anchored, name):
            if name == "payloads/1.json":
                path = self.root / name
                path.unlink()
                os.mkfifo(path)
            return original(anchored, name)

        with patch.object(TraceRoot, "open_file", changed):
            with self.assertRaisesRegex(Stage2Error, "opened-file-not-regular"):
                _load_inventory(self.root, self.receipt, self.external)

    def test_json_and_references_fail_closed(self):
        for value in (b"NaN", b"Infinity", b'{"n":1e9999}', b'{"n":1,"n":2}', b"\xff"):
            with self.subTest(value=value), self.assertRaises(Stage2Error):
                _json(value, "synthetic")
        good = {
            "raw_payload_id": "1",
            "kind": {"type": "test"},
            "path": "payloads/1.json",
        }
        raw = {"payloads/1.json": b"{}"}
        self.assertEqual(
            _ref({"source": good}, "source", raw)[:2], ("payloads/1.json", {})
        )
        for bad in (
            [],
            {"source": {**good, "raw_payload_id": None}},
            {"source": {**good, "kind": []}},
        ):
            with self.subTest(bad=bad), self.assertRaises(Stage2Error):
                _ref(bad, "source", raw)

    def test_foreign_unlisted_file_and_traversal_are_rejected(self):
        (self.root / "unlisted.json").write_bytes(b"{}")
        with self.assertRaisesRegex(Stage2Error, "inventory-mismatch"):
            _load_inventory(self.root, self.receipt, self.external)
        for name in ("../foreign", "C:/foreign", "/foreign", "payloads\\1.json"):
            with self.subTest(name=name):
                changed = {**self.receipt, name: "0" * 64}
                with self.assertRaisesRegex(Stage2Error, "receipt-path-invalid"):
                    _load_inventory(self.root, changed, canonical_hash(changed))

    def test_symlink_ancestor_is_rejected(self):
        alias = Path(self.temp.name).resolve() / "alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("host cannot create directory symlinks")
        # The final component is not a symlink; the reader must inspect parents.
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "payloads").mkdir()
        (nested / "manifest.json").write_bytes(b"{}")
        (nested / "trace.jsonl").write_bytes(b"{}\n")
        receipt = {
            "manifest.json": hashlib.sha256(b"{}").hexdigest(),
            "trace.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
        }
        with self.assertRaisesRegex(Stage2Error, "root-parent-reparse"):
            _load_inventory(alias / "nested", receipt, canonical_hash(receipt))

    def test_windows_reparse_ancestor_is_rejected_before_any_read(self):
        original = Path.lstat
        ancestor = self.root.parent

        def observed(path):
            value = original(path)
            if path == ancestor:
                return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
            return value

        with (
            patch.object(Path, "lstat", observed),
            patch.object(Path, "open", side_effect=AssertionError("must not read")),
        ):
            with self.assertRaisesRegex(Stage2Error, "root-parent-reparse"):
                _load_inventory(self.root, self.receipt, self.external)


if __name__ == "__main__":
    unittest.main()
