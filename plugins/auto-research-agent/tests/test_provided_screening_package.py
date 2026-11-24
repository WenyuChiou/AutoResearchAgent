"""A provided table can be reported without inventing reading or acceptance."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import unittest

from docx import Document
from markdown_it import MarkdownIt

import test_stage1_provided_candidate as provided_fixture
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
    _io_root,
    _records_match,
    _screening_library,
)
from research_workspace_native.project_stage1_records import ProjectStage1RecordsService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import DeliverableError, private_output, sha, read_json
from stage1_deliverable.package import build, validate
from stage1_deliverable.records import validate_records
from stage1_deliverable.screening_records import read_artifacts
from stage1_ledger.validation import validate_run


class ProvidedScreeningPackageTests(unittest.TestCase):
    def setUp(self):
        self.case = provided_fixture.ProvidedCandidateTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        c = self.case
        c.admit()
        self.ledger = c.private_ledger(c.ref)
        start = self.ledger.start_source(
            work_id=c.work,
            version_id=c.version,
            source_uri="https://example.org/table",
            tool="saved-local",
            request={"operation": "saved-table"},
            actor="alice",
            reason="Saved table only; no reading.",
        )
        raw = self.ledger.save_bytes(c.data, producer=start)
        self.ledger.finish_source(
            attempt_id=start,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=None,
            resolved_uri="https://example.org/table",
            raw_ref=raw,
            text_ref=raw,
            extraction={"method": "saved-local", "version": "v1"},
            reason="Synthetic table supplied by operator, not a search.",
        )
        c.service.checkpoint(
            "alice-token", c.ref, c.action_body(c.ref, "report-checkpoint")
        )
        self.delivery = ProjectStage1DeliveryService(c.service)

        @contextmanager
        def guard(run, ledger, report):
            with ledger.writing(repair=False):

                def check():
                    self.assertEqual(
                        validate_run(ledger.root)["state_sha256"],
                        report["state_sha256"],
                    )

                yield check

        self.producer = ProjectStage1RecordsService(
            self.delivery, materials_root=c.material, mutation_guard=guard
        )

    def produce(self):
        c = self.case
        view = c.service.read("alice-token", c.ref)
        offer = self.producer.produce_records(
            c.ref,
            expected_ledger_state_sha256=view["ledger"]["state_sha256"],
            expected_checkpoint_event_id=view["checkpoint"]["event_id"],
        )
        state = c.intake._load("alice", c.ref)
        path = Path(state["stage1_delivery_offers"][offer["offer_ref"]]["records_path"])
        return offer, path, read_json(path)

    def test_real_records_build_validate_markdown_docx_and_false_stage2_eligibility(
        self,
    ):
        offer, path, records = self.produce()
        self.assertEqual(records["schema_version"], "1.2.0")
        paper = records["papers"][0]
        self.assertEqual(paper["reading_status"], "provided-unread")
        self.assertEqual(records["claims"], [])
        self.assertEqual(records["screening"], [])
        self.assertFalse(offer["eligible_for_stage2"])
        self.assertEqual(records["screening_library"]["counts"]["completed_queries"], 0)
        self.assertEqual(records["screening_library"]["counts"]["source_attempts"], 1)
        raw = read_artifacts(records, path.parent)
        ref = records["screening_library"]["rows"][0]["discoveries"][0]["provided"][
            "material_ref"
        ]
        self.assertIn(self.case.data, raw.values())
        self.assertEqual(ref["sha256"], sha(self.case.data))
        output = _io_root(private_output(self.case.root / "package"))
        receipt = build(path, output, sha(path.read_bytes()))
        self.assertEqual(
            validate(output, receipt["manifest_sha256"])["status"], "passed"
        )
        md = (output / "literature_review.md").read_text(encoding="utf8")
        parsed = MarkdownIt().render(md)
        docx = "\n".join(
            p.text for p in Document(output / "literature_review.docx").paragraphs
        )
        for phrase in (
            "externally provided saved material",
            "Original material type:",
            "https://example.org/table",
            sha(self.case.data),
            self.case.ref,
            self.case.version,
            "no decision recorded",
            "Reading: Unknown",
            "Research claims: Unknown",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, parsed)
                self.assertIn(phrase, docx)
        self.assertFalse(
            self.case.service.read("alice-token", self.case.ref)["stage1_complete"]
        )

    def test_wrong_project_version_and_ledger_binding_are_refused(self):
        _, _, records = self.produce()
        context = self.delivery._context(self.case.ref)
        expected = _screening_library(context)
        for field, value in (
            ("project_id", "wrong-project"),
            ("input_version", 999),
            ("ledger_state_sha256", "0" * 64),
        ):
            bad = deepcopy(records)
            bad["screening_library"]["binding"][field] = value
            with (
                self.subTest(field=field),
                self.assertRaises((SessionApiError, DeliverableError)),
            ):
                _records_match(
                    bad, self.ledger, self.case.material, screening_library=expected
                )

    def test_provenance_or_fake_query_and_review_promotion_are_refused(self):
        _, _, records = self.produce()
        for field, value in (("query_id", "e000010"), ("version_id", "wrong-version")):
            bad = deepcopy(records)
            bad["screening_library"]["rows"][0]["discoveries"][0][field] = value
            with self.subTest(field=field), self.assertRaises(DeliverableError):
                validate_records(bad)
        for field, value in (
            ("reading_status", "human-reviewed"),
            ("evidence_level", "full-text"),
            ("doi", "10.5555/foreign"),
            ("venue", "Unrecorded venue"),
        ):
            bad = deepcopy(records)
            bad["papers"][0][field] = value
            with self.subTest(field=field), self.assertRaises(DeliverableError):
                validate_records(bad)

    def test_saved_material_byte_drift_is_not_accepted_as_report_evidence(self):
        _, path, records = self.produce()
        ref = records["screening_library"]["rows"][0]["discoveries"][0]["provided"][
            "material_ref"
        ]
        artifact = path.parent / "screening_artifacts" / (ref["sha256"] + ".bin")
        artifact.write_bytes(b"different table")
        with self.assertRaises(DeliverableError):
            read_artifacts(records, path.parent)

    def test_stale_checkpoint_and_real_screening_keep_the_existing_reading_gate(self):
        view = self.case.service.read("alice-token", self.case.ref)
        discovery = self.ledger.candidates()[self.case.work]["discoveries"][0]
        self.ledger.decide(
            self.case.work,
            "pending",
            reason="fixture-review-pending",
            rationale="Actual saved screening is now pending; no reading registration.",
            evidence_refs=[discovery["source_ref"]],
        )
        with self.assertRaisesRegex(
            SessionApiError, "stage1-ledger-state-stale|stage1-checkpoint-stale"
        ):
            self.producer.produce_records(
                self.case.ref,
                expected_ledger_state_sha256=view["ledger"]["state_sha256"],
                expected_checkpoint_event_id=view["checkpoint"]["event_id"],
            )
        self.case.service.checkpoint(
            "alice-token",
            self.case.ref,
            self.case.action_body(self.case.ref, "screened-checkpoint"),
        )
        with self.assertRaisesRegex(
            SessionApiError, "saved-reading-current-record-required"
        ):
            self.produce()
