"""Delivery completeness is separate from scientific validity and selection."""

import copy
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cli"))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_ideation.topic_tables import materialize_research_tables  # noqa: E402
from stage2_workflow.content_gate import derive_content_gate, validate_content_gate  # noqa: E402
from test_stage2_checker import assessment, finding  # noqa: E402
from test_stage2_evaluation_v3 import action_record  # noqa: E402
from test_stage2_topic_tables import (  # noqa: E402
    RAW,
    SNAPSHOT,
    candidate,
    extracted_candidate,
    extracted_tables,
    packet,
)


def selection(disposition="park"):
    p = packet()
    p["candidates"] = [candidate()]
    p["research_tables"] = materialize_research_tables(
        extracted_tables(), [extracted_candidate()], p, RAW, SNAPSHOT
    )
    check = assessment(p, disposition=disposition)
    check["candidate_id"] = "candidate-table"
    value = {
        "kind": "Stage2Selection",
        "schema_version": "1.0.0",
        "status": "prehuman",
        "packet_sha256": canonical_hash(p),
        "evaluation_packet": p,
        "current_options": [{"candidate": p["candidates"][0], "assessment": check}],
        "recommendations": p["candidates"] if disposition == "recommend" else [],
        "unresolved": [
            "No direction is currently ready; check independent targets next."
        ],
        "action_record_status": "complete",
        "action_record": action_record(p),
    }
    refresh_actions(value)
    return value


def refresh_actions(value):
    value["packet_sha256"] = canonical_hash(value["evaluation_packet"])
    for option in value["current_options"]:
        option["assessment"]["packet_sha256"] = value["packet_sha256"]
    record = action_record(value["evaluation_packet"])
    dispositions = {
        row["candidate"]["candidate_id"]: row["assessment"]["disposition"]
        for row in value["current_options"]
    }
    for row in record["history"] + record["latest_dispositions"]:
        row["disposition"] = dispositions[row["candidate_id"]]
    record["selected_candidate_ids"] = [
        row["candidate_id"] for row in value["recommendations"]
    ]
    value["action_record"] = record


