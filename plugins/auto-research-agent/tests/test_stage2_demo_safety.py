"""Fault injection for the fixed demo's raw-source and pre-dispatch boundaries."""

# ruff: noqa: E402 -- reuse the public fixed HTTP fixture, not a production adapter.
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stage2_demo as fixture

demo_module, PLUGIN = fixture.demo_module, fixture.PLUGIN


class DemoSafetyTests(unittest.TestCase):
    setUp = fixture.DemoTests.setUp
    new_demo = fixture.DemoTests.new_demo
    cleanup_server = fixture.DemoTests.cleanup_server
    request = fixture.DemoTests.request
    body = fixture.DemoTests.body

    def test_real_controller_delivery_then_get_post_and_reopen_never_repeat(self):
        code, prepared = self.request()
        self.assertEqual(code, 200)
        self.assertIsNone(prepared["action"])
        self.assertFalse((self.demo.root / "run-once").exists())
        code, completed = self.request("POST", self.body())
        self.assertEqual(code, 200, completed)
        row = completed["action"]
        self.assertEqual(
            row.get("outcome"),
            "succeeded",
            (self.demo.root / "worker-stderr.log").read_text(),
        )
        self.assertEqual((row["status"], row["outcome"]), ("completed", "succeeded"))
        actual = row["result"]
        self.assertEqual(
            actual["adapter_calls"],
            [
                "research",
                "extract",
                "review:challenger",
                "review:feasibility",
                "resolve",
            ],
        )
        self.assertEqual(actual["result"]["status"], "awaiting-human")
        self.assertFalse(actual["result"]["stage2_complete"])
        self.assertFalse(actual["controller_verified"]["authentic_native_execution"])
        self.assertEqual(
            actual["controller_verified"]["model_call_verification"],
            "synthetic-not-authenticatable",
        )
        self.assertTrue((self.demo.root / "run-once/controller").is_dir())
        self.assertTrue(
            (self.demo.root / "run-once/delivery/delivery_manifest.json").is_file()
        )
        self.assertTrue(self.demo.store.events(demo_module.PID))
        code, report = self.request(suffix="stage2/report")
        self.assertEqual(code, 200)
        self.assertIn("candidate-1", report["html"])
        self.assertEqual(report["sha256"], actual["report_sha256"])
        with patch.object(
            demo_module.subprocess,
            "Popen",
            side_effect=AssertionError("no replay child"),
        ):
            self.assertEqual(self.request()[1]["action"], row)
            self.assertEqual(self.request("POST", self.body())[1]["action"], row)
        self.demo.close()
        reopened = self.new_demo()
        try:
            with patch.object(
                demo_module.subprocess,
                "Popen",
                side_effect=AssertionError("no replay child"),
            ):
                self.assertEqual(
                    reopened.execute(
                        self.token, "stage2", self.body(), deadline=time.monotonic() + 5
                    )["action"],
                    row,
                )
        finally:
            reopened.close()

    def test_deadline_expires_during_stderr_open_zero_spawn_known_unsent(self):
        original, clock = Path.open, [0.0]

        def delayed_open(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path.name == "worker-stderr.log":
                clock[0] = 10.0
            return value

        with (
            patch.object(demo_module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(Path, "open", delayed_open),
            patch.object(
                demo_module.subprocess,
                "Popen",
                side_effect=AssertionError("no late spawn"),
            ) as spawn,
        ):
            actual = self.demo.execute(self.token, "stage2", self.body(), deadline=5)
        self.assertEqual(spawn.call_count, 0)
        self.assertEqual(actual["action"]["error"], "deadline-before-dispatch")
        self.assertEqual(actual["action"]["status"], "failed")
        self.assertFalse((self.demo.root / "run-once").exists())

    def test_helper_mutates_between_sweep_and_exec_refused_before_compile(self):
        repo = self.root / "isolated-repo"
        helper = (
            repo
            / "plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
        )
        helper.parent.mkdir(parents=True)
        raw_helper = (
            PLUGIN / "cli/research_workspace_native/atlas_local_source.py"
        ).read_bytes()
        helper.write_bytes(raw_helper)
        config = dict(
            self.demo.config,
            repo=str(repo),
            sources={
                "cli/research_workspace_native/atlas_local_source.py": demo_module.digest(
                    raw_helper
                )
            },
        )
        binding = self.root / "helper-race.json"
        demo_module.save(binding, config)
        original, count = demo_module.read, [0]

        def changed_read(path, *args):
            if Path(path) == helper:
                count[0] += 1
                if count[0] == 2:
                    return b"raise AssertionError('changed helper executed')\n"
            return original(path, *args)

        # Exercise the raw helper race in a synthetic isolated-worker context;
        # unittest itself need not be started with -I/-B (including CI).
        with (
            patch.object(demo_module, "read", side_effect=changed_read),
            patch.object(demo_module.sys, "flags", SimpleNamespace(isolated=1)),
            patch.object(demo_module.sys, "dont_write_bytecode", True),
        ):
            with self.assertRaisesRegex(
                ValueError, "bootstrap helper bytes differ before execution"
            ):
                demo_module.worker(binding, demo_module.digest(binding.read_bytes()))
        self.assertEqual(count[0], 2)

    def test_nonisolated_worker_refused_before_reading_binding(self):
        with (
            patch.object(demo_module.sys, "flags", SimpleNamespace(isolated=0)),
            patch.object(demo_module, "read") as read_binding,
        ):
            with self.assertRaisesRegex(
                ValueError, "isolated raw source worker required"
            ):
                demo_module.worker(self.root / "not-read.json", "not-read")
        read_binding.assert_not_called()

    def test_demo_script_mutation_in_child_refused_before_top_level_execution(self):
        script, marker = (
            self.root / "changed-demo.py",
            self.root / "changed-executed.txt",
        )
        script.write_text(
            "from pathlib import Path\nPath("
            + repr(str(marker))
            + ").write_text('bad')\n"
        )
        popen = subprocess.Popen

        def changed_script(command, **options):
            modified = list(command)
            self.assertEqual(modified[5:7], ["-c", demo_module.BOOTSTRAP])
            modified[7] = str(script)
            return popen(modified, **options)

        with patch.object(demo_module.subprocess, "Popen", side_effect=changed_script):
            code, actual = self.request("POST", self.body())
        self.assertEqual(code, 200)
        self.assertEqual(actual["action"]["status"], "failed")
        self.assertFalse(marker.exists())
        self.assertIn(
            "demo source hash differs before execution",
            (self.demo.root / "worker-stderr.log").read_text(),
        )
        self.assertFalse((self.demo.root / "run-once").exists())

    def test_unlisted_fixture_import_and_modified_binding_refused(self):
        loader = demo_module.RawTests(PLUGIN, {})
        with self.assertRaisesRegex(
            ValueError, "unlisted repository fixture import refused"
        ):
            loader.find_spec("test_stage2_controller")
        path = self.demo.root / "binding.json"
        config = json.loads(path.read_bytes())
        config["index_sha256"] = "b" * 64
        path.write_bytes(demo_module.canonical(config))
        with patch.object(
            demo_module.subprocess,
            "Popen",
            side_effect=AssertionError("no changed binding child"),
        ):
            self.assertEqual(self.request("POST", self.body())[0], 409)
        self.assertFalse((self.demo.root / "run-once").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
