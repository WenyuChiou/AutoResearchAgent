"""Exact navigation cases exercise records, not research or native calls."""

from pathlib import Path
import shutil
import subprocess
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace.atlas_model import model_asset  # noqa: E402


class AtlasNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_initial_language_and_later_stages_stay_synchronized(self):
        result = subprocess.run(
            [
                shutil.which("node"),
                str(PLUGIN / "tests/test_workspace_atlas_language.js"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("assertions passed; synthetic DOM only", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_navigation_preserves_versions_and_all_screened_records(self):
        self.assertEqual(
            model_asset(),
            (
                PLUGIN / "references/research-workspace/atlas/atlas-model.js"
            ).read_bytes(),
        )
        result = subprocess.run(
            [shutil.which("node"), str(PLUGIN / "tests/test_workspace_atlas_model.js")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("synthetic records only", result.stdout)


if __name__ == "__main__":
    unittest.main()
