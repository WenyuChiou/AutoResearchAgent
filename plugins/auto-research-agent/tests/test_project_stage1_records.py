"""Real Core and SDK parser fixtures, with authored HTTP and no external I/O."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_stage1_deliverable as package_fixture
import test_project_stage1_delivery as delivery_fixture
from research_workspace_native.project_stage1_records import ProjectStage1RecordsService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import read_json, sha
from stage1_ledger.journal import canonical


class SavedStage1RecordsTests(unittest.TestCase):
    setUpClass = classmethod(
        delivery_fixture.ProjectStage1DeliveryTests.setUpClass.__func__
    )
    saved = delivery_fixture.ProjectStage1DeliveryTests.saved
    body = delivery_fixture.ProjectStage1DeliveryTests.body

    def reopen(self):
        delivery_fixture.ProjectStage1DeliveryTests.reopen(self)
        self.producer = ProjectStage1RecordsService(
            self.delivery,
            materials_root=self.fixture_root,
            mutation_guard=lambda *args: nullcontext(),
        )

    def setUp(self):
        delivery_fixture.ProjectStage1DeliveryTests.setUp(self)

    def two_sources(self):
        fixture = self.saved()
        ledger = fixture["ledger"]
        coverage = ledger.coverage_state()
        query = ledger.start_planned(list(coverage.queries)[1])
        backend = ledger.start(
            "backend",
            {"input": coverage.arguments(list(coverage.queries)[1])},
            backend="openalex",
            parent_id=query,
        )
        output = ledger.save_bytes(
            canonical(
                [
                    dict(
                        title="Second authored saved study",
                        authors=["Synthetic Author"],
                        year=2025,
                        version="v1",
                    )
                ]
            ),
            producer=backend,
        )
        empty = ledger.save_bytes(b"", producer=backend)
        ledger.finish(
            backend,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=empty,
            stderr=empty,
            records=output,
        )
        ledger.complete_query(query)
        ledger.extract()
        work = next(
            work
            for work in ledger.candidates()
            if work != fixture["records"]["papers"][0]["work_id"]
        )
        version = ledger.candidates()[work]["version_ids"][0]
        ledger.decide(
            work,
            "pending",
            reason="fixture-unassessed",
            rationale="Unknown: authored fixture not assessed.",
            evidence_refs=[output],
        )
        source = ledger.start_source(
            work_id=work,
            version_id=version,
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored HTTP fixture; no acquisition.",
        )
        self.inputs = self.fixture_root / "second"
        self.inputs.mkdir()
        second = package_fixture.ResearchDeliverableTests.make_records(
            self,
            raw=package_fixture.HTML.replace(
                package_fixture.TITLE.encode(), b"Second authored saved study"
            ),
            title="Second authored saved study",
        )
        receipt_path = self.inputs / "source/source-fetch-result.json"
        receipt = read_json(receipt_path)
        raw = ledger.save_bytes(Path(receipt["raw_path"]).read_bytes(), producer=source)
        text = ledger.save_bytes(
            Path(receipt["extracted_text_path"]).read_bytes(), producer=source
        )
        ledger.finish_source(
            attempt_id=source,
            outcome="available",
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=200,
            resolved_uri=receipt["final_url"],
            raw_ref=raw,
            text_ref=text,
            extraction={"method": "research_hub", "version": "fixture"},
            reason="Actual SDK parser on authored bytes.",
        )
        claim = second["claims"][0]
        claim_id = ledger.claim(
            work_id=work,
            version_id=version,
            claim_text=claim["quote"],
            relation="partial",
            evidence_level=claim["evidence_level"],
            locator={"section": claim["locator"], "quote": claim["quote"]},
            source_ref=text,
            verifier={
                "actor": "fixture",
                "actor_type": "agent",
                "method": "exact-span",
            },
        )
        claim.update(
            claim_id=claim_id, source_id=source, work_id=work, version_id=version
        )
        second["papers"][0].update(
            work_id=work, version_id=version, source_ids=[source], claim_ids=[claim_id]
        )
        second["sources"][0].update(
            source_id=source,
            work_id=work,
            version_id=version,
            result_path="second/source/source-fetch-result.json",
        )
        for paper in (fixture["records"]["papers"][0], second["papers"][0]):
            ledger.decide(
                paper["work_id"],
                "include",
                reason="fixture-include",
                rationale="Fixture candidate retained; no scientific acceptance.",
                evidence_refs=[output],
            )
            ledger.review_work(
                work_id=paper["work_id"],
                version_id=paper["version_id"],
                cluster_claims={
                    coverage.plan["proposal"]["clusters"][0]["cluster_id"]: paper[
                        "claim_ids"
                    ][0]
                },
                identity_status="unverifiable",
                identity_claims={
                    key: None
                    for key in ("title", "authors", "year", "identifier", "version")
                },
                closest=False,
                assessor="fixture",
                rationale="Authored partial operational review.",
            )
        fixture["checkpoint"] = ledger.checkpoint()
        fixture["pairs"] = [
            (fixture["records"], fixture["path"].parent),
            (second, self.inputs),
        ]
        return fixture

    def register_all(self, fixture):
        ledger = fixture["ledger"]
        for records, directory in fixture["pairs"]:
            source = records["sources"][0]
            path = directory / "source/source-fetch-result.json"
            self.producer.register_source(
                fixture["ref"],
                source_id=source["source_id"],
                result_path=path,
                expected_result_sha256=sha(path.read_bytes()),
                access_note=source["access_note"],
                expected_ledger_state_sha256=ledger.state_hash(),
            )
        for records, _ in fixture["pairs"]:
            paper = records["papers"][0]
            events = ledger.coverage_state().evidence
            reading = dict(
                work_id=paper["work_id"],
                version_id=paper["version_id"],
                candidate_event_id=ledger.candidates()[paper["work_id"]]["event_id"],
                decision_event_id=events.decisions[paper["work_id"]]["event_id"],
                review_event_id=events.current()[paper["work_id"]]["event_id"],
                source_ids=paper["source_ids"],
                classification=paper["classification"],
                findings=paper["findings"],
                roles=[],
                claims=[
                    dict(
                        claim_id=claim["claim_id"],
                        source_id=claim["source_id"],
                        text_sha256=sha(
                            ledger.read_ref(
                                ledger.event(claim["claim_id"])["source_ref"]
                            )
                        ),
                        start=claim["start"],
                        end=claim["end"],
                        quote=claim["quote"],
                    )
                    for claim in records["claims"]
                ],
            )
            self.producer.register_reading(
                fixture["ref"],
                reading=reading,
                expected_ledger_state_sha256=ledger.state_hash(),
            )
        return reading

    def produce(self, fixture):
        return self.producer.produce_records(
            fixture["ref"],
            expected_ledger_state_sha256=fixture["ledger"].state_hash(),
            expected_checkpoint_event_id=fixture["checkpoint"]["event_id"],
        )

    def test_two_sources_reading_records_delivery_and_true_sqlite_reopen(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        offer = self.produce(fixture)
        self.assertFalse(offer["eligible_for_stage2"])
        delivered = self.delivery.deliver(
            "alice-token", fixture["ref"], self.body(fixture, offer)
        )
        self.assertEqual(delivered["status"], "saved")
        context = self.delivery._context(fixture["ref"])
        saved = context[1]["stage1_delivery_offers"][offer["offer_ref"]]
        records = read_json(saved["records_path"])
        self.assertEqual(
            (
                len(records["papers"]),
                len(records["sources"]),
                len(records["claims"]),
                len(records["screening"]),
            ),
            (2, 2, 2, 4),
        )
        self.assertEqual(records["claims"][1]["relation"], "partial")
        self.assertIn("Unknown", records["papers"][0]["findings"]["main_findings"])
        self.assertTrue(
            all(row["stop_decision"] == "continue" for row in records["coverage"])
        )
        path = Path(saved["records_path"])
        before = path.read_bytes()
        self.reopen()
        with patch("research_workspace_native.project_stage1_records.os.link") as write:
            again = self.produce(fixture)
            self.assertEqual(offer, again)
            write.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.runner.assert_not_called()

    def test_exact_span_rejects_repeated_quote_wrong_offset_and_missing_claim(self):
        fixture = self.two_sources()
        reading = self.register_all(fixture)
        for mutate in (
            lambda row: row["claims"][0].update(start=1),
            lambda row: row["claims"][0].update(text_sha256="0" * 64),
            lambda row: row.update(claims=[]),
            lambda row: row.update(decision_event_id="foreign"),
        ):
            bad = deepcopy(reading)
            mutate(bad)
            with self.assertRaises(SessionApiError):
                self.producer.register_reading(
                    fixture["ref"],
                    reading=bad,
                    expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                )

    def test_tampered_source_and_old_checkpoint_refuse_without_records(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        with self.assertRaises(SessionApiError):
            self.producer.produce_records(
                fixture["ref"],
                expected_ledger_state_sha256=fixture["ledger"].state_hash(),
                expected_checkpoint_event_id="old",
            )
        path = fixture["path"].parent / "source/source-fetch-result.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(SessionApiError):
            self.produce(fixture)
        self.assertEqual(list(self.fixture_root.glob("stage1-records-*.json")), [])

    def test_atomic_post_file_commit_failure_preserves_unknown_and_never_rewrites(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        save = self.intake._save

        def fail(state, kind, payload):
            if kind == "stage1-produce-records-saved":
                raise OSError("authored SQLite commit failure")
            return save(state, kind, payload)

        with patch.object(self.intake, "_save", side_effect=fail):
            with self.assertRaises(SessionApiError):
                self.produce(fixture)
        path = next(self.fixture_root.glob("stage1-records-*.json"))
        raw = path.read_bytes()
        self.reopen()
        with patch("research_workspace_native.project_stage1_records.os.link") as write:
            with self.assertRaises(SessionApiError):
                self.produce(fixture)
            write.assert_not_called()
        self.assertEqual(path.read_bytes(), raw)
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])
        self.assertNotIn("stage1_delivery_offers", state)

    def test_guard_refusal_precedes_registry_or_file_mutation(self):
        fixture = self.two_sources()
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])

        @contextmanager
        def refuse(*args):
            raise OSError("saved frontier is owned by another worker")
            yield

        self.producer.guard = refuse
        with self.assertRaises(OSError):
            self.register_all(fixture)
        self.assertEqual(
            state,
            self.intake._load(self.intake._principal("alice-token"), fixture["ref"]),
        )
        self.assertEqual(list(self.fixture_root.glob("stage1-records-*")), [])

    def first_source(self, fixture):
        records, directory = fixture["pairs"][0]
        source = records["sources"][0]
        path = directory / "source/source-fetch-result.json"
        return self.producer.register_source(
            fixture["ref"],
            source_id=source["source_id"],
            result_path=path,
            expected_result_sha256=sha(path.read_bytes()),
            access_note=source["access_note"],
            expected_ledger_state_sha256=fixture["ledger"].state_hash(),
        )

    def test_yielded_guard_check_refuses_before_admission(self):
        fixture = self.two_sources()
        principal = self.intake._principal("alice-token")
        before = self.intake._load(principal, fixture["ref"])
        action_count = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions WHERE project=?", (fixture["ref"],)
        ).fetchone()[0]

        def check():
            raise OSError("authored owner already closing")

        for value in (check, object()):
            with self.subTest(check=value):
                self.producer.guard = lambda *args: nullcontext(value)
                with self.assertRaises((OSError, SessionApiError)):
                    self.first_source(fixture)
                self.assertEqual(before, self.intake._load(principal, fixture["ref"]))
                self.assertEqual(
                    self.intake.db.execute(
                        "SELECT COUNT(*) FROM intake_actions WHERE project=?",
                        (fixture["ref"],),
                    ).fetchone()[0],
                    action_count,
                )

    def refuse_precommit(self, fixture, kind, operation, *, after_sql=False):
        principal = self.intake._principal("alice-token")
        before = self.intake._load(principal, fixture["ref"])
        saved_before = self.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events WHERE project=? AND kind=?",
            (fixture["ref"], kind + "-saved"),
        ).fetchone()[0]
        active = [True]
        calls = []

        def check():
            calls.append(active[0])
            if not active[0]:
                raise OSError("authored owner lost after local work")

        @contextmanager
        def guard(run, ledger, report):
            self.assertEqual(run["run_ref"], before["stage1_active"])
            self.assertEqual(ledger.root, fixture["ledger"].root)
            self.assertEqual(report["state_sha256"], fixture["ledger"].state_hash())
            yield check
            # Exit-only checks reproduce the original unsafe saved transaction.
            check()

        perform = self.intake._perform

        def inject(principal, project, operation_kind, body, work, **kwargs):
            def after_work(*args):
                result = work(*args)
                if operation_kind == kind and not after_sql:
                    active[0] = False
                return result

            return perform(
                principal, project, operation_kind, body, after_work, **kwargs
            )

        save = self.intake._save

        def invalidate_after_sql(state, event_kind, payload):
            result = save(state, event_kind, payload)
            if after_sql and event_kind == kind + "-saved":
                active[0] = False
            return result

        self.producer.guard = guard
        with (
            patch.object(self.intake, "_perform", side_effect=inject),
            patch.object(self.intake, "_save", side_effect=invalidate_after_sql),
        ):
            with self.assertRaises((OSError, SessionApiError)):
                operation()
        row = self.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=? ORDER BY rowid DESC LIMIT 1",
            (fixture["ref"],),
        ).fetchone()
        receipt = json.loads(row["receipt"])
        self.assertEqual(receipt["kind"], kind)
        self.assertEqual(receipt["status"], "execution-unknown")
        self.assertEqual(receipt["failure_phase"], "post-work-before-commit")
        current = self.intake._load(principal, fixture["ref"])
        for field in ("stage1_saved_registries", "stage1_delivery_offers"):
            self.assertEqual(current.get(field), before.get(field))
        self.assertEqual(
            self.intake.db.execute(
                "SELECT COUNT(*) FROM intake_events WHERE project=? AND kind=?",
                (fixture["ref"], kind + "-saved"),
            ).fetchone()[0],
            saved_before,
        )
        self.assertIn(False, calls)
        self.runner.assert_not_called()
        return receipt

    def test_source_owner_loss_before_commit_rolls_back_registry(self):
        fixture = self.two_sources()
        self.refuse_precommit(
            fixture, "stage1-source-registry", lambda: self.first_source(fixture)
        )
        self.assertEqual(list(self.fixture_root.glob("stage1-records-*")), [])

    def test_reading_owner_loss_before_commit_rolls_back_registry(self):
        fixture = self.two_sources()
        reading = deepcopy(self.register_all(fixture))
        reading["findings"]["main_findings"] = "Authored annotation revision"
        self.refuse_precommit(
            fixture,
            "stage1-reading-registry",
            lambda: self.producer.register_reading(
                fixture["ref"],
                reading=reading,
                expected_ledger_state_sha256=fixture["ledger"].state_hash(),
            ),
        )

    def test_source_owner_loss_after_saved_sql_rolls_back_registry(self):
        fixture = self.two_sources()
        self.refuse_precommit(
            fixture,
            "stage1-source-registry",
            lambda: self.first_source(fixture),
            after_sql=True,
        )

    def test_records_owner_loss_after_publication_preserves_unknown(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        receipt = self.refuse_precommit(
            fixture, "stage1-produce-records", lambda: self.produce(fixture)
        )
        path = Path(receipt["output_observation"]["records_path"])
        raw = path.read_bytes()
        self.reopen()
        with patch("research_workspace_native.project_stage1_records.os.link") as write:
            with self.assertRaises(SessionApiError):
                self.produce(fixture)
            write.assert_not_called()
        self.assertEqual(path.read_bytes(), raw)

    def test_offer_owner_loss_before_commit_rolls_back_offer_and_reopen_never_adopts(
        self,
    ):
        fixture = self.two_sources()
        self.register_all(fixture)
        self.refuse_precommit(
            fixture,
            "stage1-register-delivery",
            lambda: self.produce(fixture),
            after_sql=True,
        )
        path = next(self.fixture_root.glob("stage1-records-*.json"))
        raw = path.read_bytes()
        self.reopen()
        with patch("research_workspace_native.project_stage1_records.os.link") as write:
            with self.assertRaises(SessionApiError):
                self.produce(fixture)
            write.assert_not_called()
        self.assertEqual(path.read_bytes(), raw)

    def test_post_publish_binding_failure_records_output_as_unknown(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        context = self.producer._context

        def fail_after_file(*args):
            if list(self.fixture_root.glob("stage1-records-*.json")):
                raise OSError("authored state drift after exclusive file publication")
            return context(*args)

        with patch.object(self.producer, "_context", side_effect=fail_after_file):
            with self.assertRaises(SessionApiError) as error:
                self.produce(fixture)
        self.assertEqual(error.exception.receipt["status"], "execution-unknown")
        observation = error.exception.receipt["output_observation"]
        path = Path(observation["records_path"])
        self.assertEqual(sha(path.read_bytes()), observation["records_sha256"])
        self.reopen()
        with patch("research_workspace_native.project_stage1_records.os.link") as write:
            with self.assertRaises(SessionApiError):
                self.produce(fixture)
            write.assert_not_called()

    def test_rehashed_mutable_registry_cannot_replace_original_saved_annotation(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])
        entry = next(
            row
            for row in state["stage1_saved_registries"].values()
            if row["ref"].startswith("stage1-reading-registry-")
        )
        old = entry["ref"]
        entry["payload"]["findings"]["main_findings"] = "Tampered assertion"
        entry["sha256"] = sha(
            canonical({key: entry[key] for key in ("basis", "payload")})
        )
        entry["ref"] = "stage1-reading-registry-" + entry["sha256"]
        del state["stage1_saved_registries"][old]
        state["stage1_saved_registries"][entry["ref"]] = entry
        with self.intake.db:
            self.intake._save(state, "authored-registry-tamper", {})
        self.reopen()
        with self.assertRaises(SessionApiError) as error:
            self.produce(fixture)
        self.assertEqual(error.exception.code, "stage1-saved-registry-receipt-differs")
        self.assertEqual(list(self.fixture_root.glob("stage1-records-*")), [])

    def test_same_ref_extra_event_cannot_bypass_original_action(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        row = self.intake.db.execute(
            "SELECT id,payload FROM intake_events WHERE project=? AND kind='stage1-reading-registry-saved' ORDER BY id LIMIT 1",
            (fixture["ref"],),
        ).fetchone()
        original = canonical(json.loads(row["payload"]))
        event = json.loads(original)
        event["registry_entry"]["payload"]["findings"]["main_findings"] = (
            "Forged extra saved event"
        )
        with self.intake.db:
            self.intake.db.execute(
                "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
                (
                    fixture["ref"],
                    "stage1-reading-registry-saved",
                    canonical(event).decode(),
                ),
            )
        with self.assertRaises(SessionApiError):
            self.produce(fixture)

    def test_consistently_rehashed_state_and_appended_event_need_actual_action(self):
        fixture = self.two_sources()
        self.register_all(fixture)
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])
        row = self.intake.db.execute(
            "SELECT payload FROM intake_events WHERE project=? AND kind='stage1-reading-registry-saved' ORDER BY id LIMIT 1",
            (fixture["ref"],),
        ).fetchone()
        event = json.loads(row["payload"])
        entry = event["registry_entry"]
        entry["payload"]["findings"]["main_findings"] = (
            "Consistently self-rehashed forged revision"
        )
        entry["sha256"] = sha(
            canonical({key: entry[key] for key in ("basis", "payload")})
        )
        entry["ref"] = "stage1-reading-registry-" + entry["sha256"]
        event["key"] = event["request"]["key"] = entry["ref"]
        event["request"]["entry_sha256"] = entry["sha256"]
        event["request_sha256"] = sha(
            canonical({"kind": event["kind"], "body": event["request"]})
        )
        state["stage1_saved_registries"][entry["ref"]] = entry
        with self.intake.db:
            self.intake.db.execute(
                "INSERT INTO intake_events(project,kind,payload) VALUES(?,?,?)",
                (
                    fixture["ref"],
                    "stage1-reading-registry-saved",
                    canonical(event).decode(),
                ),
            )
            self.intake._save(state, "authored-event-and-state-tamper", {})
        self.reopen()
        with self.assertRaises(SessionApiError) as error:
            self.produce(fixture)
        self.assertEqual(error.exception.code, "stage1-saved-registry-action-differs")

    def test_failed_source_and_revised_screening_keep_original_attempts_and_reviews(
        self,
    ):
        fixture = self.two_sources()
        self.register_all(fixture)
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        work, version = paper["work_id"], paper["version_id"]
        source = ledger.start_source(
            work_id=work,
            version_id=version,
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored HTTP 503, no external request.",
        )
        self.inputs = self.fixture_root / "failed"
        self.inputs.mkdir()
        failed = package_fixture.ResearchDeliverableTests.make_records(
            self, b"authored service unavailable", "text/plain", 503
        )
        path = self.inputs / "source/source-fetch-result.json"
        receipt = read_json(path)
        raw = ledger.save_bytes(
            Path(receipt["attempts"][-1]["raw_path"]).read_bytes(), producer=source
        )
        ledger.finish_source(
            attempt_id=source,
            outcome="http_error",
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=503,
            resolved_uri=receipt["final_url"],
            raw_ref=raw,
            text_ref=None,
            extraction=None,
            reason="Original authored SDK service-failure observation.",
        )
        prior_review = ledger.coverage_state().evidence.current()[work]["event_id"]
        decision = ledger.decide(
            work,
            "exclude",
            reason="fixture-exclude",
            rationale="Excluded after source failure; old observations retained.",
            evidence_refs=[raw],
        )
        fixture["checkpoint"] = ledger.checkpoint()
        self.producer.register_source(
            fixture["ref"],
            source_id=source,
            result_path=path,
            expected_result_sha256=sha(path.read_bytes()),
            access_note=failed["sources"][0]["access_note"],
            expected_ledger_state_sha256=ledger.state_hash(),
        )
        context = self.delivery._context(fixture["ref"])
        reading = deepcopy(
            next(
                row["payload"]
                for row in self.producer._entries(context)
                if row["ref"].startswith("stage1-reading-registry-")
                and row["payload"]["work_id"] == work
            )
        )
        reading.update(
            decision_event_id=decision,
            review_event_id=None,
            source_ids=reading["source_ids"] + [source],
        )
        self.producer.register_reading(
            fixture["ref"],
            reading=reading,
            expected_ledger_state_sha256=ledger.state_hash(),
        )
        offer = self.produce(fixture)
        saved = self.delivery._context(fixture["ref"])[1]["stage1_delivery_offers"][
            offer["offer_ref"]
        ]
        records = read_json(saved["records_path"])
        self.assertEqual((len(records["sources"]), len(records["screening"])), (3, 5))
        self.assertEqual(records["screening"][-1]["status"], "exclude")
        self.assertEqual(
            read_json(
                self.fixture_root
                / next(
                    row["result_path"]
                    for row in records["sources"]
                    if row["source_id"] == source
                )
            )["attempts"][-1]["http_status"],
            503,
        )
        self.assertTrue(
            any(row["payload"]["event_id"] == prior_review for row in ledger.events())
        )
        self.assertNotIn(work, ledger.coverage_state().evidence.current())


@contextmanager
def saved_stage1_case():
    """Reusable mock-HTTP case with real persisted Core, no live authority."""
    case = SavedStage1RecordsTests()
    case.setUpClass()
    try:
        case.setUp()
        fixture = case.two_sources()
        case.register_all(fixture)
        yield case, fixture
    finally:
        case.doCleanups()
        case.tearDownClass()


if __name__ == "__main__":
    unittest.main()
