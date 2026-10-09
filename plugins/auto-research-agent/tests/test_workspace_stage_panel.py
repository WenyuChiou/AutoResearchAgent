"""Synthetic DOM contract for the saved-stage panel; not browser/native execution."""

from pathlib import Path
import shutil
import subprocess
import unittest


class StagePanelTests(unittest.TestCase):
    def test_source_bound_recovery_and_explicit_review(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable; synthetic DOM test did not run")
        root = Path(__file__).resolve().parent
        script = root / "test_workspace_stage_panel.cjs"
        source = root.parent / "cli/research_workspace_native/web/stage-panel.js"
        result = subprocess.run(
            [node, str(script), str(source)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("remount PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
