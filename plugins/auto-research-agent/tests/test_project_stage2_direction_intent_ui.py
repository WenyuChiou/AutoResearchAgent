"""Run deterministic tentative-direction UI checks without network or models."""

from pathlib import Path
import shutil
import subprocess
import unittest


class Stage2DirectionIntentUITests(unittest.TestCase):
    def test_tentative_preference_and_guarded_planning_start(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; this invariant did not run")
        root = Path(__file__).resolve().parent
        web = root.parent / "cli/research_workspace_native/web"
        result = subprocess.run(
            [
                node,
                str(root / "test_project_stage2_direction_intent.cjs"),
                str(web / "project-stage2-selection.js"),
                str(web / "project-stage2-selection.html"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=25,
            check=False,
            shell=False,
        )
        print(result.stdout, end="")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"kind":"synthetic-direction-intent-ui"', result.stdout)
        self.assertIn('"cases":20,"failures":0', result.stdout)


if __name__ == "__main__":
    unittest.main()
