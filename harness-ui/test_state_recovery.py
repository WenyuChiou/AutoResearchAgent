"""Exercise the Wiki renderer's state checks in Harness UI CI."""
from pathlib import Path
import shutil
import subprocess
import unittest


class WikiStateRecoveryTests(unittest.TestCase):
    def test_wiki_state_recovery(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the Wiki renderer tests")
        result = subprocess.run(
            [node, str(Path(__file__).with_suffix(".cjs"))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS Stage 1 loop requires a current project and binding", result.stdout)
