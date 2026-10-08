"""Neutral deterministic tests for saved-reading body completeness evidence."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.body_completeness import assess_body_completeness


RAW_HASH = "a" * 64
TEXT_HASH = "b" * 64


def pdf_row():
    return {
        "raw_sha256": RAW_HASH,
        "reading": {
            "characters": 12,
            "text_sha256": TEXT_HASH,
            "locators": [
                {"type": "pdf-page", "value": 1, "start": 0, "end": 5},
                {"type": "pdf-page", "value": 2, "start": 7, "end": 12},
            ],
            "diagnostics": {
                "pages_total": 2,
                "readable_pages": [1, 2],
                "blank_pages": [],
                "omitted_pages": [],
            },
        },
    }


def document_row():
    return {
        "raw_sha256": RAW_HASH,
        "reading": {
            "characters": 8,
            "text_sha256": TEXT_HASH,
            "locators": [{"type": "body", "start": 0, "end": 8}],
            "diagnostics": {
                "document_extent": {
                    "scope": "full-body",
                    "complete": True,
                    "raw_sha256": RAW_HASH,
                    "text_sha256": TEXT_HASH,
                    "expected_characters": 8,
                    "readable_characters": 8,
                }
            },
        },
    }


class BodyCompletenessTests(unittest.TestCase):
    def test_null_pdf_lists_are_not_affirmative_extent(self):
        for field in ("readable_pages", "omitted_pages", "blank_pages"):
            with self.subTest(field=field):
                row = pdf_row()
                row["reading"]["diagnostics"][field] = None
                self.assertEqual(assess_body_completeness(row)["status"], "incomplete")

    def test_invalid_pdf_page_values_return_incomplete_without_sort_error(self):
        row = pdf_row()
        row["reading"]["locators"][1]["value"] = "two"
        self.assertEqual(assess_body_completeness(row)["status"], "incomplete")

    def test_abstract_level_never_confirms_body_even_with_page_proof(self):
        row = pdf_row()
        row["reading"]["evidence_level"] = "abstract"
        self.assertEqual(assess_body_completeness(row)["status"], "pending")

    def test_complete_multi_page_pdf_is_confirmed_without_mutation(self):
        row = pdf_row()
        before = deepcopy(row)
        self.assertEqual(
            assess_body_completeness(row), {"status": "confirmed", "reasons": []}
        )
        self.assertEqual(row, before)

    def test_contiguous_pdf_page_extents_are_also_confirmed(self):
        row = pdf_row()
        row["reading"]["characters"] = 10
        row["reading"]["locators"][1].update(start=5, end=10)
        self.assertEqual(
            assess_body_completeness(row), {"status": "confirmed", "reasons": []}
        )

    def test_boolean_pdf_page_total_is_incomplete(self):
        row = pdf_row()
        row["reading"]["diagnostics"]["pages_total"] = True
        result = assess_body_completeness(row)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("pdf-page-count-invalid", result["reasons"])

    def test_missing_pdf_diagnostic_fields_are_pending(self):
        row = pdf_row()
        row["reading"]["diagnostics"] = {}
        self.assertEqual(
            assess_body_completeness(row),
            {"status": "pending", "reasons": ["pdf-extent-proof-missing"]},
        )

    def test_missing_extent_proof_and_boolean_only_are_pending(self):
        row = pdf_row()
        row["reading"]["diagnostics"] = {"complete": True}
        row["reading"]["locators"] = [{"type": "text", "start": 0, "end": 12}]
        self.assertEqual(
            assess_body_completeness(row),
            {"status": "pending", "reasons": ["document-extent-proof-missing"]},
        )

    def test_pdf_count_list_and_locator_mismatches_are_incomplete(self):
        row = pdf_row()
        row["reading"]["diagnostics"]["pages_total"] = 3
        result = assess_body_completeness(row)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(
            set(result["reasons"]),
            {
                "pdf-readable-page-coverage-mismatch",
                "pdf-locator-page-coverage-mismatch",
            },
        )

    def test_duplicate_readable_and_locator_pages_are_incomplete(self):
        row = pdf_row()
        row["reading"]["diagnostics"]["readable_pages"] = [1, 1]
        row["reading"]["locators"][1]["value"] = 1
        result = assess_body_completeness(row)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("pdf-readable-pages-duplicate", result["reasons"])
        self.assertIn("pdf-page-locators-duplicate", result["reasons"])

    def test_huge_declared_total_uses_only_tiny_supplied_input(self):
        row = pdf_row()
        row["reading"]["diagnostics"]["pages_total"] = 10**12
        result = assess_body_completeness(row)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("pdf-readable-page-coverage-mismatch", result["reasons"])

    def test_blank_or_omitted_pages_are_incomplete(self):
        for field, reason in (
            ("blank_pages", "pdf-pages-blank"),
            ("omitted_pages", "pdf-pages-omitted"),
        ):
            with self.subTest(field=field):
                row = pdf_row()
                row["reading"]["diagnostics"][field] = [2]
                result = assess_body_completeness(row)
                self.assertEqual(result["status"], "incomplete")
                self.assertIn(reason, result["reasons"])

    def test_fidelity_pending_and_geometry_fallback_are_pending(self):
        row = pdf_row()
        row["reading"]["diagnostics"].update(
            extraction_fidelity="Complete readable-content fidelity remains pending.",
            geometry_default_pages=[1],
        )
        self.assertEqual(
            assess_body_completeness(row),
            {
                "status": "pending",
                "reasons": [
                    "extraction-fidelity-unreviewed",
                    "pdf-geometry-fallback-unreviewed",
                ],
            },
        )

    def test_affirmative_non_pdf_receipt_with_exact_binding_is_confirmed(self):
        row = document_row()
        self.assertEqual(
            assess_body_completeness(row), {"status": "confirmed", "reasons": []}
        )

    def test_non_pdf_pending_or_incomplete_fidelity_stays_pending(self):
        for fidelity in ("fidelity pending", "incomplete readable content"):
            with self.subTest(fidelity=fidelity):
                row = document_row()
                row["reading"]["diagnostics"]["extraction_fidelity"] = fidelity
                self.assertEqual(
                    assess_body_completeness(row),
                    {
                        "status": "pending",
                        "reasons": ["extraction-fidelity-unreviewed"],
                    },
                )

    def test_stale_non_pdf_hash_is_incomplete(self):
        row = document_row()
        row["reading"]["diagnostics"]["document_extent"]["raw_sha256"] = "c" * 64
        result = assess_body_completeness(row)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("document-extent-binding-stale", result["reasons"])

    def test_abstract_only_locator_cannot_confirm_full_body(self):
        row = {
            "raw_sha256": RAW_HASH,
            "reading": {
                "characters": 8,
                "text_sha256": TEXT_HASH,
                "locators": [
                    {"type": "html-section", "value": "abstract", "start": 0, "end": 8}
                ],
                "diagnostics": {
                    "document_extent": {
                        "scope": "full-body",
                        "complete": True,
                        "raw_sha256": RAW_HASH,
                        "text_sha256": TEXT_HASH,
                        "expected_characters": 8,
                        "readable_characters": 8,
                    }
                },
            },
        }
        self.assertEqual(
            assess_body_completeness(row),
            {"status": "incomplete", "reasons": ["document-extent-locator-invalid"]},
        )


if __name__ == "__main__":
    unittest.main()
