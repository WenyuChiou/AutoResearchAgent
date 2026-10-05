"""Tests for receipt-bound native rollout trace observation."""

import copy
from pathlib import Path
import sys
import unittest


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from native_trace_fixture import NativeTraceFixture  # noqa: E402


class NativeTraceObservationTests(NativeTraceFixture):
    def test_tools_in_request_and_same_thread_delta_are_observed(self):
        self._inference("i1", "r1")
        self._inference("i2", "r2", previous="r1", tools=False)
        self._finish()

        report = self._inspect()

        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["formal_ready"])
        self.assertEqual(
            report["token_usage_totals"],
            {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24},
        )
        self.assertEqual(report["inferences"][1]["tools_inherited"], True)
        self.assertEqual(
            report["threads"][0]["offered_tools"]["counts"],
            {"namespace": 1, "custom": 1, "function": 1, "other": 0},
        )

    def test_incomplete_turn_and_tool_are_blocked_without_false_failures(self):
        self._inference("i1", "r1")
        self._event(
            "tool_call_started",
            thread=self.rollout,
            turn="turn-root-thread",
            tool_call_id="unfinished",
            kind={"type": "wait_agent"},
        )
        self._event("thread_ended", thread_id=self.rollout, status="completed")
        self._event("rollout_ended", status="completed")

        report = self._inspect()

        self.assertIn("turn-terminal-missing:turn-root-thread", report["blockers"])
        self.assertIn("tool-call-terminal-missing:unfinished", report["blockers"])
        self.assertEqual(report["counts"]["incomplete_tool_calls"], 1)
        self.assertEqual(report["counts"]["failed_tool_calls"], 0)

    def test_inference_completion_after_turn_terminal_rejects(self):
        self._inference("i1", "r1")
        completion = self.events.pop()
        self._turn_end(self.rollout)
        self.events.append(completion)
        for number, row in enumerate(self.events, 1):
            row["seq"] = number

        with self.assertRaisesRegex(Stage2Error, "inference-chronology-invalid"):
            self._inspect()

    def test_tool_completion_after_turn_terminal_rejects(self):
        self._event(
            "tool_call_started",
            thread=self.rollout,
            turn="turn-root-thread",
            tool_call_id="late-tool",
            kind={"type": "wait_agent"},
        )
        self._turn_end(self.rollout)
        self._event(
            "tool_call_ended",
            thread=self.rollout,
            turn="turn-root-thread",
            tool_call_id="late-tool",
            status="completed",
        )

        with self.assertRaisesRegex(Stage2Error, "tool-call-chronology-invalid"):
            self._inspect()

    def test_only_authentic_completed_closure_is_allowed_after_rollout(self):
        self._inference("i1", "r1")
        self._thread_start("child", self.rollout)
        self._inference("i2", "r2", thread="child")
        self._turn_end("child")
        self._finish()
        shutdown = self._payload({"type": "shutdown_complete"})
        self._event(
            "protocol_event_observed",
            event_type="shutdown_complete",
            event_payload=shutdown,
        )
        self._event("thread_ended", thread_id="child", status="completed")
        self._event(
            "thread_ended",
            thread="child",
            turn="turn-child",
            thread_id="child",
            status="completed",
        )
        self._event("rollout_ended", status="completed")
        self.assertEqual(self._inspect()["blockers"], [])

        baseline_events, baseline_payloads = (
            copy.deepcopy(self.events),
            copy.deepcopy(self.payloads),
        )
        cases = (
            "unknown-child",
            "active-child",
            "foreign-child-turn",
            "wrong-thread-turn",
            "malformed-list",
            "malformed-dict",
            "foreign-rollout-turn",
            "forged-shutdown",
            "inference",
            "child-start",
        )
        for case in cases:
            with self.subTest(case=case):
                self.events, self.payloads = (
                    copy.deepcopy(baseline_events),
                    copy.deepcopy(baseline_payloads),
                )
                child_close = self.events[-2]
                if case == "unknown-child":
                    child_close["payload"]["thread_id"] = "ghost"
                elif case == "active-child":
                    turn_end = next(
                        row
                        for row in self.events
                        if row["payload"]["type"] == "codex_turn_ended"
                        and row["thread_id"] == "child"
                    )
                    turn_end["payload"]["type"] = "ignored"
                elif case == "foreign-child-turn":
                    child_close["codex_turn_id"] = "foreign-turn"
                elif case == "wrong-thread-turn":
                    child_close["codex_turn_id"] = "turn-root-thread"
                elif case.startswith("malformed"):
                    child_close["payload"]["thread_id"] = (
                        [] if case.endswith("list") else {}
                    )
                elif case == "foreign-rollout-turn":
                    self.events[-1]["codex_turn_id"] = "foreign-turn"
                elif case == "forged-shutdown":
                    self.payloads[shutdown["path"]]["forged"] = True
                elif case == "inference":
                    self._event("inference_started", inference_call_id="late")
                else:
                    self._thread_start("late-child", self.rollout)
                error = (
                    "thread-terminal-invalid"
                    if case.startswith("malformed")
                    else "event-after-rollout-terminal"
                )
                with self.assertRaisesRegex(Stage2Error, error):
                    self._inspect()

    def test_actual_compaction_response_without_usage_remains_unknown(self):
        self._inference("i1", "r1")
        scope = {
            "thread": self.rollout,
            "turn": "turn-root-thread",
            "thread_id": self.rollout,
            "codex_turn_id": "turn-root-thread",
            "compaction_id": "compact-1",
            "compaction_request_id": "request-1",
        }
        self._event(
            "compaction_request_started",
            request_payload=self._payload({"model": "model", "input": []}),
            **scope,
        )
        self._event(
            "compaction_request_completed",
            response_payload=self._payload({"output_items": []}),
            **scope,
        )
        self._finish()

        report = self._inspect()

        self.assertIsNone(report["token_usage_totals"])
        self.assertIn("compaction-usage-missing", report["blockers"])
        self.assertEqual(report["counts"]["compactions"], 1)
        self.assertEqual(report["counts"]["compaction_events"], 2)

    def test_failed_spawn_is_counted_without_requiring_child(self):
        self._inference("i1", "r1")
        self._event(
            "tool_call_started",
            thread=self.rollout,
            turn="turn-root-thread",
            tool_call_id="spawn-1",
            kind={"type": "spawn_agent"},
        )
        self._event(
            "tool_call_ended",
            thread=self.rollout,
            turn="turn-root-thread",
            tool_call_id="spawn-1",
            status="failed",
        )
        self._finish()

        report = self._inspect()

        self.assertEqual(report["counts"]["attempted_failed_spawns"], 1)
        self.assertFalse(
            any("spawn-child-missing" in row for row in report["blockers"])
        )
        tool_end = next(
            row for row in self.events if row["payload"]["type"] == "tool_call_ended"
        )
        tool_end["payload"]["status"] = "completed"
        report = self._inspect()
        self.assertIn("spawn-child-missing:spawn-1", report["blockers"])
        tool_start = next(
            row for row in self.events if row["payload"]["type"] == "tool_call_started"
        )
        tool_start["payload"]["kind"] = []
        with self.assertRaisesRegex(Stage2Error, "tool-call-scope-invalid"):
            self._inspect()

    def test_duplicate_call_ids_and_different_terminals_reject(self):
        self._inference("i1", "r1")
        duplicate = copy.deepcopy(self.events[-2])
        duplicate["seq"] = len(self.events) + 1
        self.events.append(duplicate)
        self._finish()
        with self.assertRaisesRegex(Stage2Error, "duplicate-inference-call-id"):
            self._inspect()

        self.events.pop(-4)
        for number, row in enumerate(self.events, 1):
            row["seq"] = number
        self._event("thread_ended", thread_id=self.rollout, status="failed")
        with self.assertRaisesRegex(Stage2Error, "different-thread-terminal"):
            self._inspect()

    def test_schema_sequence_traversal_and_foreign_child_reject(self):
        self._inference("i1", "r1")
        self._finish()
        self.events[0]["payload"]["trace_id"] = "other"
        with self.assertRaisesRegex(Stage2Error, "rollout-start-invalid"):
            self._inspect()
        self.events[0]["payload"]["trace_id"] = "trace-1"
        inference = next(
            row for row in self.events if row["payload"]["type"] == "inference_started"
        )
        inference["seq"] = True
        with self.assertRaisesRegex(Stage2Error, "sequence-invalid"):
            self._inspect()
        saved = self.events[1]
        self.events[1] = []
        with self.assertRaisesRegex(Stage2Error, "sequence-invalid"):
            self._inspect()
        self.events[1] = saved
        inference["seq"] = 99
        with self.assertRaisesRegex(Stage2Error, "sequence-invalid"):
            self._inspect()

    def test_parent_cycle_rejects(self):
        self._thread_start("child-a", "child-b")
        self._thread_start("child-b", "child-a")
        for thread in ("child-a", "child-b"):
            self._turn_end(thread)
            self._event("thread_ended", thread_id=thread, status="completed")
        self._finish()

        with self.assertRaisesRegex(Stage2Error, "thread-parent-cycle"):
            self._inspect()

    def test_duplicate_identical_thread_terminal_is_tolerated(self):
        self._inference("i1", "r1")
        self._finish()
        self._event("thread_ended", thread_id=self.rollout, status="completed")

        report = self._inspect()

        self.assertEqual(report["threads"][0]["terminal_status"], "completed")


if __name__ == "__main__":
    unittest.main()
