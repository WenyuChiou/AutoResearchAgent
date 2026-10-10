"""Fake DOM and saved SQLite-view fixture; no browser/native/model calls."""

from pathlib import Path
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


class NativeAtlasChatTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_connection_and_reply_labels_require_saved_observations(self):
        result = subprocess.run(
            [
                shutil.which("node"),
                str(PLUGIN / "tests/test-native-status-labels.cjs"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "PASS 30 status cases; actual scripts + DOM fixture", result.stdout
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_drawer_refresh_and_bounded_detail_scroll_contract(self):
        result = subprocess.run(
            [
                shutil.which("node"),
                str(PLUGIN / "tests/test-native-atlas-drawer.cjs"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "PASS 4 tests; actual scripts plus DOM/CSS contract", result.stdout
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_typed_transcript_and_history_have_no_automatic_resend(self):
        result = subprocess.run(
            [
                shutil.which("node"),
                str(PLUGIN / "tests/test-native-atlas-chat.cjs"),
                str(PLUGIN / "cli/research_workspace_native/web"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "PASS 23 tests; actual fixture plus DOM substitute", result.stdout
        )


if __name__ == "__main__":
    unittest.main()
