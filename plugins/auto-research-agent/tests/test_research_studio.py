"""Synthetic subprocess integration only; never calls Codex or research providers."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_studio.runtime import Engine, fingerprint, validate_request  # noqa: E402
from research_studio.store import Store, StudioError, safe_path  # noqa: E402

TOKEN = "synthetic-private-owner-token-123456789"


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.plugin = self.root / "repo"
        self.plugin.mkdir()
        for name in ("cli", "skills", "references", "schemas", "gates", "validators"):
            (self.plugin / name).mkdir()
            (self.plugin / name / "fixture.txt").write_text(
                "synthetic", encoding="utf-8"
            )
        (self.plugin / "plugin.json").write_text("{}", encoding="utf-8")
        (self.plugin / "requirements-test.txt").write_text("", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "synthetic",
        )
        self.head = self.git("rev-parse", "HEAD").strip()
        self.store = Store(self.root / "data")
        self.home = self.root / "profile"
        self.home.mkdir()
        self.binary = Path(sys.executable).resolve()
        self.engine = Engine(
            self.store, self.binary, self.home, self.head, TOKEN, plugin=self.plugin
        )
        self.identity = fingerprint(
            self.plugin, self.binary, self.head, self.engine.env
        )
        self.probe = patch.object(self.engine, "preflight", return_value=self.identity)
        self.probe.start()
        self.addCleanup(self.probe.stop)
        supervision = patch.object(self.engine.supervisor, "cleanup")
        supervision.start()
        self.addCleanup(supervision.stop)
        if os.name == "nt":

            def terminate_fixture(process):
                process.kill()
                process.wait(timeout=10)

            # Windows is not an enabled execution host; kill only our synthetic child.
            cleanup = patch.object(self.engine, "kill", side_effect=terminate_fixture)
            cleanup.start()
            self.addCleanup(cleanup.stop)

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.plugin), *args], stderr=subprocess.DEVNULL
        ).decode()

    def tearDown(self):
        if self.engine.active:
            self.engine.stop(self.engine.active)
            self.engine.thread.join(15)
        self.store.close()
        self.temporary.cleanup()

    def request(self):
        return {
            "request_id": str(uuid.uuid4()),
            "topic": "Synthetic fixture",
            "scope": "No geographic restriction",
            "scope_confirmed": True,
            "stage": 1,
            "timeout_seconds": 60,
        }

    def run_fixture(self, request=None, extra="", wait=True):
        request = request or self.request()
        code = (
            "import pathlib,sys,time; sys.stdin.read(); pathlib.Path('final.md').write_text('synthetic only'); "
            + extra
        )
        with patch.object(
            self.engine, "command", return_value=[sys.executable, "-c", code]
        ) as command:
            result = self.engine.submit(request)
            for _ in range(100):
                if command.called:
                    break
                time.sleep(0.01)
            if wait:
                self.engine.thread.join(15)
                self.assertFalse(self.engine.thread.is_alive())
        return self.store.get(result["id"])

    def test_resume_no_reexecution(self):
        request = self.request()
        result = self.run_fixture(request, "print('fixture event')")
        self.assertEqual(result["status"], "human-review")
        with patch.object(
            self.engine, "command", side_effect=AssertionError("re-execution")
        ):
            self.assertEqual(self.engine.submit(request), result)
        request["topic"] = "changed"
        with self.assertRaisesRegex(StudioError, "different input"):
            self.engine.submit(request)
        self.store.close()
        self.store = Store(self.root / "data")
        self.assertEqual(self.store.get(result["id"]), result)

    def test_runtime_bytes_bound(self):
        fixture = self.plugin / "skills/fixture.txt"
        result = self.run_fixture(
            extra=f"pathlib.Path({str(fixture)!r}).write_text('changed')"
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("dirty", result["error"])
        self.assertEqual(result["manifest"]["runtime"], self.identity)
        self.assertEqual(result["manifest"]["artifacts"][0]["path"], "final.md")

    def test_dependency_sha_bound(self):
        with self.assertRaisesRegex(StudioError, "revision differs"):
            fingerprint(self.plugin, self.binary, "0" * 40, self.engine.env)
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "new revision",
        )
        self.assertNotEqual(self.git("rev-parse", "HEAD").strip(), self.head)
        with self.assertRaisesRegex(StudioError, "revision differs"):
            fingerprint(self.plugin, self.binary, self.head, self.engine.env)

    def test_artifact_tamper_and_secret_environment(self):
        result = self.run_fixture(
            extra="sys.stdout.buffer.write(('x' * 8191 + '中文' * 5000).encode()); sys.stdout.flush(); "
            f"sys.stdout.write({TOKEN[:10]!r}); sys.stdout.flush(); time.sleep(0.8); "
            f"sys.stdout.write({TOKEN[10:]!r}); sys.stdout.flush()"
        )
        item = result["manifest"]["artifacts"][0]
        self.assertEqual(
            self.engine.artifact(result["id"], item["id"]), b"synthetic only"
        )
        text = "".join(
            e["text"]
            for e in self.store.detail(result["id"], 0)["events"]
            if e["type"] == "stdout"
        )
        self.assertEqual(text, "x" * 8191 + "中文" * 5000 + "[redacted]")
        self.assertNotIn(TOKEN, str(self.engine.env))
        path = self.root / f"data/runs/{result['id']}/workspace/final.md"
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(StudioError, "changed"):
            self.engine.artifact(result["id"], item["id"])

    def test_stop_and_single_admission(self):
        result = self.run_fixture(extra="time.sleep(30)", wait=False)
        with self.assertRaisesRegex(StudioError, "active"):
            self.engine.submit(self.request())
        self.engine.stop(result["id"])
        self.engine.thread.join(15)
        self.assertEqual(self.store.get(result["id"])["status"], "stopped")

    def test_timeout_and_log_limit_preserve_partial_output(self):
        with patch("research_studio.runtime.MAX_LOG", 100):
            result = self.run_fixture(extra="print('x' * 1000); time.sleep(5)")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["manifest"]["artifacts"][0]["path"], "final.md")
        original = self.engine.monitor
        with patch.object(
            self.engine,
            "monitor",
            side_effect=lambda p, root, rid, limit: original(p, root, rid, 0.05),
        ):
            result = self.run_fixture(extra="time.sleep(5)")
        self.assertEqual(result["status"], "timed-out")

    def test_cleanup_failure_blocks_admission_and_artifact_index(self):
        with patch.object(
            self.engine.supervisor,
            "cleanup",
            side_effect=StudioError("survivor remains"),
        ):
            result = self.run_fixture()
        self.assertEqual(
            (result["status"], result["manifest"]["artifacts"]), ("failed", [])
        )
        self.assertTrue((self.store.root / "reconciliation-required").exists())

    def test_lock_and_restart_requires_reconciliation(self):
        with self.assertRaisesRegex(StudioError, "another server"):
            Store(self.root / "data")
        request = self.request()
        self.store.create(request)
        self.store.close()
        self.store = Store(self.root / "data")
        self.assertEqual(self.store.get(request["request_id"])["status"], "interrupted")
        self.assertTrue((self.store.root / "reconciliation-required").exists())

    def test_scope_stage_and_path_rejection(self):
        for field, value in (
            ("scope_confirmed", False),
            ("stage", 2),
            ("timeout_seconds", True),
            ("request_id", "../escape"),
        ):
            request = {**self.request(), field: value}
            with self.assertRaises(StudioError):
                validate_request(request)
        with self.assertRaisesRegex(StudioError, "Git"):
            Store(self.plugin / "private")
        with self.assertRaises(StudioError):
            safe_path(self.store.root, "../escape")
        path = self.root / "source.txt"
        path.write_text("source", encoding="utf-8")
        linked = self.store.root / "linked.txt"
        os.link(path, linked)
        with self.assertRaisesRegex(StudioError, "regular private"):
            self.engine._bytes(self.store.root, "linked.txt")


if __name__ == "__main__":
    unittest.main()
