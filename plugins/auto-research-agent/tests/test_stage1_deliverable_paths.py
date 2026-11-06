"""Path admission stays fresh while each complete ancestor chain is checked."""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from stage1_deliverable.common import DeliverableError, safe_path


class DeliverablePathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="deliverable-path-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "package"
        self.leaf = self.root / "first" / "second" / "evidence.json"
        self.leaf.parent.mkdir(parents=True)
        self.leaf.write_bytes(b"{}")
        self.relative = "first/second/evidence.json"

    def linked_stat(self, target, *, reparse):
        original = os.lstat

        def observed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if Path(path).absolute() == target.absolute():
                return SimpleNamespace(
                    st_mode=info.st_mode if reparse else stat.S_IFLNK | 0o777,
                    st_file_attributes=0x400 if reparse else 0,
                )
            return info

        return observed

    def test_nested_existing_and_missing_paths_are_admitted(self):
        self.assertEqual(safe_path(self.root, self.relative), self.leaf)
        self.assertEqual(
            safe_path(self.root, "first/second/new/absent.json"),
            self.leaf.parent / "new" / "absent.json",
        )

    def test_root_intermediate_leaf_and_root_ancestor_reparse_are_rejected(self):
        for target in (self.root.parent, self.root, self.root / "first", self.leaf):
            with (
                self.subTest(target=target),
                patch(
                    "stage1_deliverable.common.os.lstat",
                    side_effect=self.linked_stat(target, reparse=True),
                ),
                self.assertRaisesRegex(DeliverableError, "reparse point"),
            ):
                safe_path(self.root, self.relative)

    def test_root_intermediate_and_leaf_symlinks_are_rejected(self):
        for target in (self.root, self.root / "first", self.leaf):
            with (
                self.subTest(target=target),
                patch(
                    "stage1_deliverable.common.os.lstat",
                    side_effect=self.linked_stat(target, reparse=False),
                ),
                self.assertRaisesRegex(DeliverableError, "linked artifact"),
            ):
                safe_path(self.root, self.relative)

    def test_next_call_rechecks_ancestor_after_it_becomes_linked(self):
        self.assertEqual(safe_path(self.root, self.relative), self.leaf)
        with (
            patch(
                "stage1_deliverable.common.os.lstat",
                side_effect=self.linked_stat(self.root / "first", reparse=True),
            ),
            self.assertRaisesRegex(DeliverableError, "reparse point"),
        ):
            safe_path(self.root, self.relative)
        self.assertEqual(safe_path(self.root, self.relative), self.leaf)

    def test_missing_leaf_still_checks_existing_intermediate_ancestors(self):
        with (
            patch(
                "stage1_deliverable.common.os.lstat",
                side_effect=self.linked_stat(self.root / "first", reparse=True),
            ),
            self.assertRaisesRegex(DeliverableError, "reparse point"),
        ):
            safe_path(self.root, "first/second/new/absent.json")

    def test_ancestor_access_error_is_not_treated_as_missing(self):
        original = os.lstat

        def inaccessible(path, *args, **kwargs):
            if Path(path).absolute() == self.root / "first":
                raise PermissionError("authored ancestor access refusal")
            return original(path, *args, **kwargs)

        with (
            patch("stage1_deliverable.common.os.lstat", side_effect=inaccessible),
            self.assertRaises(PermissionError),
        ):
            safe_path(self.root, self.relative)

    def test_traversal_and_windows_aliases_remain_rejected(self):
        for name in (
            "../outside.json",
            "/outside.json",
            "first\\evidence.json",
            "first//evidence.json",
            "first/./evidence.json",
            "first/CON.txt",
            "first/LPT1.pdf",
            "first/name./evidence.json",
            "first/name /evidence.json",
            "first/stream:alternate",
        ):
            with self.subTest(name=name), self.assertRaises(DeliverableError):
                safe_path(self.root, name)


if __name__ == "__main__":
    unittest.main()
