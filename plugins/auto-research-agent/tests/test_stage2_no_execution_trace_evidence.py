"""A separate evidence policy never relabels offered tools as unavailable."""

import unittest
from unittest.mock import patch

import test_stage2_no_tool_trace_evidence as fixtures
from stage2_common import Stage2Error
from stage2_live.no_execution_trace_evidence import verify_no_execution_trace_evidence


class NoExecutionTraceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.NoToolTraceEvidenceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def verify(self):
        f = self.fixture
        return verify_no_execution_trace_evidence(
            f.provenance,
            f.trace_root,
            f.seal,
            f.seal_sha,
            expected_config=f.expected,
        )

    def test_unused_offered_tools_remain_visible_and_strict_policy_rejects(self):
        f = self.fixture
        f._real_traces(final_tools=[{"type": "function", "name": "shell"}])
        result = self.verify()
        self.assertEqual(result["kind"], "Stage2NoExecutionTraceEvidence")
        self.assertEqual(result["execution_policy"], "no-executed-tools-v1")
        self.assertFalse(result["tools_unavailable_attested"])
        self.assertFalse(result["formal_isolation_attested"])
        self.assertEqual(
            result["attempts"][1]["offered_tool_inventory"][0]["counts"]["function"], 1
        )
        with self.assertRaisesRegex(Stage2Error, "offered-tools-nonempty"):
            f._verify_real()

    def test_actual_tool_child_or_incomplete_trace_is_rejected(self):
        f = self.fixture
        f._real_traces(final_tools=[{"type": "function", "name": "shell"}])
        from stage2_live.no_tool_trace_evidence import inspect_native_trace

        for change, reason in (
            ({"counts": {"tool_calls": 1}}, "tool-activity"),
            ({"threads": [{}, {}]}, "child-activity"),
            ({"blockers": ["inference-terminal-missing:x"]}, "trace-incomplete"),
            ({"blockers": ["offered-tools-unknown:x"]}, "offered-tools-unresolved"),
        ):

            def observe(*args, change=change):
                value = inspect_native_trace(*args)
                value.update(change)
                return value

            with (
                self.subTest(reason=reason),
                patch(
                    "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                    side_effect=observe,
                ),
                self.assertRaisesRegex(Stage2Error, reason),
            ):
                self.verify()

    def test_changed_raw_payload_fails_even_when_offered_tools_are_allowed(self):
        f = self.fixture
        f._real_traces(final_tools=[{"type": "function", "name": "shell"}])
        target = f.trace_root / "trace-2/trace.jsonl"
        target.write_bytes(target.read_bytes() + b"{}\n")
        with self.assertRaises(Stage2Error):
            self.verify()

    def test_attempt_failures_and_unknown_usage_remain_in_results(self):
        self.fixture._real_traces(final_usage=False)
        result = self.verify()
        self.assertEqual(
            [row["status"] for row in result["attempts"]], ["failure", "completed"]
        )
        self.assertEqual(result["attempts"][0]["error"], "transient-transport")
        self.assertTrue(
            all(value is None for value in result["token_usage_totals"].values())
        )
        self.assertEqual(result["new_model_calls"], 0)
        self.assertEqual(result["new_tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
