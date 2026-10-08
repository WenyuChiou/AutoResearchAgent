"""Synthetic-only tests for authenticated execution inventory replay."""

import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import canonical_hash  # noqa: E402
from stage2_live import execution_inventory  # noqa: E402
from stage2_live import trace_producer  # noqa: E402
from native_trace_fixture import NativeTraceFixture  # noqa: E402
import test_stage2_trace_producer as fixtures  # noqa: E402


class ExecutionInventoryTests(unittest.TestCase):
    """These injected archives test mechanics; they are never live proof."""

    def setUp(self):
        self.case = fixtures.TraceProducerTests(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        project_config_guard = patch.object(
            trace_producer.native_policy, "_no_project_configs"
        )
        project_config_guard.start()
        self.addCleanup(project_config_guard.stop)
        private_root_guard = patch.object(
            trace_producer.observation,
            "private_output",
            side_effect=lambda value: Path(value).absolute(),
        )
        private_root_guard.start()
        self.addCleanup(private_root_guard.stop)

    def _inspect(self, produced, request=None):
        original_verify = execution_inventory.trace_producer._verify
        original_observation = (
            execution_inventory.observation.verify_runtime_observation
        )

        def verify(args, root, receipt, *, allow_synthetic):
            return original_verify(args, root, receipt, allow_synthetic=True)

        def verify_observation(output, receipt, *, allow_synthetic=False):
            return original_observation(output, receipt, allow_synthetic=True)

        base = {
            "evidence_class": "synthetic-test-only",
            "capture": produced["capture"],
            "call_accounting_complete": True,
            "token_usage_complete": True,
        }
        with (
            patch.object(
                execution_inventory, "verify_producer_inventory", return_value=base
            ),
            patch.object(
                execution_inventory.trace_producer, "_verify", side_effect=verify
            ),
            patch.object(
                execution_inventory.observation,
                "verify_runtime_observation",
                side_effect=verify_observation,
            ),
        ):
            return execution_inventory.inspect_execution_inventory(
                self.case.telemetry,
                produced["producer_receipt"],
                capture_request=request or self.case._args(),
            )

    def test_bound_json_does_not_reopen_an_unanchored_path(self):
        path = self.case.root / "anchored.json"
        raw = b'{"observed":true}'
        path.write_bytes(raw)
        with patch.object(Path, "open", side_effect=AssertionError("unanchored open")):
            result, digest = execution_inventory._read_bound_json(
                path, hashlib.sha256(raw).hexdigest(), "RPC"
            )
        self.assertEqual(result, {"observed": True})
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def test_leaf_replaced_after_status_is_rejected(self):
        path = self.case.root / "replaced.json"
        raw = b'{"observed":true}'
        path.write_bytes(raw)
        original = execution_inventory.SealDirectory.reader

        def replace_before_open(directory, name):
            path.rename(path.with_suffix(".original"))
            path.write_bytes(raw)
            return original(directory, name)

        with patch.object(
            execution_inventory.SealDirectory, "reader", replace_before_open
        ):
            with self.assertRaisesRegex(Exception, "identity changed"):
                execution_inventory._read_bound_json(
                    path, hashlib.sha256(raw).hexdigest(), "RPC"
                )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO race requires POSIX")
    def test_fifo_replacement_is_rejected_without_blocking(self):
        path = self.case.root / "fifo.json"
        raw = b"{}"
        path.write_bytes(raw)
        original = execution_inventory.SealDirectory.reader

        def replace_before_open(directory, name):
            path.rename(path.with_suffix(".original"))
            os.mkfifo(path)
            return original(directory, name)

        with patch.object(
            execution_inventory.SealDirectory, "reader", replace_before_open
        ):
            with self.assertRaises(Exception):
                execution_inventory._read_bound_json(
                    path, hashlib.sha256(raw).hexdigest(), "RPC"
                )

    def test_authenticated_archive_projects_inputs_tools_metadata_and_counts(self):
        produced = self.case._produce()
        report = self._inspect(produced)

        self.assertEqual((self.case.calls, self.case.rpc_calls), (1, 1))
        self.assertEqual(report["kind"], "Stage2ExecutionInventory")
        self.assertTrue(report["coverage_complete"])
        self.assertFalse(report["formal_ready"])
        self.assertEqual(report["inferences"][0]["model"], "gpt-test")
        self.assertEqual(
            report["inferences"][0]["offered_tools"]["definitions"][0]["type"],
            "namespace",
        )
        self.assertEqual(report["counts"]["inferences"], 1)
        self.assertEqual(report["token_usage_totals"]["total_tokens"], 12)
        self.assertEqual(
            [row["method"] for row in report["supported_metadata_inventory"]],
            ["config/read", "skills/list", "plugin/list", "mcpServerStatus/list"],
        )
        self.assertIsNone(report["cost"]["amount"])

    def test_unknown_tools_and_token_usage_block_coverage_without_zero_fill(self):
        original = NativeTraceFixture._inference

        def incomplete(fixture, *args, **kwargs):
            return original(fixture, *args, tools=False, usage=False, **kwargs)

        with patch.object(NativeTraceFixture, "_inference", new=incomplete):
            produced = self.case._produce()
        report = self._inspect(produced)

        self.assertFalse(report["coverage_complete"])
        self.assertIsNone(report["inferences"][0]["offered_tools"])
        self.assertIsNone(report["inferences"][0]["token_usage"])
        self.assertIsNone(report["token_usage_totals"])
        self.assertIn("offered-tools-unknown:i1", report["blockers"])
        self.assertIn("token-usage-unknown:i1", report["blockers"])

    def test_supported_rpc_above_trace_payload_limit_remains_bounded(self):
        path = self.case.root / "large-rpc.json"
        raw = json.dumps({"value": "x" * (4 * 1024 * 1024 + 1)}).encode()
        path.write_bytes(raw)
        value, _ = execution_inventory._read_bound_json(
            path, hashlib.sha256(raw).hexdigest(), "large RPC"
        )
        self.assertEqual(len(value["value"]), 4 * 1024 * 1024 + 1)
        with patch.object(
            execution_inventory.observation, "MAX_RPC_STREAM_BYTES", 1024
        ):
            with self.assertRaises(execution_inventory.CaptureError):
                execution_inventory._read_bound_json(
                    path, hashlib.sha256(raw).hexdigest(), "over-limit RPC"
                )

    def test_incomplete_supported_metadata_is_preserved_and_blocks_coverage(self):
        original = self.case._rpc

        def partial(*args, **kwargs):
            responses, events, stderr = original(*args, **kwargs)
            responses[1]["result"] = {"data": [{"skills": [], "errors": ["unknown"]}]}
            response_id = responses[1]["id"]
            for event in events:
                if (
                    event["direction"] == "response"
                    and event["payload"].get("id") == response_id
                ):
                    event["payload"] = responses[1]
            return responses, events, stderr

        self.case._rpc = partial
        produced = self.case._produce()
        report = self._inspect(produced)

        skills = report["supported_metadata_inventory"][1]
        self.assertEqual(skills["status"], "incomplete")
        self.assertEqual(skills["result"]["data"][0]["errors"], ["unknown"])
        self.assertFalse(report["coverage_complete"])

    def test_missing_child_terminal_and_lineage_remain_explicit_blockers(self):
        def write_trace():
            case = NativeTraceFixture(methodName="runTest")
            case.setUp()
            self.case.addCleanup(case.doCleanups)
            case.root = self.case.telemetry / "trace-1"
            (case.root / "payloads").mkdir(parents=True)
            case.rollout, case.events, case.payloads = "thread-1", [], {}
            case._event(
                "rollout_started", trace_id="trace-1", root_thread_id="thread-1"
            )
            case._thread_start("thread-1")
            case._inference("i1", "r1", thread="thread-1")
            case._thread_start("child", "thread-1")
            case._inference("i2", "r2", thread="child")
            for value in case.payloads.values():
                if "model" in value:
                    value["model"] = "gpt-test"
            case._turn_end("thread-1")
            case._event("thread_ended", thread_id="thread-1", status="completed")
            case._event("rollout_ended", status="completed")
            case._write()
            manifest = case.root / "manifest.json"
            value = json.loads(manifest.read_bytes())
            value["started_at_unix_ms"] = 2_000
            manifest.write_bytes((json.dumps(value, sort_keys=True) + "\n").encode())

        self.case._write_trace = write_trace
        produced = self.case._produce()
        report = self._inspect(produced)

        self.assertFalse(report["coverage_complete"])
        self.assertIn("thread-terminal-missing:child", report["blockers"])
        self.assertEqual(report["threads"][1]["parent_thread_id"], "thread-1")

    def test_mismatched_request_and_rehashed_trace_tamper_reject(self):
        produced = self.case._produce()
        with self.assertRaises(Exception):
            self._inspect(
                produced,
                {**self.case._args(), "workspace": self.case.root / "foreign-work"},
            )

        payload = next((self.case.telemetry / "trace-1/payloads").glob("*.json"))
        payload.write_bytes(b'{"tampered":true}\n')
        inventory, digest = trace_producer._snapshot(self.case.telemetry / "trace-1")
        control = self.case.telemetry / "bundle/producer.json"
        record = json.loads(control.read_bytes())
        record["trace"]["inventory"] = inventory
        record["trace"]["receipt_sha256"] = digest
        raw = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
        control.write_bytes(raw)
        receipt = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(Exception):
            self._inspect({**produced, "producer_receipt": receipt})

    def test_inherited_tool_inventory_keeps_exact_definitions_and_hash(self):
        original = NativeTraceFixture._finish

        def finish_with_delta(fixture):
            fixture._inference("i2", "r2", previous="r1", tools=False)
            for value in fixture.payloads.values():
                if "model" in value:
                    value["model"] = "gpt-test"
            original(fixture)

        with patch.object(NativeTraceFixture, "_finish", new=finish_with_delta):
            produced = self.case._produce()
        report = self._inspect(produced)
        tools = report["inferences"][1]["offered_tools"]
        self.assertEqual(tools["inherited_from_response_id"], "r1")
        self.assertEqual(tools["sha256"], canonical_hash(tools["definitions"]))


if __name__ == "__main__":
    unittest.main()
