"""Run original project UI guards in Node with synthetic DOM/channel fixtures."""

from pathlib import Path
import shutil
import subprocess
import unittest


PLUGIN = Path(__file__).resolve().parents[1]


class ProjectBrowserGuardTests(unittest.TestCase):
    def run_guard(self, filename):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node required for actual project UI guard checks")
        result = subprocess.run(
            [node, str(PLUGIN / "tests/browser" / filename)],
            cwd=PLUGIN,
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout + result.stderr, end="")

    def test_reading_panel_guards(self):
        self.run_guard("project-reading-panel-test.cjs")

    def test_atlas_channel_guards(self):
        self.run_guard("project-atlas-channel-test.cjs")

    def test_expansion_guards(self):
        self.run_guard("project-expansions-test.cjs")


if __name__ == "__main__":
    unittest.main()
