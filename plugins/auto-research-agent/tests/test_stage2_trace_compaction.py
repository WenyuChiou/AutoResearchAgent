import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error  # noqa: E402
from stage2_live.trace_compaction import CompactionState  # noqa: E402


def _ref(raw, name, value):
    raw[name] = json.dumps(value, sort_keys=True).encode()
    return {"raw_payload_id": name, "kind": {"type": "test"}, "path": name}


def _row(kind, *, thread="thread-1", turn="turn-1", **payload):
    return {
        "thread_id": thread,
        "codex_turn_id": turn,
        "payload": {"type": kind, **payload},
    }


def _start(raw, request_id, compaction_id="compact-1"):
    return _row(
        "compaction_request_started",
        compaction_id=compaction_id,
        compaction_request_id=request_id,
        thread_id="thread-1",
        codex_turn_id="turn-1",
        request_payload=_ref(raw, f"payloads/{request_id}-request.json", {"input": []}),
    )


def _usage():
    return {
        "input_tokens": 3,
        "cached_input_tokens": 1,
        "cache_write_input_tokens": 0,
        "output_tokens": 2,
        "reasoning_output_tokens": 1,
        "total_tokens": 5,
    }


class CompactionStateTests(unittest.TestCase):
    def test_legacy_scope_and_container_ids_fail_closed(self):
        for thread, turn in (
            (None, "turn"),
            ("thread", None),
            (None, None),
            ("", "turn"),
        ):
            with self.subTest(thread=thread, turn=turn):
                with self.assertRaisesRegex(Stage2Error, "compaction-scope-mismatch"):
                    CompactionState().observe(
                        _row(
                            "compaction_started",
                            thread=thread,
                            turn=turn,
                            compaction_id="c1",
                        ),
                        {},
                    )
        for identity in ([], {}, None, ""):
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(Stage2Error, "compaction-id-invalid"):
                    CompactionState().observe(
                        _row(
                            "compaction_completed",
                            compaction_id=identity,
                            token_usage=_usage(),
                        ),
                        {},
                    )

    def test_real_wire_missing_usage_and_distinct_retry_requests(self):
        raw, state = {}, CompactionState()
        state.observe(_start(raw, "request-1"), raw)
        completed = _row(
            "compaction_request_completed",
            compaction_id="compact-1",
            compaction_request_id="request-1",
            response_payload=_ref(raw, "payloads/response.json", {"output_items": []}),
        )
        state.observe(completed, raw)
        state.observe(_start(raw, "request-2"), raw)
        state.observe(
            _row(
                "compaction_request_failed",
                compaction_id="compact-1",
                compaction_request_id="request-2",
                error="retryable",
            ),
            raw,
        )
        self.assertEqual(state.attempts, {"request-1": None, "request-2": None})
        self.assertEqual(state.events, 4)
        self.assertFalse(state.unverified)

    def test_completed_usage_duplicate_and_payload_hash_conflict(self):
        raw, state = {}, CompactionState()
        state.observe(_start(raw, "request-1"), raw)
        completed = _row(
            "compaction_request_completed",
            compaction_id="compact-1",
            compaction_request_id="request-1",
            response_payload=_ref(
                raw,
                "payloads/response.json",
                {"output_items": [], "token_usage": _usage()},
            ),
        )
        state.observe(completed, raw)
        state.observe(completed, raw)
        self.assertEqual(state.attempts["request-1"], _usage())
        self.assertEqual(state.events, 3)
        raw["payloads/response.json"] = b'{"output_items":[{}]}'
        with self.assertRaisesRegex(Stage2Error, "conflicting-compaction-terminal"):
            state.observe(completed, raw)

    def test_scope_reference_and_typed_usage_fail_closed(self):
        raw, state = {}, CompactionState()
        state.observe(_start(raw, "request-1"), raw)
        response = _ref(raw, "payloads/response.json", {"token_usage": _usage()})
        bad_scope = _row(
            "compaction_request_completed",
            thread="other",
            compaction_id="compact-1",
            compaction_request_id="request-1",
            response_payload=response,
        )
        with self.assertRaisesRegex(Stage2Error, "compaction-scope-mismatch"):
            state.observe(bad_scope, raw)
        raw["payloads/response.json"] = b'{"token_usage":{"input_tokens":true}}'
        good_scope = {**bad_scope, "thread_id": "thread-1"}
        with self.assertRaisesRegex(Stage2Error, "token-usage-invalid"):
            state.observe(good_scope, raw)
        good_scope["payload"]["response_payload"]["path"] = "payloads/missing.json"
        with self.assertRaisesRegex(Stage2Error, "payload-reference-invalid"):
            state.observe(good_scope, raw)

    def test_legacy_inline_usage_overlap_and_unknown_protocol(self):
        state = CompactionState()
        state.observe(_row("compaction_started", compaction_id="call-1"), {})
        state.observe(_row("compaction_progress", compaction_id="call-1"), {})
        state.observe(
            _row("compaction_completed", compaction_id="call-1", token_usage=_usage()),
            {},
        )
        self.assertEqual(state.attempts, {"call-1": _usage()})
        self.assertEqual(state.finalize(["call-1", "call-1"]), state.attempts)
        self.assertTrue(state.unverified)
        self.assertEqual(state.events, 3)

        unknown = CompactionState()
        unknown.observe(
            _row("protocol_event_observed", event_type="future_compaction_signal"), {}
        )
        self.assertTrue(unknown.unverified)
        self.assertEqual(unknown.events, 1)
