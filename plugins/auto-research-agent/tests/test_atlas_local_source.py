"""Offline byte/protocol checks only; no real or fake child is launched."""

import importlib.util
import io
from pathlib import Path
import stat
from types import ModuleType, SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent / "cli/research_workspace_native"
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parent


def raw_module(alias, path):
    if alias not in sys.modules:
        module = ModuleType(alias)
        module.__file__ = str(path)
        sys.modules[alias] = module
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return sys.modules[alias]


source = raw_module("_atlas_local_source", ROOT / "atlas_local_source.py")
launcher = source


class LocalLauncherTests(unittest.TestCase):
    def test_invalid_or_unrepresentable_read_bounds_fail_before_filesystem_io(self):
        path = Path(tempfile.gettempdir()).resolve() / "raw.bin"
        with patch.object(Path, "lstat", side_effect=AssertionError("no I/O")):
            for limit in (float("inf"), float("nan"), 65536.5, -1, True, sys.maxsize):
                with self.subTest(limit=limit):
                    with self.assertRaisesRegex(
                        source.LauncherError, "integer file bound"
                    ):
                        source.read(path, limit, allow_empty=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "empty"
            path.touch()
            self.assertEqual(source.read(path, 0, allow_empty=True), b"")
            path.write_bytes(b"x")
            with self.assertRaisesRegex(source.LauncherError, "file bound exceeded"):
                source.read(path, 0, allow_empty=True)

    def test_chunked_raw_read_preserves_all_bytes_and_exact_maximum(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "raw.bin"
            raw = bytes(range(256)) * 1024 + b"end"
            path.write_bytes(raw)
            self.assertEqual(source.read(path, len(raw)), raw)
            self.assertEqual(source.inventory(root), {"raw.bin": source.digest(raw)})
            with self.assertRaisesRegex(source.LauncherError, "file bound"):
                source.read(path, len(raw) - 1)

    def test_short_reads_continue_to_eof_and_stop_at_bound_plus_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "raw.bin"
            path.write_bytes(b"regular")
            data = bytes(range(256)) * 1024

            class ShortReader(io.BytesIO):
                def __init__(self, raw):
                    super().__init__(raw)
                    self.requests, self.observed = [], 0

                def read(self, count):
                    self.requests.append(count)
                    raw = super().read(min(count, 17))
                    self.observed += len(raw)
                    return raw

            stream = ShortReader(data)
            with patch.object(Path, "open", return_value=stream):
                self.assertEqual(source.read(path, len(data)), data)
            self.assertLessEqual(max(stream.requests), 64 * 1024)
            stream = ShortReader(data)
            with patch.object(Path, "open", return_value=stream):
                with self.assertRaisesRegex(source.LauncherError, "file bound"):
                    source.read(path, 100)
            self.assertEqual(stream.observed, 101)

    def test_empty_and_nonregular_raw_reads_still_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "empty"
            path.touch()
            self.assertEqual(source.read(path, allow_empty=True), b"")
            with self.assertRaisesRegex(source.LauncherError, "file bound"):
                source.read(path)
            with self.assertRaisesRegex(source.LauncherError, "regular file"):
                source.read(root)

    def test_same_size_inventory_mutation_is_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "tracked.py"
            path.write_bytes(b"original\n")
            before = source.inventory(root)
            path.write_bytes(b"modified\n")
            self.assertNotEqual(source.inventory(root), before)
            with self.assertRaisesRegex(source.LauncherError, "pinned bytes"):
                source.pinned(path, before["tracked.py"])

    def test_each_ancestor_link_and_reparse_is_refused_before_open(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "tracked.py"
            path.write_bytes(b"safe\n")
            original = Path.lstat
            for selected, mode, attributes in (
                (path, stat.S_IFLNK, 0),
                (root, stat.S_IFDIR, 0x400),
            ):

                def observed(value):
                    if value == selected:
                        return SimpleNamespace(
                            st_mode=mode, st_file_attributes=attributes
                        )
                    return original(value)

                with (
                    self.subTest(path=str(selected)),
                    patch.object(Path, "lstat", observed),
                    patch.object(
                        Path, "open", side_effect=AssertionError("pre-guard read")
                    ),
                ):
                    with self.assertRaisesRegex(source.LauncherError, "links/reparse"):
                        source.read(path)

    def test_dangling_links_and_stat_errors_are_not_treated_as_absent(self):
        path = Path(tempfile.gettempdir()).resolve() / "dangling-source"
        linked = SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "lstat", return_value=linked),
        ):
            with self.assertRaisesRegex(source.LauncherError, "links/reparse"):
                source.unlinked(path)
        with patch.object(Path, "lstat", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                source.unlinked(path)

    def test_ancestor_is_rechecked_for_next_file_without_cached_grant(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            first, second = root / "a.txt", root / "b.txt"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            changed, original_stat, original_open = [], Path.lstat, Path.open

            def observed(value):
                if changed and value == root:
                    return SimpleNamespace(
                        st_mode=stat.S_IFDIR, st_file_attributes=0x400
                    )
                return original_stat(value)

            def opened(value, *args, **kwargs):
                result = original_open(value, *args, **kwargs)
                if value == first:
                    changed.append(True)
                return result

            with (
                patch.object(Path, "lstat", observed),
                patch.object(Path, "open", opened),
            ):
                with self.assertRaisesRegex(source.LauncherError, "links/reparse"):
                    source.inventory(root)

    def test_duplicates_nonfinite_and_symbolic_inventory_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e1000}'):
            with self.assertRaises((launcher.LauncherError, ValueError)):
                launcher.decode(raw)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "bytes"
            path.write_bytes(b"original")
            self.assertEqual(
                launcher.pinned(path, launcher.digest(b"original")), b"original"
            )
            path.write_bytes(b"changed")
            with self.assertRaises(launcher.LauncherError):
                launcher.pinned(path, launcher.digest(b"original"))

    def test_empty_bibliography_is_inventoried_without_relaxing_input_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "included.bib"
            path.write_bytes(b"")
            other = root / "screening.bib"
            other.write_bytes(b"")
            expected = {
                "included.bib": launcher.digest(b""),
                "screening.bib": launcher.digest(b""),
            }
            self.assertEqual(launcher.inventory(root), expected)
            with self.assertRaises(launcher.LauncherError):
                launcher.read(path)
            with self.assertRaises(launcher.LauncherError):
                launcher.pinned(path, launcher.digest(b""))
            path.write_bytes(b"@article{work1}\n")
            self.assertNotEqual(launcher.inventory(root), expected)
            with self.assertRaises(launcher.LauncherError):
                launcher.read(path, 1, allow_empty=True)
            path.write_bytes(b"")
            path.unlink()
            self.assertNotEqual(launcher.inventory(root), expected)

    def test_raw_loader_rejects_drift_and_never_uses_owned_pyc(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            cli = root / "plugins/auto-research-agent/cli"
            cli.mkdir(parents=True)
            path = cli / "candidate_owned_module.py"
            path.write_bytes(b"VALUE = 42\n")
            loader = launcher.PinnedLoader(
                root,
                {"cli/candidate_owned_module.py": launcher.digest(path.read_bytes())},
            )
            module_spec = loader.find_spec("candidate_owned_module")
            module = importlib.util.module_from_spec(module_spec)
            loader.exec_module(module)
            self.assertEqual(module.VALUE, 42)
            self.assertFalse((cli / "__pycache__").exists())
            path.write_bytes(b"VALUE = 0\n")
            with self.assertRaises(launcher.LauncherError):
                loader.exec_module(module)
            sys.modules[module.__name__] = module
            try:
                with self.assertRaises(launcher.LauncherError):
                    launcher.PinnedLoader(root, {})
            finally:
                del sys.modules[module.__name__]


if __name__ == "__main__":
    unittest.main()
