"""Exercise the scoped Stage 2 UI with deterministic authored data."""

from pathlib import Path
import shutil
import subprocess
import unittest


class EmbeddedSelectionTests(unittest.TestCase):
    def test_scoped_mount_is_version_bound_and_preserves_pending_keys(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for selection UI tests")
        script = Path(__file__).with_suffix(".cjs")
        result = subprocess.run(
            [node, "--test", str(script)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
            shell=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("fail 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