class Stage2ContentGateTests(unittest.TestCase):
    def test_complete_parked_package_is_not_authority(self):
        value = selection()
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "content-complete")
        self.assertEqual(gate["blocking_items"], [])
        self.assertFalse(gate["scientific_truth_validated"])
        self.assertFalse(gate["stage3_authorized"])
        self.assertFalse(gate["formal_ready"])
        self.assertEqual(validate_content_gate(gate, value, canonical_hash(gate)), gate)

    def test_missing_matrix_and_legacy_inputs_remain_draft(self):
        for version in ("2.2.0", "2.1.0", "1.0.0"):
            with self.subTest(version=version):
                value = selection()
                value["evaluation_packet"]["schema_version"] = version
                value["evaluation_packet"]["research_tables"] = None
                gate = derive_content_gate(value)
                self.assertEqual(gate["status"], "draft")
                self.assertIn(
                    "topic-matrix", [row["check_id"] for row in gate["blocking_items"]]
                )

    def test_missing_grid_cell_and_foreign_work_fail(self):
        for mutate in (
            lambda table: table["cells"].pop(),
            lambda table: table["cells"][0].update(work_id="foreign"),
        ):
            value = selection()
            mutate(value["evaluation_packet"]["research_tables"])
            with self.assertRaises(Stage2Error):
                derive_content_gate(value)

    def test_unknown_materials_allow_park_but_not_recommend(self):
        value = selection()
        check = value["current_options"][0]["assessment"]
        check["checks"]["materials"] = finding(
            "unknown", None, evidence_ids=[], blocking=True
        )
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")
        check["disposition"] = "recommend"
        value["recommendations"] = value["evaluation_packet"]["candidates"]
        self.assertEqual(derive_content_gate(value)["status"], "draft")

    def test_required_resource_unknown_blocks_recommendation_only(self):
        for disposition, expected in (
            ("park", "content-complete"),
            ("recommend", "draft"),
        ):
            value = selection(disposition)
            resource = value["evaluation_packet"]["research_tables"][
                "direction_resources"
            ][0]
            resource.update(
                status="unknown",
                access_conditions=None,
                license=None,
                checked_at=None,
                evidence_ids=[],
            )
            refresh_actions(value)
            self.assertEqual(derive_content_gate(value)["status"], expected)

    def test_restricted_resource_can_have_checked_conditions(self):
        value = selection("recommend")
        resource = value["evaluation_packet"]["research_tables"]["direction_resources"][
            0
        ]
        resource.update(
            status="restricted",
            access_conditions="Verified academic registration and research-only license",
        )
        refresh_actions(value)
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")

    def test_current_review_required_after_revision(self):
        value = selection()
        value["current_options"][0]["assessment"]["candidate_version"] = 2
        self.assertEqual(derive_content_gate(value)["status"], "draft")
        value["current_options"][0]["assessment"] = None
        self.assertEqual(derive_content_gate(value)["status"], "draft")

    def test_stale_resource_does_not_cover_current_candidate(self):
        value = selection()
        current = value["evaluation_packet"]["candidates"][0]
        revised = copy.deepcopy(current)
        revised.update(version=2, parent_version=1)
        value["evaluation_packet"]["candidates"].append(revised)
        option = value["current_options"][0]
        option["candidate"] = revised
        option["assessment"]["candidate_version"] = 2
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "draft")
        self.assertIn(
            "candidate-table:v2:resources",
            [row["check_id"] for row in gate["blocking_items"]],
        )

    def test_pure_theory_does_not_require_dataset_model_or_tool(self):
        value = selection()
        value["evaluation_packet"]["research_tables"]["direction_resources"] = []
        value["current_options"][0]["assessment"]["checks"]["materials"] = finding(
            "not-applicable", None, evidence_ids=[]
        )
        refresh_actions(value)
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")

    def test_zero_candidates_need_matrix_and_useful_explanation(self):
        value = selection()
        value["evaluation_packet"]["candidates"] = []
        value["evaluation_packet"]["research_tables"]["direction_resources"] = []
        value["current_options"] = []
        value["action_record"] = action_record(value["evaluation_packet"])
        self.assertEqual(derive_content_gate(value)["status"], "content-complete")
        value["unresolved"] = []
        self.assertEqual(derive_content_gate(value)["status"], "draft")

    def test_missing_action_record_and_extra_work_are_pending(self):
        value = selection()
        value["action_record_status"] = "unavailable"
        self.assertEqual(derive_content_gate(value)["status"], "draft")
        value = selection()
        value["evaluation_packet"]["literature"].append(
            {"work_id": "uncompared", "version_id": "v1", "source_ids": []}
        )
        self.assertEqual(derive_content_gate(value)["status"], "draft")

    def test_rehashed_tamper_and_foreign_selection_rejected(self):
        value = selection()
        gate = derive_content_gate(value)
        tampered = copy.deepcopy(gate)
        tampered["scientific_truth_validated"] = True
        with self.assertRaises(Stage2Error):
            validate_content_gate(tampered, value, canonical_hash(tampered))
        other = copy.deepcopy(value)
        other["evaluation_packet"]["comparison"] += " New scientific comparison."
        with self.assertRaises(Stage2Error):
            validate_content_gate(gate, other, canonical_hash(gate))

    def test_foreign_assessment_hash_or_identity_stays_draft(self):
        for field, invalid in (
            ("packet_sha256", "b" * 64),
            ("candidate_id", "other"),
            ("candidate_version", 2),
        ):
            with self.subTest(field=field):
                value = selection()
                value["current_options"][0]["assessment"][field] = invalid
                gate = derive_content_gate(value)
                self.assertEqual(gate["status"], "draft")
                self.assertIn(
                    "candidate-table:v1:review",
                    {row["check_id"] for row in gate["blocking_items"]},
                )

    def test_foreign_action_shortlist_stays_draft(self):
        value = selection()
        value["action_record"]["selected_candidate_ids"] = ["candidate-table"]
        gate = derive_content_gate(value)
        self.assertEqual(gate["status"], "draft")
        self.assertIn(
            "decision-record", {row["check_id"] for row in gate["blocking_items"]}
        )

    def test_malformed_input_raises_controlled_errors(self):
        for bad in (
            None,
            [],
            {},
            {"evaluation_packet": {}},
            {"evaluation_packet": {"candidates": [{}]}},
        ):
            with self.subTest(value=bad), self.assertRaises(Stage2Error):
                derive_content_gate(bad)
        value = selection()
        value["recommendations"] = [{"candidate_id": []}]
        with self.assertRaises(Stage2Error):
            derive_content_gate(value)


if __name__ == "__main__":
    unittest.main()
