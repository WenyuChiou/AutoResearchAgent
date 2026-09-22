"""Saved-record comparisons are reproducible observations, not source authentication."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_ledger.store import Ledger
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.validation import validate_run
from stage1_ledger.contracts import validator
from test_stage1_ledger import SYNTHETIC, rewrite_for_tamper_test


def observe(ledger, record, backend):
    query = ledger.start("search", {"query": "synthetic metadata observation"})
    attempt = ledger.start(
        "backend", {"variant": "base"}, backend=backend, parent_id=query
    )
    raw = ledger.save_bytes(canonical([record]), producer=attempt)
    empty = ledger.save_bytes(b"", producer=attempt)
    completion = ledger.finish(
        attempt,
        outcome="success_nonempty",
        http_status=200,
        exit_code=0,
        stdout=raw,
        stderr=empty,
        records=raw,
    )
    ledger.complete_query(query)
    ledger.extract()
    return completion + ":0", raw, attempt


class IdentityComparisonTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Ledger.create(
            Path(self.directory.name) / "run",
            run_id="synthetic",
            objective="Synthetic comparison",
        )
        self.target, self.raw, self.attempt = observe(
            self.ledger, SYNTHETIC, "synthetic-search"
        )
        self.work = next(iter(self.ledger.candidates()))

    def compare(self, reference=None, resolver=None):
        event = self.ledger.compare_identity(
            target_work_id=self.work,
            target_discovery_id=self.target,
            reference_discovery_id=reference,
            resolver_ref=resolver,
            assessor="synthetic-agent",
        )
        return self.ledger.event(event, "IdentityComparison")

    def test_matching_metadata_keeps_identity_version_and_claims_separate(self):
        reference, _, _ = observe(
            self.ledger,
            dict(SYNTHETIC, doi="https://doi.org/10.5555/STAGE1-SYNTHETIC"),
            "synthetic-catalog",
        )
        event = self.compare(reference)
        self.assertEqual(
            (event["work_agreement"], event["version_agreement"]),
            ("consistent", "consistent"),
        )
        self.assertEqual(event["source_relationship"], "different-backends")
        self.assertEqual(
            event["fields"],
            dict(
                title="match",
                authors="match",
                year="match",
                doi="match",
                arxiv="unavailable",
                pmid="unavailable",
                version="match",
                arxiv_version="unavailable",
            ),
        )
        self.assertEqual(
            self.ledger.candidates()[self.work]["identity_status"], "unverified"
        )
        self.assertEqual(self.ledger.records("claim_evidence.jsonl"), [])
        validator("IdentityComparison").evolve(
            schema={"$ref": "urn:auto-research-agent:stage1-ledger:1.0.0"}
        ).validate(event)
        self.assertEqual(
            self.ledger.identity_status()["identity_verification"], "not-performed"
        )
        checkpoint = self.ledger.checkpoint()
        self.assertNotEqual(
            checkpoint["stage_result"]["next_allowed_action"], "stop-sufficient"
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_resolver_and_same_backend_cannot_establish_independent_agreement(self):
        resolver = self.ledger.save_bytes(
            b'{"http_status":200,"resolved":true}', producer=self.attempt
        )
        event = self.compare(resolver=resolver)
        self.assertEqual(
            (event["work_agreement"], event["version_agreement"]),
            ("unverified", "unverified"),
        )
        self.assertEqual(event["source_relationship"], "resolver-only")
        reference, _, _ = observe(self.ledger, SYNTHETIC, "synthetic-search")
        repeated = self.compare(reference)
        self.assertEqual(repeated["fields"]["title"], "match")
        self.assertEqual(repeated["work_agreement"], "unverified")
        self.assertEqual(repeated["previous_comparison_id"], event["event_id"])
        with self.assertRaisesRegex(LedgerError, "same-discovery"):
            self.compare(self.target)

    def test_conflicts_and_unknown_versions_are_not_silently_resolved(self):
        for field, value in [
            ("title", "Different synthetic title"),
            ("authors", ["Other synthetic author"]),
            ("year", 2025),
            ("doi", "10.5555/other-synthetic"),
        ]:
            with self.subTest(field=field):
                reference, _, _ = observe(
                    self.ledger, dict(SYNTHETIC, **{field: value}), "synthetic-catalog"
                )
                event = self.compare(reference)
                self.assertEqual(event["fields"][field], "mismatch")
                self.assertEqual(event["work_agreement"], "conflict")
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_version_mismatch_and_missing_year_do_not_become_matches(self):
        reference, _, _ = observe(
            self.ledger, dict(SYNTHETIC, version="record-v2"), "synthetic-catalog"
        )
        event = self.compare(reference)
        self.assertEqual(
            (event["work_agreement"], event["version_agreement"]),
            ("consistent", "conflict"),
        )
        reference, _, _ = observe(
            self.ledger, dict(SYNTHETIC, version=None), "synthetic-catalog"
        )
        self.assertEqual(self.compare(reference)["version_agreement"], "unverified")
        reference, _, _ = observe(
            self.ledger, dict(SYNTHETIC, year=None), "synthetic-catalog"
        )
        event = self.compare(reference)
        self.assertEqual(event["fields"]["year"], "unavailable")
        self.assertNotEqual(event["work_agreement"], "consistent")

    def test_reassessment_is_append_only_and_new_discovery_makes_it_stale(self):
        reference, _, _ = observe(self.ledger, SYNTHETIC, "synthetic-catalog")
        first = self.compare(reference)
        before = (self.ledger.root / "stage_events.jsonl").read_bytes()
        self.assertTrue(self.ledger.identity_status()["comparisons"][0]["current"])
        observe(self.ledger, SYNTHETIC, "synthetic-extra")
        self.assertFalse(self.ledger.identity_status()["comparisons"][0]["current"])
        second = self.compare(reference)
        self.assertEqual(second["previous_comparison_id"], first["event_id"])
        self.assertTrue(
            (self.ledger.root / "stage_events.jsonl").read_bytes().startswith(before)
        )
        self.assertTrue(self.ledger.identity_status()["comparisons"][0]["current"])

    def test_secondary_identifiers_and_arxiv_versions_are_not_ignored(self):
        record = dict(SYNTHETIC, pmid="999111111", arxiv="9901.99999v1")
        self.target, _, _ = observe(self.ledger, record, "synthetic-search")
        reference, _, _ = observe(
            self.ledger, dict(record, pmid="999222222"), "synthetic-catalog"
        )
        event = self.compare(reference)
        self.assertEqual(event["fields"]["doi"], "match")
        self.assertEqual(event["fields"]["pmid"], "mismatch")
        self.assertEqual(event["work_agreement"], "conflict")
        reference, _, _ = observe(
            self.ledger, dict(record, pmid="invalid"), "synthetic-catalog"
        )
        self.assertEqual(self.compare(reference)["fields"]["pmid"], "invalid")
        reference, _, _ = observe(
            self.ledger, dict(record, arxiv="9901.99999v2"), "synthetic-catalog"
        )
        event = self.compare(reference)
        self.assertEqual(
            (event["work_agreement"], event["version_agreement"]),
            ("consistent", "conflict"),
        )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_metadata_without_a_shared_identifier_stays_unverified(self):
        record = {key: value for key, value in SYNTHETIC.items() if key != "doi"}
        self.target, _, _ = observe(self.ledger, record, "synthetic-search")
        self.work = next(
            c["work_id"]
            for c in self.ledger.candidates().values()
            if any(d["discovery_id"] == self.target for d in c["discoveries"])
        )
        reference, _, _ = observe(self.ledger, record, "synthetic-catalog")
        event = self.compare(reference)
        self.assertEqual(event["fields"]["title"], "match")
        self.assertEqual(event["work_agreement"], "unverified")

    def test_rehashed_fabrication_and_missing_source_fail_validation(self):
        reference, raw, _ = observe(
            self.ledger, dict(SYNTHETIC, version="record-v2"), "synthetic-catalog"
        )
        self.compare(reference)
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"].update(version_agreement="consistent"),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("identity-comparison-replay", report["errors"][0])
        with self.assertRaisesRegex(LedgerError, "invalid-identity-state"):
            self.ledger.identity_status()
        (self.ledger.root / raw["path"]).unlink()
        self.assertFalse(validate_run(self.ledger.root)["valid"])

    def test_cli_produces_the_recorded_comparison(self):
        reference, _, _ = observe(self.ledger, SYNTHETIC, "synthetic-catalog")
        request = Path(self.directory.name) / "request.json"
        request.write_bytes(
            canonical(
                dict(
                    target_work_id=self.work,
                    target_discovery_id=self.target,
                    reference_discovery_id=reference,
                    resolver_ref=None,
                    assessor="synthetic-agent",
                )
            )
        )
        process = subprocess.run(
            [
                sys.executable,
                str(PLUGIN / "cli/stage1_ledger"),
                "--run",
                str(self.ledger.root),
                "compare-identity",
                "--request",
                str(request),
            ],
            capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        event = self.ledger.event(json.loads(process.stdout)["event_id"])
        self.assertEqual(event["work_agreement"], "consistent")


if __name__ == "__main__":
    unittest.main()
