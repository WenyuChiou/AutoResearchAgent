"""Before-pin and unfinished-worker regressions for the public fake-only example."""

from contextlib import ExitStack
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
EXAMPLE = "references/research-workspace/examples/build-planned-query-fixture.py"
sys.path.insert(0, str(PLUGIN / "cli"))
from research_workspace_native.planned_queries import PlannedQueryService  # noqa: E402


def snapshot(root):
    repo, plugin = root / "repo", root / "repo/plugins/auto-research-agent"
    plugin.mkdir(parents=True)
    for name in ("cli", "schemas", "tests", "evals", "references/research-workspace"):
        shutil.copytree(
            PLUGIN / name,
            plugin / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".ruff_cache"),
        )
    for args in (
        ("init", "-q"),
        ("add", "--", "plugins/auto-research-agent"),
        ("commit", "-qm", "Test-owned example source"),
    ):
        git(repo, *args)
    return repo, plugin


def git(repo, *args):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Fixture test",
            "-c",
            "user.email=fixture@invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=60,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


def example_module():
    path = PLUGIN / EXAMPLE
    module = ModuleType("example_fixture_safety")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


class PlannedQueryFixtureSafetyTests(unittest.TestCase):
    def test_helper_assume_unchanged_and_hardlink_refused_before_execution(self):
        with tempfile.TemporaryDirectory(prefix="query-bootstrap-") as folder:
            root = Path(folder).resolve()
            repo, plugin = snapshot(root)
            helper = plugin / "cli/research_workspace_native/atlas_local_source.py"
            relative = helper.relative_to(repo).as_posix()
            original = helper.read_bytes()
            marker = root / "executed-helper"
            git(repo, "update-index", "--assume-unchanged", "--", relative)
            helper.write_bytes(
                original
                + f"\nfrom pathlib import Path\nPath({str(marker)!r}).write_bytes(b'bad-before-pin')\n".encode()
            )
            self.assertEqual(git(repo, "status", "--porcelain"), b"")

            def run():
                return subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-X",
                        "utf8",
                        str(plugin / EXAMPLE),
                        "--output",
                        str(root / "output"),
                    ],
                    cwd=repo,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    timeout=60,
                )

            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                b"helper physical/Git bytes differ before execution", result.stderr
            )
            self.assertFalse(marker.exists())
            self.assertFalse((root / "output").exists())
            helper.write_bytes(original)
            os.link(helper, root / "helper-hardlink")
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"source hardlink refused", result.stderr)
            self.assertFalse(marker.exists())

    def test_unfinished_real_service_close_keeps_injected_child_until_worker_stops(
        self,
    ):
        module = example_module()
        called, release, started = [], threading.Event(), threading.Event()

        def original():
            called.append("unpatched")

        channel = SimpleNamespace(Popen=original)
        boundary = ExitStack()
        boundary.enter_context(
            patch.object(channel, "Popen", lambda: called.append("injected"))
        )

        def work():
            started.set()
            release.wait(20)
            channel.Popen()

        worker = threading.Thread(target=work, daemon=True)
        query = object.__new__(PlannedQueryService)
        query._lock, query._closing, query._closed = threading.RLock(), False, False
        query._workers, query._projects = {"case": worker}, {}
        query.store = query.ledger_owners = SimpleNamespace(close=lambda: None)
        query.store.path = None
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            errors = module.close_fixture(None, None, None, query, boundary)
            self.assertTrue(errors)
            self.assertTrue(query._closing)
            self.assertFalse(query._closed)
            self.assertIsNot(channel.Popen, original)
            release.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(called, ["injected"])
            self.assertEqual(
                module.close_fixture(None, None, None, query, boundary), []
            )
            self.assertTrue(query._closed)
            self.assertIs(channel.Popen, original)
        finally:
            release.set()
            worker.join(3)
            if not worker.is_alive():
                boundary.close()

    def test_observation_failure_records_completion_without_masking_primary(self):
        module = example_module()
        receipt = dict(
            status="failed", failure_type="PrimaryFailure", failure="original"
        )

        def unobserved(_claim):
            raise ValueError("source-changed")

        with tempfile.TemporaryDirectory(prefix="query-finish-") as folder:
            output, errors = Path(folder), []
            with patch.object(
                module, "git", side_effect=RuntimeError("head-unobserved")
            ):
                module.finish_receipt(
                    output, receipt, unobserved, {}, output, "head", errors
                )
            saved = json.loads((output / "completion-receipt.json").read_bytes())
            self.assertEqual(saved["failure"], "original")
            self.assertEqual(saved["failure_type"], "PrimaryFailure")
            self.assertFalse(saved["source_manifest_unchanged"])
            self.assertFalse(saved["head_unchanged"])
            self.assertEqual(len(saved["cleanup_errors"]), 2)
            changed = output / "changed"
            changed.mkdir()
            errors = []
            clean_receipt = dict(status="completed-fixture-lifecycle")
            with patch.object(module, "git", return_value=b"different-head"):
                module.finish_receipt(
                    changed,
                    clean_receipt,
                    lambda _: {"different": True},
                    {},
                    output,
                    "head",
                    errors,
                )
            saved = json.loads((changed / "completion-receipt.json").read_bytes())
            self.assertEqual(saved["status"], "failed")
            self.assertFalse(saved["source_manifest_unchanged"])
            self.assertFalse(saved["head_unchanged"])
            self.assertEqual(len(saved["cleanup_errors"]), 2)
            with self.assertRaises(FileExistsError):
                module.save(output / "completion-receipt.json", {})


if __name__ == "__main__":
    unittest.main()
