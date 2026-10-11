"""Explicit rendered Atlas navigation check over an isolated synthetic export."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
CHECKOUT = PLUGIN.parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.view import write_workspace  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402


class AtlasRenderedNavigationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("ATLAS_RENDERED_CHECK") == "1",
        "set ATLAS_RENDERED_CHECK=1 to run the opt-in browser check; "
        "ordinary CI does not launch a browser",
    )
    def test_saved_synthetic_export_navigation(self):
        node = os.environ.get("ATLAS_NODE_EXECUTABLE") or shutil.which("node")
        self.assertIsNotNone(
            node,
            "ATLAS_RENDERED_CHECK=1 requires Node.js on PATH or ATLAS_NODE_EXECUTABLE",
        )
        node = Path(node).resolve()
        self.assertTrue(node.is_file(), f"Node.js executable does not exist: {node}")
        driver = PLUGIN / "tests/test_workspace_atlas_browser.js"
        self.assertTrue(driver.is_file(), f"rendered Atlas driver is missing: {driver}")

        environment = os.environ.copy()
        browser = environment.get("ATLAS_BROWSER_EXECUTABLE")
        if browser:
            self.assertTrue(
                Path(browser).is_file(),
                f"ATLAS_BROWSER_EXECUTABLE does not exist: {browser}",
            )
        probe = subprocess.run(
            [str(node), "-e", "require.resolve('playwright')"],
            cwd=PLUGIN,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            probe.returncode,
            0,
            "ATLAS_RENDERED_CHECK=1 requires the Playwright Node module; "
            "set NODE_PATH to an installed module tree\n" + probe.stdout + probe.stderr,
        )

        with tempfile.TemporaryDirectory(prefix="atlas-rendered-") as directory:
            root = Path(directory).resolve()
            self.assertFalse(
                root.is_relative_to(CHECKOUT),
                f"synthetic browser export must be outside the checkout: {root}",
            )
            site = root / "atlas"
            reference = PLUGIN / "references/research-workspace"
            with patch("research_workspace.view.private_output", side_effect=Path):
                receipt = write_workspace(fixture_index(), reference, site, atlas=True)
            self.assertIn("atlas.html", receipt["files"])
            self.assertTrue(
                (site / "atlas.html").is_file(),
                f"synthetic Atlas export was not created: {site}",
            )

            environment.update(
                {
                    "ATLAS_SITE_ROOT": str(site),
                    "ATLAS_HEADLESS": "1",
                }
            )
            result = subprocess.run(
                [str(node), str(driver)],
                cwd=PLUGIN,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, "rendered Atlas driver returned no result")
        report = json.loads(lines[-1])
        self.assertEqual(report["status"], "PASS")
        self.assertEqual([row["width"] for row in report["results"]], [1440, 768, 390])
        self.assertEqual(
            [len(row["navigation"]) for row in report["results"]], [2, 2, 2]
        )


if __name__ == "__main__":
    unittest.main()
