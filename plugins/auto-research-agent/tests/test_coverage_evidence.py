"""Coverage reviews require versioned text evidence and remain revisable."""

from copy import deepcopy
import unittest

import test_coverage_rounds as rounds
from test_stage1_ledger import SYNTHETIC, rewrite_for_tamper_test
from stage1_coverage.evidence import IDENTITY_FIELDS
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.validation import validate_run


class CoverageEvidenceTests(unittest.TestCase):
    observe = rounds.CoverageRoundTests.observe

    def setUp(self):
        rounds.CoverageRoundTests.setUp(self)
        self.ledger.open_round()
        self.planned = next(iter(self.ledger.coverage_state().queries))
        self.observe(self.planned, rows=[SYNTHETIC])
        candidate = next(iter(self.ledger.candidates().values()))
        self.work, self.version = candidate["work_id"], candidate["version_ids"][0]
        source_import = self.ledger.start_source_import(
            work_id=self.work,
            version_id=self.version,
            source_uri="https://example.invalid/synthetic",
            actor="synthetic-reviewer",
            reason="Import saved synthetic primary text",
        )
        self.source = self.ledger.save_bytes(
            b"Synthetic household record. Synthetic Author. 2024. 10.5555/stage1-synthetic. record-v1. Synthetic households differ.",
            producer=source_import,
        )
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic relevance",
            evidence_refs=[self.source],
        )
        self.claims = {}
        for field in sorted(IDENTITY_FIELDS | {"relevance"}):
            self.claims[field] = self.ledger.claim(
                work_id=self.work,
                version_id=self.version,
                claim_text="Synthetic review of " + field,
                relation="supports",
                evidence_level="full_text",
                locator={
                    "section": "synthetic source",
                    "quote": "Synthetic household record",
                },
                source_ref=self.source,
                verifier={
                    "actor": "synthetic-reviewer",
                    "method": "saved-text-review",
                    "actor_type": "agent",
                },
            )
        self.request = dict(
            work_id=self.work,
            version_id=self.version,
            cluster_claims={"cluster-1": self.claims["relevance"]},
            identity_status="verified",
            identity_claims={k: self.claims[k] for k in IDENTITY_FIELDS},
            closest=True,
            assessor="synthetic-reviewer",
            rationale="Synthetic source review, not a live paper",
        )

    def test_review_separates_identity_attestation_from_metadata_and_claims(self):
        review = self.ledger.review_work(**self.request)
        self.assertEqual(review["scope"], "reviewer-attestation")
        self.assertEqual(
            self.ledger.candidates()[self.work]["identity_status"], "unverified"
        )
        self.assertEqual(
            list(self.ledger.coverage_state().evidence.current()), [self.work]
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_missing_identity_fields_do_not_verify_closest_work(self):
        request = deepcopy(self.request)
        request["identity_claims"]["version"] = None
        with self.assertRaisesRegex(LedgerError, "coverage-review-claim-version"):
            self.ledger.review_work(**request)
        request["identity_status"] = "unverifiable"
        self.ledger.review_work(**request)
        self.assertEqual(
            self.ledger.coverage_state().evidence.current()[self.work][
                "identity_status"
            ],
            "unverifiable",
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_reversal_and_new_discovery_make_review_stale(self):
        first = self.ledger.review_work(**self.request)
        self.ledger.decide(
            self.work,
            "exclude",
            reason="scope-reassessment",
            rationale="Synthetic correction",
            evidence_refs=[self.source],
        )
        self.assertEqual(self.ledger.coverage_state().evidence.current(), {})
        with self.assertRaisesRegex(LedgerError, "stale-or-excluded"):
            self.ledger.review_work(**self.request)
        self.ledger.decide(
            self.work,
            "include",
            reason="scope-match",
            rationale="Synthetic reconsideration",
            evidence_refs=[self.source],
        )
        replacement = self.ledger.review_work(**self.request)
        self.assertEqual(replacement["replaces_event_id"], first["event_id"])
        self.observe(self.planned, rows=[SYNTHETIC])
        self.assertEqual(self.ledger.coverage_state().evidence.current(), {})

    def test_expansion_must_use_discovered_seed_and_preserves_failures(self):
        with self.assertRaisesRegex(LedgerError, "discovered-version"):
            self.ledger.start_expansion("references", "unknown", self.version)
        query = self.ledger.start_expansion("references", self.work, self.version)
        attempt = self.ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        raw = self.ledger.save_bytes(
            canonical({"error": "rate limited"}), producer=attempt
        )
        self.ledger.finish(
            attempt,
            outcome="rate_limited",
            http_status=429,
            exit_code=1,
            stdout=raw,
            stderr=raw,
        )
        completed = self.ledger.complete_query(query)
        self.ledger.receipt(
            completed, truncated=False, note="Synthetic failed expansion"
        )
        self.assertIn(
            completed, self.ledger.close_round()["summary"]["failed_query_ids"]
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_abstract_identity_and_rehashed_review_cannot_bypass_evidence(self):
        abstract = self.ledger.claim(
            work_id=self.work,
            version_id=self.version,
            claim_text="Synthetic title",
            relation="supports",
            evidence_level="abstract",
            locator={"section": "abstract", "quote": "Synthetic household record"},
            source_ref=self.source,
            verifier={
                "actor": "synthetic-reviewer",
                "method": "saved-text-review",
                "actor_type": "agent",
            },
        )
        request = deepcopy(self.request)
        request["identity_claims"]["title"] = abstract
        with self.assertRaisesRegex(LedgerError, "identity-review-needs-primary-text"):
            self.ledger.review_work(**request)
        self.ledger.review_work(**self.request)
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"]["identity_claims"].update(title=abstract),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("identity-review-needs-primary-text", report["errors"])


if __name__ == "__main__":
    unittest.main()
