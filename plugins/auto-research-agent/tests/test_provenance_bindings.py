"""Reject borrowed action receipts and cross-work/version evidence on replay."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from test_stage1_ledger import SYNTHETIC, add_query, rewrite_for_tamper_test
from stage1_ledger.journal import LedgerError
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run


class ProvenanceBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ledger = Ledger.create(
            Path(temporary.name) / "run",
            run_id="synthetic",
            objective="Synthetic provenance",
        )

    def test_shared_bytes_have_distinct_observation_receipts(self):
        _, a = add_query(self.ledger, [SYNTHETIC])
        _, b = add_query(self.ledger, [SYNTHETIC])
        self.assertEqual(a["path"], b["path"])
        self.assertNotEqual(a["producer"], b["producer"])
        self.assertNotEqual(a["artifact_id"], b["artifact_id"])
        self.ledger.extract()
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["counts"]["discoveries"], 2)

    def test_artifact_producer_bound_on_write_and_replay(self):
        ledger = self.ledger
        _, a = add_query(ledger, [SYNTHETIC])
        query = ledger.start("search", {"query": "synthetic b"})
        attempt = ledger.start(
            "backend", {"variant": "base"}, backend="b", parent_id=query
        )
        with self.assertRaisesRegex(LedgerError, "producer-mismatch"):
            ledger.finish(
                attempt,
                outcome="success_nonempty",
                http_status=200,
                exit_code=0,
                stdout=a,
                stderr=a,
                records=a,
            )
        b = ledger.save_bytes(ledger.read_ref(a), producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=b,
            stderr=b,
            records=b,
        )

        def swap(rows):
            rows[-1]["payload"]["records"] = a

        rewrite_for_tamper_test(ledger, swap)
        self.assertIn(
            "completion-artifact-producer-mismatch: records",
            validate_run(ledger.root)["errors"],
        )

    def prepare_claim(self):
        ledger = self.ledger
        add_query(
            ledger,
            [
                SYNTHETIC,
                dict(SYNTHETIC, version="record-v2"),
                dict(SYNTHETIC, doi="10.5555/other", title="Other synthetic record"),
            ],
        )
        ledger.extract()
        works = list(ledger.candidates().values())
        work = works[0]
        version = work["version_ids"][0]
        source = ledger.start_source_import(
            work_id=work["work_id"],
            version_id=version,
            source_uri="https://example.invalid/source",
            actor="synthetic",
            reason="Read saved text",
        )
        raw = ledger.save_bytes(b"Synthetic supported text", producer=source)
        return dict(
            work_id=work["work_id"],
            version_id=version,
            claim_text="Synthetic claim",
            relation="supports",
            evidence_level="full_text",
            source_ref=raw,
            locator={"section": "results", "quote": "supported text"},
            verifier={"actor": "synthetic", "actor_type": "agent", "method": "read"},
        ), works

    def test_evidence_work_version_bound_on_write_and_replay(self):
        claim, works = self.prepare_claim()
        wrong = [
            (works[1]["work_id"], works[1]["version_ids"][0]),
            (works[0]["work_id"], works[0]["version_ids"][1]),
        ]
        for work, version in wrong:
            with (
                self.subTest(work=work, version=version),
                self.assertRaisesRegex(LedgerError, "source-work-version"),
            ):
                self.ledger.claim(**dict(claim, work_id=work, version_id=version))
        self.ledger.claim(**claim)
        original = self.ledger.events()
        for work, version in wrong:

            def mutate(rows):
                rows[:] = deepcopy(original)
                rows[-1]["payload"].update(work_id=work, version_id=version)

            rewrite_for_tamper_test(self.ledger, mutate)
            self.assertIn(
                "claim-source-work-version-mismatch",
                validate_run(self.ledger.root)["errors"],
            )

    def test_batch_quote_must_belong_to_bound_record(self):
        ledger = self.ledger
        _, raw = add_query(
            ledger,
            [
                dict(SYNTHETIC, title="first text"),
                dict(SYNTHETIC, doi="10.5555/other", title="second text"),
            ],
        )
        ledger.extract()
        work = next(iter(ledger.candidates().values()))
        claim = dict(
            work_id=work["work_id"],
            version_id=work["version_ids"][0],
            claim_text="Synthetic",
            relation="supports",
            evidence_level="abstract",
            source_ref=raw,
            locator={"section": "abstract", "quote": "second text"},
            verifier={"actor": "synthetic", "actor_type": "agent", "method": "read"},
        )
        with self.assertRaisesRegex(LedgerError, "bound-record"):
            ledger.claim(**claim)
        claim["locator"]["quote"] = "first text"
        ledger.claim(**claim)
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_import_ref_requires_existing_version_and_immutable_bytes(self):
        claim, _ = self.prepare_claim()
        with self.assertRaisesRegex(LedgerError, "unknown-version"):
            self.ledger.start_source_import(
                work_id="missing",
                version_id=claim["version_id"],
                source_uri="https://example.invalid/source",
                actor="synthetic",
                reason="Synthetic",
            )
        self.ledger.claim(**claim)
        (self.ledger.root / claim["source_ref"]["path"]).write_bytes(b"changed")
        self.assertFalse(validate_run(self.ledger.root)["valid"])
