import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live import native


def jsonl(*events):
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


class Result:
    def __init__(self, stdout, stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class NativeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.output = self.root / "capture"
        self.home.mkdir()
        self.workspace.mkdir()
        (self.home / "config.toml").write_text("model = 'frozen'\n", encoding="utf-8")
        (self.workspace / "source.txt").write_text("starting source", encoding="utf-8")
        self.codex = self.root / "codex.exe"
        self.codex.write_bytes(b"synthetic launcher")
        self.input = self.root / "brief.json"
        self.input.write_text('{"topic":"synthetic"}\n', encoding="utf-8")
        self.config = self.root / "policy.json"
        self.config.write_text('{"limit":1}\n', encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def args(self, **updates):
        values = {
            "codex": self.codex,
            "codex_home": self.home,
            "workspace": self.workspace,
            "prompt": "Use native tools and report.",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {"brief": self.input},
            "config_bindings": {"budget": self.config},
            "policy_bindings": native.SUBJECT_EXECUTION_POLICY,
            "output_dir": self.output,
        }
        values.update(updates)
        return values

    def successful_runner(self, command, **kwargs):
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn("sandbox_workspace_write.network_access=true", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        final = Path(command[command.index("-o") + 1])
        final.write_text("final answer\n", encoding="utf-8")
        (Path(kwargs["cwd"]) / "created.txt").write_text(
            "tool output", encoding="utf-8"
        )
        return Result(
            jsonl(
                {"type": "thread.started", "thread_id": "thread-1"},
                {
                    "type": "item.completed",
                    "item": {"id": "w1", "type": "web_search", "query": "topic"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "s1",
                        "type": "subagent_call",
                        "name": "explorer",
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "m1",
                        "type": "agent_message",
                        "text": "final answer",
                    },
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 12,
                        "cached_input_tokens": 2,
                        "output_tokens": 7,
                    },
                },
            )
        )

    def test_complete_capture_records_tools_usage_bindings_and_limits(self):
        record = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["capture_mode"], "injected-test-adapter")
        self.assertEqual(record["actual_completed_turn_usage"]["output_tokens"], 7)
        self.assertEqual(
            [item["type"] for item in record["event_summary"]["tool_events"]],
            ["web_search", "subagent_call"],
        )
        self.assertEqual(record["cost"]["amount"], None)
        self.assertIn(
            "provider-side execution", record["host_observation"]["not_attested"]
        )
        self.assertTrue((self.output / "archive/workspace-start/source.txt").is_file())
        self.assertTrue((self.output / "archive/workspace-end/created.txt").is_file())
        self.assertEqual(
            native.verify_capture(
                self.output,
                record["record_sha256_receipt"],
                allow_injected_test_capture=True,
            )[1],
            "final answer",
        )

    def test_only_native_sessions_are_archived_and_tampering_is_rejected(self):
        sessions = self.home / "sessions"
        sessions.mkdir()
        (sessions / "child.jsonl").write_bytes(b'{"type":"synthetic-session"}\n')
        (self.home / "auth.json").write_bytes(b"test-only-secret")
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        self.assertEqual(captured["native_session_records"], "saved")
        archived = self.output / "archive/native-sessions/child.jsonl"
        self.assertEqual(archived.read_bytes(), (sessions / "child.jsonl").read_bytes())
        self.assertFalse(list(self.output.rglob("auth.json")))
        archived.write_bytes(b"changed")
        with self.assertRaisesRegex(native.CaptureError, "archive inventory"):
            native.verify_capture(
                self.output,
                captured["record_sha256_receipt"],
                allow_injected_test_capture=True,
            )

    def test_resume_no_reexecution_and_changed_binding_rejected(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )

        def forbidden(*args, **kwargs):
            raise AssertionError("completed resume must not execute")

        replay = native.capture_native(
            **self.args(resume=True),
            process_runner=forbidden,
            record_sha256_receipt=captured["record_sha256_receipt"],
        )
        self.assertEqual(replay["resume_action"], "verified-replay-no-execution")
        self.assertEqual(replay["reconstructed_final_output"], "final answer")
        self.input.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(native.CaptureError, "binding changed"):
            native.capture_native(
                **self.args(resume=True),
                process_runner=forbidden,
                record_sha256_receipt=captured["record_sha256_receipt"],
            )

    def test_resume_rejects_tampered_archive(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        (self.output / "stdout.jsonl").write_bytes(b"{}\n")

        def forbidden(*args, **kwargs):
            raise AssertionError("resume must not execute")

        with self.assertRaisesRegex(native.CaptureError, "archive inventory"):
            native.capture_native(
                **self.args(resume=True),
                process_runner=forbidden,
                record_sha256_receipt=captured["record_sha256_receipt"],
            )

    def test_rehash_tamper_rejected_by_input_binding_cross_check(self):
        native.capture_native(**self.args(), process_runner=self.successful_runner)
        archived = self.output / "archive/input_bindings/brief"
        archived.write_text("tampered", encoding="utf-8")
        record_path = self.output / "run.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        relative = archived.relative_to(self.output).as_posix()
        record["archived_files"][relative] = native.sha256(archived.read_bytes())
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(native.CaptureError, "input_bindings bytes"):
            native.verify_capture(
                self.output,
                native.sha256(record_path.read_bytes()),
                allow_injected_test_capture=True,
            )

    def test_external_receipt_rejects_record_field_tampering(self):
        for field, value in (
            ("status", "failed"),
            ("command", ["changed"]),
            ("capture_mode", "authentic-subprocess"),
            ("ended_at", "2030-01-01T00:00:00+00:00"),
        ):
            with self.subTest(field=field):
                output = self.root / ("capture-" + field)
                captured = native.capture_native(
                    **self.args(output_dir=output),
                    process_runner=self.successful_runner,
                )
                path = output / "run.json"
                record = json.loads(path.read_text(encoding="utf-8"))
                record[field] = value
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaisesRegex(native.CaptureError, "receipt differs"):
                    native.verify_capture(
                        output,
                        captured["record_sha256_receipt"],
                        allow_injected_test_capture=True,
                    )

    def test_rehashed_record_still_requires_reconstructed_command_and_usage(self):
        for field in ("command", "actual_completed_turn_usage"):
            with self.subTest(field=field):
                output = self.root / ("capture-rehashed-" + field)
                native.capture_native(
                    **self.args(output_dir=output),
                    process_runner=self.successful_runner,
                )
                path = output / "run.json"
                record = json.loads(path.read_text(encoding="utf-8"))
                record[field] = (
                    ["changed"] if field == "command" else {"output_tokens": 999}
                )
                path.write_text(json.dumps(record), encoding="utf-8")
                attacker_receipt = native.sha256(path.read_bytes())
                expected = "recorded command" if field == "command" else "usage differs"
                with self.assertRaisesRegex(native.CaptureError, expected):
                    native.verify_capture(
                        output,
                        attacker_receipt,
                        allow_injected_test_capture=True,
                    )

    def test_final_workspace_archive_tamper_fails_after_manifest_rehash(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        archived = self.output / "archive/workspace-end/created.txt"
        archived.write_text("tampered", encoding="utf-8")
        path = self.output / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        relative = archived.relative_to(self.output).as_posix()
        record["archived_files"][relative] = native.sha256(archived.read_bytes())
        path.write_text(json.dumps(record), encoding="utf-8")
        attacker_receipt = native.sha256(path.read_bytes())
        self.assertNotEqual(attacker_receipt, captured["record_sha256_receipt"])
        with self.assertRaisesRegex(native.CaptureError, "final workspace"):
            native.verify_capture(
                self.output,
                attacker_receipt,
                allow_injected_test_capture=True,
            )

    def test_npm_script_launcher_cannot_miss_changed_vendor_runtime(self):
        package = self.root / "node_modules/@openai/codex"
        launcher = package / "bin/codex.js"
        vendor = package / "vendor/platform/codex"
        launcher.parent.mkdir(parents=True)
        vendor.parent.mkdir(parents=True)
        launcher.write_text(
            "#!/usr/bin/env node\n// launch vendor executable", encoding="utf-8"
        )
        for content in (b"native-v1", b"native-v2"):
            vendor.write_bytes(content)
            with self.assertRaisesRegex(native.CaptureError, "standalone Codex binary"):
                native.codex_runtime_sha(launcher)
        self.assertNotEqual(
            native.codex_runtime_sha(vendor), native.sha256(b"native-v1")
        )

    def test_runtime_bytes_bound_on_resume(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        self.codex.write_bytes(b"different executable package")
        with self.assertRaisesRegex(native.CaptureError, "binding changed"):
            native.capture_native(
                **self.args(resume=True),
                process_runner=self.successful_runner,
                record_sha256_receipt=captured["record_sha256_receipt"],
            )

    def test_dependency_sha_bound_on_resume(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        self.config.write_bytes(b"changed dependency bytes")
        with self.assertRaisesRegex(native.CaptureError, "binding changed"):
            native.capture_native(
                **self.args(resume=True),
                process_runner=self.successful_runner,
                record_sha256_receipt=captured["record_sha256_receipt"],
            )

    def test_failure_is_saved_and_never_resumed(self):
        failed_events = jsonl(
            {"type": "thread.started", "thread_id": "thread-2"},
            {"type": "turn.failed", "error": {"message": "synthetic failure"}},
        )

        def failing(command, **kwargs):
            return Result(failed_events, b"failure detail", 1)

        record = native.capture_native(**self.args(), process_runner=failing)
        self.assertEqual(record["status"], "failed")
        self.assertEqual((self.output / "stderr.txt").read_bytes(), b"failure detail")
        self.assertTrue((self.output / "run.json").is_file())
        with self.assertRaisesRegex(native.CaptureError, "only a completed"):
            native.capture_native(
                **self.args(resume=True),
                record_sha256_receipt=record["record_sha256_receipt"],
            )

    def test_incomplete_when_usage_or_final_is_missing(self):
        def incomplete(command, **kwargs):
            return Result(
                jsonl(
                    {"type": "thread.started", "thread_id": "thread-3"},
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "unsaved"},
                    },
                    {"type": "turn.completed"},
                )
            )

        record = native.capture_native(**self.args(), process_runner=incomplete)
        self.assertEqual(record["status"], "incomplete")
        self.assertIsNone(record["actual_completed_turn_usage"])
        with self.assertRaisesRegex(native.CaptureError, "only a completed"):
            native.capture_native(
                **self.args(resume=True),
                record_sha256_receipt=record["record_sha256_receipt"],
            )

    def test_malformed_json_primitive_is_saved_as_failed_capture(self):
        for name, payload in (("primitive", b"1\n"), ("null-item", b'{"item":null}\n')):
            with self.subTest(name=name):
                output = self.root / ("capture-" + name)

                def malformed(command, **kwargs):
                    return Result(payload)

                record = native.capture_native(
                    **self.args(output_dir=output), process_runner=malformed
                )
                self.assertEqual(record["status"], "failed")
                self.assertEqual(
                    record["event_summary"]["parse_error"], "invalid-jsonl"
                )
                self.assertTrue((output / "run.json").is_file())

    def test_injected_capture_requires_explicit_synthetic_verification(self):
        captured = native.capture_native(
            **self.args(), process_runner=self.successful_runner
        )
        with self.assertRaisesRegex(
            native.CaptureError, "cannot be verified as authentic"
        ):
            native.verify_capture(self.output, captured["record_sha256_receipt"])

    def test_authentic_path_streams_directly_to_exclusive_files(self):
        payload = jsonl(
            {"type": "thread.started", "thread_id": "thread-native"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "native final"},
            },
            {"type": "turn.completed", "usage": {"output_tokens": 2}},
        )

        class FakePopen:
            def __init__(inner, command, **kwargs):
                self.assertNotEqual(kwargs["stdout"], native.subprocess.PIPE)
                self.assertNotEqual(kwargs["stderr"], native.subprocess.PIPE)
                kwargs["stdout"].write(payload)
                kwargs["stdout"].flush()
                kwargs["stderr"].write(b"native stderr")
                kwargs["stderr"].flush()
                Path(command[command.index("-o") + 1]).write_text(
                    "native final\n", encoding="utf-8"
                )
                inner.returncode = 0

            def communicate(inner, input):
                self.assertEqual(input, b"Use native tools and report.")

        with patch.object(native.subprocess, "Popen", FakePopen):
            captured = native.capture_native(**self.args())
        self.assertEqual(captured["capture_mode"], "authentic-subprocess")
        self.assertEqual((self.output / "stdout.jsonl").read_bytes(), payload)
        self.assertEqual(
            native.verify_capture(self.output, captured["record_sha256_receipt"])[1],
            "native final",
        )

    def test_post_process_archive_failure_is_saved(self):
        original = native._copy_binding

        def fail_end(source, destination):
            if Path(destination).name == "workspace-end":
                raise OSError("synthetic archive failure")
            return original(source, destination)

        with patch.object(native, "_copy_binding", side_effect=fail_end):
            record = native.capture_native(
                **self.args(), process_runner=self.successful_runner
            )
        self.assertEqual(record["status"], "failed")
        self.assertIn("final workspace archive failed", record["exception"]["message"])
        self.assertTrue((self.output / "run.json").is_file())

    def test_policy_and_path_isolation_are_fail_closed(self):
        with self.assertRaisesRegex(native.CaptureError, "preserve workspace-write"):
            native.capture_native(
                **self.args(policy_bindings={"sandbox": "danger-full-access"})
            )
        with self.assertRaisesRegex(native.CaptureError, "must be separate"):
            native.capture_native(**self.args(output_dir=self.workspace / "nested"))


if __name__ == "__main__":
    unittest.main()
