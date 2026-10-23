"""Run the actual presentation source in a bounded authored DOM."""

from pathlib import Path
import shutil
import subprocess
import unittest


class SavedStage1BrowserTests(unittest.TestCase):
    def test_saved_reference_selection_is_readonly_and_preserves_reader_state(self):
        node = shutil.which("node")
        self.assertIsNotNone(
            node, "Node is required for the saved-reference DOM checks"
        )
        result = subprocess.run(
            [node, str(Path(__file__).with_suffix(".cjs"))],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("project saved Stage1 view VM checks: passed", result.stdout)
