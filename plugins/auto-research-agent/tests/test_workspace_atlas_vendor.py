"""Offline vendored byte inventory; no renderer, network or model invocation."""

import hashlib
import json
from pathlib import Path
import unittest


class AtlasVendorTests(unittest.TestCase):
    def test_declared_bundled_bytes_and_license_notices_match(self):
        root = Path(__file__).parents[1] / "references/research-workspace/atlas"
        lock = json.loads((root / "vendor/vendor-lock.json").read_bytes())
        self.assertFalse(lock["verification"]["npm_lifecycle_executed"])
        for package in lock["packages"]:
            for name, expected in package["files"].items():
                raw = (root / name).read_bytes()
                self.assertEqual(len(raw), expected["bytes"], name)
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(), expected["sha256"], name
                )
        notices = (root / "vendor/THIRD_PARTY_LICENSES.txt").read_bytes()
        self.assertIn(b"MIT", notices)
        self.assertFalse(notices.endswith(b"\n\n"))


if __name__ == "__main__":
    unittest.main()
