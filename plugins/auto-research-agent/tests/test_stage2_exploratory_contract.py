"""Exploratory provenance remains private, externally bound and immutable."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_common.contract import SCHEMA_PATHS
from stage2_check import initialize_run, inspect_run
from stage2_workflow import add_snapshot, initialize_workflow, inspect_workflow
import test_stage1_stage2_handoff as fixtures


class ExploratoryContractTests(unittest.TestCase):
    def test_unused_schema_does_not_break_legacy_validation(self):
        read_text = Path.read_text

        def corrupt(path, *args, **kwargs):
            if path == SCHEMA_PATHS["2.1.0"]:
                return "invalid JSON"
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", corrupt):
            validate_packet(self.fixture.packet(), self.fixture.output)
            with self.assertRaisesRegex(Stage2Error, "cannot load"):
                validate_packet(self.packet, self.fixture.output)

    def setUp(self):
        self.fixture = fixtures.Stage1Stage2HandoffTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.build()
        self.packet = self.fixture.packet()
        self.packet["schema_version"] = "2.1.0"
        upstream = self.packet["upstream"]
        acceptance = {
            "kind": "Stage2ExploratoryAcceptance",
            "schema_version": "1.0.0",
            "accepted_by": "Fixture researcher",
            "decision_source_ref": "fixture:explicit-exploratory-decision",
            "purpose": "exploratory-stage2-planning",
            "deliverable_manifest_sha256": upstream[
                "stage1_deliverable_manifest_sha256"
            ],
            "stage1_records_sha256": upstream["stage1_records_sha256"],
            "research_brief_sha256": upstream["research_brief_sha256"],
            "resources_sha256": upstream["resources_sha256"],
            "included_work_ids": upstream["included_work_ids"],
            "limitations": ["Source claims remain unresolved."],
        }
        self.packet["unresolved"].extend(acceptance["limitations"])
        upstream.update(
            schema_version="2.0.0",
            stage1_handoff_sha256=None,
            eligible_for_stage2=False,
            intake_mode="exploratory",
            acceptance=acceptance,
            acceptance_sha256=canonical_hash(acceptance),
            acceptance_file_sha256=canonical_hash(acceptance),
        )
        self._rehash()

    def _rehash(self):
        upstream = self.packet["upstream"]
        upstream["binding_sha256"] = canonical_hash(
            {k: v for k, v in upstream.items() if k != "binding_sha256"}
        )

    def _write(self):
        path = self.fixture.output / "packet.json"
        path.write_text(json.dumps(self.packet), encoding="utf-8")
        return path

    def test_exploratory_packet_preserves_unknowns_and_false_eligibility(self):
        validate_packet(self.packet, self.fixture.output)
        self.assertFalse(self.packet["upstream"]["eligible_for_stage2"])
        self.assertEqual(self.packet["evidence"][0]["relation"], "unverified")

    def test_exploratory_preserves_original_inaccessible_source_state(self):
        from stage2_common.contract import stage1_projection_hash

        self.packet["sources"][0]["access_status"] = "inaccessible"
        self.packet["upstream"]["stage1_sources_sha256"] = stage1_projection_hash(
            self.packet["sources"], omit=("path",)
        )
        self._rehash()
        validate_packet(self.packet, self.fixture.output)
        self.assertEqual(self.packet["sources"][0]["access_status"], "inaccessible")

    def test_rehashed_acceptance_scope_and_limitations_mismatch_rejected(self):
        for field, value in (
            ("research_brief_sha256", "f" * 64),
            ("included_work_ids", ["different-work"]),
            ("limitations", ["Missing preserved limitation"]),
        ):
            with self.subTest(field=field):
                packet = copy.deepcopy(self.packet)
                acceptance = packet["upstream"]["acceptance"]
                acceptance[field] = value
                packet["upstream"]["acceptance_sha256"] = canonical_hash(acceptance)
                packet["upstream"]["binding_sha256"] = canonical_hash(
                    {
                        k: v
                        for k, v in packet["upstream"].items()
                        if k != "binding_sha256"
                    }
                )
                with self.assertRaises(Stage2Error):
                    validate_packet(packet, self.fixture.output)

    def test_exploratory_init_requires_external_packet_hash(self):
        path = self._write()
        with self.assertRaisesRegex(Stage2Error, "expected-packet-sha256-required"):
            initialize_run(path, self.fixture.output, self.fixture.root / "checker")
        digest = canonical_hash(self.packet)
        manifest = initialize_run(
            path, self.fixture.output, self.fixture.root / "checker", digest
        )
        self.assertEqual(manifest["packet_sha256"], digest)
        self.assertEqual(len(manifest["stage_run"]["input_refs"]), 2)
        inspect_run(self.fixture.root / "checker")

    def test_exploratory_workflow_rejects_rehashed_upstream_change(self):
        path = self._write()
        run = self.fixture.root / "workflow"
        initialize_workflow(
            path,
            self.fixture.output,
            run,
            {"model": "synthetic"},
            {"kind": "synthetic-policy"},
            expected_packet_sha256=canonical_hash(self.packet),
        )
        state = inspect_workflow(run)
        self.packet["upstream"]["acceptance"]["accepted_by"] = "Other actor"
        self.packet["upstream"]["acceptance_sha256"] = canonical_hash(
            self.packet["upstream"]["acceptance"]
        )
        self._rehash()
        path = self._write()
        with self.assertRaisesRegex(Stage2Error, "upstream-stage1-binding-rewritten"):
            add_snapshot(
                run,
                path,
                self.fixture.output,
                reason="Must not replace acceptance",
                impact={
                    "affected_candidate_ids": [],
                    "impact_unknown_candidate_ids": [],
                },
                expected_head=state["head_sha256"],
            )
