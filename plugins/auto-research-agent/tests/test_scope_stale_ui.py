"""Scope native-event interleave, exact refusal recovery and explicit retry UI."""

from pathlib import Path
import shutil
import subprocess
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


class ScopeStaleUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_exact_refusal_unlocks_only_explicit_new_action(self):
        result = subprocess.run(
            [shutil.which("node"), str(PLUGIN / "tests/test-scope-stale.cjs")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS 12 scope stale DOM tests", result.stdout)


if __name__ == "__main__":
    unittest.main()
