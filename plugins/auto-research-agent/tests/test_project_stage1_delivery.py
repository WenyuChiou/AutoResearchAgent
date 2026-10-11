"""Real saved-record delivery; authored HTTP fixtures and no external execution."""

from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_stage1_deliverable as package_fixture
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
    _io_root,
)
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import read_json, sha, write_json
from stage1_ledger.journal import canonical
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import (
    authenticate,
    bound_body,
    compile_body,
    submit_body,
)


class ProjectStage1DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package_fixture.ResearchDeliverableTests.setUpClass.__func__(cls)

    def setUp(self):
        package_fixture.ResearchDeliverableTests.setUp(self)
        self.assertEqual(self.root.parent, self.private_test_root.resolve())
        self.assertTrue(self.root.name.startswith("stage1-deliverable-test-"))
        # The root was preflighted outside Git. Use the extended handle for
        # cleanup too, so Windows can remove the real full-hash paper filename.
        self.temp.name = str(_io_root(self.root))
        self.fixture_root = self.inputs
        self.intake_root = self.root / "p"
        self.runner = Mock(side_effect=AssertionError("external query dispatched"))
        self.reopen()
        self.addCleanup(lambda: self.intake.close())

    def reopen(self):
        if hasattr(self, "intake"):
            self.intake.close()
        self.intake = ProjectIntakeService(self.intake_root, authenticate=authenticate)
        self.stage1 = ProjectStage1Service(self.intake, query_runner=self.runner)
        self.delivery = ProjectStage1DeliveryService(self.stage1)

    def saved(
        self, key="one", topic="Aircraft diagnosis with sensor drift", *, doi=None
    ):
        created = self.intake.create("alice-token", {"key": key, "topic": topic})
        ref = created["project_ref"]
        self.intake.submit(
            "alice-token", ref, submit_body(self.intake.read("alice-token", ref))
        )
        self.intake.compile(
            "alice-token", ref, compile_body(self.intake.read("alice-token", ref))
        )
        offer = self.stage1.read("alice-token", ref)["initialization_offer"]
        self.stage1.initialize(
            "alice-token",
            ref,
            dict(
                bound_body(self.intake.read("alice-token", ref), "initialize"),
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            ),
        )
        state = self.intake._load(self.intake._principal("alice-token"), ref)
        run = state["stage1_runs"][state["stage1_active"]]
        ledger = CoverageLedger(self.intake._path(ref, run["path"]))
        coverage = ledger.coverage_state()
        planned = next(iter(coverage.queries))
        query = ledger.start_planned(planned)
        attempt = ledger.start(
            "backend",
            {"input": coverage.arguments(planned)},
            backend="openalex",
            parent_id=query,
        )
        metadata = dict(
            title=package_fixture.TITLE,
            authors=["Synthetic Author"],
            year=2024,
            version="v1",
        )
        if doi is not None:
            metadata["doi"] = doi
        refs = ledger.save_bytes(canonical([metadata]), producer=attempt)
        empty = ledger.save_bytes(b"", producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=empty,
            stderr=empty,
            records=refs,
        )
        query_event = ledger.complete_query(query)
        ledger.extract()
        candidate = next(iter(ledger.candidates().values()))
        work, version = candidate["work_id"], candidate["version_ids"][0]
        reason = "Authored fixture remains pending; scientific findings are unknown."
        decision = ledger.decide(
            work,
            "pending",
            reason="fixture-unassessed",
            rationale=reason,
            evidence_refs=[refs],
        )
        source = ledger.start_source(
            work_id=work,
            version_id=version,
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored HTTP response; no external acquisition.",
        )
        self.inputs = self.fixture_root / key
        self.inputs.mkdir()
        records = package_fixture.ResearchDeliverableTests.make_records(self)
        records_path = self.records
        receipt = read_json(self.inputs / records["sources"][0]["result_path"])
        text = Path(receipt["extracted_text_path"]).read_bytes()
        raw_ref = ledger.save_bytes(
            Path(receipt["raw_path"]).read_bytes(), producer=source
        )
        text_ref = ledger.save_bytes(text, producer=source)
        ledger.finish_source(
            attempt_id=source,
            outcome="available",
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=200,
            resolved_uri=receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=text_ref,
            extraction={"method": "research_hub", "version": "fixture"},
            reason="Real parser output from an authored HTTP fixture.",
        )
        claim = records["claims"][0]
        claim.update(text=claim["quote"], relation="supports")
        claim_id = ledger.claim(
            work_id=work,
            version_id=version,
            claim_text=claim["text"],
            relation="supports",
            evidence_level=claim["evidence_level"],
            locator={"section": claim["locator"], "quote": claim["quote"]},
            source_ref=text_ref,
            verifier={
                "actor": "fixture",
                "actor_type": "agent",
                "method": "exact-span",
            },
        )
        paper = records["papers"][0]
        paper.update(
            work_id=work,
            version_id=version,
            doi=doi,
            source_ids=[source],
            claim_ids=[claim_id],
        )
        paper["classification"] = {
            name: "Unknown: not assessed in authored fixture."
            for name in paper["classification"]
        }
        paper["findings"] = {
            name: "Unknown: not assessed in authored fixture."
            for name in paper["findings"]
        }
        records["sources"][0].update(source_id=source, work_id=work, version_id=version)
        claim.update(
            claim_id=claim_id, work_id=work, version_id=version, source_id=source
        )
        records["screening"][0].update(
            decision_id=decision,
            work_id=work,
            version_id=version,
            status="pending",
            reason=reason,
            query=coverage.arguments(planned)["query"],
            discovery_path=query_event,
            observed_at=ledger.event(decision)["created_at"],
        )
        records.update(topic=topic, as_of=receipt["retrieved_at"])
        records["coverage"][0].update(
            need_id=coverage.plan["proposal"]["clusters"][0]["cluster_id"],
            work_ids=[],
            stop_decision="continue",
            reason="Synthetic incomplete ledger; no stop claim.",
        )
        write_json(records_path, records)
        checkpoint = ledger.checkpoint()
        self.assertTrue(validate_run(ledger.root)["valid"])
        self.assertEqual(checkpoint["stage_result"]["next_allowed_action"], "continue")
        return dict(
            ref=ref,
            ledger=ledger,
            records=records,
            path=records_path,
            checkpoint=checkpoint,
            receipt=receipt,
        )

    def register(self, fixture, path=None):
        path = path or fixture["path"]
        return self.delivery.register_records(
            fixture["ref"],
            records_path=path,
            expected_records_sha256=sha(path.read_bytes()),
            expected_ledger_state_sha256=fixture["ledger"].state_hash(),
        )

    def body(self, fixture, offer, key="deliver"):
        return dict(
            bound_body(self.intake.read("alice-token", fixture["ref"]), key),
            confirmed=True,
            ledger_state_sha256=fixture["ledger"].state_hash(),
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
        )

    def append_screening(self, fixture, status):
        ledger, records = fixture["ledger"], fixture["records"]
        work = records["papers"][0]["work_id"]
        discovery = ledger.candidates()[work]["discoveries"][-1]
        reason = "Authored screening " + status + "; no scientific endorsement."
        event = ledger.decide(
            work,
            status,
            reason="fixture-screening",
            rationale=reason,
            evidence_refs=[discovery["source_ref"]],
        )
        row = deepcopy(records["screening"][0])
        row.update(
            decision_id=event,
            status=status,
            reason=reason,
            observed_at=ledger.event(event)["created_at"],
        )
        records["screening"].append(row)
        write_json(fixture["path"], records)
        return event

    def reviewed(self):
        fixture = self.saved()
        ledger, records = fixture["ledger"], fixture["records"]
        paper = records["papers"][0]
        self.append_screening(fixture, "include")
        review = ledger.review_work(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            cluster_claims={records["coverage"][0]["need_id"]: paper["claim_ids"][0]},
            identity_status="unverifiable",
            identity_claims={
                key: None
                for key in ("title", "authors", "year", "identifier", "version")
            },
            closest=False,
            assessor="fixture",
            rationale="Authored cluster attestation; identity remains unverified.",
        )
        fixture["checkpoint"] = ledger.checkpoint()
        self.assertTrue(validate_run(ledger.root)["valid"])
        self.assertEqual(
            ledger.coverage_state().evidence.current()[paper["work_id"]], review
        )
        return fixture, review

    def test_screening_reversal_preserves_historical_review_without_reusing_it(self):
        fixture, review = self.reviewed()
        previous = self.register(fixture)
        self.append_screening(fixture, "exclude")
        fixture["checkpoint"] = fixture["ledger"].checkpoint()
        self.assertTrue(validate_run(fixture["ledger"].root)["valid"])
        self.assertEqual(fixture["ledger"].coverage_state().evidence.current(), {})
        offer = self.register(fixture)
        self.assertNotEqual(previous["offer_ref"], offer["offer_ref"])
        self.delivery.deliver("alice-token", fixture["ref"], self.body(fixture, offer))
        binding = self.delivery.binding(fixture["ref"])
        records = read_json(
            Path(binding["deliverable_dir"]) / "provenance_manifest.json"
        )["canonical_records"]
        self.assertEqual(records["screening"], fixture["records"]["screening"])
        self.assertEqual(
            [row["status"] for row in records["screening"]],
            ["pending", "include", "exclude"],
        )
        self.assertEqual(fixture["ledger"].event(review["event_id"]), review)
        self.assertFalse(binding["eligible_for_stage2"])

    def test_new_candidate_revision_uses_latest_version_and_preserves_old_review(self):
        fixture, review = self.reviewed()
        previous = self.register(fixture)
        ledger, records = fixture["ledger"], fixture["records"]
        paper = records["papers"][0]
        work, old_version = paper["work_id"], paper["version_id"]
        state = ledger.coverage_state()
        planned = list(state.queries)[1]
        query = ledger.start_planned(planned)
        attempt = ledger.start(
            "backend",
            {"input": state.arguments(planned)},
            backend="openalex",
            parent_id=query,
        )
        metadata = deepcopy(ledger.candidates()[work]["discoveries"][-1]["record"])
        metadata["version"] = "v2"
        raw = ledger.save_bytes(canonical([metadata]), producer=attempt)
        empty = ledger.save_bytes(b"", producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_nonempty",
            http_status=200,
            exit_code=0,
            stdout=empty,
            stderr=empty,
            records=raw,
        )
        ledger.complete_query(query)
        ledger.extract()
        version = ledger.candidates()[work]["discoveries"][-1]["version_id"]
        self.assertNotEqual(version, old_version)
        self.assertEqual(ledger.coverage_state().evidence.current(), {})
        source = ledger.start_source(
            work_id=work,
            version_id=version,
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored new version; no external acquisition.",
        )
        self.inputs = fixture["path"].parent / "v2"
        self.inputs.mkdir()
        fresh = package_fixture.ResearchDeliverableTests.make_records(self)
        receipt = read_json(self.inputs / "source/source-fetch-result.json")
        raw_ref = ledger.save_bytes(
            Path(receipt["raw_path"]).read_bytes(), producer=source
        )
        text_ref = ledger.save_bytes(
            Path(receipt["extracted_text_path"]).read_bytes(), producer=source
        )
        ledger.finish_source(
            attempt_id=source,
            outcome="available",
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=200,
            resolved_uri=receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=text_ref,
            extraction={"method": "research_hub", "version": "fixture"},
            reason="Real parser output from an authored v2 source.",
        )
        claim = deepcopy(records["claims"][0])
        claim_id = ledger.claim(
            work_id=work,
            version_id=version,
            claim_text=claim["text"],
            relation=claim["relation"],
            evidence_level=claim["evidence_level"],
            locator={"section": claim["locator"], "quote": claim["quote"]},
            source_ref=text_ref,
            verifier={
                "actor": "fixture",
                "actor_type": "agent",
                "method": "exact-span",
            },
        )
        paper.update(version_id=version, source_ids=[source], claim_ids=[claim_id])
        fresh["sources"][0].update(
            source_id=source,
            work_id=work,
            version_id=version,
            result_path="v2/source/source-fetch-result.json",
        )
        claim.update(claim_id=claim_id, source_id=source, version_id=version)
        records.update(sources=fresh["sources"], claims=[claim])
        for decision in records["screening"]:
            # Core DecisionEvent is work-bound; canonical v1 has one selected
            # version per work. Original event IDs and history stay unchanged.
            decision["version_id"] = version
        write_json(fixture["path"], records)
        fixture["checkpoint"] = ledger.checkpoint()
        self.assertTrue(validate_run(ledger.root)["valid"])
        offer = self.register(fixture)
        self.assertNotEqual(previous["offer_ref"], offer["offer_ref"])
        self.delivery.deliver("alice-token", fixture["ref"], self.body(fixture, offer))
        binding = self.delivery.binding(fixture["ref"])
        delivered = read_json(
            Path(binding["deliverable_dir"]) / "provenance_manifest.json"
        )["canonical_records"]
        self.assertEqual(delivered["papers"][0]["version_id"], version)
        self.assertEqual(delivered["claims"][0]["claim_id"], claim_id)
        self.assertEqual(ledger.event(review["event_id"]), review)
        self.assertEqual(len(ledger.candidates()[work]["discoveries"]), 2)
        self.assertFalse(binding["eligible_for_stage2"])

    def test_available_source_binds_selected_response_before_failed_terminal_attempt(
        self,
    ):
        original = package_fixture.ResearchDeliverableTests.make_records
        doi = "10.5555/authored-fixture"
        for status in (404, 503):
            with self.subTest(terminal_status=status):

                def produce(owner):
                    records = original(owner)

                    def response(url, **_):
                        if url == "https://example.org/study":
                            return package_fixture.Response(
                                package_fixture.HTML, "text/html", 200
                            )
                        return package_fixture.Response(
                            b"Authored inaccessible fallback", "text/plain", status
                        )

                    with (
                        patch(
                            "research_hub.source_fetch._resolve_host_addresses",
                            return_value=("93.184.216.34",),
                        ),
                        patch("requests.Session.get", side_effect=response) as requests,
                    ):
                        receipt = package_fixture.fetch_public_source(
                            output_dir=owner.inputs / "selected-source",
                            doi=doi,
                            url="https://example.org/study",
                            title=package_fixture.TITLE,
                        ).to_dict()
                    self.assertGreater(requests.call_count, 1)
                    self.assertEqual(receipt["status"], "available")
                    self.assertEqual(receipt["attempts"][-1]["http_status"], status)
                    selected = next(
                        row
                        for row in receipt["attempts"]
                        if row["raw_path"] == receipt["raw_path"]
                    )
                    self.assertEqual(selected["http_status"], 200)
                    self.assertEqual(selected["raw_sha256"], receipt["raw_sha256"])
                    self.assertEqual(selected["final_url"], receipt["final_url"])
                    path = owner.inputs / "selected-source/source-fetch-result.json"
                    records["sources"][0].update(
                        result_path="selected-source/source-fetch-result.json",
                        result_sha256=sha(path.read_bytes()),
                    )
                    records["papers"][0]["doi"] = doi
                    return records

                with patch.object(
                    package_fixture.ResearchDeliverableTests,
                    "make_records",
                    side_effect=produce,
                ):
                    fixture = self.saved("selected-" + str(status), doi=doi)
                self.assertTrue(validate_run(fixture["ledger"].root)["valid"])
                offer = self.register(fixture)
                self.delivery.deliver(
                    "alice-token", fixture["ref"], self.body(fixture, offer)
                )
                binding = self.delivery.binding(fixture["ref"])
                manifest = read_json(
                    Path(binding["deliverable_dir"]) / "provenance_manifest.json"
                )
                self.assertEqual(manifest["canonical_records"], fixture["records"])
                self.assertFalse(binding["eligible_for_stage2"])

    def test_selected_source_attempt_ambiguity_or_mismatch_rejects_before_build(self):
        fixture = self.saved()
        original_records = deepcopy(fixture["records"])
        original_path = (
            fixture["path"].parent / original_records["sources"][0]["result_path"]
        )
        original_bytes = original_path.read_bytes()
        for variant in ("duplicate", "digest-mismatch"):
            with self.subTest(variant=variant):
                receipt = read_json(original_path)
                selected = next(
                    row
                    for row in receipt["attempts"]
                    if row["raw_path"] == receipt["raw_path"]
                    and row["raw_sha256"] == receipt["raw_sha256"]
                )
                if variant == "duplicate":
                    duplicate = deepcopy(selected)
                    duplicate["sequence"] = len(receipt["attempts"]) + 1
                    receipt["attempts"].append(duplicate)
                else:
                    receipt["raw_sha256"] = sha(b"authored selected digest mismatch")
                receipt["receipt_sha256"] = package_fixture.sources.receipt_digest(
                    receipt
                )
                package_fixture.sources.validate_receipt_shape(receipt)
                # Rehashed adversarial copies cannot replace the saved SDK
                # observation. Keep its original receipt and raw bytes intact.
                tampered_path = original_path.with_name(variant + "-receipt.json")
                write_json(tampered_path, receipt)
                records = deepcopy(original_records)
                records["sources"][0].update(
                    result_path=tampered_path.relative_to(
                        fixture["path"].parent
                    ).as_posix(),
                    result_sha256=sha(tampered_path.read_bytes()),
                )
                write_json(fixture["path"], records)
                with patch(
                    "research_workspace_native.project_stage1_delivery.package.build"
                ) as build:
                    with self.assertRaises(SessionApiError) as error:
                        self.register(fixture)
                    self.assertEqual(
                        error.exception.code, "stage1-source-observation-differs"
                    )
                    build.assert_not_called()
                self.assertEqual(original_path.read_bytes(), original_bytes)
                self.assertEqual(
                    sha(Path(fixture["receipt"]["raw_path"]).read_bytes()),
                    fixture["receipt"]["raw_sha256"],
                )

    def test_real_package_replay_preserves_unknowns_and_actual_incomplete_handoff(self):
        fixture = self.saved()
        offer = self.register(fixture)
        self.assertNotIn("records_path", offer)
        self.assertFalse(offer["eligible_for_stage2"])
        result = self.delivery.deliver(
            "alice-token", fixture["ref"], self.body(fixture, offer)
        )
        self.assertEqual(result["status"], "saved")
        binding = self.delivery.binding(fixture["ref"])
        root = Path(binding["deliverable_dir"])
        report = package_fixture.package.validate(root, binding["manifest_sha256"])
        self.assertTrue(report["source_semantic_replay"])
        self.assertFalse(report["scientific_quality_scored"])
        manifest = read_json(root / "provenance_manifest.json")
        self.assertEqual(manifest["canonical_records"], fixture["records"])
        paper = fixture["records"]["papers"][0]
        paper_paths = [name for name in manifest["files"] if name.startswith("papers/")]
        self.assertEqual(len(paper_paths), 1)
        natural_path = root / paper_paths[0]
        self.assertIn(paper["work_id"], natural_path.name)
        self.assertIn(paper["version_id"], natural_path.name)
        # Exercise the real full-hash filename beyond Windows MAX_PATH. The
        # portable manifest keeps the same filename after physical relocation.
        self.assertGreater(len(str(natural_path).removeprefix("\\\\?\\")), 260)
        self.assertTrue(natural_path.is_file())
        with tempfile.TemporaryDirectory(
            prefix="s1d-", dir=self.private_test_root
        ) as temporary:
            moved = Path(temporary) / "p"
            shutil.copytree(root, moved)
            self.assertLessEqual(len(str(moved / paper_paths[0])), 260)
            self.assertEqual(
                sha((moved / "provenance_manifest.json").read_bytes()),
                binding["manifest_sha256"],
            )
            replay = package_fixture.package.validate(moved, binding["manifest_sha256"])
            self.assertEqual(replay["status"], "passed")
            self.assertTrue(replay["source_semantic_replay"])
        handoff_path = Path(binding["handoff_path"])
        self.assertEqual(sha(handoff_path.read_bytes()), binding["handoff_sha256"])
        handoff = read_json(handoff_path)
        self.assertFalse(handoff["eligible_for_stage2"])
        self.assertEqual(
            handoff["source_state_sha256"], fixture["checkpoint"]["state_sha256"]
        )
        self.assertIn(
            handoff_path.relative_to(fixture["ledger"].root).as_posix(),
            [row["path"] for row in fixture["checkpoint"]["stage_result"]["outputs"]],
        )
        self.assertIsNotNone(
            self.delivery.read("alice-token", fixture["ref"])["canonical_package"]
        )
        self.assertFalse(result["stage1_complete"])
        self.runner.assert_not_called()

    def test_all_actual_screening_revisions_are_required_and_retained(self):
        fixture = self.saved()
        old = fixture["records"]["screening"][0]
        ledger = fixture["ledger"]
        event_id = ledger.decide(
            old["work_id"],
            "pending",
            reason="fixture-rechecked",
            rationale="Authored recheck leaves the same scientific unknowns.",
            evidence_refs=[
                next(iter(ledger.candidates().values()))["discoveries"][0]["source_ref"]
            ],
        )
        event = ledger.event(event_id)
        revised = dict(
            old,
            decision_id=event_id,
            reason=event["rationale"],
            observed_at=event["created_at"],
        )
        fixture["records"]["screening"].append(revised)
        write_json(fixture["path"], fixture["records"])
        fixture["checkpoint"] = ledger.checkpoint()
        self.register(fixture)
        omitted = deepcopy(fixture["records"])
        omitted["screening"] = [revised]
        path = fixture["path"].with_name("omitted-screening.json")
        write_json(path, omitted)
        with self.assertRaises(SessionApiError):
            self.register(fixture, path)

    def test_offer_reads_preserve_sqlite_history_and_ledger_bytes_without_building(
        self,
    ):
        fixture = self.saved()
        offer = self.register(fixture)
        before = {
            p.relative_to(fixture["ledger"].root).as_posix(): p.read_bytes()
            for p in fixture["ledger"].root.rglob("*")
            if p.is_file()
        }
        history = self.intake.history("alice-token", fixture["ref"])
        with (
            patch(
                "research_workspace_native.project_stage1_delivery.package.build"
            ) as build,
            patch(
                "research_workspace_native.project_stage1_delivery.package.validate"
            ) as validate,
        ):
            for _ in range(2):
                view = self.delivery.read("alice-token", fixture["ref"])
                self.assertEqual(view["offers"], [offer])
                self.assertIsNone(view["canonical_package"])
            build.assert_not_called()
            validate.assert_not_called()
        self.assertEqual(history, self.intake.history("alice-token", fixture["ref"]))
        after = {
            p.relative_to(fixture["ledger"].root).as_posix(): p.read_bytes()
            for p in fixture["ledger"].root.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_canonical_identity_decisions_and_claims_must_match_real_ledger(self):
        fixture = self.saved()
        changes = (
            lambda rows: rows.update(topic="Foreign topic"),
            lambda rows: rows["papers"][0].update(title="Foreign title"),
            lambda rows: rows["papers"][0].update(version_id="foreign-version"),
            lambda rows: rows["screening"][0].update(status="include"),
            lambda rows: rows["screening"][0].update(
                reason="Invented screening rationale"
            ),
            lambda rows: rows["claims"][0].update(claim_id="invented-claim"),
        )
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            for index, change in enumerate(changes):
                with self.subTest(index=index):
                    rows = deepcopy(fixture["records"])
                    change(rows)
                    path = fixture["path"].with_name(f"mismatch-{index}.json")
                    write_json(path, rows)
                    with self.assertRaises((SessionApiError, ValueError)):
                        self.register(fixture, path)
            build.assert_not_called()

    def test_foreign_principal_project_and_client_paths_never_build(self):
        first, second = self.saved("first"), self.saved("second")
        offer = self.register(first)
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            for credential in ("bob-token", "wrong"):
                with (
                    self.subTest(credential=credential),
                    self.assertRaises(SessionApiError),
                ):
                    self.delivery.read(credential, first["ref"])
                with (
                    self.subTest(action=credential),
                    self.assertRaises(SessionApiError),
                ):
                    self.delivery.deliver(
                        credential, first["ref"], self.body(first, offer, credential)
                    )
            with self.assertRaises(SessionApiError):
                self.delivery.deliver(
                    "alice-token", second["ref"], self.body(second, offer)
                )
            with self.assertRaises(SessionApiError):
                self.delivery.deliver(
                    "alice-token",
                    first["ref"],
                    {
                        **self.body(first, offer, "path"),
                        "records_path": str(first["path"]),
                    },
                )
            build.assert_not_called()

    def test_record_tampering_after_offer_rejects_before_build(self):
        fixture = self.saved()
        offer = self.register(fixture)
        fixture["path"].write_bytes(fixture["path"].read_bytes() + b" ")
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError):
                self.delivery.deliver(
                    "alice-token", fixture["ref"], self.body(fixture, offer)
                )
            build.assert_not_called()

    def test_source_tampering_cannot_become_a_canonical_package(self):
        fixture = self.saved()
        offer = self.register(fixture)
        Path(fixture["receipt"]["raw_path"]).write_bytes(b"tampered authored response")
        with self.assertRaises(SessionApiError):
            self.delivery.deliver(
                "alice-token", fixture["ref"], self.body(fixture, offer)
            )
        self.assertIsNone(
            self.delivery.read("alice-token", fixture["ref"])["canonical_package"]
        )

    def test_saved_offer_eligibility_tamper_rejects_before_build(self):
        fixture = self.saved()
        offer = self.register(fixture)
        body = self.body(fixture, offer)
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])
        state["stage1_delivery_offers"][offer["offer_ref"]]["eligible_for_stage2"] = (
            True
        )
        with self.intake.db:
            self.intake._save(
                state, "fixture-offer-tamper", {"offer_ref": offer["offer_ref"]}
            )
        self.reopen()
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError) as error:
                self.delivery.deliver("alice-token", fixture["ref"], body)
            self.assertEqual(error.exception.code, "intake-operation-failed")
            self.assertEqual(error.exception.receipt["status"], "failed")
            self.assertEqual(
                error.exception.receipt["error"], "stage1-delivery-offer-hash-differs"
            )
            build.assert_not_called()

    def test_receipt_observation_drift_rejects_even_with_new_records_hash(self):
        for field in ("request_url", "final_url", "retrieved_at"):
            with self.subTest(field=field):
                fixture = self.saved("source-drift-" + field)
                receipt_path = (
                    fixture["path"].parent
                    / fixture["records"]["sources"][0]["result_path"]
                )
                receipt = read_json(receipt_path)
                if field == "request_url":
                    receipt["request"]["url"] = "https://example.org/foreign-study"
                elif field == "final_url":
                    receipt["final_url"] = "https://example.org/foreign-result"
                else:
                    receipt["retrieved_at"] = "2000-01-01T00:00:00Z"
                # These are adversarial mutations of the genuine saved fixture
                # receipt. Shape and records hashes pass; ledger facts must not.
                package_fixture.sources.validate_receipt_shape(receipt)
                write_json(receipt_path, receipt)
                fixture["records"]["sources"][0]["result_sha256"] = sha(
                    receipt_path.read_bytes()
                )
                write_json(fixture["path"], fixture["records"])
                with patch(
                    "research_workspace_native.project_stage1_delivery.package.build"
                ) as build:
                    with self.assertRaises(SessionApiError) as error:
                        self.register(fixture)
                    self.assertEqual(
                        error.exception.code, "stage1-source-observation-differs"
                    )
                    build.assert_not_called()

    def test_saved_artifact_metadata_tamper_rejects_receipt_and_offer_mismatch(self):
        fixture = self.saved()
        offer = self.register(fixture)
        self.delivery.deliver("alice-token", fixture["ref"], self.body(fixture, offer))
        principal = self.intake._principal("alice-token")
        original = self.intake._load(principal, fixture["ref"])
        artifact_ref = original["stage1_canonical_package"]["artifact_ref"]
        for field in ("eligible_for_stage2", "counts", "binding"):
            with self.subTest(field=field):
                changed = deepcopy(original)
                artifact = changed["stage1_canonical_package"]
                if field == "eligible_for_stage2":
                    artifact[field] = True
                elif field == "counts":
                    artifact[field]["papers"] += 1
                else:
                    artifact[field]["brief_sha256"] = "0" * 64
                # Both cached copies agree. The real package, offer and saved
                # delivery action receipt remain the independent authority.
                changed["stage1_canonical_packages"][artifact_ref][field] = deepcopy(
                    artifact[field]
                )
                with self.intake.db:
                    self.intake._save(
                        changed, "fixture-artifact-tamper", {"field": field}
                    )
                self.reopen()
                with patch(
                    "research_workspace_native.project_stage1_delivery.package.build"
                ) as build:
                    with self.assertRaises(SessionApiError):
                        self.delivery.binding(fixture["ref"])
                    build.assert_not_called()
                with (
                    patch(
                        "research_workspace_native.project_stage1_delivery.package.build"
                    ) as build,
                    patch(
                        "research_workspace_native.project_stage1_delivery.package.validate"
                    ) as validate,
                ):
                    view = self.delivery.read("alice-token", fixture["ref"])
                    self.assertEqual(
                        view["canonical_package"]["status"], "source-binding-failed"
                    )
                    build.assert_not_called()
                    validate.assert_not_called()

    def test_failed_network_observation_binds_exact_sdk_receipt_bytes(self):
        fixture = self.saved()
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        source_id = ledger.start_source(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored timeout; no external acquisition.",
        )
        self.inputs = fixture["path"].parent / "network-failure"
        self.inputs.mkdir()
        failed = package_fixture.ResearchDeliverableTests.make_records(
            self,
            package_fixture.Timeout("authored offline timeout"),
            "",
            None,
        )
        receipt_path = self.inputs / "source/source-fetch-result.json"
        receipt = read_json(receipt_path)
        self.assertFalse(receipt["raw_path"])
        self.assertFalse(receipt["attempts"][-1]["raw_path"])
        self.assertFalse(receipt["extracted_text_path"])
        self.assertEqual(failed["claims"], [])
        # This is the real SDK failure observation receipt, not an invented
        # empty response or claimed full text. Core requires a raw-output ref.
        raw_ref = ledger.save_bytes(receipt_path.read_bytes(), producer=source_id)
        ledger.finish_source(
            attempt_id=source_id,
            outcome="network_error",
            observed_at=receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=None,
            resolved_uri=receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=None,
            extraction=None,
            reason="Original SDK receipt for an authored timeout; no response bytes or full text.",
        )
        source = failed["sources"][0]
        source.update(
            source_id=source_id,
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            result_path="network-failure/source/source-fetch-result.json",
        )
        fixture["records"]["sources"].append(source)
        paper["source_ids"].append(source_id)
        write_json(fixture["path"], fixture["records"])
        fixture["checkpoint"] = ledger.checkpoint()
        self.assertFalse(self.register(fixture)["eligible_for_stage2"])
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        source["result_sha256"] = sha(receipt_path.read_bytes())
        write_json(fixture["path"], fixture["records"])
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError) as error:
                self.register(fixture)
            self.assertEqual(error.exception.code, "stage1-source-raw-bytes-differ")
            build.assert_not_called()

    def test_http_failure_types_cannot_be_interchanged_with_real_source_receipts(self):
        fixture = self.saved()
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        source_id = ledger.start_source(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            source_uri="https://example.org/study",
            tool="research_hub.source_fetch",
            request={"public_only": True},
            actor="fixture",
            reason="Authored service failure; no external acquisition.",
        )
        self.inputs = fixture["path"].parent / "service-failure"
        self.inputs.mkdir()
        failed = package_fixture.ResearchDeliverableTests.make_records(
            self,
            b"authored service unavailable",
            "text/plain",
            503,
        )
        failed_receipt = read_json(self.inputs / "source/source-fetch-result.json")
        self.assertFalse(failed_receipt["raw_path"])
        self.assertFalse(failed_receipt["extracted_text_path"])
        attempt = failed_receipt["attempts"][-1]
        self.assertTrue(attempt["raw_path"])
        raw_ref = ledger.save_bytes(
            Path(attempt["raw_path"]).read_bytes(), producer=source_id
        )
        ledger.finish_source(
            attempt_id=source_id,
            outcome="http_error",
            observed_at=failed_receipt["retrieved_at"].replace("+00:00", "Z"),
            http_status=503,
            resolved_uri=failed_receipt["final_url"],
            raw_ref=raw_ref,
            text_ref=None,
            extraction=None,
            reason="Preserved real receipt from an authored HTTP 503 response.",
        )
        source = failed["sources"][0]
        source.update(
            source_id=source_id,
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            result_path="service-failure/source/source-fetch-result.json",
        )
        fixture["records"]["sources"].append(source)
        paper["source_ids"].append(source_id)
        write_json(fixture["path"], fixture["records"])
        fixture["checkpoint"] = ledger.checkpoint()
        self.register(fixture)

        self.inputs = fixture["path"].parent / "http-failure"
        self.inputs.mkdir()
        replacement = package_fixture.ResearchDeliverableTests.make_records(
            self,
            b"authored not found",
            "text/plain",
            404,
        )
        replacement_path = self.inputs / "source/source-fetch-result.json"
        replacement_receipt = read_json(replacement_path)
        self.assertEqual(failed_receipt["status"], replacement_receipt["status"])
        self.assertEqual(replacement_receipt["attempts"][-1]["http_status"], 404)
        # Keep the second producer's original receipt bytes and original output
        # directory. Only the canonical source points to the wrong observation.
        source.update(
            result_path="http-failure/source/source-fetch-result.json",
            result_sha256=replacement["sources"][0]["result_sha256"],
        )
        write_json(fixture["path"], fixture["records"])
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError) as error:
                self.register(fixture)
            self.assertEqual(error.exception.code, "stage1-source-observation-differs")
            build.assert_not_called()

    def test_changed_ledger_without_current_checkpoint_rejects_registration(self):
        fixture = self.saved()
        planned = list(fixture["ledger"].coverage_state().queries)[1]
        fixture["ledger"].start_planned(planned)
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError):
                self.register(fixture)
            build.assert_not_called()

    def test_new_project_input_invalidates_previously_registered_offer(self):
        fixture = self.saved()
        offer = self.register(fixture)
        body = self.body(fixture, offer)
        self.intake.revise(
            "alice-token",
            fixture["ref"],
            dict(
                bound_body(self.intake.read("alice-token", fixture["ref"]), "revise"),
                topic="Polyphonic music transcription",
            ),
        )
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            with self.assertRaises(SessionApiError):
                self.delivery.deliver("alice-token", fixture["ref"], body)
            build.assert_not_called()

    def test_saved_same_key_survives_sqlite_reopen_without_rebuilding(self):
        fixture = self.saved()
        offer = self.register(fixture)
        body = self.body(fixture, offer)
        first = self.delivery.deliver("alice-token", fixture["ref"], body)
        binding = self.delivery.binding(fixture["ref"])
        before = {
            p.relative_to(Path(binding["deliverable_dir"])).as_posix(): p.read_bytes()
            for p in Path(binding["deliverable_dir"]).rglob("*")
            if p.is_file()
        }
        self.reopen()
        with (
            patch(
                "research_workspace_native.project_stage1_delivery.package.build"
            ) as build,
            patch(
                "research_workspace_native.project_stage1_delivery.package.validate"
            ) as validate,
        ):
            replay = self.delivery.deliver(
                "alice-token", fixture["ref"], {**body, "revision": 999}
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(
                {k: v for k, v in replay.items() if k != "replayed"},
                {k: v for k, v in first.items() if k != "replayed"},
            )
            for _ in range(2):
                self.delivery.read("alice-token", fixture["ref"])
            build.assert_not_called()
            validate.assert_not_called()
        after = {
            p.relative_to(Path(binding["deliverable_dir"])).as_posix(): p.read_bytes()
            for p in Path(binding["deliverable_dir"]).rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_repeated_records_at_new_checkpoint_keep_independent_delivery_artifacts(
        self,
    ):
        fixture = self.saved()
        first_offer = self.register(fixture)
        first = self.delivery.deliver(
            "alice-token",
            fixture["ref"],
            self.body(fixture, first_offer, "deliver-first"),
        )
        first_binding = self.delivery.binding(fixture["ref"])
        fixture["checkpoint"] = fixture["ledger"].checkpoint()
        second_offer = self.register(fixture)
        self.assertNotEqual(first_offer["offer_ref"], second_offer["offer_ref"])
        second = self.delivery.deliver(
            "alice-token",
            fixture["ref"],
            self.body(fixture, second_offer, "deliver-second"),
        )
        self.assertEqual(
            first["artifact_ref"], "stage1-canonical-" + first["request_sha256"][:32]
        )
        self.assertEqual(
            second["artifact_ref"], "stage1-canonical-" + second["request_sha256"][:32]
        )
        self.assertNotEqual(first["artifact_ref"], second["artifact_ref"])
        state = self.intake._load(self.intake._principal("alice-token"), fixture["ref"])
        saved = state["stage1_canonical_packages"]
        self.assertEqual(set(saved), {first["artifact_ref"], second["artifact_ref"]})
        self.assertEqual(
            saved[first["artifact_ref"]]["offer_ref"], first_offer["offer_ref"]
        )
        self.assertEqual(
            saved[second["artifact_ref"]]["offer_ref"], second_offer["offer_ref"]
        )
        self.reopen()
        second_binding = self.delivery.binding(fixture["ref"])
        self.assertEqual(second_binding["artifact_ref"], second["artifact_ref"])
        first_records = read_json(
            Path(first_binding["deliverable_dir"]) / "provenance_manifest.json"
        )["canonical_records"]
        second_records = read_json(
            Path(second_binding["deliverable_dir"]) / "provenance_manifest.json"
        )["canonical_records"]
        self.assertEqual(first_records, second_records)

    def test_partial_build_failure_is_preserved_and_same_key_never_rebuilds(self):
        fixture = self.saved()
        offer = self.register(fixture)
        body = self.body(fixture, offer)
        outputs = []

        def partial(records_path, output, expected):
            output = Path(output)
            output.mkdir(parents=True, exist_ok=False)
            marker = output / "partial-output.txt"
            marker.write_bytes(b"preserved partial build")
            outputs.append(marker)
            raise OSError("authored failure after partial output")

        with patch(
            "research_workspace_native.project_stage1_delivery.package.build",
            side_effect=partial,
        ):
            with self.assertRaises(SessionApiError) as error:
                self.delivery.deliver("alice-token", fixture["ref"], body)
        self.assertEqual(error.exception.receipt["status"], "failed")
        self.assertEqual(outputs[0].read_bytes(), b"preserved partial build")
        self.reopen()
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            replay = self.delivery.deliver("alice-token", fixture["ref"], body)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["status"], "failed")
            build.assert_not_called()
        self.assertEqual(outputs[0].read_bytes(), b"preserved partial build")

    def test_crash_after_build_remains_unknown_and_reopen_does_not_rebuild(self):
        fixture = self.saved()
        offer = self.register(fixture)
        body = self.body(fixture, offer)
        save = self.intake._save

        def crash(state, kind, payload):
            if kind == "stage1-deliver-saved":
                raise OSError("authored crash before delivery commit")
            return save(state, kind, payload)

        with patch.object(self.intake, "_save", side_effect=crash):
            with self.assertRaises(SessionApiError) as error:
                self.delivery.deliver("alice-token", fixture["ref"], body)
        self.assertEqual(error.exception.receipt["status"], "execution-unknown")
        manifests = list(self.intake_root.rglob("provenance_manifest.json"))
        self.assertEqual(len(manifests), 1)
        original = manifests[0].read_bytes()
        self.reopen()
        with patch(
            "research_workspace_native.project_stage1_delivery.package.build"
        ) as build:
            replay = self.delivery.deliver("alice-token", fixture["ref"], body)
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["status"], "execution-unknown")
            build.assert_not_called()
        self.assertEqual(manifests[0].read_bytes(), original)
        self.assertIsNone(
            self.delivery.read("alice-token", fixture["ref"])["canonical_package"]
        )


if __name__ == "__main__":
    unittest.main()
