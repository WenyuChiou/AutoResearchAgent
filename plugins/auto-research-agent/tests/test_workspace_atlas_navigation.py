"""Exact navigation cases exercise records, not research or native calls."""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace.atlas_model import model_asset  # noqa: E402


class AtlasNavigationTests(unittest.TestCase):
    def test_status_badge_meets_normal_text_contrast(self):
        css = (PLUGIN / "references/research-workspace/atlas/atlas.css").read_text(
            encoding="utf-8"
        )
        rule = re.search(r"#atlas-status\s*\{([^}]+)\}", css)
        self.assertIsNotNone(rule)
        foreground = re.search(r"color:\s*(#[0-9a-fA-F]{6})", rule.group(1)).group(1)
        background = re.search(r"background:\s*(#[0-9a-fA-F]{6})", rule.group(1)).group(
            1
        )

        def luminance(color):
            channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
            channels = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

        light, dark = sorted(
            (luminance(foreground), luminance(background)), reverse=True
        )
        self.assertGreaterEqual((light + 0.05) / (dark + 0.05), 4.5)

    def test_phone_navigation_is_single_row_and_scrollable(self):
        css = (PLUGIN / "references/research-workspace/atlas/atlas.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            ".atlas-sidebar nav, .atlas-workspace-nav { display: flex !important; grid-template-columns: none !important; gap: 6px; overflow-x: auto;",
            css,
        )
        self.assertIn(
            ".atlas-sidebar nav > *, .atlas-workspace-nav > * { flex: 0 0 auto; }",
            css,
        )
        self.assertIn(
            ".atlas-tabs, .atlas-network-actions, .atlas-spatial-controls { flex-wrap: nowrap;",
            css,
        )
        self.assertNotIn("#atlas-content > .atlas-network-split { order:", css)
        self.assertNotIn(".atlas-spatial-host { order:", css)
        self.assertIn(".atlas-topbar-controls { flex-wrap: nowrap;", css)
        self.assertIn(
            "@media (max-width: 700px) { .atlas-spatial-host { height: 420px; } }", css
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_initial_language_and_host_panel_stay_synchronized(self):
        result = subprocess.run(
            [
                shutil.which("node"),
                str(PLUGIN / "tests/test_workspace_atlas_language.js"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "assertions passed; synthetic DOM and inert host only", result.stdout
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_navigation_preserves_versions_and_all_screened_records(self):
        self.assertEqual(
            model_asset(),
            (
                PLUGIN / "references/research-workspace/atlas/atlas-model.js"
            ).read_bytes(),
        )
        result = subprocess.run(
            [shutil.which("node"), str(PLUGIN / "tests/test_workspace_atlas_model.js")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("synthetic records only", result.stdout)


if __name__ == "__main__":
    unittest.main()
