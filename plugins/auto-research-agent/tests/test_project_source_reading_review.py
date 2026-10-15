"""Manual reading registry with authored sources, real Core and real SQLite."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from test_project_saved_claims import request as claim_request, saved_case
from research_workspace_native.project_reading_review import ProjectReadingReviewService
from research_workspace_native.project_saved_claims import ProjectSavedClaimService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha


def api(case, claims):
    return ProjectReadingReviewService(saved_claims=claims)


def body(service, ref, work, key="manual-reading"):
    view = service.view_source("alice-token", ref, work)
    return dict(
        key=key,
        confirmed=True,
        offer_ref=view["reading_review_offer"]["offer_ref"],
        offer_sha256=view["reading_review_offer"]["offer_sha256"],
        review={
            field: deepcopy(view[field])
            for field in ("classification", "findings", "roles")
        },
        **{
            field: view[field]
            for field in (
                "revision",
                "input_version",
                "brief_sha256",
                "ledger_state_sha256",
                "work_ref",
                "source_snapshot_sha256",
            )
        },
    )


def actions(case, ref):
    return case.intake.history("alice-token", ref)["actions"]


def repeated_claim(case, fixture, claims, work):
    quote = "Long authored source. "
    value = claim_request(claims, fixture["ref"], work, quote=quote)
    source = claims._context(fixture["ref"], work, None)["sources"][0]
    raw = fixture["ledger"].read_ref(source["text_ref"])
    start = raw.index(quote.encode(), raw.index(quote.encode()) + 1)
    value.update(start_byte=start, end_byte=start + len(quote.encode()), quote=quote)
    result = claims.claim("alice-token", fixture["ref"], value)
    return result, value, raw


class SourceReadingReviewTests(unittest.TestCase):
    def test_repeated_manual_span_all_claims_and_unknowns_are_registered(self):
        with saved_case(long=True) as (case, fixture, claims, work):
            ref, ledger = fixture["ref"], fixture["ledger"]
            manual, request, raw = repeated_claim(case, fixture, claims, work)
            event = ledger.event(manual["claim_event_id"])
            pending = ledger.claim(
                work_id=work,
                version_id=event["version_id"],
                claim_text="Unknown: authored unassessed observation",
                relation="pending",
                evidence_level="unavailable",
                locator=None,
                source_ref=event["source_ref"],
                verifier=dict(actor="fixture", actor_type="human", method="authored"),
            )
            service = api(case, claims)
            before = ledger.events()
            view = service.view_source("alice-token", ref, work)
            self.assertEqual(view["source_mode"], "saved-source-review")
            self.assertEqual(view["model_calls"], 0)
            self.assertNotIn("draft", view)
            self.assertNotIn("output_ref", view)
            self.assertNotIn("draft_sha256", view)
            request_body = body(service, ref, work)
            result = service.review_source("alice-token", ref, request_body)
            self.assertEqual(result["status"], "saved")
            reading = result["registry_entry"]["payload"]
            self.assertEqual(reading["findings"], view["findings"])
            self.assertTrue(reading["findings"]["main_findings"].startswith("Unknown"))
            required = {
                row["payload"]["event_id"]
                for row in before
                if row["payload"]["kind"] == "ClaimEvidence"
                and (row["payload"]["work_id"], row["payload"]["version_id"])
                == (work, reading["version_id"])
            }
            self.assertEqual({row["claim_id"] for row in reading["claims"]}, required)
            span = next(
                row
                for row in reading["claims"]
                if row["claim_id"] == manual["claim_event_id"]
            )
            self.assertEqual(span, manual["reading_locator"])
            self.assertEqual(
                span["start"], len(raw[: request["start_byte"]].decode("utf8"))
            )
            self.assertGreater(span["start"], raw.decode("utf8").find(request["quote"]))
            null_span = next(
                row for row in reading["claims"] if row["claim_id"] == pending
            )
            self.assertEqual(
                [null_span[field] for field in ("start", "end", "quote")], [None] * 3
            )
            self.assertEqual(ledger.events(), before)
            self.assertIn(
                result["registry_entry"],
                case.producer._entries(case.delivery._saved_context(ref)),
            )
            raw_receipt = case.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", ref, request_body["key"]),
            ).fetchone()
            saved_request = json.loads(raw_receipt[0])["request"]
            self.assertEqual(
                saved_request,
                {
                    key: value
                    for key, value in request_body.items()
                    if key != "revision"
                },
            )
            case.runner.assert_not_called()

    def test_strict_source_owner_input_deadline_and_byte_drift_fail_before_intent(self):
        with saved_case() as (case, fixture, claims, work):
            ref = fixture["ref"]
            service = api(case, claims)
            good = body(service, ref, work)
            before, events = actions(case, ref), fixture["ledger"].events()
            for update in (
                {"root": "caller-path"},
                {"output_ref": "0" * 64},
                {"confirmed": 1},
                {"revision": 999},
                {"input_version": 999},
                {"brief_sha256": "0" * 64},
                {"ledger_state_sha256": "0" * 64},
                {"source_snapshot_sha256": "0" * 64},
                {"offer_sha256": "0" * 64},
                {"work_ref": "foreign-work"},
            ):
                with (
                    self.subTest(update=update),
                    self.assertRaises((SessionApiError, ValueError)),
                ):
                    service.review("alice-token", ref, {**good, **update})
                self.assertEqual(actions(case, ref), before)
            with self.assertRaises(SessionApiError):
                service.view_source("bob-token", ref, work)
            with self.assertRaises(SessionApiError):
                service.review("bob-token", ref, good)

            def expired():
                raise TimeoutError("authored deadline expired")

            with self.assertRaises(TimeoutError):
                service.review("alice-token", ref, good, check_deadline=expired)

            @contextmanager
            def lost_owner(*_):
                raise OSError("authored owner unavailable")
                yield  # pragma: no cover

            with patch.object(case.producer, "guard", lost_owner):
                with self.assertRaises(OSError):
                    service.review("alice-token", ref, good)
            path = fixture["pairs"][0][1] / "source/source-fetch-result.json"
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b" authored drift")
                with self.assertRaises((SessionApiError, ValueError)):
                    service.review("alice-token", ref, good)
            finally:
                path.write_bytes(raw)
            self.assertEqual(actions(case, ref), before)
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_saved_key_true_sqlite_reopen_replays_without_source_read_or_register(self):
        with saved_case(long=True) as (case, fixture, claims, work):
            ref = fixture["ref"]
            repeated_claim(case, fixture, claims, work)
            service = api(case, claims)
            good = body(service, ref, work)
            result = service.review("alice-token", ref, good)
            before, events = actions(case, ref), fixture["ledger"].events()
            case.reopen()
            service = api(case, ProjectSavedClaimService(case.stage1, case.producer))
            with (
                patch.object(
                    service,
                    "_source_view",
                    side_effect=AssertionError("replay source read"),
                ),
                patch.object(
                    case.producer,
                    "register_reading",
                    side_effect=AssertionError("replay register"),
                ),
            ):
                replay = service.review("alice-token", ref, {**good, "revision": 999})
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["registry_entry"], result["registry_entry"])
                changed = deepcopy(good)
                changed["review"]["findings"]["main_findings"] = (
                    "Changed authored annotation"
                )
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    service.review("alice-token", ref, changed)
            self.assertEqual(actions(case, ref), before)
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_post_intent_unknown_survives_sqlite_reopen_and_blocks_new_key(self):
        with saved_case(long=True) as (case, fixture, claims, work):
            ref = fixture["ref"]
            repeated_claim(case, fixture, claims, work)
            service, save = api(case, claims), case.intake._save
            good = body(service, ref, work)

            def fail(state, kind, payload):
                if kind == "stage1-reading-registry-saved":
                    raise OSError("authored precommit failure")
                return save(state, kind, payload)

            with (
                patch.object(case.intake, "_save", fail),
                self.assertRaises(SessionApiError) as error,
            ):
                service.review("alice-token", ref, good)
            self.assertEqual(error.exception.receipt["status"], "execution-unknown")
            before, events = actions(case, ref), fixture["ledger"].events()
            case.reopen()
            service = api(case, ProjectSavedClaimService(case.stage1, case.producer))
            with patch.object(
                case.producer,
                "register_reading",
                side_effect=AssertionError("unknown retry"),
            ):
                self.assertEqual(
                    service.review("alice-token", ref, good)["status"],
                    "execution-unknown",
                )
                with self.assertRaisesRegex(
                    SessionApiError, "reading-review-unresolved"
                ):
                    service.review(
                        "alice-token",
                        ref,
                        {
                            **good,
                            "key": "new",
                            "revision": case.intake.read("alice-token", ref)[
                                "revision"
                            ],
                        },
                    )
            self.assertEqual(actions(case, ref), before)
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()

    def test_rehashed_matching_receipts_cannot_change_selected_manual_occurrence(self):
        with saved_case(long=True) as (case, fixture, claims, work):
            ref = fixture["ref"]
            manual, request, raw = repeated_claim(case, fixture, claims, work)
            service = api(case, claims)
            good = body(service, ref, work)
            row = case.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", ref, request["key"]),
            ).fetchone()
            receipt = json.loads(row[0])
            first_byte = raw.find(request["quote"].encode())
            first = len(raw[:first_byte].decode("utf8"))
            receipt["reading_locator"].update(
                start=first, end=first + len(request["quote"])
            )
            receipt["saved_source_claim"].update(
                start=first_byte, end=first_byte + len(request["quote"].encode())
            )
            receipt["request"].update(
                start_byte=first_byte,
                end_byte=first_byte + len(request["quote"].encode()),
            )
            receipt["request_sha256"] = sha(
                canonical(dict(kind="stage1-claim", body=receipt["request"]))
            )
            changed = canonical(receipt).decode()
            case.intake.db.execute(
                "UPDATE intake_actions SET request_hash=?,receipt=? WHERE principal=? AND project=? AND key=?",
                (receipt["request_sha256"], changed, "alice", ref, request["key"]),
            )
            case.intake.db.commit()
            before = actions(case, ref)
            with self.assertRaisesRegex(
                SessionApiError, "manual-claim-receipt-differs"
            ):
                service.review("alice-token", ref, good)
            self.assertEqual(actions(case, ref), before)
            self.assertEqual(
                fixture["ledger"].event(manual["claim_event_id"])["locator"]["quote"],
                request["quote"],
            )
            case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
