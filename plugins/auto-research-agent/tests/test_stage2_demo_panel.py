"""Synthetic DOM contract for the optional repository Stage 2 demo panel."""

from pathlib import Path
import shutil
import subprocess
import unittest


class Stage2DemoPanelTests(unittest.TestCase):
    def test_fixed_once_action_and_read_only_recovery(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable; synthetic DOM test did not run")
        root = Path(__file__).resolve().parent
        script = root / "test_stage2_demo_panel.cjs"
        source = (
            root.parent / "references/research-workspace/examples/stage2-demo-panel.js"
        )
        if not source.exists():
            source = root / "stage2-demo-panel.js"
        result = subprocess.run(
            [node, str(script), str(source)],
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
        self.assertIn("translation PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
