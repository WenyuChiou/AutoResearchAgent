"""Source intake records observations; it never performs retrieval or verifies science."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_stage1_ledger import fixture, add_query, SYNTHETIC, rewrite_for_tamper_test
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.validation import validate_run
from stage1_ledger.readiness import readiness
from stage1_export.bundle import export_run, validate_export


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger, self.refs, self.work, _ = fixture(self.root / "run")
        self.version = self.ledger.candidates()[self.work]["version_ids"][0]

    def start(self, uri="https://example.invalid/synthetic-source"):
        return self.ledger.start_source(
            work_id=self.work,
            version_id=self.version,
            source_uri=uri,
            tool="synthetic-reader",
            request={"url": uri},
            actor="synthetic-agent",
            reason="Read a discovered synthetic version; no network is executed.",
        )

    def finish(
        self, attempt, outcome="available", status=200, body=b"Synthetic paper text."
    ):
        raw = self.ledger.save_bytes(body, producer=attempt)
        request = dict(
            attempt_id=attempt,
            outcome=outcome,
            observed_at=self.ledger.clock(),
            http_status=status,
            resolved_uri="https://example.invalid/synthetic-source",
            raw_ref=raw,
            text_ref=raw if outcome == "available" else None,
            extraction={"method": "identity", "version": "1"}
            if outcome == "available"
            else None,
            reason="Synthetic captured observation; source authenticity not established.",
        )
        return self.ledger.finish_source(**request), raw, request

    def claim(self, ref, **updates):
        request = dict(
            work_id=self.work,
            version_id=self.version,
            claim_text="Synthetic scoped claim",
            relation="supports",
            evidence_level="full_text",
            locator={"section": "Synthetic section", "quote": "Synthetic paper text"},
            source_ref=ref,
            verifier={
                "actor": "synthetic-agent",
                "actor_type": "agent",
                "method": "saved text only",
            },
        )
        request.update(updates)
        return self.ledger.claim(**request)

    def test_source_lifecycle_keeps_search_counts_and_identity_separate(self):
        before = validate_run(self.ledger.root)["counts"]
        attempt = self.start()
        self.assertEqual(self.ledger.recover()["pending_actions"], [attempt])
        self.assertEqual(self.ledger.recover()["automatic_retries"], 0)
        _, raw, _ = self.finish(attempt)
        self.claim(raw)
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["counts"], dict(before, claims=1))
        self.assertEqual(report["source_reads"]["available"], 1)
        self.assertEqual(report["pending_actions"], [])
        self.assertEqual(
            self.ledger.candidates()[self.work]["identity_status"], "unverified"
        )
        self.ledger.checkpoint()
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_pending_and_failure_block_a_previously_sufficient_stop(self):
        from test_coverage_gate import CoverageGateTests

        case = CoverageGateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.prepare_review()
        case.finish_round(first=True)
        case.finish_round()
        case.finish_round()
        self.ledger, self.work, self.version = case.ledger, case.work, case.version
        self.assertEqual(
            readiness(validate_run(self.ledger.root))[1], "stop-sufficient"
        )
        first = self.start()
        self.assertNotEqual(
            readiness(validate_run(self.ledger.root))[1], "stop-sufficient"
        )
        with self.assertRaisesRegex(LedgerError, "source-attempt-pending"):
            self.start()
        self.finish(first, "rate_limited", 429, b"Synthetic rate limit")
        report = validate_run(self.ledger.root)
        self.assertIn(
            "source-read-failure-requires-review", readiness(report)[0]["reasons"]
        )
        replacement = self.start("https://example.invalid/synthetic-alternate")
        self.assertEqual(self.ledger.event(replacement)["previous_attempt_id"], first)
        self.finish(replacement)
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["source_reads"]["failed"], 1)
        self.assertEqual(report["source_reads"]["available"], 1)
        self.assertEqual(report["source_reads"]["unresolved_failure_attempt_ids"], [])
        self.assertEqual(readiness(report)[1], "stop-sufficient")
        self.ledger.checkpoint()
        rendered = (self.ledger.root / "coverage_and_stop.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(first, rendered)
        self.assertIn(replacement, rendered)
        self.assertIn("429", rendered)
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_claim_rejects_pending_failed_or_other_version_source(self):
        action = self.start()
        raw = self.ledger.save_bytes(b"Synthetic paper text", producer=action)
        with self.assertRaisesRegex(LedgerError, "claim-source-work-version"):
            self.claim(raw)
        self.finish(action, "http_error", 403, b"Synthetic paper text")
        with self.assertRaisesRegex(LedgerError, "claim-source-work-version"):
            self.claim(raw)
        self.claim(
            raw, relation="unverifiable", evidence_level="unavailable", locator=None
        )
        self.finish(self.start())
        latest = self.ledger.events()[-1]["payload"]["text_ref"]
        add_query(
            self.ledger,
            [
                dict(
                    SYNTHETIC,
                    doi="10.5555/stage1-source-other",
                    title="Synthetic other work",
                )
            ],
        )
        self.ledger.extract()
        other = next(
            w for w in self.ledger.candidates().values() if w["work_id"] != self.work
        )
        with self.assertRaisesRegex(LedgerError, "claim-source-work-version"):
            self.claim(
                latest, work_id=other["work_id"], version_id=other["version_ids"][0]
            )

    def test_failed_read_cannot_label_error_receipt_as_paper_evidence(self):
        _, raw, _ = self.finish(self.start(), "rate_limited", 429)
        for relation in ("pending", "unclear", "unverifiable"):
            for level in (
                "metadata",
                "abstract",
                "full-text",
                "full_text",
                "primary_data_or_table",
            ):
                with (
                    self.subTest(relation=relation, level=level),
                    self.assertRaisesRegex(LedgerError, "claim-source-work-version"),
                ):
                    self.claim(raw, relation=relation, evidence_level=level)
            with self.assertRaisesRegex(
                LedgerError, "unavailable-evidence-has-locator"
            ):
                self.claim(raw, relation=relation, evidence_level="unavailable")
            self.claim(
                raw, relation=relation, evidence_level="unavailable", locator=None
            )
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_unresolved_text_claim_must_use_extracted_text_not_raw_response(self):
        attempt = self.start()
        raw = self.ledger.save_bytes(b"<p>Synthetic paper text</p>", producer=attempt)
        text = self.ledger.save_bytes(b"Synthetic paper text", producer=attempt)
        self.ledger.finish_source(
            attempt_id=attempt,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=200,
            resolved_uri=None,
            raw_ref=raw,
            text_ref=text,
            extraction={"method": "synthetic-html-text", "version": "1"},
            reason="Synthetic raw response and separately extracted text",
        )
        for relation in ("pending", "unclear", "unverifiable"):
            for level in (
                "abstract",
                "full-text",
                "full_text",
                "primary_data_or_table",
            ):
                with (
                    self.subTest(relation=relation, level=level),
                    self.assertRaisesRegex(LedgerError, "claim-source-work-version"),
                ):
                    self.claim(raw, relation=relation, evidence_level=level)
                self.claim(text, relation=relation, evidence_level=level)
        self.assertTrue(validate_run(self.ledger.root)["valid"])

    def test_rehashed_failed_read_claim_cannot_promote_error_bytes(self):
        _, raw, _ = self.finish(self.start(), "rate_limited", 429)
        self.claim(
            raw, relation="unverifiable", evidence_level="unavailable", locator=None
        )
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: next(
                row["payload"]
                for row in rows
                if row["payload"].get("kind") == "ClaimEvidence"
            ).update(
                evidence_level="full_text",
                locator={"section": "Synthetic error", "quote": "Synthetic paper text"},
            ),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"], report)
        self.assertIn("claim-source-work-version-or-availability", report["errors"])

    def test_no_empty_text_false_http_success_or_future_observation(self):
        action = self.start()
        raw = self.ledger.save_bytes(b"", producer=action)
        request = dict(
            attempt_id=action,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=200,
            resolved_uri=None,
            raw_ref=raw,
            text_ref=raw,
            extraction={"method": "identity", "version": "1"},
            reason="Synthetic",
        )
        with self.assertRaisesRegex(LedgerError, "source-text-empty"):
            self.ledger.finish_source(**request)
        request["http_status"] = 403
        with self.assertRaisesRegex(LedgerError, "source-http-failure-outcome"):
            self.ledger.finish_source(**request)
        request.update(http_status=200, observed_at="2030-01-01T00:00:00Z")
        with self.assertRaisesRegex(LedgerError, "source-observation-time-order"):
            self.ledger.finish_source(**request)
        self.finish(action)

    def test_text_extraction_binding_and_missing_raw_fail_closed(self):
        action = self.start()
        raw = self.ledger.save_bytes(b"<p>Synthetic paper text</p>", producer=action)
        text = self.ledger.save_bytes(b"Synthetic paper text", producer=action)
        request = dict(
            attempt_id=action,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=None,
            resolved_uri=None,
            raw_ref=raw,
            text_ref=text,
            extraction={"method": "identity", "version": "1"},
            reason="Synthetic tool has no observed HTTP status",
        )
        with self.assertRaisesRegex(LedgerError, "source-identity-extraction"):
            self.ledger.finish_source(**request)
        request["extraction"] = {"method": "synthetic-html-text", "version": "1"}
        self.ledger.finish_source(**request)
        self.claim(text)
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        (self.ledger.root / raw["path"]).unlink()
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn(raw["path"], str(report["errors"]))
        self.assertIsNone(report["source_reads"])

    def test_completion_cannot_borrow_another_producers_identical_bytes(self):
        first = self.start()
        _, foreign, _ = self.finish(first)
        second = self.start()
        local = self.ledger.save_bytes(b"Synthetic paper text.", producer=second)
        self.assertEqual(local["path"], foreign["path"])
        request = dict(
            attempt_id=second,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=200,
            resolved_uri=None,
            raw_ref=local,
            text_ref=local,
            extraction={"method": "identity", "version": "1"},
            reason="Synthetic binding test",
        )
        for field in ("raw_ref", "text_ref"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    LedgerError, "source-artifact-producer-mismatch"
                ),
            ):
                self.ledger.finish_source(**dict(request, **{field: foreign}))
        self.ledger.finish_source(**request)
        with self.assertRaisesRegex(LedgerError, "source-attempt-not-open"):
            self.ledger.finish_source(**request)
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: next(
                row["payload"]
                for row in rows
                if row["payload"].get("attempt_id") == second
            ).update(raw_ref=foreign, text_ref=foreign),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("source-artifact-producer-mismatch", report["errors"])

    def test_failure_kinds_are_explicit_and_cannot_supply_support(self):
        for outcome, status in [
            ("not_found", 404),
            ("not_found", 410),
            ("rate_limited", 429),
            ("http_error", 503),
            ("network_error", None),
            ("parse_error", 200),
            ("unavailable", None),
            ("interrupted", None),
        ]:
            with self.subTest(outcome=outcome, status=status):
                attempt = self.start()
                _, raw, _ = self.finish(
                    attempt, outcome, status, b"Synthetic paper text."
                )
                with self.assertRaisesRegex(
                    LedgerError, "claim-source-work-version-or-availability"
                ):
                    self.claim(raw)
                self.claim(
                    raw,
                    relation="unverifiable",
                    evidence_level="unavailable",
                    locator=None,
                )
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["source_reads"]["failed"], 8)
        self.assertEqual(report["source_reads"]["available"], 0)
        self.assertNotEqual(readiness(report)[1], "stop-sufficient")

    def test_inconsistent_status_and_new_schema_version_reject_before_write(self):
        attempt = self.start()
        raw = self.ledger.save_bytes(b"Synthetic error", producer=attempt)
        request = dict(
            attempt_id=attempt,
            outcome="unavailable",
            observed_at=self.ledger.clock(),
            http_status=None,
            resolved_uri=None,
            raw_ref=raw,
            text_ref=None,
            extraction=None,
            reason="Synthetic failure",
        )
        before = self.ledger.events()
        for outcome, status in [
            ("unavailable", 429),
            ("not_found", 200),
            ("http_error", 200),
            ("network_error", 200),
            ("parse_error", 403),
            ("unavailable", 503),
        ]:
            with self.subTest(outcome=outcome), self.assertRaises(LedgerError):
                self.ledger.finish_source(
                    **dict(request, outcome=outcome, http_status=status)
                )
        from stage1_ledger.contracts import check_payload

        with self.assertRaisesRegex(LedgerError, "schema:"):
            check_payload(dict(self.ledger.event(attempt), schema_version="999.0.0"))
        self.assertEqual(self.ledger.events(), before)
        self.ledger.finish_source(**request)

    def test_coverage_review_consumes_bound_source_text_without_promoting_identity(
        self,
    ):
        from test_coverage_gate import CoverageGateTests

        case = CoverageGateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.ledger, self.work, self.version = case.ledger, case.work, case.version
        _, raw, _ = self.finish(self.start())
        claim = self.claim(raw)
        request = dict(
            case.request,
            cluster_claims={key: claim for key in case.request["cluster_claims"]},
        )
        self.ledger.review_work(**request)
        case.expand("references")
        case.expand("cited-by")
        case.finish_round(first=True)
        case.finish_round()
        case.finish_round()
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(readiness(report)[1], "stop-sufficient")
        self.assertEqual(
            self.ledger.candidates()[self.work]["identity_status"], "unverified"
        )

    def test_rehashed_source_history_cannot_borrow_another_attempt(self):
        first = self.start()
        self.finish(first)
        second = self.start()
        self.finish(second)
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: next(
                r["payload"] for r in rows if r["payload"].get("event_id") == second
            ).update(previous_attempt_id=None),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("source-attempt-history", report["errors"])

    def test_export_replays_source_observations_without_scoring(self):
        self.finish(self.start())
        self.ledger.checkpoint()
        output = self.root / "export"
        result = export_run(self.ledger.root, output)
        self.assertTrue(result["valid"], result)
        self.assertTrue(validate_export(output)["valid"])
        inputs = json.loads((output / "metric_inputs.json").read_bytes())
        self.assertEqual(inputs["judgment_scores"]["P1"]["status"], "not_scored")

    def test_public_cli_records_a_source_attempt(self):
        request = dict(
            work_id=self.work,
            version_id=self.version,
            source_uri="https://example.invalid/synthetic",
            tool="synthetic-reader",
            request={"url": "https://example.invalid/synthetic"},
            actor="synthetic-agent",
            reason="Synthetic CLI contract",
        )
        path = self.root / "source-request.json"
        path.write_bytes(canonical(request))
        cli = Path(__file__).resolve().parents[1] / "cli/stage1_ledger"
        completed = subprocess.run(
            [
                sys.executable,
                str(cli),
                "--run",
                str(self.ledger.root),
                "start-source",
                "--request",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        event = json.loads(completed.stdout)["event_id"]
        self.assertEqual(self.ledger.event(event)["request"], request["request"])
        from stage1_ledger.store import Ledger

        self.ledger = Ledger(self.ledger.root)
        raw = self.ledger.save_bytes(
            b"Synthetic source acquired through public CLI", producer=event
        )
        observation = dict(
            attempt_id=event,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=None,
            resolved_uri=None,
            raw_ref=raw,
            text_ref=raw,
            extraction={"method": "identity", "version": "1"},
            reason="Synthetic CLI observation",
        )
        path = self.root / "source-completion.json"
        path.write_bytes(canonical(observation))
        completed = subprocess.run(
            [
                sys.executable,
                str(cli),
                "--run",
                str(self.ledger.root),
                "finish-source",
                "--request",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(
            self.ledger.event(json.loads(completed.stdout)["event_id"])["raw_ref"], raw
        )
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["source_reads"]["available"], 1)


if __name__ == "__main__":
    unittest.main()
