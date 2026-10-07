"""Catalog binding for DOIs observed after a URL-only source request."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_deliverable.common import DeliverableError  # noqa: E402
from stage1_deliverable.sources import (  # noqa: E402
    receipt_digest,
    validate_paper_identity,
)
import test_stage1_deliverable as fixtures  # noqa: E402


class ObservedDoiTests(unittest.TestCase):
    def setUp(self):
        self.paper = {"title": "Neutral household study", "doi": "10.1234/neutral"}
        self.result = {
            "expected_identity": {"title": self.paper["title"], "doi": ""},
            "observed_identity": {"title": "", "doi": self.paper["doi"]},
            "status": "available",
            "identity_status": "unverified",
        }

    def test_url_request_observed_doi_preserves_identity_and_receipt(self):
        before = copy.deepcopy(self.result)
        validate_paper_identity(self.paper, self.result)
        self.assertEqual(before, self.result)
        self.assertEqual("unverified", self.result["identity_status"])

    def test_request_bound_doi_and_legacy_missing_doi_are_unchanged(self):
        for doi in (self.paper["doi"], None):
            with self.subTest(doi=doi):
                paper = dict(self.paper, doi=doi)
                self.result["expected_identity"]["doi"] = doi or ""
                validate_paper_identity(paper, self.result)

    def test_wrong_or_missing_observation_cannot_supply_catalog_doi(self):
        for doi in ("", "10.1234/another-edition", "https://example.org/article"):
            with self.subTest(doi=doi):
                self.result["observed_identity"]["doi"] = doi
                with self.assertRaises(DeliverableError):
                    validate_paper_identity(self.paper, self.result)

    def test_observed_doi_cannot_override_request_title_or_version_conflict(self):
        cases = (
            (
                "title",
                lambda: self.result["expected_identity"].update(title="Other work"),
            ),
            (
                "request",
                lambda: self.result["expected_identity"].update(
                    doi="10.1234/old-edition"
                ),
            ),
            ("identity", lambda: self.result.update(identity_status="mismatch")),
            ("status", lambda: self.result.update(status="identity-mismatch")),
            ("failure", lambda: self.result.update(status="parse-error")),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                self.setUp()
                mutate()
                with self.assertRaises(DeliverableError):
                    validate_paper_identity(self.paper, self.result)


class ObservedDoiExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResearchDeliverableTests.setUpClass.__func__(cls)

    def setUp(self):
        fixtures.ResearchDeliverableTests.setUp(self)

    def test_url_only_request_exports_replayed_doi_without_rewriting_receipt(self):
        raw = fixtures.HTML.replace(
            b"</head>", b'<meta name="citation_doi" content="10.1234/neutral"></head>'
        )
        records = fixtures.ResearchDeliverableTests.make_records(self, raw=raw)
        receipt = self.inputs / "source/source-fetch-result.json"
        before = receipt.read_bytes()
        original = fixtures.read_json(receipt)
        self.assertEqual("", original["expected_identity"]["doi"])
        self.assertEqual("10.1234/neutral", original["observed_identity"]["doi"])
        records["papers"][0]["doi"] = "10.1234/neutral"
        fixtures.write_json(self.records, records)
        report = fixtures.package.build(
            self.records, self.output, fixtures.sha(self.records.read_bytes())
        )
        self.assertEqual("passed", report["status"])
        self.assertTrue(report["source_semantic_replay"])
        self.assertEqual(before, receipt.read_bytes())
        self.assertIn("10.1234/neutral", (self.output / "references.bib").read_text())

    def test_source_replay_rejects_forged_observed_doi(self):
        records = fixtures.ResearchDeliverableTests.make_records(self)
        receipt = self.inputs / "source/source-fetch-result.json"
        altered = fixtures.read_json(receipt)
        altered["observed_identity"]["doi"] = "10.1234/forged"
        altered["receipt_sha256"] = receipt_digest(altered)
        fixtures.write_json(receipt, altered)
        records["sources"][0]["result_sha256"] = fixtures.sha(receipt.read_bytes())
        records["papers"][0]["doi"] = "10.1234/forged"
        fixtures.write_json(self.records, records)
        with self.assertRaisesRegex(DeliverableError, "semantic replay"):
            fixtures.package.build(
                self.records, self.output, fixtures.sha(self.records.read_bytes())
            )


if __name__ == "__main__":
    unittest.main()
