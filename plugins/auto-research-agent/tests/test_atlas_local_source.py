"""Offline byte/protocol checks only; no real or fake child is launched."""

import importlib.util
from pathlib import Path
from types import ModuleType
import sys
import tempfile
import unittest

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
