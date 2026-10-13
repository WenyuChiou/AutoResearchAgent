"""Neutral saved-page declarations with hand-specified character extents."""

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unicodedata
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace.normalized_page_comparison import (
    NORMALIZATION,
    compare_normalized_page_evidence,
)
from stage1_deliverable.common import DeliverableError


def declaration(saved, independent, equal, differences):
    # Callers supply literal normalized texts, never comparator output.
    return {
        "saved_normalized_sha256": hashlib.sha256(saved.encode("utf-8")).hexdigest(),
        "independent_normalized_sha256": hashlib.sha256(
            independent.encode("utf-8")
        ).hexdigest(),
        "strict_equal": equal,
        "differences": differences,
    }


def difference(operation, saved_extent, independent_extent, saved, independent):
    return {
        "operation": operation,
        "saved_extent": saved_extent,
        "independent_extent": independent_extent,
        "saved": saved,
        "independent": independent,
    }


class NormalizedPageComparisonTests(unittest.TestCase):
    def assert_bad(self, record):
        with self.assertRaises(DeliverableError):
            compare_normalized_page_evidence("ab", "ba", record)

    def ordered_declaration(self):
        return declaration(
            "ab",
            "ba",
            False,
            [
                difference("insert", [0, 0], [0, 1], " ab ", " ba "),
                difference("delete", [1, 2], [2, 2], "ab", "ba"),
            ],
        )

    def test_nfc_and_whitespace_are_equal(self):
        record = declaration("café text", "café text", True, [])
        with patch(
            "research_workspace.normalized_page_comparison.SequenceMatcher",
            side_effect=AssertionError("equal pages must skip matching"),
        ):
            facts = compare_normalized_page_evidence(
                "cafe\u0301\r\n\t text", " café  text ", record
            )
        self.assertTrue(facts["strict_equal"])
        self.assertEqual(facts["operations"], [])
        self.assertEqual(facts["normalization"], NORMALIZATION)
        self.assertEqual(
            facts["normalization_unicode_version"], unicodedata.unidata_version
        )

    def test_punctuation_word_boundaries_and_compatibility_are_preserved(self):
        cases = [
            ("a,b", "a b", "replace", [1, 2], [1, 2]),
            ("a b", "ab", "delete", [1, 2], [1, 1]),
            ("①", "1", "replace", [0, 1], [0, 1]),
            ("éx", "éy", "replace", [1, 2], [1, 2]),
        ]
        for saved, independent, operation, left, right in cases:
            with self.subTest(saved=saved):
                record = declaration(
                    saved,
                    independent,
                    False,
                    [difference(operation, left, right, saved, independent)],
                )
                facts = compare_normalized_page_evidence(saved, independent, record)
                self.assertFalse(facts["strict_equal"])
                self.assertEqual(
                    facts["operations"],
                    [
                        {
                            "operation": operation,
                            "saved_extent": left,
                            "independent_extent": right,
                        }
                    ],
                )

    def test_order_is_not_normalized_away(self):
        facts = compare_normalized_page_evidence("ab", "ba", self.ordered_declaration())
        self.assertEqual(
            facts["operations"],
            [
                {
                    "operation": "insert",
                    "saved_extent": [0, 0],
                    "independent_extent": [0, 1],
                },
                {
                    "operation": "delete",
                    "saved_extent": [1, 2],
                    "independent_extent": [2, 2],
                },
            ],
        )

    def test_forged_hashes_are_rejected(self):
        for key in ("saved_normalized_sha256", "independent_normalized_sha256"):
            for value in ("0" * 64, None, 17):
                with self.subTest(key=key, value=value):
                    record = declaration("a", "a", True, [])
                    record[key] = value
                    with self.assertRaises(DeliverableError):
                        compare_normalized_page_evidence("a", "a", record)

    def test_forged_or_non_boolean_verdict_is_rejected(self):
        for value in (False, 1, "true", None):
            record = declaration("a", "a", True, [])
            record["strict_equal"] = value
            with self.subTest(value=value), self.assertRaises(DeliverableError):
                compare_normalized_page_evidence("a", "a", record)

    def test_omitted_reordered_or_extra_operations_are_rejected(self):
        for mode in ("omit", "reverse", "extra"):
            record = self.ordered_declaration()
            if mode == "omit":
                record["differences"].pop()
            elif mode == "reverse":
                record["differences"].reverse()
            else:
                record["differences"].append(deepcopy(record["differences"][0]))
            with self.subTest(mode=mode):
                self.assert_bad(record)

    def test_extent_shape_type_and_offsets_are_strict(self):
        malformed = (
            None,
            "0,0",
            (0, 0),
            [],
            [0],
            [0, 0, 0],
            [False, 0],
            [0.0, 0],
            ["0", 0],
            [-1, 0],
            [0, 1],
        )
        for key in ("saved_extent", "independent_extent"):
            for value in malformed:
                record = self.ordered_declaration()
                record["differences"][0][key] = value
                # [0, 1] is correct only for the independent insertion extent.
                if key == "independent_extent" and value == [0, 1]:
                    record["differences"][0][key] = [1, 2]
                with self.subTest(key=key, value=value):
                    self.assert_bad(record)

    def test_context_must_be_nonempty_and_present(self):
        for key in ("saved", "independent"):
            for value in (None, [], "", " \t ", "missing", "AB"):
                record = self.ordered_declaration()
                record["differences"][0][key] = value
                with self.subTest(key=key, value=value):
                    self.assert_bad(record)

    def test_exact_comparison_and_difference_keys(self):
        for level in ("comparison", "difference"):
            for mode in ("missing", "extra", "wrong_type"):
                record = self.ordered_declaration()
                target = record if level == "comparison" else record["differences"][0]
                if mode == "missing":
                    target.pop(next(iter(target)))
                elif mode == "extra":
                    target["unexpected"] = True
                elif level == "comparison":
                    record = []
                else:
                    record["differences"][0] = []
                with self.subTest(level=level, mode=mode):
                    self.assert_bad(record)

    def test_malformed_text_list_and_operation_raise_deliverable_error(self):
        for text in (None, b"ab", [], "\ud800"):
            for saved, independent in ((text, "ba"), ("ab", text)):
                with self.subTest(text=repr(text)), self.assertRaises(DeliverableError):
                    compare_normalized_page_evidence(
                        saved, independent, self.ordered_declaration()
                    )
        for value in (None, {}, "differences"):
            record = self.ordered_declaration()
            record["differences"] = value
            self.assert_bad(record)
        for value in (None, "replace", [], 1):
            record = self.ordered_declaration()
            record["differences"][0]["operation"] = value
            self.assert_bad(record)

    def test_pure_deterministic_output_does_not_alias_input(self):
        record = self.ordered_declaration()
        original = deepcopy(record)
        with (
            patch("builtins.open", side_effect=AssertionError("unexpected I/O")),
            patch("subprocess.run", side_effect=AssertionError("unexpected process")),
        ):
            first = compare_normalized_page_evidence("ab", "ba", record)
            second = compare_normalized_page_evidence("ab", "ba", record)
        self.assertEqual(first, second)
        self.assertEqual(record, original)
        self.assertEqual(
            set(first),
            {
                "normalization",
                "normalization_unicode_version",
                "strict_equal",
                "saved_normalized_sha256",
                "independent_normalized_sha256",
                "operations",
            },
        )
        first["operations"][0]["saved_extent"][0] = 99
        self.assertEqual(record, original)
        self.assertEqual(second["operations"][0]["saved_extent"], [0, 0])


if __name__ == "__main__":
    unittest.main()
