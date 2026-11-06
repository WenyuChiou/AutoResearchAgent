"""Atomic publication retains exclusive ownership across Windows long paths."""

import builtins
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error  # noqa: E402
from stage2_workflow import store  # noqa: E402


def readable(path):
    return Path("\\\\?\\" + str(path)) if os.name == "nt" else path


class AtomicPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="atomic-451-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.target = self.root / "result.json"
        self.temporary_path = self.target.with_name(
            f".{self.target.name}.{os.getpid()}.tmp"
        )

    def test_portable_exact_bytes_and_same_directory_exclusive_link(self):
        raw = b"synthetic\x00bytes\r\n"
        original = os.link
        calls = []

        def link(source, destination):
            self.assertEqual(Path(source).parent, Path(destination).parent)
            self.assertEqual(Path(source).read_bytes(), raw)
            self.assertFalse(Path(destination).exists())
            calls.append((source, destination))
            return original(source, destination)

        with patch.object(store.os, "link", side_effect=link):
            store._write_new(self.target, raw)
        self.assertEqual(self.target.read_bytes(), raw)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.temporary_path.exists())

    def test_portable_target_conflict_keeps_existing_target_and_cleans_owned_temp(self):
        self.target.write_bytes(b"existing owner")
        with self.assertRaisesRegex(Stage2Error, "exclusive-write-conflict"):
            store._write_new(self.target, b"new writer")
        self.assertEqual(self.target.read_bytes(), b"existing owner")
        self.assertFalse(self.temporary_path.exists())

    def test_portable_temporary_conflict_never_unlinks_other_owner(self):
        self.temporary_path.write_bytes(b"other writer pending bytes")
        with self.assertRaises(FileExistsError):
            store._write_new(self.target, b"new writer")
        self.assertEqual(
            self.temporary_path.read_bytes(), b"other writer pending bytes"
        )
        self.assertFalse(self.target.exists())

    def test_portable_fsync_failure_cleans_only_owned_temp_and_preserves_exception(
        self,
    ):
        failure = OSError("synthetic fsync failure")
        with patch.object(store.os, "fsync", side_effect=failure):
            with self.assertRaises(OSError) as raised:
                store._write_new(self.target, b"pending")
        self.assertIs(raised.exception, failure)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.temporary_path.exists())

    def test_portable_link_failure_cleans_owned_temp_without_publishing(self):
        with patch.object(
            store.os, "link", side_effect=OSError("synthetic link failure")
        ):
            with self.assertRaisesRegex(Stage2Error, "workflow-write-failed"):
                store._write_new(self.target, b"pending")
        self.assertFalse(self.target.exists())
        self.assertFalse(self.temporary_path.exists())

    def test_portable_canonical_json_bytes_are_unchanged(self):
        value = {"z": "中文", "a": [1, None]}
        store._write_new(self.target, value)
        self.assertEqual(self.target.read_bytes(), store._canonical_bytes(value))

    def test_non_windows_representation_keeps_original_path_object(self):
        with patch.object(store, "_IS_WINDOWS", False):
            self.assertIs(store._io_path(self.target), self.target)

    def test_windows_representation_rejects_unsafe_inputs_without_normalizing(self):
        unsafe = [
            "relative.json",
            "C:relative.json",
            r"\rooted.json",
            r"\\server\share\file.json",
            r"\\?\C:\safe\file.json",
            r"\\.\C:\safe\file.json",
            r"C:\safe\..\file.json",
            r"C:\safe\.\file.json",
            r"C:\safe\\file.json",
            "C:/safe/file.json",
            r"C:\safe\file.json:stream",
            "C:\\safe\\file. ",
            r"C:\safe\NUL.json",
            r"C:\safe\COM1",
        ]
        with patch.object(store, "_IS_WINDOWS", True):
            for value in unsafe:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(Stage2Error, "unsafe-windows-io-path"):
                        store._io_path(value)
            path = PureWindowsPath("C:/space ' 中文/file.json")
            self.assertEqual(store._io_path(path), "\\\\?\\" + str(path))

    def test_portable_open_failure_does_not_remove_any_temporary_file(self):
        failure = PermissionError("synthetic open denial")
        with (
            patch.object(builtins, "open", side_effect=failure),
            patch.object(store.os, "unlink") as unlink,
        ):
            with self.assertRaises(PermissionError) as raised:
                store._write_new(self.target, b"pending")
        self.assertIs(raised.exception, failure)
        unlink.assert_not_called()

    def test_portable_cleanup_failure_keeps_published_bytes_and_owned_residue(self):
        failure = PermissionError("synthetic cleanup denial")
        with patch.object(store.os, "unlink", side_effect=failure):
            with self.assertRaises(PermissionError) as raised:
                store._write_new(self.target, b"published")
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.target.read_bytes(), b"published")
        self.assertEqual(self.temporary_path.read_bytes(), b"published")

    @unittest.skipUnless(os.name == "nt", "Real Windows file I/O boundary")
    def test_windows_real_long_temporary_name_publishes_exact_bytes(self):
        parent = self.root / ("p" * (246 - len(str(self.root)) - 1))
        parent.mkdir()
        target = parent / "summary.json"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        self.assertEqual(len(str(target)), 259)
        self.assertGreaterEqual(len(str(temporary)), 266)
        store._write_new(target, b"exact synthetic summary")
        self.assertEqual(readable(target).read_bytes(), b"exact synthetic summary")
        self.assertFalse(readable(temporary).exists())

    @unittest.skipUnless(os.name == "nt", "Real Windows file I/O boundary")
    def test_windows_real_long_target_and_conflicts_preserve_all_owners(self):
        parent = self.root / ("p" * (236 - len(str(self.root)) - 1))
        parent.mkdir()
        target = parent / ("x" * 40 + ".json")
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")

        def cleanup_owned_files():
            for owned in (temporary, target):
                self.assertTrue(owned.is_relative_to(self.root))
                readable(owned).unlink(missing_ok=True)

        self.addCleanup(cleanup_owned_files)
        self.assertGreater(len(str(target)), 260)
        store._write_new(target, b"owner one")
        self.assertEqual(readable(target).read_bytes(), b"owner one")
        with self.assertRaisesRegex(Stage2Error, "exclusive-write-conflict"):
            store._write_new(target, b"owner two")
        self.assertEqual(readable(target).read_bytes(), b"owner one")
        self.assertFalse(readable(temporary).exists())
        readable(temporary).write_bytes(b"pending owner three")
        with self.assertRaises(FileExistsError):
            store._write_new(target, b"owner four")
        self.assertEqual(readable(temporary).read_bytes(), b"pending owner three")
        self.assertEqual(readable(target).read_bytes(), b"owner one")


if __name__ == "__main__":
    unittest.main()
