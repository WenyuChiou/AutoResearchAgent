"""Contract tests for source-bound Stage 2 research tables."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_ideation.extraction import IdeationError, validate_extraction  # noqa: E402
from stage2_ideation.prompts import build_extraction_task  # noqa: E402
from stage2_ideation.integration import build_next_packet  # noqa: E402
from stage2_ideation.topic_tables import (  # noqa: E402
    TopicTableError,
    materialize_research_tables,
    validate_research_tables,
)


SNAPSHOT = "a" * 64
RAW = "\n".join(
    [
        "The brief needs comparable measurement and access conditions.",
        "Work one reports the feature and describes monthly measurement.",
        "Work two explicitly says the feature is absent after full design inspection.",
        "The dataset is available under a named license for the candidate.",
    ]
)


def span(quote):
    start = RAW.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote}


def packet():
    with tempfile.TemporaryDirectory() as root:
        value = write_stage2_fixture(Path(root), candidate_count=0)
    value["schema_version"] = "2.2.0"
    value["research_tables"] = None
    value["literature"] = [
        {"work_id": "work-1", "version_id": "v1", "source_ids": ["src-1"]},
        {"work_id": "work-2", "version_id": "v1", "source_ids": ["src-2"]},
    ]
    return value


def candidate():
    return {
        "candidate_id": "candidate-table",
        "version": 1,
        "parent_version": None,
        "question": "Can the bounded comparison improve measurement?",
        "research_mode": "method-development",
        "opportunity": "The comparison identifies a measurement issue.",
        "value": "The result could improve the bounded decision.",
        "approach": "Compare both recorded observations.",
        "requirements": ["Use supplied sources"],
        "limitations": ["External validity is unknown"],
        "evidence_ids": ["ev-1"],
    }


def extracted_candidate():
    return {
        "candidate": candidate(),
        "route": "improvement",
        "mechanism": "Align the measurement conditions.",
        "closest_work_refs": [],
        "strong_alternatives": ["Retain the existing measure"],
        "change_mind_conditions": ["Alignment worsens held-out error"],
        "claim_labels": [
            {
                "text": "Benefit remains untested",
                "status": "untested-benefit",
                "evidence_ids": [],
            }
        ],
        "spans": [
            span("The brief needs comparable measurement and access conditions.")
        ],
    }


def extracted_tables():
    need = "The brief needs comparable measurement and access conditions."
    work_one = "Work one reports the feature and describes monthly measurement."
    work_two = (
        "Work two explicitly says the feature is absent after full design inspection."
    )
    resource = "The dataset is available under a named license for the candidate."
    return {
        "dimensions": [
            {
                "dimension_id": "feature-use",
                "label": "Uses the target feature",
                "research_need": "Compare whether each design uses the target feature.",
                "rationale": "Feature use changes interpretation of the brief.",
                "definition": "Affirmative use or affirmative bounded absence.",
                "value_kind": "feature",
                "conditions": ["Inspect the recorded design"],
                "spans": [span(need)],
            },
            {
                "dimension_id": "measurement",
                "label": "Measurement interval",
                "research_need": "Compare the interval used by each work.",
                "rationale": "Intervals determine whether results are comparable.",
                "definition": "The interval explicitly described by the source.",
                "value_kind": "text",
                "conditions": ["Preserve unknown when not described"],
                "spans": [span(need)],
            },
        ],
        "work_refs": [
            {"work_id": "work-1", "version_id": "v1"},
            {"work_id": "work-2", "version_id": "v1"},
        ],
        "cells": [
            {
                "dimension_id": "feature-use",
                "work_id": "work-1",
                "version_id": "v1",
                "status": "present",
                "value": True,
                "reason": "The source reports use.",
                "inspection_scope": "Recorded method statement",
                "negative_basis": None,
                "evidence_ids": ["ev-1"],
                "spans": [span(work_one)],
            },
            {
                "dimension_id": "feature-use",
                "work_id": "work-2",
                "version_id": "v1",
                "status": "absent",
                "value": False,
                "reason": "The source explicitly records absence.",
                "inspection_scope": "Full design description",
                "negative_basis": "bounded-design-inspection",
                "evidence_ids": ["ev-2"],
                "spans": [span(work_two)],
            },
            {
                "dimension_id": "measurement",
                "work_id": "work-1",
                "version_id": "v1",
                "status": "described",
                "value": "monthly",
                "reason": "The interval is described.",
                "inspection_scope": "Recorded measurement statement",
                "negative_basis": None,
                "evidence_ids": ["ev-1"],
                "spans": [span(work_one)],
            },
            {
                "dimension_id": "measurement",
                "work_id": "work-2",
                "version_id": "v1",
                "status": "unknown",
                "value": None,
                "reason": "No interval was inspected.",
                "inspection_scope": None,
                "negative_basis": None,
                "evidence_ids": [],
                "spans": [span(work_two)],
            },
        ],
        "direction_resources": [
            {
                "resource_id": "resource-data",
                "candidate_index": 0,
                "category": "dataset",
                "name": "Bounded dataset",
                "purpose": "Measure the proposed outcome.",
                "url": None,
                "version": "v1",
                "required": True,
                "status": "available",
                "access_conditions": "Public download",
                "license": "Named synthetic license",
                "cost_basis": None,
                "limitations": ["Synthetic only"],
                "alternatives": ["Collect a replacement sample"],
                "evidence_ids": ["ev-1"],
                "checked_at": "2026-10-06T20:00:00Z",
                "spans": [span(resource)],
            }
        ],
    }


def extraction(value):
    source_packet = packet()
    task = build_extraction_task(RAW, source_packet, SNAPSHOT)
    return source_packet, {
        "kind": "Stage2IdeationExtraction",
        "schema_version": "1.1.0",
        "snapshot_sha256": SNAPSHOT,
        "packet_sha256": task["packet_sha256"],
        "raw_proposal_sha256": task["raw_proposal_sha256"],
        "input_hash": task["input_hash"],
        "receipt": {
            "policy_boundary": "declared-task-policy",
            "tools_policy": "none",
            "tool_calls": [],
            "isolation_verified": False,
        },
        "bibliography": [],
        "comparison_rows": [],
        "candidates": [extracted_candidate()],
        "unresolved": ["Measurement interval for work two remains unknown."],
        "research_tables": value,
    }


class Stage2TopicTableTests(unittest.TestCase):
    def materialized(self):
        source_packet = packet()
        return source_packet, materialize_research_tables(
            extracted_tables(), [extracted_candidate()], source_packet, RAW, SNAPSHOT
        )

    def assert_rejected(self, mutate):
        source_packet, tables = self.materialized()
        mutate(tables, source_packet)
        with self.assertRaises(TopicTableError):
            validate_research_tables(tables, source_packet)

    def test_positive_complete_grid_and_candidate_version_binding(self):
        source_packet, tables = self.materialized()
        augmented = copy.deepcopy(source_packet)
        augmented["candidates"].append(candidate())
        self.assertEqual(validate_research_tables(tables, augmented), tables)
        self.assertEqual(
            tables["direction_resources"][0]["candidate_id"], "candidate-table"
        )
        self.assertEqual(tables["input_packet_sha256"], canonical_hash(source_packet))

    def test_extraction_1_1_is_only_selected_for_packet_2_2(self):
        source_packet, value = extraction(extracted_tables())
        self.assertEqual(
            build_extraction_task(RAW, source_packet, SNAPSHOT)["schema_version"],
            "1.1.0",
        )
        validate_extraction(RAW, value, source_packet, SNAPSHOT)

        legacy = copy.deepcopy(source_packet)
        legacy["schema_version"] = "1.0.0"
        legacy.pop("research_tables")
        self.assertEqual(
            build_extraction_task(RAW, legacy, SNAPSHOT)["schema_version"], "1.0.0"
        )
        with self.assertRaises(IdeationError):
            validate_extraction(RAW, value, legacy, SNAPSHOT)

    def test_integration_preserves_input_and_host_materializes_tables(self):
        source_packet, value = extraction(extracted_tables())
        before = copy.deepcopy(source_packet)
        with patch("stage2_ideation.integration.validate_packet"):
            result = build_next_packet(
                source_packet, Path("unused"), RAW, value, SNAPSHOT
            )

        self.assertEqual(source_packet, before)
        self.assertEqual(result["packet"]["evidence"], before["evidence"])
        self.assertEqual(result["packet"]["sources"], before["sources"])
        self.assertEqual(result["packet"]["candidates"], [candidate()])
        tables = result["packet"]["research_tables"]
        self.assertEqual(tables["raw_proposal"], RAW)
        self.assertEqual(tables["input_packet_sha256"], canonical_hash(before))
        self.assertEqual(tables["input_snapshot_sha256"], SNAPSHOT)

    def test_rejects_incomplete_or_duplicate_grid(self):
        self.assert_rejected(lambda tables, packet: tables["cells"].pop())
        self.assert_rejected(
            lambda tables, packet: tables["cells"].append(
                copy.deepcopy(tables["cells"][0])
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["work_refs"].append(
                copy.deepcopy(tables["work_refs"][0])
            )
        )

    def test_rejects_work_version_and_source_binding_errors(self):
        self.assert_rejected(
            lambda tables, packet: tables["work_refs"][0].update(version_id="v2")
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(evidence_ids=["ev-2"])
        )
        self.assert_rejected(
            lambda tables, packet: packet["evidence"][0].update(
                source_id="missing-source"
            )
        )

    def test_rejects_sibling_source_from_same_work_version(self):
        def add_sibling(tables, packet):
            sibling = copy.deepcopy(packet["sources"][0])
            sibling["source_id"] = "src-1-sibling"
            packet["sources"].append(sibling)
            sibling_evidence = copy.deepcopy(packet["evidence"][0])
            sibling_evidence.update(
                evidence_id="ev-1-sibling", source_id="src-1-sibling"
            )
            packet["evidence"].append(sibling_evidence)
            tables["cells"][0]["evidence_ids"] = ["ev-1-sibling"]

        self.assert_rejected(add_sibling)

    def test_missing_or_metadata_evidence_cannot_become_absence(self):
        self.assert_rejected(
            lambda tables, packet: tables["cells"][1].update(evidence_ids=[])
        )
        self.assert_rejected(
            lambda tables, packet: packet["sources"][1].update(
                evidence_level="metadata"
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][1].update(inspection_scope=None)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][1].update(negative_basis=None)
        )

    def test_bounded_design_absence_requires_full_text(self):
        self.assert_rejected(
            lambda tables, packet: packet["sources"][1].update(
                evidence_level="abstract"
            )
        )

    def test_unknown_remains_null_and_has_no_negative_basis(self):
        self.assert_rejected(
            lambda tables, packet: tables["cells"][3].update(
                value="missing description"
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][3].update(
                negative_basis="explicit-statement"
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][3].update(reason=None)
        )

    def test_metadata_partial_reports_exact_cell_without_upgrading_evidence(self):
        source_packet, tables = self.materialized()
        source_packet["sources"][0]["evidence_level"] = "metadata"
        cell = tables["cells"][0]
        cell.update(status="partial", value=None)
        before = copy.deepcopy((source_packet, tables))
        with self.assertRaises(TopicTableError) as caught:
            validate_research_tables(tables, source_packet)
        for expected in (
            "known cell status requires non-metadata evidence",
            f"dimension={cell['dimension_id']}",
            "work=work-1",
            "version=v1",
            "evidence=ev-1",
            "source=src-1",
            "status=partial",
            "use unknown with null value",
        ):
            self.assertIn(expected, str(caught.exception))
        self.assertEqual((source_packet, tables), before)

    def test_metadata_unknown_is_valid_without_claiming_partial_coverage(self):
        source_packet, tables = self.materialized()
        source_packet["candidates"].append(candidate())
        source_packet["sources"][1]["evidence_level"] = "metadata"
        cell = tables["cells"][1]
        cell.update(
            status="unknown",
            value=None,
            negative_basis=None,
            inspection_scope=None,
            reason="Title alone does not establish the mechanism; inspect the method.",
        )
        self.assertEqual(validate_research_tables(tables, source_packet), tables)

    def test_known_cells_require_reason_scope_and_described_value(self):
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(reason=None)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(inspection_scope=None)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][2].update(value=None)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(
                negative_basis="explicit-statement"
            )
        )

    def test_statuses_follow_dimension_value_kind(self):
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(status="described")
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][2].update(status="present")
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0].update(value=False)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][1].update(value=True)
        )
        self.assert_rejected(lambda tables, packet: tables["cells"][2].update(value=12))

    def test_resource_access_and_candidate_index_fail_closed(self):
        self.assert_rejected(
            lambda tables, packet: tables["direction_resources"][0].update(
                evidence_ids=[]
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["direction_resources"][0].update(
                checked_at=None
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["direction_resources"][0].update(
                checked_at="2026-10-06"
            )
        )
        self.assert_rejected(
            lambda tables, packet: packet["sources"][0].update(
                evidence_level="metadata"
            )
        )
        self.assert_rejected(
            lambda tables, packet: tables["direction_resources"][0].update(
                candidate_version=True
            )
        )
        source_packet = packet()
        invalid = extracted_tables()
        invalid["direction_resources"][0]["candidate_index"] = 1
        with self.assertRaises(TopicTableError):
            materialize_research_tables(
                invalid, [extracted_candidate()], source_packet, RAW, SNAPSHOT
            )

    def test_hash_span_and_candidate_version_are_bound(self):
        self.assert_rejected(
            lambda tables, packet: tables.update(raw_proposal_sha256="b" * 64)
        )
        self.assert_rejected(
            lambda tables, packet: tables["cells"][0]["spans"][0].update(quote="forged")
        )
        self.assert_rejected(
            lambda tables, packet: tables["direction_resources"][0].update(
                candidate_version=2
            )
        )


if __name__ == "__main__":
    unittest.main()
