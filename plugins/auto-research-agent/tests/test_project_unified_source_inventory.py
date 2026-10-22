"""Lazy imports keep their original source pins; changed bytes still fail."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import project_unified_browser_fixture as fixture


class UnifiedSourceInventoryTests(unittest.TestCase):
    def test_lazy_import_uses_existing_pin_and_bytecode_is_not_source(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            plugin = repo / "plugins/auto-research-agent"
            cli = plugin / "cli"
            cli.mkdir(parents=True)
            eager, lazy = cli / "eager.py", cli / "lazy.py"
            eager.write_bytes(b"eager")
            lazy.write_bytes(b"lazy")
            harness = plugin / "tests/browser"
            harness.mkdir(parents=True)
            script = harness / "fixture.py"
            for p in (
                script,
                harness / "project-unified-test.cjs",
                plugin / "tests/test_project_unified_browser.py",
            ):
                p.write_bytes(b"test fixture")
            loaded = {str(eager): fixture.digest(eager.read_bytes())}
            host = SimpleNamespace(host_binding={"served_files": {}})
            with patch.object(fixture, "__file__", str(script)):
                initial = fixture.source_inventory(repo, loaded, host)
                loaded[str(lazy)] = fixture.digest(lazy.read_bytes())
                bytecode = cli / "__pycache__"
                bytecode.mkdir()
                (bytecode / "lazy.pyc").write_bytes(b"cache")
                self.assertEqual(fixture.source_inventory(repo, loaded, host), initial)
                lazy.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "source changed"):
                    fixture.source_inventory(repo, loaded, host)
                lazy.write_bytes(b"lazy")
                (cli / "new.py").write_bytes(b"new source")
                self.assertNotEqual(
                    fixture.source_inventory(repo, loaded, host), initial
                )


if __name__ == "__main__":
    unittest.main()
