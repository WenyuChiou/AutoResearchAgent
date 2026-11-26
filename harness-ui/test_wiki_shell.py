"""Shared Wiki shell presentation checks; no research or external providers."""
from pathlib import Path
import shutil
import subprocess
import unittest


class WikiShellTests(unittest.TestCase):
    def test_shared_shell(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for Wiki shell checks')
        run = subprocess.run([node, str(Path(__file__).with_suffix('.cjs'))],
                             capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('PASS Wiki shell:', run.stdout)
