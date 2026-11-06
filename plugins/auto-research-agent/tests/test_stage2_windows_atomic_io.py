"""Atomic publication retains exclusive ownership across Windows long paths."""

import builtins
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error  # noqa: E402
from stage2_workflow import store  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402


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

    def cleanup_long_tree(self, path):
        self.assertTrue(path.is_absolute() and path.is_relative_to(self.root))
        self.assertNotEqual(path, self.root)
        root_state = readable(self.root).lstat()
        path_state = readable(path).lstat()
        self.assertFalse(
            path_state.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        shutil.rmtree(readable(path))
        after = readable(self.root).lstat()
        self.assertEqual(
            (after.st_dev, after.st_ino), (root_state.st_dev, root_state.st_ino)
        )
        self.assertFalse(readable(path).exists())

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
            self.assertIs(store._io(self.target), self.target)

    def test_status_observation_does_not_hide_permission_failure(self):
        with patch.object(
            Path, "stat", side_effect=PermissionError("synthetic denied")
        ):
            for kind in ("exists", "file", "dir"):
                with self.subTest(kind=kind):
                    with self.assertRaises(PermissionError):
                        store._status(self.target, kind)
        with patch.object(
            Path, "lstat", side_effect=PermissionError("synthetic denied")
        ):
            with self.assertRaises(PermissionError):
                store._status(self.target, "symlink")

    def test_public_relative_inputs_and_lexical_artifact_guard(self):
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(store._resolved(Path("relative")), self.root / "relative")
            store._write_new(self.target, {"ok": True})
            self.assertEqual(store._read_json(Path("result.json")), {"ok": True})
            for relative in (
                "../escape",
                "./result.json",
                "dir//file",
                "dir\\file",
                "file:stream",
            ):
                with self.subTest(relative=relative):
                    with self.assertRaises(Stage2Error):
                        store._inside(self.root, relative, "artifact")
        finally:
            os.chdir(original_cwd)

    def test_inside_still_rejects_a_link_observed_by_the_real_predicate(self):
        target = self.root / "linked"
        original = store._status

        def observe(path, kind):
            return (
                True if path == target and kind == "symlink" else original(path, kind)
            )

        with patch.object(store, "_status", side_effect=observe):
            with self.assertRaisesRegex(Stage2Error, "symlink-artifact-path"):
                store._inside(self.root, "linked/file.json", "artifact")

    @unittest.skipUnless(os.name == "nt", "Real Windows guarded workflow lifecycle")
    def test_windows_long_action_artifact_roundtrip_and_tampering_rejects(self):
        sources = self.root / "sources"
        packet = write_stage2_fixture(sources, candidate_count=1)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        workflow = self.root / ("w" * (180 - len(str(self.root)) - 1))
        store.initialize_workflow(
            packet_path,
            sources,
            workflow,
            {"model": "test-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.addCleanup(self.cleanup_long_tree, workflow)
        state = store.inspect_workflow(workflow)
        action_id = "ui-choice-" + "a" * 64
        action_dir = workflow / "actions" / action_id
        self.assertGreater(len(str(action_dir)), 260)
        started = store.start_action(
            workflow, action_id, "search", {}, {}, state["head_sha256"]
        )
        artifact = self.root / "summary.json"
        raw = b"retained synthetic summary"
        artifact.write_bytes(raw)
        completed = store.finish_action(
            workflow,
            action_id,
            "complete",
            {
                "summary.json": {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            },
            None,
            None,
            started["event"]["event_sha256"],
        )
        state = store.inspect_workflow(
            workflow, expected_head=completed["event_sha256"]
        )
        self.assertEqual(state["actions"][action_id]["result"]["status"], "complete")
        stored = action_dir / "artifacts" / "summary.json"
        self.assertEqual(store._io(stored).read_bytes(), raw)
        self.assertEqual(
            {item.name for item in store._entries(workflow / "actions")}, {action_id}
        )
        self.assertTrue(store._status(action_dir, "dir"))
        self.assertFalse(str(state["root"]).startswith("\\\\?\\"))
        store._io(stored).write_bytes(b"actual tampering")
        with self.assertRaisesRegex(Stage2Error, "artifact-hash-mismatch"):
            store.inspect_workflow(workflow)

    @unittest.skipUnless(os.name == "nt", "Real Windows long-path guard observation")
    def test_windows_long_guard_status_json_and_listing_use_actual_objects(self):
        parent = self.root / ("p" * (236 - len(str(self.root)) - 1))
        parent.mkdir()
        child = parent / ("d" * 40)
        store._io(child).mkdir()
        self.addCleanup(self.cleanup_long_tree, child)
        target = child / "record.json"
        store._write_new(target, {"value": "synthetic"})
        self.assertTrue(store._status(child, "exists"))
        self.assertTrue(store._status(child, "dir"))
        self.assertFalse(store._status(child, "symlink"))
        self.assertTrue(store._status(target, "file"))
        self.assertEqual(store._read_json(target), {"value": "synthetic"})
        self.assertEqual(list(store._entries(child)), [target])
        self.assertEqual(store._resolved(target), target)
        self.assertEqual(
            store._inside(parent, child.name + "/record.json", "artifact"), target
        )

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
