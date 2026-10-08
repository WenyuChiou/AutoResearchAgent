"""Shared synthetic fixture for observed preflight tests."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_live import preflight  # noqa: E402


def _bytes(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


class ObservedPreflightFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.capture = Path(self.temporary.name).resolve() / "capture"
        self.trace_root = Path(self.temporary.name).resolve() / "telemetry"
        self.workspace = PurePosixPath("/synthetic-workspace")
        self.shell = PurePosixPath("/bin/bash")
        self.nonce = "synthetic-nonce-visible-only-after-read"
        self.written = b"synthetic-written-bytes\n"
        (self.capture / "archive/workspace-start/input").mkdir(parents=True)
        (self.capture / "archive/workspace-end/output").mkdir(parents=True)
        (self.capture / "archive/native-sessions").mkdir(parents=True)
        (self.capture / "archive/workspace-start/input/nonce.txt").write_text(
            self.nonce, encoding="utf-8"
        )
        (self.capture / "archive/workspace-end/output/result.txt").write_bytes(
            self.written
        )
        (self.capture / "archive/native-sessions/root.jsonl").write_text(
            "{}\n", encoding="utf-8"
        )
        self.request = {
            "capture_dir": str(self.capture),
            "trace_root": str(self.trace_root),
        }
        self.spec = {
            "kind": "Stage2ProductionRuntimeProbeSpec",
            "schema_version": "1.2.0",
            "executor": {
                "shell_path": str(self.shell),
                "shell_sha256": "a" * 64,
                "working_directory": str(self.workspace),
                "family": "posix",
            },
            "expected": {
                "model": "synthetic-model",
                "reasoning": "synthetic-effort",
                "sandbox": "workspace-write",
                "network_access": True,
            },
            "probes": {
                "read": {
                    "event_id": "read-call",
                    "source_path": "input/nonce.txt",
                    "command_path": str(self.workspace / "input/nonce.txt"),
                    "nonce": self.nonce,
                },
                "write": {
                    "event_id": "write-call",
                    "output_path": "output/result.txt",
                    "sha256": hashlib.sha256(self.written).hexdigest(),
                },
                "search": {"event_id": "search-call"},
                "child": {
                    "event_id": "child-call",
                    "child_thread_id": "child-thread",
                },
            },
            "observation": {
                "telemetry_root": str(self.trace_root),
                "producer_receipt": "p" * 64,
                "capture_request": self.request,
            },
        }

    def _ref(self, raw, name, value, kind):
        path = f"payloads/{name}.json"
        raw[path] = _bytes(value)
        return {"raw_payload_id": f"raw:{name}", "kind": {"type": kind}, "path": path}

    def _fixture(self):
        raw, rows = {}, []

        def event(payload, *, thread="root-thread", event_id=None):
            row = {
                "seq": len(rows) + 1,
                "thread_id": thread,
                "codex_turn_id": f"turn-{thread}",
                "payload": payload,
            }
            if event_id is not None:
                row["event_id"] = event_id
            rows.append(row)
            return row

        request_ref = self._ref(
            raw,
            "initial-request",
            {
                "model": "synthetic-model",
                "input": [{"role": "user", "content": "begin"}],
            },
            "model_request",
        )
        event(
            {
                "type": "inference_started",
                "inference_call_id": "initial-inference",
                "request_payload": request_ref,
            }
        )

        def tool(call_id, invocation, result, *, runtime=True, runtime_end=None):
            invocation_ref = self._ref(
                raw, f"{call_id}-invocation", invocation, "tool_invocation"
            )
            event(
                {
                    "type": "tool_call_started",
                    "tool_call_id": call_id,
                    "kind": {"type": invocation["tool_name"]},
                    "invocation_payload": invocation_ref,
                },
                event_id=f"{call_id}-start",
            )
            if runtime:
                command = json.loads(invocation["payload"]["arguments"])["cmd"]
                common = {
                    "call_id": call_id,
                    "command": [str(self.shell), "-c", command],
                    "cwd": str(self.workspace),
                    "process_id": 101,
                    "turn_id": "turn-root-thread",
                }
                started = self._ref(
                    raw, f"{call_id}-runtime-start", common, "tool_runtime_event"
                )
                event(
                    {
                        "type": "tool_call_runtime_started",
                        "tool_call_id": call_id,
                        "runtime_payload": started,
                    }
                )
                ended_value = {
                    **common,
                    "exit_code": 0,
                    "aggregated_output": result["value"]["output"],
                }
                ended_value.update(runtime_end or {})
                ended = self._ref(
                    raw, f"{call_id}-runtime-end", ended_value, "tool_runtime_event"
                )
                event(
                    {
                        "type": "tool_call_runtime_ended",
                        "tool_call_id": call_id,
                        "status": "completed",
                        "runtime_payload": ended,
                    }
                )
            elif runtime_end is not None:
                ended = self._ref(
                    raw, f"{call_id}-runtime-end", runtime_end, "tool_runtime_event"
                )
                event(
                    {
                        "type": "tool_call_runtime_ended",
                        "tool_call_id": call_id,
                        "status": "completed",
                        "runtime_payload": ended,
                    }
                )
            result_ref = self._ref(raw, f"{call_id}-result", result, "tool_result")
            event(
                {
                    "type": "tool_call_ended",
                    "tool_call_id": call_id,
                    "status": "completed",
                    "result_payload": result_ref,
                },
                event_id=f"{call_id}-end",
            )

        def invocation(name, namespace, arguments):
            return {
                "tool_name": name,
                "tool_namespace": namespace,
                "payload": {"type": "function", "arguments": json.dumps(arguments)},
            }

        read_command = preflight.read_probe_command(
            self.spec["probes"]["read"]["command_path"], "posix"
        )
        execution = {
            "shell": str(self.shell),
            "workdir": str(self.workspace),
            "login": False,
        }
        tool(
            "read-call",
            invocation("exec_command", None, {**execution, "cmd": read_command}),
            {
                "type": "code_mode_response",
                "value": {"exit_code": 0, "output": self.nonce},
            },
        )
        write_target = str(self.workspace / "output/result.txt")
        write_text = self.written.decode("utf-8")
        write_command = (
            f"printf %s {shlex.quote(write_text)} > {shlex.quote(write_target)}"
        )
        tool(
            "write-call",
            invocation(
                "exec_command", "functions", {**execution, "cmd": write_command}
            ),
            {"type": "code_mode_response", "value": {"exit_code": 0, "output": ""}},
        )
        tool(
            "search-call",
            invocation("run", "web", {"search_query": [{"q": "synthetic query"}]}),
            {
                "type": "code_mode_response",
                "value": "Synthetic source (https://example.org/study) \ue200cite\ue202turn0search0\ue201",
            },
            runtime=False,
        )
        tool(
            "child-call",
            invocation("spawn_agent", "collaboration", {"task_name": "synthetic"}),
            {"type": "code_mode_response", "value": "synthetic child started"},
            runtime=False,
            runtime_end={
                "event_id": "child-call",
                "agent_thread_id": "child-thread",
                "kind": "started",
            },
        )
        configured = self._ref(
            raw,
            "child-configured",
            {
                "thread_id": "child-thread",
                "parent_thread_id": "root-thread",
                "forked_from_id": "root-thread",
                "model": "synthetic-model",
                "reasoning_effort": "synthetic-effort",
            },
            "protocol_event",
        )
        event(
            {
                "type": "protocol_event_observed",
                "event_type": "session_configured",
                "event_payload": configured,
            },
            thread="child-thread",
        )
        carried = self._ref(
            raw,
            "child-result",
            {"status": {"completed": "done"}, "message": "done"},
            "agent_result",
        )
        event(
            {
                "type": "agent_result_observed",
                "child_thread_id": "child-thread",
                "parent_thread_id": "root-thread",
                "message": "done",
                "carried_payload": carried,
            },
            thread="child-thread",
        )
        event(
            {
                "type": "thread_ended",
                "thread_id": "child-thread",
                "status": "completed",
            },
            thread="child-thread",
        )
        raw["trace.jsonl"] = b"\n".join(_bytes(row) for row in rows) + b"\n"
        return raw, rows

    def _rewrite(self, raw, rows):
        raw["trace.jsonl"] = b"\n".join(_bytes(row) for row in rows) + b"\n"

    def _change_tool_command(self, raw, call_id, command):
        invocation_path = f"payloads/{call_id}-invocation.json"
        invocation = json.loads(raw[invocation_path])
        arguments = json.loads(invocation["payload"]["arguments"])
        arguments["cmd"] = command
        invocation["payload"]["arguments"] = json.dumps(arguments)
        raw[invocation_path] = _bytes(invocation)
        for phase in ("start", "end"):
            path = f"payloads/{call_id}-runtime-{phase}.json"
            runtime = json.loads(raw[path])
            runtime["command"] = [str(self.shell), "-c", command]
            raw[path] = _bytes(runtime)

    def _native_child_case(self):
        raw, rows = self._fixture()
        for thread_id, turn_id in (
            ("root-thread", "root-turn"),
            ("child-thread", "child-turn"),
        ):
            rows.append(
                {
                    "seq": len(rows) + 1,
                    "thread_id": thread_id,
                    "codex_turn_id": turn_id,
                    "payload": {
                        "type": "codex_turn_started",
                        "thread_id": thread_id,
                        "codex_turn_id": turn_id,
                    },
                }
            )
        self._rewrite(raw, rows)
        sessions = [
            [
                {
                    "type": "turn_context",
                    "payload": {"turn_id": "root-turn", "marker": "inherited"},
                },
                {
                    "type": "turn_context",
                    "payload": {"turn_id": "child-turn", "marker": "child"},
                },
            ]
        ]
        actual = {
            **self.spec["expected"],
            "permission_workspace_write": True,
            "approval_policy": "never",
        }
        stable = {"workspace": str(self.workspace)}
        return raw, rows, sessions, stable, actual
