"""Captured sources extend history without carrying forward old verification."""

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_live.source_updates import prepare_source_update
from stage2_fixture_helpers import write_stage2_fixture


class SourceUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packet = write_stage2_fixture(self.root / "old")
        self.original = copy.deepcopy(self.packet)
        raw = (
            b"The public dictionary measures annual totals, not monthly consumption.\n"
        )
        self.raw_path = self.root / "download.txt"
        self.raw_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        self.addition = {
            "source": {
                "source_id": "src-new",
                "work_id": "work-new",
                "version_id": "v2",
                "path": "new/dictionary.txt",
                "sha256": digest,
                "evidence_level": "full-text",
            },
            "evidence": [
                {
                    "evidence_id": "ev-new",
                    "source_id": "src-new",
                    "work_id": "work-new",
                    "version_id": "v2",
                    "locator": "line 1",
                    "quote": raw.decode().strip(),
                }
            ],
            "raw_path": str(self.raw_path),
            "acquisition": {
                "status": "obtained",
                "url": "https://example.org/dictionary",
                "retrieved_at": "2026-10-03T00:00:00Z",
                "raw_sha256": digest,
                "identity_status": "matched",
                "evidence_level": "full-text",
                "reason": "Read the acquired dictionary",
                "action_ref": "native-call-1",
            },
        }
        revised = copy.deepcopy(self.packet["candidates"][0])
        revised.update(version=2, parent_version=1, evidence_ids=["ev-1", "ev-new"])
        revised["question"] = "Can annual totals answer the narrowed question?"
        self.revisions = [revised]
        self.impact = {
            "candidate-1": {
                "status": "affected",
                "reason": "The dictionary changes temporal resolution.",
            },
            "candidate-2": {
                "status": "unknown",
                "reason": "Review influence of new evidence.",
            },
        }

    def build(self, additions=None, **kwargs):
        return prepare_source_update(
            self.packet,
            self.root / "old",
            additions or [self.addition],
            self.revisions,
            self.impact,
            self.root / "output",
            expected_packet_sha256=kwargs.get("expected", canonical_hash(self.packet)),
        )

    def test_new_snapshot_preserves_input_and_requires_rechecks(self):
        result = self.build()
        import json

        revised = json.loads(Path(result["packet_path"]).read_text())
        validate_packet(revised, result["source_root"])
        self.assertEqual(self.packet, self.original)
        self.assertEqual(revised["candidates"][:2], self.original["candidates"])
        self.assertTrue(result["review_required"])
        self.assertFalse(result["prior_reviews_carried_forward"])
        self.assertFalse(result["scientific_quality_verified"])

    def test_failures_are_retained_not_empty_success(self):
        failed = copy.deepcopy(self.addition["acquisition"])
        failed.update(status="rate-limit", raw_sha256=None, evidence_level=None)
        result = self.build([self.addition, {"acquisition": failed}])
        self.assertEqual(result["acquisitions"][1]["status"], "rate-limit")

    def test_parent_binding_and_source_tamper_rejected(self):
        with self.assertRaisesRegex(Stage2Error, "parent-hash"):
            self.build(expected="0" * 64)
        self.raw_path.write_text("Other content")
        with self.assertRaisesRegex(Stage2Error, "raw-hash"):
            self.build()

    def test_failure_cannot_be_promoted_to_evidence(self):
        self.addition["acquisition"]["status"] = "parse-failure"
        with self.assertRaisesRegex(Stage2Error, "failure-cannot"):
            self.build()

    def test_abstract_does_not_become_full_text(self):
        self.addition["acquisition"]["evidence_level"] = "abstract"
        with self.assertRaisesRegex(Stage2Error, "evidence-level"):
            self.build()

    def test_unverified_full_text_identity_blocked(self):
        self.addition["acquisition"]["identity_status"] = "unverified"
        with self.assertRaisesRegex(Stage2Error, "identity-unverified"):
            self.build()

    def test_revised_candidate_must_be_in_impact(self):
        self.impact["candidate-1"]["status"] = "unaffected"
        with self.assertRaisesRegex(Stage2Error, "must-be-affected"):
            self.build()

    def test_path_escape_and_duplicate_cannot_write(self):
        self.addition["source"]["path"] = "../escape.txt"
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "escape.txt").exists())
        self.addition["source"]["path"] = "SOURCE-1.txt"
        with self.assertRaisesRegex(Stage2Error, "duplicate-source-path"):
            self.build()


if __name__ == "__main__":
    unittest.main()
