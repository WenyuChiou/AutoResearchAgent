"""Regression tests proving the Stage 1 CI quality commands reject bad input."""

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class Stage1CiQualityTests(unittest.TestCase):
    def test_metadata_cannot_replace_source_contract_statuses(self):
        workflows = REPO_ROOT / ".github/workflows"
        source = yaml.load(
            (workflows / "stage1-plugin.yml").read_text(), Loader=yaml.BaseLoader
        )
        metadata = yaml.load(
            (workflows / "research-pr-metadata.yml").read_text(), Loader=yaml.BaseLoader
        )
        self.assertEqual(
            source["on"]["pull_request"]["types"], ["opened", "synchronize", "reopened"]
        )
        self.assertEqual(
            metadata["on"]["pull_request"]["types"],
            ["opened", "synchronize", "reopened", "edited", "ready_for_review"],
        )
        self.assertEqual(set(metadata["jobs"]), {"pr-contract"})
        self.assertNotIn("pr-contract", source["jobs"])
        job = source["jobs"]["contracts"]
        self.assertEqual(
            job["strategy"]["matrix"]["os"],
            ["ubuntu-latest", "windows-latest", "macos-latest"],
        )
        self.assertEqual(job["needs"], "scope")
        self.assertEqual(job["if"], "${{ always() }}")
        self.assertEqual(source["permissions"], metadata["permissions"])
        self.assertEqual(
            source["concurrency"]["cancel-in-progress"],
            "${{ github.event_name == 'pull_request' }}",
        )

    def test_required_platform_guard_rejects_selector_failure_and_unknown_plan(self):
        path = REPO_ROOT / ".github/workflows/stage1-plugin.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        command = shlex.split(workflow["jobs"]["contracts"]["steps"][0]["run"])
        self.assertEqual(command[:2], ["python", "-c"])
        for result, scope, expected in [
            ("success", "docs", 0),
            ("success", "ui", 0),
            ("success", "full", 0),
            ("failure", "docs", 1),
            ("cancelled", "full", 1),
            ("skipped", "ui", 1),
            ("success", "", 1),
            ("success", "unknown", 1),
        ]:
            with self.subTest(result=result, scope=scope):
                process = subprocess.run(
                    [sys.executable, *command[1:]],
                    env={
                        **os.environ,
                        "SCOPE_RESULT": result,
                        "PLUGIN_TEST_SCOPE": scope,
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(process.returncode, expected, process.stderr)

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
