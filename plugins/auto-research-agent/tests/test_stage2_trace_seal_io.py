"""Directory replacement must never redirect seal reads or writes."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error  # noqa: E402
from stage2_live.trace_seal_io import SealDirectory  # noqa: E402


class SealIOTests(unittest.TestCase):
    def test_closed_handle_rejects_operations_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            bound = SealDirectory(root)
            with self.assertRaisesRegex(Stage2Error, "closed"):
                bound.write("before", b"no")
            with bound:
                child = bound.make_dir("child")
            for operation in (
                lambda: bound.write("after", b"no"),
                lambda: bound.reader("after"),
                lambda: bound.make_dir("other"),
                lambda: bound.status("after"),
                child.__enter__,
            ):
                with (
                    self.subTest(operation=operation),
                    self.assertRaisesRegex(Stage2Error, "closed"),
                ):
                    operation()
            self.assertEqual({item.name for item in root.iterdir()}, {"child"})

    def test_invalid_leaf_never_creates_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with SealDirectory(root) as bound:
                for leaf in (
                    "../x",
                    "..",
                    "a/b",
                    "a\\b",
                    "x:stream",
                    "x.",
                    "x ",
                    "x\x00",
                ):
                    with self.subTest(leaf=leaf), self.assertRaises(Stage2Error):
                        bound.write(leaf, b"no")
            self.assertEqual(list(root.iterdir()), [])

    def test_replacement_does_not_redirect_read_or_exclusive_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, foreign = root / "source", root / "foreign"
            source.mkdir()
            foreign.mkdir()
            (source / "control").write_bytes(b"source")
            (foreign / "control").write_bytes(b"foreign")
            with SealDirectory(source) as bound:
                if os.name == "nt":
                    with self.assertRaises(OSError):
                        source.rename(root / "held")
                else:
                    source.rename(root / "held")
                    source.symlink_to(foreign, target_is_directory=True)
                with bound.reader("control") as reader:
                    self.assertEqual(reader.read(), b"source")
                bound.write("created", b"safe")
                with self.assertRaises(FileExistsError):
                    bound.write("created", b"overwrite")
            self.assertFalse((foreign / "created").exists())
            self.assertEqual((foreign / "control").read_bytes(), b"foreign")

    def test_child_replacement_and_invalid_leaf_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "foreign").mkdir()
            with SealDirectory(root) as bound:
                child = bound.make_dir("child")
                (root / "child").rmdir()
                try:
                    (root / "child").symlink_to(
                        root / "foreign", target_is_directory=True
                    )
                except OSError:
                    self.skipTest("Creating a symlink requires host permission")
                with self.assertRaises((OSError, Stage2Error)):
                    child.__enter__()
                for leaf in ("../foreign/x", "..", "nested/file", "nested\\file"):
                    with self.subTest(leaf=leaf), self.assertRaises(Stage2Error):
                        bound.write(leaf, b"no")
            self.assertEqual(list((root / "foreign").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
