"""Synthetic mechanics tests for pure typed tool-witness projection.

These in-memory rows are not authentic execution, authentication, or readiness
evidence. They only exercise parsing and lifecycle validation.
"""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live.preflight_trace_witnesses import project_tool_witness  # noqa: E402


def _bytes(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


class ToolWitnessProjectionTests(unittest.TestCase):
    root_thread_id = "synthetic-root-thread"
    call_id = "synthetic-call"

    def fixture(self, *, kind="exec_command", runtime="pair"):
        invocation = {
            "tool_name": "exec_command" if kind == "exec_command" else kind,
            "tool_namespace": None if kind == "exec_command" else "synthetic",
            "payload": {
                "type": "function",
                "arguments": json.dumps(
                    {
                        "cmd": "Write-Output synthetic-mechanics-only",
                        "options": {"login": False, "max_output_tokens": 17},
                    },
                    separators=(",", ":"),
                ),
            },
        }
        result = {"type": "function_call_output", "value": {"output": "synthetic"}}
        raw = {
            "payloads/invocation.json": _bytes(invocation),
            "payloads/result.json": _bytes(result),
        }

        def ref(name, reference_kind):
            return {
                "raw_payload_id": f"synthetic:{name}",
                "kind": {"type": reference_kind},
                "path": f"payloads/{name}.json",
            }

        rows = [
            {
                "seq": 1,
                "event_id": "synthetic-event-start",
                "thread_id": self.root_thread_id,
                "payload": {
                    "type": "tool_call_started",
                    "tool_call_id": self.call_id,
                    "requester": {
                        "type": "code_cell",
                        "runtime_cell_id": "synthetic-cell",
                    },
                    "kind": {"type": kind},
                    "invocation_payload": ref("invocation", "tool_invocation"),
                },
            }
        ]
        sequence = 2
        if runtime == "pair":
            runtime_start = {"call_id": self.call_id, "started_at_ms": 10}
            raw["payloads/runtime-start.json"] = _bytes(runtime_start)
            rows.append(
                {
                    "seq": sequence,
                    "event_id": "synthetic-event-runtime-start",
                    "thread_id": self.root_thread_id,
                    "payload": {
                        "type": "tool_call_runtime_started",
                        "tool_call_id": self.call_id,
                        "runtime_payload": ref("runtime-start", "tool_runtime_event"),
                    },
                }
            )
            sequence += 1
        if runtime in {"pair", "end-only"}:
            runtime_end = (
                {"call_id": self.call_id, "status": "completed", "completed_at_ms": 20}
                if runtime == "pair"
                else {"agent_thread_id": "synthetic-child", "kind": "spawn_agent"}
            )
            raw["payloads/runtime-end.json"] = _bytes(runtime_end)
            rows.append(
                {
                    "seq": sequence,
                    "event_id": "synthetic-event-runtime-end",
                    "thread_id": self.root_thread_id,
                    "payload": {
                        "type": "tool_call_runtime_ended",
                        "tool_call_id": self.call_id,
                        "status": "completed",
                        "runtime_payload": ref("runtime-end", "tool_runtime_event"),
                    },
                }
            )
            sequence += 1
        rows.append(
            {
                "seq": sequence,
                "event_id": "synthetic-event-end",
                "thread_id": self.root_thread_id,
                "payload": {
                    "type": "tool_call_ended",
                    "tool_call_id": self.call_id,
                    "status": "completed",
                    "result_payload": ref("result", "tool_result"),
                },
            }
        )
        raw["trace.jsonl"] = b"\n".join(_bytes(row) for row in rows) + b"\n"
        return raw, rows, invocation, result

    def project(self, raw):
        return project_tool_witness(raw, self.root_thread_id, self.call_id)

    def rewrite(self, raw, rows):
        raw["trace.jsonl"] = b"\n".join(_bytes(row) for row in rows) + b"\n"

    def test_nested_code_cell_native_exec_arguments_and_refs_are_preserved(self):
        raw, _, invocation, result = self.fixture()
        witness = self.project(raw)
        expected_refs = [
            ("invocation", "synthetic-event-start", 1, "payloads/invocation.json"),
            (
                "runtime_start",
                "synthetic-event-runtime-start",
                2,
                "payloads/runtime-start.json",
            ),
            (
                "runtime_end",
                "synthetic-event-runtime-end",
                3,
                "payloads/runtime-end.json",
            ),
            ("result", "synthetic-event-end", 4, "payloads/result.json"),
        ]
        self.assertEqual(witness["invocation"], invocation)
        self.assertEqual(witness["result"], result)
        self.assertEqual(
            json.loads(witness["invocation"]["payload"]["arguments"])["options"],
            {"login": False, "max_output_tokens": 17},
        )
        self.assertEqual(
            [
                (ref["role"], ref["event_id"], ref["seq"], ref["path"])
                for ref in witness["evidence_refs"]
            ],
            expected_refs,
        )
        self.assertTrue(
            all(
                ref["sha256"] == hashlib.sha256(raw[ref["path"]]).hexdigest()
                for ref in witness["evidence_refs"]
            )
        )

    def test_web_without_runtime_is_accepted(self):
        raw, _, _, _ = self.fixture(kind="other", runtime="none")
        witness = self.project(raw)
        self.assertEqual(
            (witness["runtime_start"], witness["runtime_end"]), (None, None)
        )
        self.assertEqual(
            [ref["role"] for ref in witness["evidence_refs"]], ["invocation", "result"]
        )

    def test_empty_referenced_objects_and_foreign_spawn_identity_reject(self):
        for name in ("invocation", "result", "runtime-end"):
            with self.subTest(name=name):
                raw, _, _, _ = self.fixture(kind="spawn_agent", runtime="end-only")
                raw[f"payloads/{name}.json"] = _bytes({})
                with self.assertRaisesRegex(Stage2Error, "payload-invalid"):
                    self.project(raw)
        for field, value, reason in (
            ("sender_thread_id", "foreign-root", "sender-thread"),
            ("event_id", "different-call", "event-id"),
        ):
            with self.subTest(field=field):
                raw, _, _, _ = self.fixture(kind="spawn_agent", runtime="end-only")
                runtime = json.loads(raw["payloads/runtime-end.json"])
                runtime[field] = value
                raw["payloads/runtime-end.json"] = _bytes(runtime)
                with self.assertRaisesRegex(Stage2Error, reason):
                    self.project(raw)

    def test_end_only_spawn_runtime_is_accepted(self):
        raw, _, _, _ = self.fixture(kind="spawn_agent", runtime="end-only")
        witness = self.project(raw)
        self.assertIsNone(witness["runtime_start"])
        self.assertEqual(witness["runtime_end"]["agent_thread_id"], "synthetic-child")

    def test_native_web_and_spawn_envelopes_are_preserved(self):
        raw, _, _, _ = self.fixture(kind="other", runtime="none")
        web = {"type": "code_mode_response", "value": "synthetic search result"}
        raw["payloads/result.json"] = _bytes(web)
        self.assertEqual(self.project(raw)["result"], web)
        raw, _, _, _ = self.fixture(kind="spawn_agent", runtime="end-only")
        spawned = {"type": "direct_response", "value": {"id": "synthetic-child"}}
        runtime = {
            "event_id": self.call_id,
            "kind": "started",
            "sender_thread_id": self.root_thread_id,
            "agent_thread_id": "synthetic-child",
        }
        raw["payloads/result.json"] = _bytes(spawned)
        raw["payloads/runtime-end.json"] = _bytes(runtime)
        witness = self.project(raw)
        self.assertEqual(witness["runtime_end"], runtime)
        self.assertEqual(witness["result"], spawned)

    def test_duplicate_start_and_end_are_rejected(self):
        for event_type, error in (
            ("tool_call_started", "start-count"),
            ("tool_call_ended", "end-count"),
        ):
            with self.subTest(event_type=event_type):
                raw, rows, _, _ = self.fixture(runtime="none")
                duplicate = copy.deepcopy(
                    next(row for row in rows if row["payload"]["type"] == event_type)
                )
                duplicate["seq"] = rows[-1]["seq"] + 1
                rows.append(duplicate)
                self.rewrite(raw, rows)
                with self.assertRaisesRegex(Stage2Error, error):
                    self.project(raw)

    def test_missing_or_failed_end_is_rejected(self):
        raw, rows, _, _ = self.fixture(runtime="none")
        rows.pop()
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "end-count"):
            self.project(raw)
        raw, rows, _, _ = self.fixture(runtime="none")
        rows[-1]["payload"]["status"] = "failed"
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "end-incomplete"):
            self.project(raw)

    def test_foreign_thread_and_reversed_chronology_are_rejected(self):
        raw, rows, _, _ = self.fixture(runtime="none")
        rows[-1]["thread_id"] = "synthetic-foreign-thread"
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "foreign-thread"):
            self.project(raw)
        raw, rows, _, _ = self.fixture(runtime="none")
        rows[0]["seq"], rows[-1]["seq"] = rows[-1]["seq"], rows[0]["seq"]
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "event-invalid|chronology"):
            self.project(raw)

    def test_malformed_payload_and_reference_are_rejected(self):
        raw, rows, _, _ = self.fixture(runtime="none")
        rows[0]["payload"] = []
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "event-invalid"):
            self.project(raw)
        raw, rows, _, _ = self.fixture(runtime="none")
        rows[0]["payload"]["invocation_payload"].pop("path")
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "payload-reference-invalid"):
            self.project(raw)

    def test_runtime_duplicates_missing_end_failure_and_call_id_mismatch_reject(self):
        for index, error in ((1, "runtime-start-count"), (2, "runtime-end-count")):
            with self.subTest(error=error):
                raw, rows, _, _ = self.fixture()
                duplicate = copy.deepcopy(rows[index])
                duplicate["seq"] = rows[-1]["seq"] + 1
                rows.append(duplicate)
                self.rewrite(raw, rows)
                with self.assertRaisesRegex(Stage2Error, error):
                    self.project(raw)

        raw, rows, _, _ = self.fixture()
        rows.remove(
            next(
                row
                for row in rows
                if row["payload"]["type"] == "tool_call_runtime_ended"
            )
        )
        for number, row in enumerate(rows, 1):
            row["seq"] = number
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "runtime-end-missing"):
            self.project(raw)

        raw, rows, _, _ = self.fixture()
        runtime_end = next(
            row for row in rows if row["payload"]["type"] == "tool_call_runtime_ended"
        )
        runtime_end["payload"]["status"] = "failed"
        self.rewrite(raw, rows)
        with self.assertRaisesRegex(Stage2Error, "runtime-end-incomplete"):
            self.project(raw)

        raw, _, _, _ = self.fixture()
        raw["payloads/runtime-end.json"] = _bytes(
            {"call_id": self.call_id, "status": "failed"}
        )
        with self.assertRaisesRegex(Stage2Error, "runtime-payload-incomplete"):
            self.project(raw)

        raw, _, _, _ = self.fixture()
        raw["payloads/runtime-start.json"] = _bytes({"call_id": "synthetic-other-call"})
        with self.assertRaisesRegex(Stage2Error, "runtime-start-call-id"):
            self.project(raw)


if __name__ == "__main__":
    unittest.main()
