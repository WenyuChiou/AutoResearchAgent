import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import sys

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage1_eval import model_calls  # noqa: E402
from stage1_eval.common import EvaluationError  # noqa: E402
from stage1_eval.model import DISABLED, _api_schema  # noqa: E402
from stage2_live import native, observation  # noqa: E402
from stage2_live.native_namespace import NativeNamespaceError  # noqa: E402


def _events():
    values = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]
    return b"".join(json.dumps(value).encode() + b"\n" for value in values)


class _Result:
    stdout = _events()
    stderr = b""
    returncode = 0


class NamespaceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.work = self.root / "workspace"
        self.capture_root = self.root / "captures"
        self.telemetry = self.root / "telemetry"
        for path in (self.home, self.work, self.capture_root, self.telemetry):
            path.mkdir()
        self.codex = self.root / "codex.exe"
        self.codex.write_bytes(b"native executable")
        self.scope_file = self.home / "native-namespace.json"
        self.scope_file.write_bytes(b'{"synthetic":true}\n')
        self.binding = {
            "path": str(self.scope_file),
            "sha256": hashlib.sha256(self.scope_file.read_bytes()).hexdigest(),
            "scope": {
                "codex": str(self.codex),
                "home": str(self.home),
                "workspace": str(self.work),
                "capture_root": str(self.capture_root),
            },
            "dispatcher_sha256": "d" * 64,
        }

    @staticmethod
    def wrap(command, binding):
        return command if binding is None else ["bwrap", "--"] + command

    def native_args(self, output):
        return {
            "codex": self.codex,
            "codex_home": self.home,
            "workspace": self.work,
            "prompt": "prompt",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {},
            "config_bindings": {},
            "policy_bindings": native.SUBJECT_EXECUTION_POLICY,
            "output_dir": output,
        }

    def rpc(self, command, home, workspace, requests, timeout):
        self.observed_rpc_command = command
        values = {
            "config/read": {"config": {}},
            "skills/list": {"data": []},
            "plugin/list": {"marketplaces": [], "marketplaceLoadErrors": []},
            "mcpServerStatus/list": {"data": [], "nextCursor": None},
        }
        responses = [
            {"id": request["id"], "result": values[request["method"]]}
            for request in requests
        ]
        events = [
            {"direction": "request", "payload": {"id": 0, "method": "initialize"}},
            {"direction": "response", "payload": {"id": 0, "result": {}}},
            {"direction": "request", "payload": {"method": "initialized"}},
        ]
        for request, response in zip(requests, responses):
            events += [
                {"direction": "request", "payload": request},
                {"direction": "response", "payload": response},
            ]
        return responses, events, b""

    def test_absence_preserves_legacy_shapes_and_argv(self):
        self.scope_file.unlink()
        binding = native._request_binding(
            self.codex,
            self.home,
            self.work,
            b"p",
            "m",
            "high",
            {},
            {},
            native.SUBJECT_EXECUTION_POLICY,
        )
        self.assertNotIn("native_namespace", binding)
        output = self.root / "legacy"
        command = native._expected_command(
            {"stable_request_binding": native._stable_request(binding)}, output
        )
        self.assertEqual(
            command[0:4], [str(self.codex), "exec", "--sandbox", "workspace-write"]
        )
        config = model_calls._request_config(self.codex, self.home, "m", "high")
        self.assertEqual(
            set(config),
            {
                "codex",
                "codex_executable_sha256",
                "evaluator_home",
                "model",
                "reasoning",
            },
        )
        plain = model_calls._command(self.codex, "m", "high", "schema", "output")
        self.assertEqual(
            model_calls._namespace_command(config, "m", "high", "schema", "output"),
            plain,
        )

    def test_all_three_launches_are_wrapped_and_keep_native_flags(self):
        capture = self.capture_root / "native"

        def run(command, **kwargs):
            self.native_command = command
            Path(command[command.index("-o") + 1]).write_text("ok\n", encoding="utf-8")
            return _Result()

        with (
            patch.object(native, "bind_namespace", return_value=self.binding),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
        ):
            record = native.capture_native(
                **self.native_args(capture), process_runner=run
            )
        self.assertEqual(self.native_command[:2], ["bwrap", "--"])
        self.assertIn("--sandbox", self.native_command)
        self.assertIn("workspace-write", self.native_command)
        self.assertEqual(
            (capture / "archive/native-namespace.json").read_bytes(),
            self.scope_file.read_bytes(),
        )
        self.assertIn("native_namespace", record["stable_request_binding"])

        observed = self.capture_root / "observation"
        with (
            patch.object(observation, "bind_namespace", return_value=self.binding),
            patch.object(observation, "wrap_namespace", side_effect=self.wrap),
        ):
            result = observation.collect_runtime_observation(
                codex=self.codex,
                codex_home=self.home,
                workspace=self.work,
                output_dir=observed,
                rpc_transport=self.rpc,
            )
            observation.verify_runtime_observation(
                observed, result["record_sha256_receipt"], allow_synthetic=True
            )
        self.assertEqual(self.observed_rpc_command[:2], ["bwrap", "--"])
        self.assertEqual(
            (observed / "native-namespace.json").read_bytes(),
            self.scope_file.read_bytes(),
        )
        changed_observation = json.loads(json.dumps(self.binding))
        changed_observation["dispatcher_sha256"] = "e" * 64
        with (
            patch.object(
                observation, "bind_namespace", return_value=changed_observation
            ),
            self.assertRaisesRegex(native.CaptureError, "binding changed"),
        ):
            observation.verify_runtime_observation(
                observed, result["record_sha256_receipt"], allow_synthetic=True
            )
        observation_path = observed / "observation.json"
        malformed = json.loads(observation_path.read_text())
        malformed["binding"].pop("native_namespace")
        malformed["artifacts"].pop("native-namespace.json")
        malformed_raw = (
            json.dumps(malformed, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode()
        observation_path.write_bytes(malformed_raw)
        with self.assertRaisesRegex(native.CaptureError, "artifact binding"):
            observation.verify_runtime_observation(
                observed,
                hashlib.sha256(malformed_raw).hexdigest(),
                allow_synthetic=True,
            )

        with (
            patch.object(model_calls, "bind_namespace", return_value=self.binding),
            patch.object(model_calls, "wrap_namespace", side_effect=self.wrap),
        ):
            schema = self.capture_root / "schema.json"
            schema.write_text(
                json.dumps(
                    {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    }
                ),
                encoding="utf-8",
            )

            def model_run(command, **kwargs):
                self.model_command = command
                value = {"ok": True}
                Path(command[command.index("-o") + 1]).write_text(
                    json.dumps(value), encoding="utf-8"
                )
                rows = [
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(value),
                        },
                    },
                    {"type": "turn.completed"},
                ]
                return SimpleNamespace(
                    returncode=0,
                    stdout=("\n".join(map(json.dumps, rows)) + "\n").encode(),
                    stderr=b"",
                )

            with patch.object(
                model_calls, "_execute_bound_process", side_effect=model_run
            ):
                model_calls.call_model_v31(
                    "prompt",
                    schema,
                    self.capture_root,
                    "judge",
                    codex=self.codex,
                    evaluator_home=self.home,
                    model="m",
                    reasoning="high",
                    timeout=30,
                    execution_policy={
                        "schema_version": model_calls.MODEL_CALL_ARCHIVE_VERSION,
                        "timeout_seconds": 30,
                        "max_transient_transport_retries": 0,
                        "evaluator_bundle_sha256": "a" * 64,
                    },
                    resume_verified=False,
                    semantic_validator=lambda value: value["ok"],
                    api_schema=lambda value: _api_schema(
                        value, preserve_constraints=True
                    ),
                )
        request = json.loads(
            (self.capture_root / "judge.model-call/request.json").read_text()
        )
        self.assertEqual(request["config"]["effective_cwd"], str(self.work))
        self.assertEqual(self.model_command[:2], ["bwrap", "--"])
        self.assertEqual(
            (self.capture_root / "judge.model-call/native-namespace.json").read_bytes(),
            self.scope_file.read_bytes(),
        )
        for flag in ("--ignore-user-config", "--sandbox", "read-only"):
            self.assertIn(flag, self.model_command)
        for disabled in DISABLED:
            self.assertIn(disabled, self.model_command)

    def test_changed_scope_fails_before_each_dispatch(self):
        rejected = NativeNamespaceError("namespace binding changed before dispatch")
        runner = Mock()
        with (
            patch.object(native, "bind_namespace", return_value=self.binding),
            patch.object(native, "wrap_namespace", side_effect=rejected),
            self.assertRaisesRegex(native.CaptureError, "changed before dispatch"),
        ):
            native.capture_native(
                **self.native_args(self.capture_root / "rejected-native"),
                process_runner=runner,
            )
        runner.assert_not_called()

        resume_output = self.capture_root / "resume-native"

        def successful(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_text("ok\n", encoding="utf-8")
            return _Result()

        launch = Mock(side_effect=successful)
        with (
            patch.object(native, "bind_namespace", return_value=self.binding),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
        ):
            completed = native.capture_native(
                **self.native_args(resume_output), process_runner=launch
            )
            verified, reconstructed = native.verify_capture(
                resume_output,
                completed["record_sha256_receipt"],
                allow_injected_test_capture=True,
            )
        self.assertEqual(
            verified["stable_request_binding"]["native_namespace"], self.binding
        )
        self.assertEqual(reconstructed, "ok")
        launch.reset_mock()
        with (
            patch.object(native, "bind_namespace", return_value=self.binding),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
        ):
            resumed = native.capture_native(
                **self.native_args(resume_output),
                process_runner=launch,
                resume=True,
                record_sha256_receipt=completed["record_sha256_receipt"],
            )
        self.assertEqual(resumed["resume_action"], "verified-replay-no-execution")
        launch.assert_not_called()
        changed = json.loads(json.dumps(self.binding))
        changed["dispatcher_sha256"] = "e" * 64
        with (
            patch.object(native, "bind_namespace", return_value=changed),
            patch.object(native, "wrap_namespace", side_effect=self.wrap),
            self.assertRaisesRegex(native.CaptureError, "binding changed"),
        ):
            native.capture_native(
                **self.native_args(resume_output),
                process_runner=launch,
                resume=True,
                record_sha256_receipt=completed["record_sha256_receipt"],
            )
        launch.assert_not_called()

        transport = Mock()
        with (
            patch.object(observation, "bind_namespace", return_value=self.binding),
            patch.object(observation, "wrap_namespace", side_effect=rejected),
            self.assertRaisesRegex(native.CaptureError, "changed before dispatch"),
        ):
            observation.collect_runtime_observation(
                codex=self.codex,
                codex_home=self.home,
                workspace=self.work,
                output_dir=self.capture_root / "rejected-observation",
                rpc_transport=transport,
            )
        transport.assert_not_called()

        with (
            patch.object(model_calls, "bind_namespace", return_value=self.binding),
            patch.object(model_calls, "wrap_namespace", side_effect=rejected),
        ):
            config = model_calls._request_config(self.codex, self.home, "m", "high")
            with self.assertRaisesRegex(EvaluationError, "changed before dispatch"):
                model_calls._namespace_command(
                    config,
                    "m",
                    "high",
                    self.capture_root / "schema.json",
                    self.capture_root / "output.json",
                )

    def test_model_paths_must_be_in_declared_scope(self):
        config = {
            "codex": str(self.codex),
            "native_namespace": self.binding,
        }
        with self.assertRaisesRegex(
            EvaluationError, "inside capture_root or workspace"
        ):
            model_calls._namespace_command(
                config,
                "m",
                "high",
                self.home / "schema.json",
                self.capture_root / "output.json",
            )

    def test_legacy_model_config_does_not_reject_script_launcher(self):
        launcher = self.root / "legacy.cmd"
        launcher.write_bytes(b"legacy launcher")
        with patch.object(model_calls, "bind_namespace", return_value=None):
            config = model_calls._request_config(launcher, self.home, "m", "high")
        self.assertEqual(config["codex"], str(launcher))
        with (
            patch.object(model_calls, "bind_namespace", return_value=self.binding),
            self.assertRaisesRegex(EvaluationError, "standalone Codex binary"),
        ):
            model_calls._request_config(launcher, self.home, "m", "high")

    def test_request_fingerprint_binds_namespace_module_hash(self):
        policy = {
            "kind": "EvaluatorModelExecutionPolicy",
            "schema_version": model_calls.MODEL_CALL_ARCHIVE_VERSION,
            "timeout_seconds": 30,
            "max_transient_transport_retries": 0,
            "evaluator_bundle_sha256": "a" * 64,
        }
        first = {
            "codex": str(self.codex),
            "native_namespace": self.binding,
        }
        changed = json.loads(json.dumps(first))
        changed["native_namespace"]["dispatcher_sha256"] = "e" * 64
        one = model_calls._request_record("p", b"{}", b"{}", first, policy, "x")
        two = model_calls._request_record("p", b"{}", b"{}", changed, policy, "x")
        self.assertNotEqual(
            one["request_fingerprint_sha256"], two["request_fingerprint_sha256"]
        )


if __name__ == "__main__":
    unittest.main()
