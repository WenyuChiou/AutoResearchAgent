"""Discoverable owned-app integration check; optional installed browser runtime.

Set ARA_UNIFIED_BROWSER_NODE, ARA_UNIFIED_BROWSER_PLAYWRIGHT and
ARA_UNIFIED_BROWSER_CHROME to run outside the bundled Windows environment.
ARA_UNIFIED_BROWSER_OUTPUT retains the exact receipt and screenshots privately.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class UnifiedProjectBrowserTests(unittest.TestCase):
    def test_saved_projects_switch_inline_without_research_or_mutation(self):
        deps = (
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        )
        paths = {
            "node": Path(
                os.environ.get("ARA_UNIFIED_BROWSER_NODE", deps / "bin/node.exe")
            ),
            "playwright": Path(
                os.environ.get(
                    "ARA_UNIFIED_BROWSER_PLAYWRIGHT", deps / "node_modules/playwright"
                )
            ),
            "chrome": Path(
                os.environ.get(
                    "ARA_UNIFIED_BROWSER_CHROME",
                    "C:/Program Files/Google/Chrome/Application/chrome.exe",
                )
            ),
        }
        if not all(path.exists() for path in paths.values()):
            self.skipTest(
                "installed Chrome and Playwright required; configure ARA_UNIFIED_BROWSER runtime paths"
            )
        repo = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="unified-browser-") as temporary:
            output_root = Path(
                os.environ.get("ARA_UNIFIED_BROWSER_OUTPUT", temporary)
            ).resolve()
            output_root.mkdir(parents=True, exist_ok=True)
            self.assertFalse(
                output_root.is_relative_to(repo), "browser evidence stays outside Git"
            )
            output = output_root / "browser-receipt.json"
            self.assertFalse(output.exists(), "fresh receipt path required")
            run = subprocess.run(
                [
                    str(paths["node"]),
                    str(Path(__file__).parent / "browser/project-unified-test.cjs"),
                    "--repo",
                    str(repo),
                    "--python",
                    sys.executable,
                    "--temp-root",
                    str(Path(tempfile.gettempdir()).resolve()),
                    "--output",
                    str(output),
                    "--playwright",
                    str(paths["playwright"]),
                    "--chrome",
                    str(paths["chrome"]),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=240,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {}
                ),
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(receipt["passed"], receipt["failure"])
            self.assertEqual(receipt["post_count"], 0)
            self.assertTrue(receipt["fixture_final"]["readonly_sqlite_and_ledger"])
            self.assertGreaterEqual(len(receipt["checks"]), 8)


if __name__ == "__main__":
    unittest.main()
