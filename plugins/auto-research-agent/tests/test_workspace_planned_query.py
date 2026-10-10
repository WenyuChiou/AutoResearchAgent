"""Run the synthetic DOM contract without starting a service or browser."""

import atlas_test_paths  # noqa: F401
from pathlib import Path
import shutil
import subprocess
import unittest


class WorkspacePlannedQueryPanelTests(unittest.TestCase):
    def test_intent_history_binding_and_visible_query_controls(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable")
        result = subprocess.run(
            [node, str(Path(__file__).with_name("test-workspace-planned-query.cjs"))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            shell=False,
        )
        self.assertEqual(
            result.returncode, 0, result.stdout.decode("utf8", errors="replace")
        )
        self.assertIn("PASS 27", result.stdout.decode("utf8"))
