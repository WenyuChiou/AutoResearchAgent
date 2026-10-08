"""Separate capture policies preserve authentic tool availability and failures."""

import shutil
import unittest
import test_stage2_no_tool_trace_evidence as fixtures
from stage2_live.no_tool_trace_capture import (
    NoToolTraceCaptureFailure,
    begin_no_tool_trace_capture,
    finish_no_execution_trace_capture,
    finish_no_tool_trace_capture,
)


class NoExecutionTraceCaptureTests(unittest.TestCase):
    def test_unused_tools_recorded_and_strict_failure_retains_original_seal(self):
        fixture = fixtures.NoToolTraceEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        telemetry = fixture.base / "telemetry"
        telemetry.mkdir()
        token = begin_no_tool_trace_capture(fixture.base / "evidence", telemetry)
        strict = begin_no_tool_trace_capture(
            fixture.base / "strict-evidence", telemetry
        )
        fixture._real_traces(final_tools=[{"type": "function", "name": "shell"}])
        for trace in fixture.trace_root.iterdir():
            shutil.copytree(trace, telemetry / trace.name)
        result = finish_no_execution_trace_capture(
            token, {"extract": fixture.provenance}, expected_config=fixture.expected
        )
        proof = result["units"]["extract"]["proof"]
        self.assertEqual(result["kind"], "Stage2NoExecutionTraceCapture")
        self.assertEqual(proof["execution_policy"], "no-executed-tools-v1")
        self.assertFalse(proof["tools_unavailable_attested"])
        with self.assertRaisesRegex(
            NoToolTraceCaptureFailure, "offered-tools-nonempty"
        ) as raised:
            finish_no_tool_trace_capture(
                strict,
                {"extract": fixture.provenance},
                expected_config=fixture.expected,
            )
        self.assertTrue(
            raised.exception.retained_seal_receipts["extract"]["seal_sha256"]
        )
        self.assertEqual(raised.exception.completed_units, {})


if __name__ == "__main__":
    unittest.main()
