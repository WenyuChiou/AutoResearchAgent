"""A clean CODEX_HOME is not sufficient to disable personal skills."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live.profile import prepare_profile  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_fresh_profile_enables_sandbox_preserves_bundled_and_cannot_claim_ready(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "skills.json"
            source.write_text(
                json.dumps(
                    {
                        "result": {
                            "data": [
                                {
                                    "errors": [],
                                    "skills": [
                                        {
                                            "path": "C:/personal/SKILL.md",
                                            "scope": "user",
                                            "enabled": True,
                                        },
                                        {
                                            "path": "C:/bundled/SKILL.md",
                                            "scope": "system",
                                            "enabled": True,
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            report = prepare_profile(root / "fresh", source, sha, platform="win32")
            config = tomllib.loads(
                (root / "fresh/config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(config["windows"]["sandbox"], "unelevated")
            self.assertEqual(
                config["skills"]["config"],
                [{"path": "C:/personal/SKILL.md", "enabled": False}],
            )
            self.assertFalse(report["runtime_gate"])
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                prepare_profile(root / "fresh", source, sha)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                prepare_profile(root / "other", source, "0" * 64)

    def test_discovery_failure_does_not_create_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "skills.json"
            source.write_text(
                '{"data":[{"errors":["unreadable"],"skills":[]}]}', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "incomplete"):
                prepare_profile(
                    root / "fresh",
                    source,
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                )
            self.assertFalse((root / "fresh").exists())


if __name__ == "__main__":
    unittest.main()
