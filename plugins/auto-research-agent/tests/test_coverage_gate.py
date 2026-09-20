"""End-to-end synthetic coverage gates, without live or benchmark inputs."""

import unittest
from copy import deepcopy

import test_coverage_evidence as evidence_tests
import test_coverage_rounds as round_tests
from test_stage1_ledger import rewrite_for_tamper_test
from test_stage1_ledger import SYNTHETIC
from stage1_ledger.journal import LedgerError, canonical, decode
from stage1_ledger.readiness import readiness
from stage1_ledger.validation import validate_run


class CoverageGateTests(unittest.TestCase):
    setUp = evidence_tests.CoverageEvidenceTests.setUp
    observe = round_tests.CoverageRoundTests.observe

    def expand(self, operation):
        query = self.ledger.start_expansion(operation, self.work, self.version)
        attempt = self.ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        raw = self.ledger.save_bytes(canonical([]), producer=attempt)
        self.ledger.finish(
            attempt,
            outcome="success_empty",
            http_status=200,
            exit_code=0,
            stdout=raw,
            stderr=raw,
            records=raw,
        )
        complete = self.ledger.complete_query(query)
        self.ledger.receipt(
            complete, truncated=False, note="Synthetic complete expansion"
        )

    def finish_round(self, *, first=False, failed=False):
        if not first:
            self.ledger.open_round()
        for index, planned in enumerate(self.ledger.coverage_state().queries):
            if first and planned == self.planned:
                continue
            self.observe(planned, failure=failed and index == 1)
        return self.ledger.close_round()

    def prepare_review(self, *, verified=True, expand=True):
        request = deepcopy(self.request)
        if not verified:
            request["identity_status"] = "unverifiable"
            request["identity_claims"]["version"] = None
        self.ledger.review_work(**request)
        if expand:
            self.expand("references")
            self.expand("cited-by")

    def test_sufficient_operational_stop_requires_two_complete_zero_yield_rounds(self):
        self.prepare_review()
        self.finish_round(first=True)
        self.finish_round()
        self.assertEqual(readiness(validate_run(self.ledger.root))[1], "continue")
        self.finish_round()
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(
            [len(r["new_qualified_work_ids"]) for r in report["coverage"]["rounds"]],
            [1, 0, 0],
        )
        self.assertEqual(report["coverage"]["blockers"], [])
        checkpoint = self.ledger.checkpoint()
        self.assertEqual(
            checkpoint["stage_result"]["next_allowed_action"], "stop-sufficient"
        )
        self.assertEqual(checkpoint["stage_result"]["status"], "completed")
        handoff_ref = checkpoint["stage_result"]["outputs"][-1]
        handoff = decode(self.ledger.read_ref(handoff_ref), "handoff")
        self.assertTrue(handoff["eligible_for_stage2"])
        self.assertEqual(handoff["papers"][0]["reviewed_version_id"], self.version)
        self.assertFalse(handoff["stage2"]["execution_authorized"])
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        self.ledger.recover()
        self.assertIn(
            "scientific truth is not evaluated",
            (self.ledger.root / "coverage_and_stop.md").read_text(encoding="utf-8"),
        )
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"]["stage_result"]["gate"].update(
                reasons=["fabricated stopping justification"]
            ),
        )
        self.assertIn(
            "checkpoint-gate-mismatch", validate_run(self.ledger.root)["errors"]
        )

    def test_missing_closest_verification_and_human_acceptance_cannot_override(self):
        self.prepare_review(verified=False)
        self.finish_round(first=True)
        self.finish_round()
        self.finish_round()
        state = self.ledger.state_hash()
        action = self.ledger.human_action(
            action="accept-stop",
            actor="synthetic-human",
            user_input="Synthetic approval, not a real user authorization",
            reviewed_state_sha256=state,
        )
        self.assertEqual(action["reviewed_state_sha256"], state)
        report = validate_run(self.ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertIn("closest-work-unverified", report["coverage"]["blockers"])
        self.assertEqual(readiness(report)[1], "human-review")
        with self.assertRaisesRegex(LedgerError, "stale-human-authorization"):
            self.ledger.human_action(
                action="accept-stop",
                actor="synthetic-human",
                user_input="Stale input",
                reviewed_state_sha256=state,
            )

    def test_429_round_does_not_count_as_zero_yield_saturation(self):
        self.prepare_review()
        self.finish_round(first=True)
        self.finish_round(failed=True)
        self.finish_round()
        report = validate_run(self.ledger.root)
        self.assertEqual(
            report["coverage"]["consecutive_complete_zero_yield_rounds"], 1
        )
        self.assertEqual(readiness(report)[1], "human-review")
        self.assertEqual(report["counts"]["backend_failures"], 1)

    def test_missing_expansion_and_exclusion_reversal_remove_stop_eligibility(self):
        self.prepare_review(expand=False)
        self.finish_round(first=True)
        self.finish_round()
        self.finish_round()
        report = validate_run(self.ledger.root)
        self.assertTrue(
            any(
                "closest-expansion-incomplete" in b
                for b in report["coverage"]["blockers"]
            )
        )
        self.ledger.decide(
            self.work,
            "exclude",
            reason="scope-reassessment",
            rationale="Synthetic reversal",
            evidence_refs=[self.source],
        )
        report = validate_run(self.ledger.root)
        self.assertEqual(report["coverage"]["clusters"]["cluster-1"]["work_ids"], [])
        self.assertNotEqual(readiness(report)[1], "stop-sufficient")

    def test_human_cluster_request_needs_new_complete_queries(self):
        self.prepare_review()
        self.finish_round(first=True)
        action = self.ledger.human_action(
            action="request-cluster",
            actor="synthetic-human",
            user_input="Please search synthetic cluster 1 again",
            reviewed_state_sha256=self.ledger.state_hash(),
            cluster_id="cluster-1",
        )
        self.assertEqual(
            validate_run(self.ledger.root)["coverage"]["outstanding_human_actions"],
            [action["event_id"]],
        )
        self.finish_round()
        self.assertEqual(
            validate_run(self.ledger.root)["coverage"]["outstanding_human_actions"], []
        )
        self.finish_round()
        self.assertEqual(
            readiness(validate_run(self.ledger.root))[1], "stop-sufficient"
        )

    def test_rehashed_human_input_cannot_borrow_another_state(self):
        self.ledger.human_action(
            action="request-cluster",
            actor="synthetic-human",
            user_input="Synthetic request",
            reviewed_state_sha256=self.ledger.state_hash(),
            cluster_id="cluster-1",
        )
        rewrite_for_tamper_test(
            self.ledger,
            lambda rows: rows[-1]["payload"].update(reviewed_state_sha256="0" * 64),
        )
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("stale-human-authorization", report["errors"])

    def test_missing_evidence_and_unreviewed_work_fail_closed(self):
        self.finish_round(first=True)
        report = validate_run(self.ledger.root)
        self.assertEqual(report["coverage"]["unreviewed_work_ids"], [self.work])
        self.assertFalse(report["coverage"]["rounds"][0]["complete"])
        (self.ledger.root / self.source["path"]).unlink()
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertEqual(readiness(report)[1], "human-review")

    def test_foreign_source_cannot_verify_closest_work_or_stop(self):
        self.observe(self.planned, rows=[dict(SYNTHETIC, doi="10.5555/other")])
        other = next(
            w for w in self.ledger.candidates().values() if w["work_id"] != self.work
        )
        acquisition = self.ledger.start_source_import(
            work_id=other["work_id"],
            version_id=other["version_ids"][0],
            source_uri="https://example.invalid/other",
            actor="synthetic",
            reason="Other work",
        )
        raw = self.ledger.save_bytes(
            b"Synthetic household record", producer=acquisition
        )
        claim = dict(self.ledger.event(self.claims["title"]))
        for key in ("event_id", "created_at", "schema_version"):
            claim.pop(key)
        claim["source_ref"] = raw
        # Bypass the writing API to model a rehashed/malicious journal.
        forged = self.ledger.append(claim)
        request = deepcopy(self.request)
        request["identity_claims"]["title"] = forged["event_id"]
        with self.assertRaisesRegex(LedgerError, "source-work-version"):
            self.ledger.review_work(**request)
        report = validate_run(self.ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("claim-source-work-version-mismatch", report["errors"])
        self.assertNotEqual(readiness(report)[1], "stop-sufficient")


if __name__ == "__main__":
    unittest.main()
