"""Extraction conversion preserves earlier records without granting approval."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_common import Stage2Error
from stage2_fixture_helpers import write_stage2_fixture
from stage2_ideation import build_extraction_task
from stage2_ideation.integration import build_next_packet


class Stage2IdeationIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet = write_stage2_fixture(self.root, candidate_count=1)
        self.raw = "A simple new design could expose a measurement error."
        self.snapshot = "a" * 64
        task = build_extraction_task(self.raw, self.packet, self.snapshot)
        self.extraction = {
            "kind": "Stage2IdeationExtraction",
            "schema_version": "1.0.0",
            "snapshot_sha256": self.snapshot,
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
            "candidates": [],
            "unresolved": ["Check if the necessary variables share identifiers."],
        }

    def candidate_row(self):
        candidate = copy.deepcopy(self.packet["candidates"][0])
        candidate["candidate_id"] = "new-idea"
        return {
            "candidate": candidate,
            "route": "new-concept",
            "mechanism": "Expose measurement disagreement.",
            "closest_work_refs": [],
            "strong_alternatives": ["An existing direct measure could suffice."],
            "change_mind_conditions": ["A direct measure is already accurate."],
            "claim_labels": [
                {"text": self.raw, "status": "untested-benefit", "evidence_ids": []}
            ],
            "spans": [{"start": 0, "end": len(self.raw), "quote": self.raw}],
        }

    def convert(self, *, update_mode="append"):
        return build_next_packet(
            self.packet,
            self.root,
            self.raw,
            self.extraction,
            self.snapshot,
            update_mode=update_mode,
        )

    def test_empty_result_preserves_all_candidates_and_unknowns(self):
        original = copy.deepcopy(self.packet)
        result = self.convert()
        self.assertEqual(self.packet, original)
        self.assertEqual(result["packet"]["candidates"], original["candidates"])
        self.assertTrue(
            set(original["unresolved"]) <= set(result["packet"]["unresolved"])
        )
        self.assertTrue(result["review_required"])
        self.assertFalse(result["native_execution_verified"])

    def test_new_idea_retains_prior_evidence_and_does_not_create_assessment(self):
        self.extraction["candidates"] = [self.candidate_row()]
        result = self.convert()
        self.assertEqual(len(result["packet"]["candidates"]), 2)
        self.assertEqual(result["packet"]["sources"], self.packet["sources"])
        self.assertEqual(result["packet"]["evidence"], self.packet["evidence"])
        self.assertNotIn("assessments", result["packet"])
        self.assertFalse(result["scientific_quality_verified"])

    def test_rewritten_history_and_missing_source_are_rejected(self):
        row = self.candidate_row()
        row["candidate"]["candidate_id"] = self.packet["candidates"][0]["candidate_id"]
        row["candidate"]["question"] = "A replacement with the same version."
        self.extraction["candidates"] = [row]
        with self.assertRaises((Stage2Error, ValueError)):
            self.convert()
        self.extraction["candidates"] = []
        (self.root / self.packet["sources"][0]["path"]).write_text(
            "tampered", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "hash mismatch"):
            self.convert()

    def test_content_revision_replaces_current_text_and_preserves_history(self):
        previous = copy.deepcopy(self.packet["candidates"][0])
        revised = copy.deepcopy(previous)
        revised.update(
            version=previous["version"] + 1,
            parent_version=previous["version"],
            question="A corrected source-bound question.",
        )
        row = self.candidate_row()
        row["candidate"] = revised
        row["route"] = "improvement"
        self.extraction["candidates"] = [row]
        self.extraction["comparison_rows"] = [
            {
                "dimension": "corrected population",
                "finding": "The current comparison now states the supported population.",
                "comparability": "partly-comparable",
                "noncomparability": "The admitted studies use different populations.",
                "source_roles": [],
                "shared_relationships": [],
                "evidence_ids": [self.packet["evidence"][0]["evidence_id"]],
                "spans": [{"start": 0, "end": len(self.raw), "quote": self.raw}],
            }
        ]
        self.extraction["unresolved"] = ["Current artifact access remains unknown."]
        result = self.convert(update_mode="replace-comparison-unresolved")
        current = result["packet"]
        self.assertEqual(current["candidates"][:-1], self.packet["candidates"])
        self.assertEqual(current["candidates"][-1], revised)
        self.assertNotIn(self.packet["comparison"], current["comparison"])
        self.assertIn("corrected population", current["comparison"])
        self.assertEqual(current["unresolved"], self.extraction["unresolved"])
        self.assertEqual(result["affected_candidate_ids"], [previous["candidate_id"]])

    def test_content_revision_accepts_candidate_only_and_rejects_version_only(self):
        self.extraction["unresolved"] = copy.deepcopy(self.packet["unresolved"])
        previous = copy.deepcopy(self.packet["candidates"][0])
        revised = copy.deepcopy(previous)
        revised.update(
            version=previous["version"] + 1,
            parent_version=previous["version"],
            question="A substantive candidate-only correction.",
        )
        row = self.candidate_row()
        row["candidate"] = revised
        self.extraction["candidates"] = [row]
        result = self.convert(update_mode="replace-comparison-unresolved")
        self.assertEqual(result["packet"]["comparison"], self.packet["comparison"])
        self.assertEqual(result["packet"]["candidates"][-1], revised)

        row["candidate"] = copy.deepcopy(previous)
        row["candidate"].update(
            version=previous["version"] + 1,
            parent_version=previous["version"],
        )
        with self.assertRaisesRegex(Stage2Error, "invalid-candidate"):
            self.convert(update_mode="replace-comparison-unresolved")

    def test_content_revision_accepts_comparison_only_and_rejects_foreign_candidate(
        self,
    ):
        self.extraction["comparison_rows"] = [
            {
                "dimension": "correction",
                "finding": "A correction is proposed.",
                "comparability": "unknown",
                "noncomparability": None,
                "source_roles": [],
                "shared_relationships": [],
                "evidence_ids": [],
                "spans": [{"start": 0, "end": len(self.raw), "quote": self.raw}],
            }
        ]
        result = self.convert(update_mode="replace-comparison-unresolved")
        self.assertIn("A correction is proposed.", result["packet"]["comparison"])
        row = self.candidate_row()
        self.extraction["candidates"] = [row]
        with self.assertRaisesRegex(Stage2Error, "invalid-candidate"):
            self.convert(update_mode="replace-comparison-unresolved")

    def test_content_revision_accepts_unresolved_only_and_rejects_true_noop(self):
        result = self.convert(update_mode="replace-comparison-unresolved")
        self.assertEqual(result["packet"]["comparison"], self.packet["comparison"])
        self.assertEqual(result["packet"]["unresolved"], self.extraction["unresolved"])
        self.extraction["unresolved"] = copy.deepcopy(self.packet["unresolved"])
        with self.assertRaisesRegex(Stage2Error, "no-substantive-change"):
            self.convert(update_mode="replace-comparison-unresolved")


if __name__ == "__main__":
    unittest.main()
