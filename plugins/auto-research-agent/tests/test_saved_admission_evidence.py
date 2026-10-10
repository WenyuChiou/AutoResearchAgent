"""Strict byte-bound evidence reader regressions."""

import hashlib
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.saved_admission_evidence import read_bound, read_bound_json
from stage1_deliverable.common import DeliverableError


def reference(path, raw):
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


class SavedAdmissionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="saved-admission-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        self.root.mkdir()

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return reference(name, raw)

    def test_reads_unicode_json_and_empty_bytes_without_mutating_reference(self):
        raw = '{"title":"日本","items":[]}'.encode("utf-8")
        json_ref = self.write("nested/evidence.json", raw)
        empty_ref = self.write("empty.bin", b"")
        before = deepcopy(json_ref)

        self.assertEqual(
            read_bound_json(self.root, json_ref), {"title": "日本", "items": []}
        )
        self.assertEqual(read_bound(self.root, empty_ref), b"")
        self.assertEqual(json_ref, before)

    def test_rejects_unsafe_paths_and_malformed_closed_reference(self):
        valid = self.write("evidence.json", b"{}")
        for path in ("../evidence.json", "/evidence.json", "nested\\evidence.json"):
            with self.subTest(path=path), self.assertRaises(DeliverableError):
                read_bound(self.root, {**valid, "path": path})

        malformed = (
            {**valid, "extra": True},
            {**valid, "sha256": valid["sha256"].upper()},
            {**valid, "bytes": True},
            {**valid, "bytes": -1},
        )
        for ref in malformed:
            with self.subTest(ref=ref), self.assertRaises(DeliverableError):
                read_bound(self.root, ref)

    def test_rejects_missing_non_regular_changed_hash_and_changed_size(self):
        valid = self.write("evidence.bin", b"bound bytes")
        cases = (
            {**valid, "path": "missing.bin"},
            {**valid, "sha256": "0" * 64},
            {**valid, "bytes": valid["bytes"] + 1},
            reference("directory", b""),
        )
        (self.root / "directory").mkdir()
        for ref in cases:
            with self.subTest(ref=ref), self.assertRaises(DeliverableError):
                read_bound(self.root, ref)

    def test_rejects_duplicate_keys_invalid_utf8_and_nonfinite_json(self):
        cases = (
            b'{"same":1,"same":2}',
            b'"\xff"',
            b'{"value":NaN}',
        )
        for number, raw in enumerate(cases):
            ref = self.write(f"invalid-{number}.json", raw)
            with self.subTest(raw=raw), self.assertRaises(DeliverableError):
                read_bound_json(self.root, ref)

    def test_rejects_linked_root(self):
        linked = Path(self.temp.name) / "linked-evidence"
        try:
            os.symlink(self.root, linked, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            original_lstat = os.lstat

            def reparse_root(path):
                info = original_lstat(path)
                if Path(path) == self.root.absolute():
                    return SimpleNamespace(
                        st_mode=info.st_mode,
                        st_file_attributes=0x400,
                    )
                return info

            valid = self.write("evidence.bin", b"bound bytes")
            with (
                patch("stage1_deliverable.common.os.lstat", side_effect=reparse_root),
                self.assertRaises(DeliverableError, msg=str(exc)),
            ):
                read_bound(self.root, valid)
            return
        valid = self.write("evidence.bin", b"bound bytes")
        with self.assertRaises(DeliverableError):
            read_bound(linked, valid)


if __name__ == "__main__":
    unittest.main()
