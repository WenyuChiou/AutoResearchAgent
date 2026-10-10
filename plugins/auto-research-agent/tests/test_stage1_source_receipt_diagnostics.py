"""Optional source diagnostics must survive strict receipt validation."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from stage1_deliverable.common import DeliverableError, canonical
from stage1_deliverable.sources import validate_receipt_shape, validate_paper_identity


def receipt():
    url = "https://example.test/paper"
    return {
        "schema_version": "1.0.0",
        "request": {
            "operation": "source-fetch",
            "doi": "",
            "url": url,
            "title": "Synthetic source",
            "output_dir": "private/source",
            "public_only": True,
        },
        "receipt_sha256": "a" * 64,
        "status": "available",
        "evidence_level": "full-text",
        "source_url": url,
        "final_url": url,
        "retrieved_at": "2026-01-01T00:00:00Z",
        "expected_identity": {"doi": "", "title": "Synthetic source"},
        "observed_identity": {"doi": "", "title": "Synthetic source"},
        "identity_status": "consistent",
        "source_version": "sha256:" + "b" * 64,
        "attempts": [
            {
                "sequence": 1,
                "purpose": "synthetic fixture",
                "url": url,
                "final_url": url,
                "requested_at": "2026-01-01T00:00:00Z",
                "received_at": "2026-01-01T00:00:01Z",
                "http_status": 200,
                "content_type": "text/html",
                "outcome": "parsed",
                "response_bytes": 12,
                "response_truncated": False,
                "raw_path": "private/source/raw.html",
                "raw_sha256": "b" * 64,
                "error": None,
            }
        ],
        "raw_path": "private/source/raw.html",
        "raw_sha256": "b" * 64,
        "extracted_text_path": "private/source/source.txt",
        "extracted_text_sha256": "c" * 64,
        "locators": [],
        "errors": [],
        "output_dir": "private/source",
    }


class SourceReceiptDiagnosticsTests(unittest.TestCase):
    def test_legacy_and_diagnostics_receipts_preserve_bytes(self):
        for extra in (
            {},
            {"diagnostics": {"parser": {"status": "pending"}, "omitted_pages": [2]}},
        ):
            result = receipt() | extra
            before = canonical(result)
            validate_receipt_shape(result)
            self.assertEqual(canonical(result), before)

    def test_malformed_diagnostics_are_rejected(self):
        for value in (None, [], True, "discard me"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(
                    DeliverableError, "diagnostics must be an object"
                ),
            ):
                validate_receipt_shape(receipt() | {"diagnostics": value})

    def test_unknown_or_missing_fields_remain_rejected(self):
        result = receipt() | {"diagnostics": {}}
        with self.assertRaisesRegex(DeliverableError, "unexpected or missing fields"):
            validate_receipt_shape(result | {"unrecognized": True})
        missing = deepcopy(result)
        missing.pop("raw_sha256")
        with self.assertRaisesRegex(DeliverableError, "unexpected or missing fields"):
            validate_receipt_shape(missing)

    def test_diagnostics_do_not_bypass_public_access_or_secret_checks(self):
        result = receipt() | {"diagnostics": {}}
        result["request"]["public_only"] = False
        with self.assertRaisesRegex(DeliverableError, "credential-free"):
            validate_receipt_shape(result)
        result = receipt() | {"diagnostics": {"access_token": "synthetic-credential"}}
        with self.assertRaises(DeliverableError):
            validate_receipt_shape(result)


class ObservedSourceTitleTests(unittest.TestCase):
    def test_replayed_own_title_can_replace_stale_lookup_without_promotion(self):
        result = receipt()
        result["expected_identity"]["title"] = "Earlier edition lookup title"
        result["identity_status"] = "unverified"
        before = canonical(result)
        validate_paper_identity({"title": "Synthetic source", "doi": None}, result)
        self.assertEqual(canonical(result), before)

    def test_wrong_observed_title_or_failed_identity_stays_rejected(self):
        for field, value in (
            ("status", "parse-error"),
            ("identity_status", "mismatch"),
            ("observed_title", "Different source"),
            ("observed_title", None),
        ):
            with self.subTest(field=field, value=value):
                result = receipt()
                result["expected_identity"]["title"] = "Earlier edition lookup title"
                if field == "observed_title":
                    result["observed_identity"]["title"] = value
                else:
                    result[field] = value
                with self.assertRaises(DeliverableError):
                    validate_paper_identity(
                        {"title": "Synthetic source", "doi": None}, result
                    )

    def test_observed_title_does_not_override_conflicting_requested_doi(self):
        result = receipt()
        result["expected_identity"].update(
            title="Earlier edition lookup title", doi="10.1234/wrong"
        )
        result["observed_identity"]["doi"] = "10.1234/correct"
        with self.assertRaises(DeliverableError):
            validate_paper_identity(
                {"title": "Synthetic source", "doi": "10.1234/correct"}, result
            )

    def test_url_only_request_binds_observed_title_and_doi(self):
        result = receipt()
        result["expected_identity"].update(title="", doi="")
        result["observed_identity"].update(
            title="  Synthetic SOURCE. ", doi="10.1234/correct"
        )
        validate_paper_identity(
            {"title": "Synthetic source", "doi": "10.1234/correct"}, result
        )


if __name__ == "__main__":
    unittest.main()
