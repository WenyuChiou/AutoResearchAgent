"""Focused tests for the host-observed native trace producer."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import trace_producer  # noqa: E402
from native_trace_fixture import NativeTraceFixture  # noqa: E402
from test_stage2_named_policy import _config, _policy  # noqa: E402


def _jsonl(*rows):
    return b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)


class TraceProducerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.telemetry = self.root / "telemetry"
        self.capture = self.root / "capture"
        for path in (self.home, self.workspace, self.telemetry):
            path.mkdir()
        (self.workspace / "source.txt").write_text("source", encoding="utf-8")
        self.codex = self.root / "codex.exe"
        self.codex.write_bytes(b"runtime")
        self.brief = self.root / "brief.json"
        self.brief.write_bytes(b'{"topic":"test"}\n')
        self.budget = self.root / "budget.json"
        self.budget.write_bytes(b'{"limit":1}\n')
        config = _config(self.workspace, self.home, self.telemetry, self.capture)
        (self.home / "config.toml").write_bytes(config)
        self.policy = _policy(config, self.telemetry)
        self.calls = 0
        self.rpc_calls = 0
        self.trace_mode = "good"
        self.environment = patch.dict(
            os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.telemetry)}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _rpc(self, command, home, workspace, requests, timeout):
        self.rpc_calls += 1
        results = {
            "config/read": {"config": {}},
            "skills/list": {"data": []},
            "plugin/list": {"marketplaces": [], "marketplaceLoadErrors": []},
            "mcpServerStatus/list": {"data": []},
        }
        responses = [
            {"id": row["id"], "result": results[row["method"]]} for row in requests
        ]
        events = [
            {"direction": "request", "payload": {"id": 0, "method": "initialize"}},
            {"direction": "response", "payload": {"id": 0, "result": {}}},
            {"direction": "request", "payload": {"method": "initialized"}},
        ]
        for request, response in zip(requests, responses):
            events.extend(
                (
                    {"direction": "request", "payload": request},
                    {"direction": "response", "payload": response},
                )
            )
        return responses, events, b""

    def _write_trace(self):
        roots = 2 if self.trace_mode == "extra" else 1
        for index in range(roots):
            case = NativeTraceFixture(methodName="runTest")
            case.setUp()
            self.addCleanup(case.doCleanups)
            thread = "wrong-root" if self.trace_mode == "root" else "thread-1"
            case.root = self.telemetry / f"trace-{index + 1}"
            (case.root / "payloads").mkdir(parents=True)
            case.rollout, case.events, case.payloads = thread, [], {}
            case._event("rollout_started", trace_id="trace-1", root_thread_id=thread)
            case._thread_start(thread)
            case._inference("i1", "r1", thread=thread)
            request = next(
                value for value in case.payloads.values() if "model" in value
            )
            request["model"] = (
                "wrong-model" if self.trace_mode == "model" else "gpt-test"
            )
            case._finish()
            case._write()
            manifest = case.root / "manifest.json"
            value = json.loads(manifest.read_bytes())
            value["started_at_unix_ms"] = 1 if self.trace_mode == "time" else 2_000
            manifest.write_bytes(_jsonl(value))

    def _runner(self, command, **kwargs):
        self.calls += 1
        if self.trace_mode != "failed":
            self._write_trace()
        final = Path(command[command.index("-o") + 1])
        if self.trace_mode != "failed":
            final.write_text("final\n", encoding="utf-8")
        events = (
            {"type": "thread.started", "thread_id": "thread-1"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "final"},
            },
            {"type": "turn.completed", "usage": {"output_tokens": 1}},
        )
        return SimpleNamespace(
            stdout=_jsonl(*events),
            stderr=b"failure" if self.trace_mode == "failed" else b"",
            returncode=1 if self.trace_mode == "failed" else 0,
        )

    def _args(self, **updates):
        values = {
            "codex": self.codex,
            "codex_home": self.home,
            "workspace": self.workspace,
            "prompt": "Run once.",
            "model": "gpt-test",
            "reasoning": "high",
            "input_bindings": {"brief": self.brief},
            "config_bindings": {"budget": self.budget},
            "policy_bindings": self.policy,
            "capture_dir": self.capture,
        }
        values.update(updates)
        return values

    def _produce(self, **updates):
        with patch.object(
            trace_producer.native,
            "_utc_now",
            side_effect=("1970-01-01T00:00:01+00:00", "1970-01-01T00:00:03+00:00"),
        ):
            return trace_producer._capture_observed_native(
                **self._args(**updates),
                process_runner=self._runner,
                rpc_transport=self._rpc,
                allow_synthetic_test=True,
            )

    def test_success_and_resume_execute_exactly_once(self):
        produced = self._produce()
        self.assertEqual(self.calls, 1)
        self.assertEqual(produced["status"], "complete")
        self.assertEqual(produced["evidence_class"], "synthetic-test-only")
        self.assertFalse(produced["formal_ready"])
        resumed = self._produce(
            resume=True, producer_receipt=produced["producer_receipt"]
        )
        self.assertEqual(resumed["resume_action"], "verified-replay-no-execution")
        self.assertEqual(self.calls, 1)

    def test_stale_and_extra_telemetry_reject(self):
        (self.telemetry / "stale").mkdir()
        with self.assertRaisesRegex(Stage2Error, "telemetry-not-empty"):
            self._produce()
        (self.telemetry / "stale").rmdir()
        self.trace_mode = "extra"
        with self.assertRaisesRegex(Stage2Error, "telemetry-inventory-mismatch"):
            self._produce()
        self.assertEqual(self.calls, 1)

    def test_trace_root_model_and_time_are_bound(self):
        for mode, error in (
            ("root", "root-mismatch"),
            ("model", "model-mismatch"),
            ("time", "time-outside-capture"),
        ):
            with self.subTest(mode=mode):
                case = TraceProducerTests(methodName="runTest")
                case.setUp()
                self.addCleanup(case.doCleanups)
                case.trace_mode = mode
                with self.assertRaisesRegex(Stage2Error, error):
                    case._produce()

    def test_resume_rejects_current_source_runtime_config_and_input_changes(self):
        produced = self._produce()
        receipt = produced["producer_receipt"]
        checks = (
            (self.codex, b"runtime-changed", "observation-binding-mismatch"),
            (self.budget, b'{"limit":2}\n', "binding-changed"),
            (self.brief, b'{"topic":"changed"}\n', "binding-changed"),
        )
        for path, changed, error in checks:
            original = path.read_bytes()
            path.write_bytes(changed)
            with self.subTest(path=path.name), self.assertRaisesRegex(Exception, error):
                self._produce(resume=True, producer_receipt=receipt)
            path.write_bytes(original)
        with patch.object(trace_producer, "_source_sha", return_value="0" * 64):
            with self.assertRaisesRegex(Stage2Error, "source-changed"):
                self._produce(resume=True, producer_receipt=receipt)

    def test_failed_capture_has_immutable_nonformal_record_without_seal(self):
        self.trace_mode = "failed"
        produced = self._produce()
        self.assertEqual(produced["status"], "failed")
        self.assertFalse(produced["formal_ready"])
        self.assertFalse((self.telemetry / "bundle/sealed").exists())
        self.assertTrue((self.telemetry / "bundle/producer.json").is_file())

    def test_invalid_policy_and_mixed_test_seams_reject_before_calls(self):
        invalid = dict(self.policy, config_sha256="0" * 64)
        with self.assertRaises(Exception):
            self._produce(policy_bindings=invalid)
        self.assertEqual((self.calls, self.rpc_calls), (0, 0))
        self.assertEqual(list(self.telemetry.iterdir()), [])
        with self.assertRaisesRegex(Stage2Error, "mixed-synthetic-seam"):
            trace_producer._capture_observed_native(
                **self._args(),
                process_runner=self._runner,
                allow_synthetic_test=True,
            )
        self.assertEqual((self.calls, self.rpc_calls), (0, 0))

    def test_rehashed_bool_alias_rejects(self):
        self._produce()
        control = self.telemetry / "bundle/producer.json"
        original = control.read_bytes()
        value = json.loads(original)
        value["capture"]["exit_code"] = False
        raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        control.write_bytes(raw)
        receipt = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "capture-binding-mismatch"):
            self._produce(resume=True, producer_receipt=receipt)

    def test_source_change_during_capture_is_saved_as_failure(self):
        with patch.object(
            trace_producer, "_source_sha", side_effect=("a" * 64, "b" * 64)
        ):
            produced = self._produce()
        self.assertEqual(produced["status"], "failed")
        self.assertFalse((self.telemetry / "bundle/sealed").exists())

    @unittest.skipUnless(os.name == "nt", "Windows retained-handle replacement check")
    def test_inventory_root_replacement_is_blocked_without_redirected_writes(self):
        original = self._rpc
        blocked = False

        def replace_during_transport(*args, **kwargs):
            nonlocal blocked
            try:
                os.replace(self.telemetry, self.root / "displaced-telemetry")
            except PermissionError:
                blocked = True
            return original(*args, **kwargs)

        self._rpc = replace_during_transport
        self._produce()
        self.assertTrue(blocked)
        self.assertFalse((self.workspace / "observation.json").exists())

    def test_foreign_observation_binding_rejects_initial_and_rehashed_replay(self):
        collect = trace_producer.observation.collect_runtime_observation

        def foreign(**kwargs):
            value = collect(**kwargs)
            value["binding"]["runtime_sha256"] = "0" * 64
            return value

        with patch.object(
            trace_producer.observation,
            "collect_runtime_observation",
            side_effect=foreign,
        ):
            with self.assertRaisesRegex(Stage2Error, "observation-binding-mismatch"):
                self._produce()
        self.assertEqual(self.calls, 0)

        case = TraceProducerTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case._produce()
        observation_path = case.telemetry / "bundle/inventory/observation.json"
        observed = json.loads(observation_path.read_bytes())
        observed["binding"]["runtime_sha256"] = "0" * 64
        observed_raw = (json.dumps(observed, sort_keys=True) + "\n").encode()
        observation_path.write_bytes(observed_raw)
        control = case.telemetry / "bundle/producer.json"
        producer = json.loads(control.read_bytes())
        producer["runtime_observation_receipt"] = hashlib.sha256(
            observed_raw
        ).hexdigest()
        producer_raw = (json.dumps(producer, indent=2, sort_keys=True) + "\n").encode()
        control.write_bytes(producer_raw)
        receipt = hashlib.sha256(producer_raw).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "observation-binding-mismatch"):
            case._produce(resume=True, producer_receipt=receipt)


if __name__ == "__main__":
    unittest.main()
