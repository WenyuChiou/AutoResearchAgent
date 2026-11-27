"""The Wiki entry must refuse a command-line Stage 1 run request, never ignore it."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "plugins" / "auto-research-agent"
sys.path[:0] = [str(HERE), str(PLUGIN / "cli"), str(PLUGIN / "tests")]

import run_v7

PIN = "a" * 64


class RunRequestRefusalTests(unittest.TestCase):
    def setUp(self):
        # Private data must stay outside any Git checkout, like the real entry requires.
        path = self.enterContext(tempfile.TemporaryDirectory(prefix="rv7-"))
        self.tmp = Path(path).resolve()
        self.limits = self.tmp / "limits.json"
        self.limits.write_text(
            json.dumps(
                dict(model_calls=0, seconds=0, search_calls=0, source_reads=0, rounds=0)
            ),
            encoding="utf-8",
            newline="",
        )
        self.request = self.tmp / "request.json"
        self.request.write_text("{}", encoding="utf-8", newline="")
        self.projects = self.tmp / "projects"
        self.base = [
            "--repo",
            str(REPO),
            "--source-helper-sha256",
            PIN,
            "--projects-root",
            str(self.projects),
            "--run-limits",
            str(self.limits),
        ]

    def assert_refusal_text(self, message):
        self.assertIn("progression API", message)
        self.assertIn("old launcher", message)
        self.assertIn("--stage1-run-request", message)

    def test_request_and_sha_are_refused_before_any_work(self):
        for extra in (
            ["--stage1-run-request", str(self.request)],
            ["--stage1-run-request-sha256", PIN],
            [
                "--stage1-run-request",
                str(self.request),
                "--stage1-run-request-sha256",
                PIN,
            ],
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError) as caught:
                    run_v7.main(self.base + extra)
                self.assert_refusal_text(str(caught.exception))
        self.assertFalse(self.projects.exists())

    def test_run_v9_exits_with_the_clear_error_and_creates_nothing(self):
        state, incoming = self.tmp / "state", self.tmp / "incoming"
        state.mkdir()
        incoming.mkdir()
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(HERE), str(PLUGIN / "cli"), str(PLUGIN / "tests")]
        )
        result = subprocess.run(
            [
                sys.executable,
                str(HERE / "run_v9.py"),
                "--ui-state-root",
                str(state),
                "--incoming-root",
                str(incoming),
                *self.base,
                "--stage1-run-request",
                str(self.request),
                "--stage1-run-request-sha256",
                PIN,
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tmp,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assert_refusal_text(result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertFalse(self.projects.exists())


if __name__ == "__main__":
    unittest.main()
