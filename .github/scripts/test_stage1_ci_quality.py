"""Regression tests proving the Stage 1 CI quality commands reject bad input."""

from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]


class Stage1CiQualityTests(unittest.TestCase):
    def test_ruff_check_rejects_unused_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unused.py"
            path.write_text("import os\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "--project",
                    str(REPO_ROOT / "scripts"),
                    "ruff",
                    "check",
                    str(path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("F401", result.stdout)

    def test_git_diff_check_rejects_crlf_with_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args, check=True):
                return subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    check=check,
                    capture_output=True,
                    text=True,
                )

            git("init")
            git("config", "user.name", "CI test")
            git("config", "user.email", "ci@example.invalid")
            git("config", "core.autocrlf", "false")
            path = repo / "quality.txt"
            path.write_bytes(b"clean\n")
            git("add", "quality.txt")
            git("commit", "-m", "clean")
            path.write_bytes(b"bad trailing space \r\n")
            result = git("diff", "--check", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trailing whitespace", result.stdout)


if __name__ == "__main__":
    unittest.main()
