"""Realistic native payload inventories stay bounded without truncation."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stage2_common import Stage2Error, canonical_hash
from stage2_live import trace_files, trace_producer
from stage2_live.trace_handles import TraceRoot


class TraceCapacityTests(unittest.TestCase):
    def test_research_turn_with_697_files_loads_and_snapshots_every_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payloads").mkdir()
            (root / "manifest.json").write_bytes(b"{}")
            (root / "trace.jsonl").write_bytes(b"{}\n")
            for number in range(695):
                (root / "payloads" / f"{number}.json").write_bytes(b"{}")
            receipt = {
                path.relative_to(root).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(len(receipt), 697)
            loaded = trace_files._load_inventory(root, receipt, canonical_hash(receipt))
            self.assertEqual(set(loaded), set(receipt))
            snapshot, digest = trace_producer._snapshot(root)
            self.assertEqual(snapshot, receipt)
            self.assertEqual(digest, canonical_hash(receipt))

    def test_inventory_over_ceiling_is_rejected_before_any_file_open(self):
        digest = hashlib.sha256(b"{}").hexdigest()
        receipt = {
            f"payloads/{number}.json": digest
            for number in range(trace_files.MAX_FILES + 1)
        }
        with patch.object(TraceRoot, "open_file") as opened:
            with self.assertRaisesRegex(Stage2Error, "inventory-file-limit"):
                trace_files._load_inventory(
                    Path("unused"), receipt, canonical_hash(receipt)
                )
            opened.assert_not_called()

    def test_actual_directory_count_is_bounded_independently_of_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payloads").mkdir()
            for number in range(4):
                (root / "payloads" / str(number)).write_bytes(b"x")
            with TraceRoot(root) as anchored:
                self.assertEqual(len(anchored.entries(4)), 4)
                with self.assertRaisesRegex(Stage2Error, "inventory-file-limit"):
                    anchored.entries(3)

    def test_growing_count_does_not_disable_byte_or_external_hash_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payloads").mkdir()
            (root / "manifest.json").write_bytes(b"large")
            (root / "trace.jsonl").write_bytes(b"{}\n")
            receipt = {
                "manifest.json": hashlib.sha256(b"large").hexdigest(),
                "trace.jsonl": hashlib.sha256(b"{}\n").hexdigest(),
            }
            with patch.object(trace_files, "MAX_TOTAL_BYTES", 4):
                with self.assertRaisesRegex(Stage2Error, "total-size-limit"):
                    trace_files._load_inventory(root, receipt, canonical_hash(receipt))
            with self.assertRaisesRegex(Stage2Error, "receipt-hash-mismatch"):
                trace_files._load_inventory(root, receipt, "0" * 64)
