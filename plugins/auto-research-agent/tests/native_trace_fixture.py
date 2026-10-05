import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from stage2_common import canonical_hash


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


class NativeTraceFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "trace"
        (self.root / "payloads").mkdir(parents=True)
        self.rollout = "root-thread"
        self.events = []
        self.payloads = {}
        self._event("rollout_started", trace_id="trace-1", root_thread_id=self.rollout)
        self._thread_start(self.rollout)

    def _payload(self, value):
        name = f"payloads/{len(self.payloads) + 1}.json"
        self.payloads[name] = value
        return {
            "raw_payload_id": f"raw:{len(self.payloads)}",
            "kind": {"type": "test"},
            "path": name,
        }

    def _event(self, payload_type, *, thread=None, turn=None, **values):
        self.events.append(
            {
                "schema_version": 1,
                "seq": len(self.events) + 1,
                "wall_time_unix_ms": len(self.events) + 100,
                "rollout_id": self.rollout,
                "thread_id": thread,
                "codex_turn_id": turn,
                "payload": {"type": payload_type, **values},
            }
        )

    def _thread_start(self, thread, parent=None):
        metadata = {"thread_id": thread}
        if parent is not None:
            metadata["parent_thread_id"] = parent
        self._event(
            "thread_started",
            thread_id=thread,
            metadata_payload=self._payload(metadata),
        )
        self._event(
            "codex_turn_started",
            thread=thread,
            turn=f"turn-{thread}",
            thread_id=thread,
            codex_turn_id=f"turn-{thread}",
        )

    def _turn_end(self, thread, status="completed"):
        self._event(
            "codex_turn_ended",
            thread=thread,
            turn=f"turn-{thread}",
            codex_turn_id=f"turn-{thread}",
            status=status,
        )

    def _inference(
        self,
        call_id,
        response_id,
        *,
        thread=None,
        previous=None,
        tools=True,
        usage=True,
    ):
        thread = thread or self.rollout
        request = {"model": "model", "input": []}
        if previous is not None:
            request["previous_response_id"] = previous
        if tools:
            request["input"].append(
                {
                    "type": "additional_tools",
                    "role": "developer",
                    "tools": [
                        {
                            "type": "namespace",
                            "name": "functions",
                            "tools": [{"type": "custom", "name": "exec"}],
                        },
                        {"type": "function", "name": "plain"},
                    ],
                }
            )
        request_ref = self._payload(request)
        self._event(
            "inference_started",
            thread=thread,
            turn=f"turn-{thread}",
            inference_call_id=call_id,
            thread_id=thread,
            codex_turn_id=f"turn-{thread}",
            request_payload=request_ref,
        )
        response = {"response_id": response_id, "output_items": []}
        if usage:
            response["token_usage"] = {
                "input_tokens": 10,
                "cached_input_tokens": 7,
                "cache_write_input_tokens": 0,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
                "total_tokens": 12,
            }
        self._event(
            "inference_completed",
            thread=thread,
            turn=f"turn-{thread}",
            inference_call_id=call_id,
            response_id=response_id,
            response_payload=self._payload(response),
        )

    def _finish(self):
        self._turn_end(self.rollout)
        self._event("thread_ended", thread_id=self.rollout, status="completed")
        self._event("rollout_ended", status="completed")

    def _write(self):
        manifest = {
            "schema_version": 1,
            "trace_id": "trace-1",
            "rollout_id": self.rollout,
            "root_thread_id": self.rollout,
            "started_at_unix_ms": 1,
            "raw_event_log": "trace.jsonl",
            "payloads_dir": "payloads",
        }
        (self.root / "manifest.json").write_bytes(_bytes(manifest))
        (self.root / "trace.jsonl").write_bytes(
            b"".join(_bytes(row) for row in self.events)
        )
        for name, value in self.payloads.items():
            (self.root / name).write_bytes(_bytes(value))
        receipt = {
            path.relative_to(self.root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        return receipt, canonical_hash(receipt)

    def _inspect(self):
        # The observer lands after this reusable fixture/parser slice.
        from stage2_live.trace_observation import inspect_native_trace

        receipt, digest = self._write()
        return inspect_native_trace(self.root, receipt, digest)
