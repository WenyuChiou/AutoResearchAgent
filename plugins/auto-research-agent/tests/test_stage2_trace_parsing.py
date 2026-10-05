"""Boundary tests for native trace inference parsing helpers."""

from pathlib import Path
import sys
import unittest


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live.trace_parsing import (  # noqa: E402
    _tool_counts,
    _tools,
    _usage,
    summarize_inferences,
)


TOOLS = [{"type": "function", "name": "lookup"}]


def _usage_record():
    return {
        "input_tokens": 10,
        "cached_input_tokens": 4,
        "cache_write_input_tokens": 2,
        "output_tokens": 3,
        "reasoning_output_tokens": 1,
        "total_tokens": 13,
    }


def _inference(seq, *, thread="root", request=None, terminal="inference_completed"):
    item = {
        "seq": seq,
        "thread_id": thread,
        "codex_turn_id": f"turn-{thread}",
        "request_ref": f"payloads/request-{seq}.json",
        "request_sha256": f"request-{seq}",
        "request": request if request is not None else {"input": [], "tools": TOOLS},
        "terminal": terminal,
        "completion_seq": seq + 1 if terminal is not None else None,
    }
    if terminal == "inference_completed":
        item.update(
            response_ref=f"payloads/response-{seq}.json",
            response_sha256=f"response-{seq}",
            response={"token_usage": _usage_record()},
        )
    return item


class NativeTraceParsingTests(unittest.TestCase):
    def test_tool_aliases_distinguish_known_empty_from_unknown(self):
        additional = [{"type": "additional_tools", "role": "developer", "tools": TOOLS}]
        self.assertEqual(_tools({"input": additional}), TOOLS)
        self.assertEqual(_tools({"input": additional, "tools": TOOLS}), TOOLS)
        self.assertEqual(_tools({"input": [], "tools": []}), [])
        self.assertIsNone(_tools({"input": []}))

        with self.assertRaisesRegex(Stage2Error, "offered-tools-alias-mismatch"):
            _tools({"input": additional, "tools": []})

    def test_nested_tool_depth_and_definition_count_limits(self):
        nested = {"type": "namespace", "name": "level-8"}
        for depth in range(7, 0, -1):
            nested = {
                "type": "namespace",
                "name": f"level-{depth}",
                "tools": [nested],
            }
        self.assertEqual(_tool_counts([nested])["namespace"], 8)

        too_deep = {"type": "custom", "name": "level-9"}
        cursor = too_deep
        for depth in range(8, 0, -1):
            cursor = {
                "type": "namespace",
                "name": f"level-{depth}",
                "tools": [cursor],
            }
        with self.assertRaisesRegex(Stage2Error, "tool-definition-limit"):
            _tool_counts([cursor])

        definitions = [{"type": "custom", "name": str(i)} for i in range(256)]
        self.assertEqual(_tool_counts(definitions)["custom"], 256)
        with self.assertRaisesRegex(Stage2Error, "tool-definition-limit"):
            _tool_counts(definitions + [{"type": "custom", "name": "overflow"}])

    def test_usage_rejects_bool_missing_and_negative_fields(self):
        mutations = {
            "bool": ("input_tokens", True),
            "missing": ("cached_input_tokens", None),
            "negative": ("output_tokens", -1),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(label=label):
                usage = _usage_record()
                if value is None:
                    del usage[field]
                else:
                    usage[field] = value
                with self.assertRaisesRegex(Stage2Error, "token-usage-invalid"):
                    _usage({"token_usage": usage})

    def test_usage_rejects_subset_and_total_mismatches(self):
        subset = _usage_record()
        subset["cached_input_tokens"] = 11
        with self.assertRaisesRegex(Stage2Error, "token-usage-subset-mismatch"):
            _usage({"token_usage": subset})

        total = _usage_record()
        total["total_tokens"] = 14
        with self.assertRaisesRegex(Stage2Error, "token-usage-total-mismatch"):
            _usage({"token_usage": total})

    def test_delta_inherits_only_from_completed_prior_same_thread_response(self):
        first = _inference(1)
        same_thread = _inference(
            3, request={"input": [], "previous_response_id": "response-1"}
        )
        inferences = {"first": first, "same": same_thread}
        rows, _, totals = summarize_inferences(
            inferences, {"response-1": first}, [], {}, False
        )
        self.assertFalse(rows[0]["tools_inherited"])
        self.assertTrue(rows[1]["tools_inherited"])
        self.assertEqual(totals["total_tokens"], 26)

        invalid_priors = {
            "foreign": {**first, "thread_id": "child", "resolved_tools": TOOLS},
            "late": {**first, "completion_seq": 4, "resolved_tools": TOOLS},
            "failed": {
                **first,
                "terminal": "inference_failed",
                "resolved_tools": TOOLS,
            },
            "incomplete": {**first, "terminal": None, "resolved_tools": TOOLS},
            "bool-completion": {
                **first,
                "completion_seq": True,
                "resolved_tools": TOOLS,
            },
        }
        missing_completion = {**first, "resolved_tools": TOOLS}
        del missing_completion["completion_seq"]
        invalid_priors["missing-completion"] = missing_completion
        for label, prior in invalid_priors.items():
            with self.subTest(label=label):
                current = _inference(
                    3, request={"input": [], "previous_response_id": "prior"}
                )
                blockers = []
                rows, _, _ = summarize_inferences(
                    {"current": current}, {"prior": prior}, blockers, {}, False
                )
                self.assertFalse(rows[0]["tools_inherited"])
                self.assertEqual(blockers, ["offered-tools-unknown:current"])

    def test_compaction_usage_is_validated_and_counted_once(self):
        invalid = []
        for label, field, value in (
            ("negative", "input_tokens", -1),
            ("bool", "input_tokens", True),
            ("missing", "cached_input_tokens", None),
            ("subset", "cached_input_tokens", 11),
            ("sum", "total_tokens", 14),
        ):
            usage = _usage_record()
            if value is None:
                del usage[field]
            else:
                usage[field] = value
            error = (
                "token-usage-subset-mismatch"
                if label == "subset"
                else "token-usage-total-mismatch"
                if label == "sum"
                else "token-usage-invalid"
            )
            invalid.append((label, usage, error))

        for label, usage, error in invalid:
            with self.subTest(label=label):
                with self.assertRaisesRegex(Stage2Error, error):
                    summarize_inferences(
                        {"done": _inference(1)}, {}, [], {"compact-1": usage}, False
                    )

        _, _, totals = summarize_inferences(
            {"done": _inference(1)}, {}, [], {"compact-1": _usage_record()}, False
        )
        self.assertEqual(
            totals, {"input_tokens": 20, "output_tokens": 6, "total_tokens": 26}
        )

    def test_incomplete_inference_and_unknown_compaction_make_totals_unknown(self):
        incomplete = _inference(1, terminal=None)
        blockers = []
        rows, _, totals = summarize_inferences(
            {"open": incomplete}, {}, blockers, {}, False
        )
        self.assertEqual(rows[0]["status"], "incomplete")
        self.assertIsNone(totals)
        self.assertIn("inference-terminal-missing:open", blockers)
        self.assertIn("token-usage-unknown:open", blockers)

        blockers = []
        _, _, totals = summarize_inferences(
            {"done": _inference(1)}, {}, blockers, {"compact-1": None}, True
        )
        self.assertIsNone(totals)
        self.assertIn("compaction-accounting-unverified", blockers)
        self.assertIn("compaction-usage-missing", blockers)


if __name__ == "__main__":
    unittest.main()
