"""Synthetic bytes for the no-tool archive/trace join contract."""

import hashlib
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live.no_tool_trace_evidence import verify_no_tool_trace_evidence  # noqa: E402
from native_trace_fixture import NativeTraceFixture  # noqa: E402


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True).encode() + b"\n")


class NoToolTraceEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.archive = self.base / "extract.model-call"
        self.archive.mkdir()
        self.expected = {
            "model": "synthetic-model",
            "reasoning": "medium",
            "sandbox_mode": "read-only",
            "approval_policy": "never",
        }
        config = {"model": "synthetic-model", "reasoning": "medium"}
        fingerprint = "f" * 64
        _write(
            self.archive / "request.json",
            {
                "archive_version": "3.1.0",
                "label": "extract",
                "config": config,
                "request_fingerprint_sha256": fingerprint,
            },
        )
        records, stdouts = [], []
        for number, (root, status, error) in enumerate(
            (
                ("retry-root", "failed", "transient-transport"),
                ("final-root", "completed", None),
            ),
            1,
        ):
            stdout = (
                json.dumps({"type": "thread.started", "thread_id": root}) + "\n"
            ).encode()
            stdout_path = self.archive / f"attempt-{number:02d}.stdout.jsonl"
            stdout_path.write_bytes(stdout)
            record_path = self.archive / f"attempt-{number:02d}.record.json"
            _write(
                record_path,
                {
                    "archive_version": "3.1.0",
                    "attempt": number,
                    "request_fingerprint_sha256": fingerprint,
                    "config": config,
                    "generation_status": status,
                    "failure_class": error,
                    "files": {
                        "stdout": {
                            "path": stdout_path.name,
                            "sha256": hashlib.sha256(stdout).hexdigest(),
                        }
                    },
                },
            )
            records.append(record_path)
            stdouts.append(stdout_path)
        self.provenance = {
            "execution_status": "native-replayed",
            "call_archive": str(self.archive),
            "request_fingerprint_sha256": fingerprint,
            "config": config,
            "attempt": 2,
            "attempt_record_sha256": hashlib.sha256(
                records[-1].read_bytes()
            ).hexdigest(),
            "stdout_sha256": hashlib.sha256(stdouts[-1].read_bytes()).hexdigest(),
        }
        self.trace_root = self.base / "traces"
        self.inventories, self.roots = {}, {}
        for number, root in enumerate(("retry-root", "final-root"), 1):
            trace = self.trace_root / f"trace-{number}"
            _write(
                trace / "payloads/config.json",
                {
                    "thread_id": root,
                    "model": "synthetic-model",
                    "reasoning_effort": "medium",
                    "sandbox_policy": {"type": "read-only"},
                    "approval_policy": "never",
                },
            )
            _write(
                trace / "trace.jsonl",
                {
                    "payload": {
                        "type": "protocol_event_observed",
                        "event_type": "session_configured",
                        "event_payload": {
                            "path": "payloads/config.json",
                            "raw_payload_id": "x",
                            "kind": {"type": "test"},
                        },
                    }
                },
            )
            (trace / "manifest.json").write_bytes(b"{}\n")
            _write(
                trace / "payloads/request.json",
                {"model": "synthetic-model", "input": [], "tools": []},
            )
            self.inventories[trace.name] = self._inventory(trace)
            self.roots[trace.name] = root
        self.seal = self.base / "original-seal.json"
        self._write_seal()

    @staticmethod
    def _inventory(trace):
        return {
            path.relative_to(trace).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in trace.rglob("*")
            if path.is_file()
        }

    def _write_seal(self):
        _write(
            self.seal,
            {
                "kind": "Stage2NoToolTraceSeal",
                "schema_version": "1.0.0",
                "request_fingerprint_sha256": self.provenance[
                    "request_fingerprint_sha256"
                ],
                "attempt_record_sha256": self.provenance["attempt_record_sha256"],
                "stdout_sha256": self.provenance["stdout_sha256"],
                "traces": self.inventories,
            },
        )
        self.seal_sha = hashlib.sha256(self.seal.read_bytes()).hexdigest()

    def _observation(self, trace, *_args):
        root = self.roots[trace.name]
        complete = root == "final-root"
        usage = {
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "cache_write_input_tokens": 0,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
            "total_tokens": 12,
        }
        return {
            "root_thread_id": root,
            "inferences": [
                {
                    "status": "inference_completed",
                    "token_usage": usage,
                    "request_ref": "payloads/request.json",
                }
            ]
            if complete
            else [],
            "threads": [
                {
                    "thread_id": root,
                    "terminal_status": "completed" if complete else "failed",
                    "offered_tools": {
                        "definitions": [],
                        "counts": {
                            "namespace": 0,
                            "custom": 0,
                            "function": 0,
                            "other": 0,
                        },
                    },
                }
            ],
            "counts": {"tool_calls": 0},
            "blockers": [] if complete else ["rollout-not-completed"],
        }

    def verify(self, observer=None):
        with patch(
            "stage2_live.no_tool_trace_evidence.inspect_native_trace",
            side_effect=observer or self._observation,
        ):
            return verify_no_tool_trace_evidence(
                self.provenance,
                self.trace_root,
                self.seal,
                self.seal_sha,
                expected_config=self.expected,
            )

    def test_joins_all_attempts_retains_failure_and_unknown_usage(self):
        result = self.verify()
        self.assertEqual(result["matched_roots"], ["final-root", "retry-root"])
        self.assertEqual(
            [row["status"] for row in result["attempts"]], ["failure", "completed"]
        )
        self.assertEqual(result["attempts"][0]["error"], "transient-transport")
        self.assertTrue(
            all(value is None for value in result["token_usage_totals"].values())
        )
        self.assertEqual((result["new_model_calls"], result["new_tool_calls"]), (0, 0))

    def test_rejects_changed_archive_or_original_seal_bytes(self):
        stdout = self.archive / "attempt-01.stdout.jsonl"
        stdout.write_bytes(stdout.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(Stage2Error, "attempt-binding-mismatch"):
            self.verify()
        self.setUp()
        self.seal.write_bytes(self.seal.read_bytes() + b" ")
        with self.assertRaisesRegex(Stage2Error, "original-seal-mismatch"):
            self.verify()
        self.setUp()
        value = json.loads(self.seal.read_bytes())
        value["stdout_sha256"] = "0" * 64
        _write(self.seal, value)
        self.seal_sha = hashlib.sha256(self.seal.read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "seal-archive-binding-mismatch"):
            self.verify()

    def test_rejects_missing_extra_and_foreign_trace_roots(self):
        inventory = self.inventories.pop("trace-2")
        self._write_seal()
        with self.assertRaisesRegex(Stage2Error, "trace-inventory-mismatch"):
            self.verify()
        self.inventories["trace-2"] = inventory
        extra = self.trace_root / "trace-extra"
        extra.mkdir()
        self._write_seal()
        with self.assertRaisesRegex(Stage2Error, "trace-inventory-mismatch"):
            self.verify()
        extra.rmdir()
        self.roots["trace-2"] = "retry-root"
        with self.assertRaisesRegex(Stage2Error, "foreign-or-duplicate-root"):
            self.verify()

    def test_rejects_tools_children_incomplete_and_config_drift(self):
        original = self._observation
        for update, error in (
            ({"counts": {"tool_calls": 1}}, "tool-activity"),
            ({"threads": [{}, {}]}, "child-activity"),
            ({"blockers": ["tool-call-terminal-missing:x"]}, "trace-incomplete"),
        ):

            def changed(trace, *args, update=update):
                value = original(trace, *args)
                value.update(update)
                return value

            with self.subTest(error=error), self.assertRaisesRegex(Stage2Error, error):
                self.verify(changed)
        config = self.trace_root / "trace-2/payloads/config.json"
        value = json.loads(config.read_bytes())
        value["reasoning_effort"] = "changed"
        _write(config, value)
        self.inventories["trace-2"] = self._inventory(self.trace_root / "trace-2")
        self._write_seal()
        with self.assertRaisesRegex(Stage2Error, "effective-config-mismatch"):
            self.verify()

    def _real_traces(
        self,
        *,
        final_tools=None,
        final_usage=True,
        retry_complete=False,
        compaction=False,
    ):
        for name, root in self.roots.items():
            fixture = NativeTraceFixture()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            fixture._event(
                "protocol_event_observed",
                event_type="session_configured",
                event_payload=fixture._payload(
                    {
                        "thread_id": fixture.rollout,
                        "model": "synthetic-model",
                        "reasoning_effort": "medium",
                        "sandbox_policy": {"type": "read-only"},
                        "approval_policy": "never",
                    }
                ),
            )
            fixture._inference("i1", "r1", tools=False, usage=final_usage)
            request = next(
                value for value in fixture.payloads.values() if "input" in value
            )
            request.update(
                model="synthetic-model",
                tools=[] if name == "trace-1" else final_tools or [],
            )
            if compaction and root == "final-root":
                fields = {
                    "thread": fixture.rollout,
                    "turn": f"turn-{fixture.rollout}",
                    "thread_id": fixture.rollout,
                    "codex_turn_id": f"turn-{fixture.rollout}",
                    "compaction_id": "compact-1",
                    "compaction_request_id": "request-1",
                }
                fixture._event(
                    "compaction_request_started",
                    request_payload=fixture._payload({"input": []}),
                    **fields,
                )
                fixture._event(
                    "compaction_request_completed",
                    response_payload=fixture._payload(
                        {
                            "output_items": [],
                            "token_usage": {
                                "input_tokens": 50,
                                "cached_input_tokens": 0,
                                "cache_write_input_tokens": 0,
                                "output_tokens": 10,
                                "reasoning_output_tokens": 0,
                                "total_tokens": 60,
                            },
                        }
                    ),
                    **fields,
                )
            fixture._finish()
            if root == "retry-root" and not retry_complete:
                for event in fixture.events:
                    payload = event["payload"]
                    if payload["type"] in {
                        "codex_turn_ended",
                        "thread_ended",
                        "rollout_ended",
                    }:
                        payload["status"] = "failed"
            fixture.events = json.loads(
                json.dumps(fixture.events).replace("root-thread", root)
            )
            fixture.payloads = json.loads(
                json.dumps(fixture.payloads).replace("root-thread", root)
            )
            fixture.rollout = root
            fixture._write()
            target = self.trace_root / name
            shutil.rmtree(target)
            shutil.copytree(fixture.root, target)
            self.inventories[name] = self._inventory(target)
        self._write_seal()

    def _verify_real(self):
        return verify_no_tool_trace_evidence(
            self.provenance,
            self.trace_root,
            self.seal,
            self.seal_sha,
            expected_config=self.expected,
        )

    def test_real_parser_rejects_unused_offered_tools(self):
        self._real_traces(final_tools=[{"type": "function", "name": "shell"}])
        with self.assertRaisesRegex(Stage2Error, "offered-tools-nonempty"):
            self._verify_real()

    def test_real_parser_unknown_usage_does_not_change_completed_status(self):
        self._real_traces(final_usage=False)
        result = self._verify_real()
        self.assertEqual(
            [item["status"] for item in result["attempts"]], ["failure", "completed"]
        )
        self.assertTrue(
            all(value is None for value in result["token_usage_totals"].values())
        )

    def test_real_parser_completed_terminal_cannot_match_failed_archive(self):
        self._real_traces(retry_complete=True, final_usage=False)
        with self.assertRaisesRegex(Stage2Error, "attempt-trace-status-mismatch"):
            self._verify_real()

    def test_real_parser_compaction_usage_is_not_silently_omitted(self):
        from stage2_live.trace_observation import inspect_native_trace
        from stage2_common import canonical_hash

        self._real_traces(compaction=True)
        inventory = self.inventories["trace-2"]
        observation = inspect_native_trace(
            self.trace_root / "trace-2", inventory, canonical_hash(inventory)
        )
        self.assertEqual(observation["counts"]["compactions"], 1)
        self.assertEqual(observation["token_usage_totals"]["total_tokens"], 72)
        result = self._verify_real()
        self.assertEqual(result["attempts"][1]["status"], "completed")
        self.assertTrue(
            all(value is None for value in result["attempts"][1]["usage"].values())
        )
        self.assertTrue(
            all(value is None for value in result["token_usage_totals"].values())
        )


if __name__ == "__main__":
    unittest.main()
