"""Run the saved-plan guide projection without research or a network host."""

from pathlib import Path
import shutil
import subprocess
import unittest


class PlanReadingGuideTests(unittest.TestCase):
    def test_saved_plan_guide_projection(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for this interface contract")
        result = subprocess.run(
            [
                node,
                "--test",
                str(Path(__file__).with_name("test_v9_plan_reading_guide.cjs")),
            ],
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
