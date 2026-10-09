"""Fake DOM and saved SQLite-view fixture; no browser/native/model calls."""

from pathlib import Path
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


class NativeAtlasChatTests(unittest.TestCase):
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
        self.assertIn("PASS 9 tests; actual fixture plus DOM substitute", result.stdout)


if __name__ == "__main__":
    unittest.main()
