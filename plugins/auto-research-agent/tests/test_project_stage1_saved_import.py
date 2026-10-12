"""Real SDK local import and Core; authored HTML, no new acquisition/model."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import atlas_test_paths  # noqa: F401
from research_hub.source_fetch_saved import import_saved_public_source

import test_project_stage1_records as records_fixture
import test_stage1_deliverable as package_fixture
from research_workspace_native.project_stage1_saved_import import (
    complete_saved_sdk_import,
    prepare_saved_sdk_import,
    source_observation_time_matches,
)
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import read_json, sha, write_json
from stage1_ledger.validation import validate_run


class SavedSdkImportTests(unittest.TestCase):
    setUpClass = classmethod(
        records_fixture.SavedStage1RecordsTests.setUpClass.__func__
    )
    setUp = records_fixture.SavedStage1RecordsTests.setUp
    reopen = records_fixture.SavedStage1RecordsTests.reopen
    saved = records_fixture.SavedStage1RecordsTests.saved
    body = records_fixture.SavedStage1RecordsTests.body

    def local_import(self):
        fixture = self.saved()
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        directory = self.fixture_root / "local-import"
        directory.mkdir()
        raw = directory / "authored.html"
        raw.write_bytes(package_fixture.HTML)
        manifest = dict(
            schema_version="saved-public-source-input/v1",
            url="https://example.org/study",
            final_url="https://example.org/study",
            doi="",
            title=package_fixture.TITLE,
            raw_path=raw.name,
            raw_sha256=sha(raw.read_bytes()),
            content_type="text/html",
            original_acquired_at=(
                datetime.now(timezone.utc) - timedelta(seconds=2)
            ).isoformat(),
        )
        manifest_path = directory / "input.json"
        write_json(manifest_path, manifest)
        import_saved_public_source(
            input_manifest=manifest_path,
            expected_manifest_sha256=sha(manifest_path.read_bytes()),
            output_dir=directory / "sdk",
        )
        path = directory / "sdk/source-fetch-result.json"
        before = path.read_bytes()
        receipt = read_json(path)
        self.assertEqual(receipt["request"]["operation"], "source import-saved")
        self.assertEqual(receipt["request"]["doi"], "")
        principal = self.intake._principal("alice-token")

        def current():
            self.assertEqual(
                self.intake._load(principal, fixture["ref"])["project_ref"],
                fixture["ref"],
            )
            self.assertIn(
                paper["version_id"],
                ledger.candidates()[paper["work_id"]]["version_ids"],
            )

        arguments = dict(
            materials_root=self.fixture_root,
            result_path=path,
            expected_result_sha256=sha(before),
            runtime_sha256="1" * 64,
            check_current=current,
        )
        proposed = prepare_saved_sdk_import(**arguments)
        source = ledger.start_source(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            source_uri=proposed["source_uri"],
            tool=proposed["tool"],
            request=proposed["request"],
            actor="fixture",
            reason="New local observation of original saved SDK bytes.",
        )
        arguments.update(
            source_id=source,
            expected_start=ledger.event(source, "SourceReadStarted"),
            reason="Saved local input; no HTTP execution attestation.",
        )
        return fixture, arguments, receipt, before

    def complete(self, fixture, arguments):
        return complete_saved_sdk_import(fixture["ledger"], **arguments)

    def refuse(self, fixture, arguments):
        before = fixture["ledger"].events()
        with self.assertRaises((ValueError, OSError, SessionApiError)):
            self.complete(fixture, arguments)
        self.assertEqual(fixture["ledger"].events(), before)
        self.runner.assert_not_called()

    def test_sdk_original_times_to_core_registry_reading_and_canonical_delivery(self):
        fixture, arguments, receipt, original = self.local_import()
        ledger = fixture["ledger"]
        result = self.complete(fixture, arguments)
        self.assertEqual(arguments["result_path"].read_bytes(), original)
        self.assertEqual(result["sdk_retrieved_at"], receipt["retrieved_at"])
        self.assertNotEqual(result["local_observed_at"], receipt["retrieved_at"])
        self.assertIsNone(result["finish"]["http_status"])
        self.assertFalse(result["original_http_acquisition_verified"])
        self.assertTrue(validate_run(ledger.root)["valid"])
        # The source observation alone never creates a current evidence review.
        paper = fixture["records"]["papers"][0]
        records_fixture.delivery_fixture.ProjectStage1DeliveryTests.append_screening(
            self, fixture, "include"
        )
        ledger.review_work(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            cluster_claims={
                fixture["records"]["coverage"][0]["need_id"]: paper["claim_ids"][0]
            },
            identity_status="unverifiable",
            identity_claims={
                name: None
                for name in ("title", "authors", "year", "identifier", "version")
            },
            closest=False,
            assessor="fixture",
            rationale="Authored saved-source review; identity remains unverified.",
        )
        fixture["checkpoint"] = ledger.checkpoint()
        first = fixture["records"]["sources"][0]
        old_path = fixture["path"].parent / first["result_path"]
        for source, path in (
            (first, old_path),
            (result["source_description"], arguments["result_path"]),
        ):
            self.producer.register_source(
                fixture["ref"],
                source_id=source["source_id"],
                result_path=path,
                expected_result_sha256=sha(path.read_bytes()),
                access_note=source["access_note"],
                expected_ledger_state_sha256=ledger.state_hash(),
            )
        paper = fixture["records"]["papers"][0]
        evidence = ledger.coverage_state().evidence
        reading = dict(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            candidate_event_id=ledger.candidates()[paper["work_id"]]["event_id"],
            decision_event_id=evidence.decisions[paper["work_id"]]["event_id"],
            review_event_id=evidence.current()[paper["work_id"]]["event_id"],
            source_ids=[first["source_id"], result["source_id"]],
            classification=paper["classification"],
            findings=paper["findings"],
            roles=[],
            claims=[
                dict(
                    claim_id=c["claim_id"],
                    source_id=c["source_id"],
                    text_sha256=sha(
                        ledger.read_ref(ledger.event(c["claim_id"])["source_ref"])
                    ),
                    start=c["start"],
                    end=c["end"],
                    quote=c["quote"],
                )
                for c in fixture["records"]["claims"]
            ],
        )
        self.producer.register_reading(
            fixture["ref"],
            reading=reading,
            expected_ledger_state_sha256=ledger.state_hash(),
        )
        offer = self.producer.produce_records(
            fixture["ref"],
            expected_ledger_state_sha256=ledger.state_hash(),
            expected_checkpoint_event_id=fixture["checkpoint"]["event_id"],
        )
        delivered = self.delivery.deliver(
            "alice-token", fixture["ref"], self.body(fixture, offer)
        )
        self.assertEqual(delivered["status"], "saved")
        context = self.delivery._context(fixture["ref"])
        stored = context[1]["stage1_delivery_offers"][offer["offer_ref"]]
        records = read_json(stored["records_path"])
        self.assertEqual(len(records["sources"]), 2)
        self.assertEqual(
            {c["claim_id"] for c in records["claims"]},
            {c["claim_id"] for c in fixture["records"]["claims"]},
        )
        self.assertEqual(
            [(c["relation"], c["quote"], c["source_id"]) for c in records["claims"]],
            [
                (c["relation"], c["quote"], c["source_id"])
                for c in fixture["records"]["claims"]
            ],
        )
        self.assertIn("Unknown", records["papers"][0]["findings"]["main_findings"])
        self.assertFalse(offer["eligible_for_stage2"])
        self.assertEqual(arguments["result_path"].read_bytes(), original)
        self.runner.assert_not_called()

    def test_reopened_ledger_refuses_repeat_without_new_core_events(self):
        fixture, arguments, _, _ = self.local_import()
        self.complete(fixture, arguments)
        fixture["ledger"] = CoverageLedger(fixture["ledger"].root)
        self.refuse(fixture, arguments)

    def test_owner_refusal_precedes_core_artifact_or_finish(self):
        fixture, arguments, _, _ = self.local_import()

        def denied():
            raise SessionApiError("owner-lost", 409)

        arguments["check_current"] = denied
        self.refuse(fixture, arguments)

    def test_wrong_receipt_hash_or_captured_start_refuses_before_write(self):
        fixture, arguments, _, _ = self.local_import()
        bad = deepcopy(arguments)
        bad["expected_result_sha256"] = "0" * 64
        self.refuse(fixture, bad)
        bad = deepcopy(arguments)
        bad["expected_start"]["request"]["kind"] = "caller-receipt"
        self.refuse(fixture, bad)

    def test_rehashed_import_cannot_invent_http_observation(self):
        fixture, arguments, receipt, _ = self.local_import()
        from stage1_deliverable.sources import receipt_digest

        variants = []
        bad = deepcopy(receipt)
        bad["attempts"][-1]["http_status"] = 200
        variants.append(("invented-http", bad))
        bad = deepcopy(receipt)
        bad["attempts"][0]["sequence"] = 2
        variants.append(("wrong-sequence", bad))
        bad = deepcopy(receipt)
        bad["attempts"][0]["requested_at"] = bad["retrieved_at"]
        variants.append(("attempt-time-differs", bad))
        bad = deepcopy(receipt)
        bad["diagnostics"]["saved_import"]["imported_at"] = bad["diagnostics"][
            "saved_import"
        ]["import_started_at"]
        variants.append(("import-time-differs", bad))
        bad = deepcopy(receipt)
        bad["attempts"][0]["content_type"] = "text/html"
        variants.append(("provenance-content-type", bad))
        bad = deepcopy(receipt)
        bad["raw_path"] = bad["attempts"][0]["raw_path"]
        bad["raw_sha256"] = bad["attempts"][0]["raw_sha256"]
        variants.append(("selected-provenance-as-source", bad))
        for name, bad in variants:
            with self.subTest(name=name):
                bad["receipt_sha256"] = receipt_digest(bad)
                write_json(arguments["result_path"], bad)
                arguments["expected_result_sha256"] = sha(
                    arguments["result_path"].read_bytes()
                )
                self.refuse(fixture, arguments)

    def test_legacy_fetch_still_requires_original_sdk_observed_time_equality(self):
        start = {"tool": "research_hub.source_fetch"}
        receipt = {"retrieved_at": "2026-01-01T00:00:00Z"}
        self.assertFalse(
            source_observation_time_matches(
                start,
                {"observed_at": "2026-01-01T00:00:01Z"},
                receipt,
                "0" * 64,
                materials_root=None,
                result_path=None,
            )
        )


if __name__ == "__main__":
    unittest.main()
