"""Passive Host overview joins actual Core, source bytes and SQLite registries."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_project_stage1_records as saved_fixtures
from test_project_saved_claims import request as claim_body
from test_project_source_reading_review import body as reading_body
from test_workspace_project_intake import bound_body, compile_body, submit_body
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_reading_review import ProjectReadingReviewService
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_saved_claims import ProjectSavedClaimService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
from stage1_coverage.run import CoverageLedger
from stage1_ledger.journal import canonical


@contextmanager
def case():
    fixture = saved_fixtures.SavedStage1RecordsTests(methodName="runTest")
    fixture.setUpClass()
    try:
        fixture.setUp()
        saved = fixture.two_sources()
        for records, directory in saved["pairs"]:
            source = records["sources"][0]
            path = directory / "source/source-fetch-result.json"
            fixture.producer.register_source(
                saved["ref"],
                source_id=source["source_id"],
                result_path=path,
                expected_result_sha256=sha(path.read_bytes()),
                access_note=source["access_note"],
                expected_ledger_state_sha256=saved["ledger"].state_hash(),
            )
        claims = ProjectSavedClaimService(fixture.stage1, fixture.producer)
        readings = ProjectReadingReviewService(saved_claims=claims)
        host = object.__new__(ProjectHost)  # No listener, socket or network.
        host.projects = fixture.intake
        host.project_stage1 = fixture.stage1
        host.project_stage1_delivery = fixture.delivery
        host.project_stage1_records = fixture.producer
        host.project_records_prepare = ProjectRecordsPrepareService(fixture.producer)
        host.project_models = host.project_stage2 = None
        host.project_expansions = host.project_stage1_sources = None
        yield fixture, saved, claims, readings, host
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()


def register(readings, saved):
    for index, (records, _) in enumerate(saved["pairs"]):
        work = records["papers"][0]["work_id"]
        readings.review_source(
            "alice-token",
            saved["ref"],
            reading_body(readings, saved["ref"], work, "notes-" + str(index)),
        )


def observation(fixture, saved):
    rows = fixture.intake.db.execute(
        "SELECT id,project,kind,payload FROM intake_events ORDER BY id"
    ).fetchall()
    actions = fixture.intake.history("alice-token", saved["ref"])
    state = fixture.intake.read("alice-token", saved["ref"])
    return (
        [tuple(row) for row in rows],
        actions,
        state,
        deepcopy(saved["ledger"].events()),
    )


class ReadingRegistrationTests(unittest.TestCase):
    def test_host_missing_producer_refusal_then_manual_registration_ready_without_get_writes(
        self,
    ):
        with case() as (fixture, saved, claims, readings, host):
            ref, ledger = saved["ref"], saved["ledger"]
            work = saved["records"]["papers"][0]["work_id"]
            claims.claim("alice-token", ref, claim_body(claims, ref, work))
            saved["checkpoint"] = ledger.checkpoint()
            before = observation(fixture, saved)
            overview = host.overview("alice-token", ref)
            view = overview["stage1"]["reading_registration"]
            self.assertEqual(
                (
                    view["status"],
                    view["required_work_count"],
                    view["registered_work_count"],
                ),
                ("missing", 2, 0),
            )
            self.assertEqual(
                {row["work_ref"] for row in view["missing_works"]},
                set(ledger.candidates()),
            )
            self.assertEqual(view["ledger_state_sha256"], ledger.state_hash())
            self.assertEqual(view["brief_sha256"], overview["project"]["brief_sha256"])
            self.assertEqual(
                overview["stage1"]["progress"]["next_action"]["reason"],
                "reading-registration-required",
            )
            self.assertEqual(observation(fixture, saved), before)
            with self.assertRaisesRegex(
                SessionApiError, "saved-reading-current-record-required"
            ):
                fixture.produce(saved)
            self.assertEqual(observation(fixture, saved), before)
            register(readings, saved)
            before = observation(fixture, saved)
            for _ in range(2):
                overview = host.overview("alice-token", ref)
                view = overview["stage1"]["reading_registration"]
                self.assertEqual(
                    (
                        view["status"],
                        view["required_work_count"],
                        view["registered_work_count"],
                        view["missing_works"],
                    ),
                    ("ready", 2, 2, []),
                )
                self.assertFalse(view["grants_execution"])
                self.assertEqual(
                    overview["stage1"]["progress"]["next_action"]["target"], "coverage"
                )
            self.assertEqual(observation(fixture, saved), before)
            self.assertEqual(
                fixture.produce(saved)["status"], "ready-for-saved-evidence-delivery"
            )
            fixture.runner.assert_not_called()

    def test_decision_change_requires_new_current_registration_and_stale_hash_is_held(
        self,
    ):
        with case() as (fixture, saved, _, readings, host):
            register(readings, saved)
            ledger, ref = saved["ledger"], saved["ref"]
            old_hash = ledger.state_hash()
            work = saved["records"]["papers"][0]["work_id"]
            source_ref = ledger.event(saved["records"]["claims"][0]["claim_id"])[
                "source_ref"
            ]
            event = ledger.decide(
                work,
                "pending",
                reason="authored-revision",
                rationale="Unknown: review again.",
                evidence_refs=[source_ref],
            )
            view = host.overview("alice-token", ref)["stage1"]["reading_registration"]
            self.assertEqual(view["status"], "missing")
            self.assertEqual([row["work_ref"] for row in view["missing_works"]], [work])
            self.assertEqual(view["missing_works"][0]["decision_event_id"], event)
            self.assertEqual(
                fixture.producer.reading_readiness(
                    "alice-token", ref, expected_ledger_state_sha256=old_hash
                )["status"],
                "held",
            )
            readings.review_source(
                "alice-token", ref, reading_body(readings, ref, work, "revised-reading")
            )
            self.assertEqual(
                host.overview("alice-token", ref)["stage1"]["reading_registration"][
                    "status"
                ],
                "ready",
            )

    def test_registry_action_and_source_tampering_return_held_without_writes(self):
        for tamper in ("action", "source", "registry"):
            with (
                self.subTest(tamper=tamper),
                case() as (fixture, saved, _, readings, host),
            ):
                register(readings, saved)
                ref = saved["ref"]
                if tamper == "action":
                    row = fixture.intake.db.execute(
                        "SELECT key FROM intake_actions WHERE project=? AND receipt LIKE '%stage1-reading-registry%' LIMIT 1",
                        (ref,),
                    ).fetchone()
                    fixture.intake.db.execute(
                        "UPDATE intake_actions SET request_hash=? WHERE project=? AND key=?",
                        ("0" * 64, ref, row[0]),
                    )
                    fixture.intake.db.commit()
                elif tamper == "source":
                    path = saved["pairs"][0][1] / "source/source-fetch-result.json"
                    path.write_bytes(path.read_bytes() + b" authored byte drift")
                else:
                    state = fixture.intake._load("alice", ref)
                    entry = next(
                        row
                        for row in state["stage1_saved_registries"].values()
                        if row["ref"].startswith("stage1-reading-registry-")
                    )
                    entry["payload"]["findings"]["main_findings"] = "Tampered prose"
                    fixture.intake.db.execute(
                        "UPDATE intake_projects SET state=? WHERE ref=?",
                        (json.dumps(state), ref),
                    )
                    fixture.intake.db.commit()
                before = observation(fixture, saved)
                view = host.overview("alice-token", ref)["stage1"][
                    "reading_registration"
                ]
                self.assertEqual(view["status"], "held")
                self.assertIsNone(view["registered_work_count"])
                self.assertEqual(observation(fixture, saved), before)

    def test_absent_records_or_owner_returns_unconnected_or_held_without_adoption(self):
        with case() as (fixture, saved, _, _, host):
            before = observation(fixture, saved)
            host.project_stage1_records = None
            self.assertEqual(
                host.overview("alice-token", saved["ref"])["stage1"][
                    "reading_registration"
                ]["status"],
                "unconnected",
            )
            host.project_stage1_records = fixture.producer

            @contextmanager
            def absent(*_):
                raise SessionApiError("project-query-records-owner-unavailable")
                yield  # pragma: no cover

            with patch.object(fixture.producer, "guard", absent):
                view = host.overview("alice-token", saved["ref"])["stage1"][
                    "reading_registration"
                ]
                self.assertEqual(view["status"], "held")
                self.assertEqual(
                    view["reason"], "project-query-records-owner-unavailable"
                )
            self.assertEqual(observation(fixture, saved), before)

    def test_metadata_only_candidates_need_no_invented_reading_registration(self):
        with case() as (fixture, _, _, _, host):
            ref = fixture.intake.create(
                "alice-token", dict(key="metadata", topic="Authored metadata topic")
            )["project_ref"]
            fixture.intake.submit(
                "alice-token", ref, submit_body(fixture.intake.read("alice-token", ref))
            )
            fixture.intake.compile(
                "alice-token",
                ref,
                compile_body(fixture.intake.read("alice-token", ref)),
            )
            offer = fixture.stage1.read("alice-token", ref)["initialization_offer"]
            fixture.stage1.initialize(
                "alice-token",
                ref,
                dict(
                    bound_body(
                        fixture.intake.read("alice-token", ref), "metadata-init"
                    ),
                    offer_ref=offer["offer_ref"],
                    offer_sha256=offer["offer_sha256"],
                    confirmed=True,
                ),
            )
            state = fixture.intake._load("alice", ref)
            run = state["stage1_runs"][state["stage1_active"]]
            ledger = CoverageLedger(fixture.intake._path(ref, run["path"]))
            view = host.overview("alice-token", ref)["stage1"]
            self.assertEqual(
                (
                    view["reading_registration"]["status"],
                    view["reading_registration"]["required_work_count"],
                ),
                ("ready", 0),
            )
            self.assertEqual(view["progress"]["next_action"]["target"], "query")
            plan = ledger.coverage_state()
            planned = next(iter(plan.queries))
            query = ledger.start_planned(planned)
            attempt = ledger.start(
                "backend",
                {"input": plan.arguments(planned)},
                backend="openalex",
                parent_id=query,
            )
            records = ledger.save_bytes(
                canonical(
                    [
                        dict(
                            title="Authored unread candidate",
                            authors=["Fixture"],
                            year=2025,
                            version="v1",
                        )
                    ]
                ),
                producer=attempt,
            )
            empty = ledger.save_bytes(b"", producer=attempt)
            ledger.finish(
                attempt,
                outcome="success_nonempty",
                http_status=200,
                exit_code=0,
                stdout=empty,
                stderr=empty,
                records=records,
            )
            ledger.complete_query(query)
            ledger.extract()
            before = fixture.intake.history("alice-token", ref), ledger.events()
            view = host.overview("alice-token", ref)["stage1"]
            self.assertEqual(
                (
                    view["reading_registration"]["status"],
                    view["reading_registration"]["required_work_count"],
                    view["reading_registration"]["missing_works"],
                ),
                ("ready", 0, []),
            )
            self.assertEqual(view["progress"]["next_action"]["target"], "screening")
            self.assertEqual(
                (fixture.intake.history("alice-token", ref), ledger.events()), before
            )

    def test_uncertain_reading_save_remains_held_in_passive_overview(self):
        with case() as (fixture, saved, _, readings, host):
            work = saved["records"]["papers"][0]["work_id"]
            request = reading_body(readings, saved["ref"], work, "unknown-notes")
            save = fixture.intake._save

            def crash(state, kind, value):
                if kind == "stage1-reading-registry-saved":
                    raise OSError("authored post-work failure")
                return save(state, kind, value)

            with patch.object(fixture.intake, "_save", side_effect=crash):
                with self.assertRaises(SessionApiError):
                    readings.review_source("alice-token", saved["ref"], request)
            before = observation(fixture, saved)
            view = host.overview("alice-token", saved["ref"])["stage1"]
            self.assertEqual(
                (
                    view["reading_registration"]["status"],
                    view["reading_registration"]["reason"],
                ),
                ("held", "reading-registration-unresolved"),
            )
            self.assertEqual(view["progress"]["next_action"]["target"], "history")
            self.assertEqual(observation(fixture, saved), before)


if __name__ == "__main__":
    unittest.main()
