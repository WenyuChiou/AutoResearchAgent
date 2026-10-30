"""Run the Wiki bridge and planning-diagram DOM tests in the normal UI CI."""

from pathlib import Path
import shutil
import subprocess
import unittest


class WikiStage3DiagramTests(unittest.TestCase):
    def test_wiki_and_saved_plan_diagram(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the Wiki diagram contract")
        here = Path(__file__).resolve().parent
        tests = here.parent / "plugins/auto-research-agent/tests/browser"
        result = subprocess.run(
            [
                node,
                "--test",
                str(here / "test_v9_stage3_bridge.cjs"),
                str(here / "test_v9_selection_integration.cjs"),
                str(tests / "project-stage3-research-diagram.cjs"),
                str(tests / "project-stage3-wiki.cjs"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            shell=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("fail 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
