"""Execute the synthetic three-language Stage2 entry contract in CI."""

from pathlib import Path
import shutil
import subprocess
import unittest


class Stage2SelectionEntryTests(unittest.TestCase):
    def test_current_project_navigation_and_stale_refusal(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; this invariant did not run")
        root = Path(__file__).resolve().parent
        result = subprocess.run(
            [
                node,
                str(root / "test_project_stage2_selection_entry.cjs"),
                str(
                    root.parent / "cli/research_workspace_native/web/projects-stages.js"
                ),
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
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Three-language current-project navigation", result.stdout)

    def test_delayed_responses_keep_original_project_binding(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; this invariant did not run")
        root = Path(__file__).resolve().parent
        result = subprocess.run(
            [
                node,
                str(root / "test_project_stage2_selection_requests.cjs"),
                str(
                    root.parent
                    / "cli/research_workspace_native/web/project-stage2-selection.js"
                ),
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
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "Delayed success/error and captured-project submission PASS", result.stdout
        )

    def test_save_and_start_keeps_existing_transaction_boundaries(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; this invariant did not run")
        root = Path(__file__).resolve().parent
        result = subprocess.run(
            [
                node,
                str(root / "test_project_stage2_selection_oneclick.cjs"),
                str(
                    root.parent
                    / "cli/research_workspace_native/web/project-stage2-selection.js"
                ),
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
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"cases":14', result.stdout)


if __name__ == "__main__":
    unittest.main()
