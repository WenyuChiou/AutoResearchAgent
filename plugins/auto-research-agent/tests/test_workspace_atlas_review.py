"""Synthetic review/provenance DOM contracts; no server or native execution."""

from pathlib import Path
import shutil
import subprocess
import unittest


PLUGIN = Path(__file__).resolve().parents[1]


class WorkspaceAtlasReviewTests(unittest.TestCase):
    def test_stage_review_and_recorded_provenance_preserve_source_authority(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for atlas DOM contracts")
        result = subprocess.run(
            [node, str(PLUGIN / "tests" / "test_workspace_atlas_review.js")],
            cwd=PLUGIN,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Atlas review DOM regression:", result.stdout)


if __name__ == "__main__":
    unittest.main()
