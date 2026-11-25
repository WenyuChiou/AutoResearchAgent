"""Run the bounded startup controller regression in the normal UI CI discovery."""

import os
from pathlib import Path
import subprocess
import unittest

from build_v7 import snapshot


class StartupRecoveryTests(unittest.TestCase):
    def test_bounded_read_only_recovery(self):
        subprocess.run(
            [
                os.environ.get("NODE_BINARY", "node"),
                str(Path(__file__).with_suffix(".cjs")),
            ],
            check=True,
        )

    def test_normal_snapshot_contains_fallback_and_recovery_asset(self):
        assets, manifest = snapshot(Path(__file__).resolve().parents[1])
        self.assertIn("startup-recovery.js", manifest["source_sha256"])
        self.assertEqual(assets["/"], assets["/index.html"])
        self.assertIn(b'id="wiki-startup-recovery"', assets["/"])
        self.assertIn(b'id="wiki-startup-retry"', assets["/"])
        self.assertIn(b'<script src="/startup-recovery.js"></script>', assets["/"])
        self.assertIn(b"wiki-startup-retry-v1", assets["/startup-recovery.js"])


if __name__ == "__main__":
    unittest.main()
