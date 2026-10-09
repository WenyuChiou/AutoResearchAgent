"""Presentation and exact recovery notices; no browser/native/model calls."""

from pathlib import Path
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


class NativeReadableTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_content_first_and_exact_saved_notice_keep_unknown_intents(self):
        result = subprocess.run(
            [shutil.which("node"), str(PLUGIN / "tests/test-native-readable.cjs")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS 4 tests; actual scripts with DOM substitute", result.stdout)


if __name__ == "__main__":
    unittest.main()
