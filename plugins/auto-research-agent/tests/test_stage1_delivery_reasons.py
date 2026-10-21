"""Reason contracts and real producer exports; no research or model calls."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from test_project_saved_claims import saved_case, request
from test_project_stage1_claims import reading_case, body as draft_body
from test_research_workspace_view import fixture_index
import test_research_workspace_harness_ops as ops_case
from stage1_ledger.contracts import check_payload
from stage1_ledger.journal import LedgerError
from research_workspace.delivery_review import derive_delivery_review
from research_workspace_native.session_api import SessionApiError


class DeliveryReasonTests(unittest.TestCase):
    def test_status_label_is_not_a_screening_explanation(self):
        from test_workspace_academic_screening import decision

        index = fixture_index()
        index["screening"] = [
            decision(1, reason="include"),
            decision(2, work=1, reason="Specific recorded topic observation"),
        ]
        result = derive_delivery_review(index)
        self.assertIn(
            "decision-reason-is-status-only",
            result["screening"]["rows"][0]["reason_issues"],
        )

    def test_unique_unknown_reasons_still_require_per_work_review(self):
        from test_workspace_academic_screening import decision

        index = fixture_index()
        index["screening"] = [
            decision(1, reason="Unknown: relevance missing for work A"),
            decision(2, work=1, reason="Unknown: relevance missing for work B"),
        ]
        result = derive_delivery_review(index)
        self.assertTrue(
            all(r["reason_review_required"] for r in result["screening"]["rows"])
        )
        self.assertIn(
            "per-work-screening-reason-review-required", result["repair_required"]
        )

    def test_missing_legacy_reason_is_not_invented_from_a_readable_quote(self):
        index = fixture_index()
        index["claims"] = [
            dict(
                claim_id="legacy",
                work_id="fixture-0",
                version_id="version-0",
                relation="unverified",
                quote="Saved exact text",
            )
        ]
        original = deepcopy(index)
        result = derive_delivery_review(index)
        row = result["claims"][0]
        self.assertEqual(row["relation"], "unverified")
        self.assertEqual(row["reason_code"], "assessment-reason-not-recorded")
        self.assertIsNone(row["assessment"])
        self.assertIn("claim-assessment-reasons-missing", result["repair_required"])
        self.assertEqual(index, original)

    def test_reason_validation_before_durable_intent_and_schema_replay(self):
        with saved_case() as (case, f, service, work):
            good = request(service, f["ref"], work)
            before = case.intake.history("alice-token", f["ref"])
            reasons = [
                None,
                {},
                dict(reason_code="why", rationale=" "),
                dict(reason_code="why", rationale="Unverified"),
                dict(reason_code="why", rationale="中" * 342),
                dict(reason_code="Bad code", rationale="Specific observation"),
                dict(reason_code="why", rationale="Specific", invented=True),
            ]
            for reason in reasons:
                with (
                    self.subTest(reason=reason),
                    self.assertRaises((ValueError, TypeError)),
                ):
                    service.claim(
                        "alice-token",
                        f["ref"],
                        {**good, "review": {**good["review"], "assessment": reason}},
                    )
                self.assertEqual(case.intake.history("alice-token", f["ref"]), before)
            good["review"]["assessment"] = dict(
                reason_code="scope-ambiguous",
                rationale="The passage does not distinguish the two populations in this assertion.",
            )
            good["review"]["relation"] = "unclear"
            saved = service.claim("alice-token", f["ref"], good)
            event = f["ledger"].event(saved["claim_event_id"])
            check_payload(event)
            with self.assertRaises(LedgerError):
                check_payload(
                    {
                        **event,
                        "assessment": dict(reason_code="why", rationale="中" * 342),
                    }
                )
            for change in (dict(schema_version="1.0.0"), dict(assessment=None)):
                with self.assertRaises(LedgerError):
                    check_payload({**event, **change})
            absent = deepcopy(event)
            del absent["assessment"]
            with self.assertRaises(LedgerError):
                check_payload(absent)
            changed = deepcopy(good)
            changed["review"]["assessment"]["rationale"] = "Changed reason"
            with self.assertRaisesRegex(SessionApiError, "idempotency"):
                service.claim("alice-token", f["ref"], changed)

    def test_draft_review_also_records_reason_without_changing_relation(self):
        with reading_case() as c:
            body = draft_body(c)
            body["review"]["assessment"] = dict(
                reason_code="source-scope-support",
                rationale="The saved passage supports this assertion in the stated scope.",
            )
            saved = c["claims"].claim("alice-token", c["ref"], body)
            event = c["fixture"]["ledger"].event(saved["claim_event_id"])
            self.assertEqual(event["assessment"], body["review"]["assessment"])
            self.assertEqual(event["schema_version"], "1.1.0")


class ReasonExportTests(unittest.TestCase):
    def test_actual_operation_exports_and_reads_explanations(self):
        case = ops_case.HarnessOpsTests(
            "test_export_fixed_inventory_hashes_and_tamper_rejected"
        )
        case.setUp()
        self.addCleanup(case.doCleanups)
        result = case.run_action(case.request("export-selection"))
        by_name = {f["name"]: f for f in result["artifacts"]}
        for name in (
            "academic_screening.json",
            "academic_screening_history.csv",
            "claim_verification.json",
            "delivery_review.json",
        ):
            item = by_name["literature/" + name]
            raw = case.service.artifact(
                "token-a", "alpha", "first", item["name"], item["sha256"]
            )
            if name.endswith(".json"):
                self.assertIsInstance(json.loads(raw), dict)


if __name__ == "__main__":
    unittest.main()
