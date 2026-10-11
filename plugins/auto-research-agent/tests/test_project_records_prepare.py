"""Explicit records preparation with real SQLite/Core and authored SDK data."""

from contextlib import contextmanager
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body
from research_workspace_native.project_records_prepare import (
    KIND,
    ProjectRecordsPrepareService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, read_json, sha


def body(case, fixture, key="prepare-records"):
    return dict(
        bound_body(case.intake.read("alice-token", fixture["ref"]), key),
        ledger_state_sha256=fixture["ledger"].state_hash(),
        checkpoint_event_id=fixture["checkpoint"]["event_id"],
        confirmed=True,
    )


def actions(case, fixture):
    return case.intake.history("alice-token", fixture["ref"])["actions"]


class ProjectRecordsPrepareTests(unittest.TestCase):
    def test_saved_ui_semantic_hash_real_offer_and_history_only_replay(self):
        with saved_stage1_case() as (case, fixture):
            service = ProjectRecordsPrepareService(case.producer)
            request = body(case, fixture)
            events = fixture["ledger"].events()
            result = service.prepare("alice-token", fixture["ref"], request)
            self.assertEqual(result["status"], "saved")
            semantic = {
                name: value for name, value in request.items() if name != "revision"
            }
            raw = case.intake.db.execute(
                "SELECT request_hash,receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                ("alice", fixture["ref"], request["key"]),
            ).fetchone()
            receipt = json.loads(raw["receipt"])
            self.assertEqual(receipt["request"], semantic)
            self.assertEqual(
                raw["request_hash"], sha(canonical(dict(kind=KIND, body=semantic)))
            )
            self.assertEqual(result["request_sha256"], raw["request_hash"])
            offer = result["delivery_offer"]
            self.assertFalse(offer["eligible_for_stage2"])
            state = case.intake._load("alice", fixture["ref"])
            saved = state["stage1_delivery_offers"][offer["offer_ref"]]
            path = Path(saved["records_path"])
            observed = path.read_bytes()
            self.assertEqual(sha(observed), offer["records_sha256"])
            records = read_json(path)
            self.assertEqual(len(records["papers"]), 2)
            self.assertIn("partial", {claim["relation"] for claim in records["claims"]})
            self.assertIn("Unknown", records["papers"][0]["findings"]["main_findings"])
            self.assertEqual(fixture["ledger"].events(), events)
            prior = actions(case, fixture)
            with patch.object(
                case.producer,
                "produce_records",
                side_effect=AssertionError("replay produced"),
            ) as produce:
                replay = service.prepare(
                    "alice-token", fixture["ref"], {**request, "revision": 999}
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["records_sha256"], result["records_sha256"])
                with self.assertRaisesRegex(SessionApiError, "idempotency"):
                    service.prepare(
                        "alice-token",
                        fixture["ref"],
                        {**request, "checkpoint_event_id": "changed"},
                    )
                with self.assertRaisesRegex(SessionApiError, "already-prepared"):
                    service.prepare(
                        "alice-token", fixture["ref"], body(case, fixture, "new-key")
                    )
                produce.assert_not_called()
            self.assertEqual(actions(case, fixture), prior)
            self.assertEqual(path.read_bytes(), observed)
            case.runner.assert_not_called()

    def test_shape_source_owner_checkpoint_and_same_deadline_refuse_before_intent(self):
        with saved_stage1_case() as (case, fixture):
            service, request = (
                ProjectRecordsPrepareService(case.producer),
                body(case, fixture),
            )
            baseline, events = actions(case, fixture), fixture["ledger"].events()
            for update in (
                {"records_path": "caller-path"},
                {"confirmed": 1},
                {"revision": 999},
                {"input_version": 999},
                {"brief_sha256": "0" * 64},
                {"ledger_state_sha256": "0" * 64},
                {"checkpoint_event_id": "old"},
            ):
                with self.subTest(update=update), self.assertRaises(SessionApiError):
                    service.prepare(
                        "alice-token", fixture["ref"], {**request, **update}
                    )
                self.assertEqual(actions(case, fixture), baseline)
            with self.assertRaises(SessionApiError):
                service.prepare("bob-token", fixture["ref"], request)
            path = fixture["pairs"][0][1] / "source/source-fetch-result.json"
            original_bytes = path.read_bytes()
            try:
                path.write_bytes(original_bytes + b" altered")
                with self.assertRaises(SessionApiError):
                    service.prepare("alice-token", fixture["ref"], request)
            finally:
                path.write_bytes(original_bytes)

            @contextmanager
            def lost_owner(*_):
                raise OSError("synthetic saved owner lost")
                yield  # pragma: no cover

            with patch.object(case.producer, "guard", lost_owner):
                with self.assertRaisesRegex(OSError, "owner lost"):
                    service.prepare("alice-token", fixture["ref"], request)

            def expired():
                raise TimeoutError("synthetic records deadline expired")

            with self.assertRaises(TimeoutError):
                service.prepare(
                    "alice-token", fixture["ref"], request, check_deadline=expired
                )
            prepared = []
            original_records = case.producer._records

            def records(*args, **kwargs):
                result = original_records(*args, **kwargs)
                prepared.append(True)
                return result

            def deadline():
                if prepared:
                    expired()

            with patch.object(case.producer, "_records", side_effect=records):
                with self.assertRaises(TimeoutError):
                    service.prepare(
                        "alice-token", fixture["ref"], request, check_deadline=deadline
                    )
            self.assertEqual(len(prepared), 1)
            self.assertEqual(actions(case, fixture), baseline)
            self.assertEqual(fixture["ledger"].events(), events)
            source_id = fixture["pairs"][0][0]["sources"][0]["source_id"]
            fixture["ledger"].save_bytes(
                b"Synthetic checkpoint drift", producer=source_id
            )
            drifted = fixture["ledger"].events()
            with self.assertRaises(SessionApiError):
                service.prepare("alice-token", fixture["ref"], body(case, fixture))
            self.assertEqual(actions(case, fixture), baseline)
            self.assertEqual(fixture["ledger"].events(), drifted)
            self.assertEqual(list(case.fixture_root.glob("stage1-records-*")), [])
            case.runner.assert_not_called()

    def test_partial_publication_unknown_survives_actual_sqlite_reopen(self):
        with saved_stage1_case() as (case, fixture):
            service, request = (
                ProjectRecordsPrepareService(case.producer),
                body(case, fixture),
            )
            events = fixture["ledger"].events()
            with patch(
                "research_workspace_native.project_stage1_records.os.link",
                side_effect=OSError("synthetic exclusive publication failure"),
            ) as publish:
                with self.assertRaises(SessionApiError) as failed:
                    service.prepare("alice-token", fixture["ref"], request)
                publish.assert_called_once()
            receipt = failed.exception.receipt
            self.assertEqual(receipt["status"], "execution-unknown")
            self.assertEqual(receipt["failure_phase"], "post-work-before-commit")
            observation = receipt["output_observation"]
            partial, target = (
                Path(observation["partial_path"]),
                Path(observation["records_path"]),
            )
            saved_bytes = partial.read_bytes()
            self.assertEqual(sha(saved_bytes), observation["records_sha256"])
            self.assertFalse(target.exists())
            self.assertIn("publication failure", observation["write_error"])
            self.assertNotIn(
                "stage1_delivery_offers", case.intake._load("alice", fixture["ref"])
            )
            prior = actions(case, fixture)
            old_db = case.intake.db
            case.reopen()
            self.assertIsNot(case.intake.db, old_db)
            service = ProjectRecordsPrepareService(case.producer)
            with patch.object(
                case.producer,
                "produce_records",
                side_effect=AssertionError("unknown produced"),
            ) as produce:
                replay = service.prepare(
                    "alice-token", fixture["ref"], {**request, "revision": 999}
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["status"], "execution-unknown")
                self.assertEqual(replay["output_observation"], observation)
                with self.assertRaisesRegex(SessionApiError, "unresolved"):
                    service.prepare(
                        "alice-token", fixture["ref"], body(case, fixture, "new-key")
                    )
                produce.assert_not_called()
            self.assertEqual(actions(case, fixture), prior)
            self.assertEqual(partial.read_bytes(), saved_bytes)
            self.assertFalse(target.exists())
            self.assertEqual(fixture["ledger"].events(), events)
            case.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
