import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_core.assessment import validate_assessment


class CoreAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        texts = {
            "new": "A new method connects population projections with household agent decisions.",
            "old": "An old, frequently cited paper studies unrelated astronomy.",
            "review-a": "A later review identifies the new method as a widely adopted foundation.",
            "review-b": "A separate survey documents independent uptake of the new method.",
        }
        sources, evidence = [], []
        for key, value in texts.items():
            path = self.root / f"{key}.txt"
            path.write_text(value, encoding="utf-8")
            sources.append(
                {
                    "source_id": key,
                    "work_id": key,
                    "version_id": "v1",
                    "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_type": "recognition"
                    if key.startswith("review")
                    else "abstract",
                }
            )
            evidence.append(
                {
                    "evidence_id": key,
                    "source_id": key,
                    "locator": "abstract",
                    "quote": value,
                }
            )
        self.record = {
            "kind": "Stage1CoreAssessment",
            "schema_version": "1.0.0",
            "topic_id": "aging-agent-topic",
            "requirements": ["need-method"],
            "sources": sources,
            "evidence": evidence,
            "works": [
                {
                    "work_id": "new",
                    "version_id": "v1",
                    "requirement_ids": ["need-method"],
                    "roles": ["method-or-resource", "closest-work"],
                    "selection_tier": "topic-core",
                    "historical_status": "not-assessed",
                    "closest_status": "closest-supported",
                    "contribution": "Maps demographic projections to household decisions.",
                    "decision_relevance": "Changes the proposed simulation interface.",
                    "omission_consequence": "The project could duplicate this method.",
                    "alternatives_considered": ["old"],
                    "evidence_ids": ["new"],
                    "recognition_evidence_ids": [],
                    "similarity_dimensions": {
                        "question": "same research question",
                        "system": "same household system",
                        "method": "related agent mapping",
                        "outcome": "consumption outcome",
                    },
                    "limitations": ["Only the abstract is available."],
                },
                {
                    "work_id": "old",
                    "version_id": "v1",
                    "requirement_ids": [],
                    "roles": [],
                    "selection_tier": "supporting",
                    "historical_status": "not-assessed",
                    "closest_status": "not-assessed",
                    "contribution": "",
                    "decision_relevance": "",
                    "omission_consequence": "",
                    "alternatives_considered": [],
                    "evidence_ids": ["old"],
                    "recognition_evidence_ids": [],
                    "similarity_dimensions": {},
                    "limitations": [],
                },
            ],
        }

    def test_recent_direct_work_can_be_topic_core_and_closest_without_classic(self):
        self.assertEqual(validate_assessment(self.record, self.root), [])

    def test_old_unrelated_work_does_not_become_core_by_age(self):
        old = self.record["works"][1]
        old["selection_tier"] = "topic-core"
        self.assertTrue(
            any(
                "topic-core" in error
                for error in validate_assessment(self.record, self.root)
            )
        )

    def test_classic_needs_two_independent_recognition_sources(self):
        work = self.record["works"][0]
        work["historical_status"] = "classic-supported"
        work["recognition_evidence_ids"] = ["review-a"]
        self.assertTrue(
            any(
                "two independent" in error
                for error in validate_assessment(self.record, self.root)
            )
        )
        work["recognition_evidence_ids"] = ["review-a", "review-b"]
        self.assertEqual(validate_assessment(self.record, self.root), [])

    def test_swapped_version_and_fake_quote_fail(self):
        wrong = copy.deepcopy(self.record)
        wrong["works"][0]["version_id"] = "v2"
        self.assertTrue(
            any(
                "same-version" in error
                for error in validate_assessment(wrong, self.root)
            )
        )
        wrong = copy.deepcopy(self.record)
        wrong["evidence"][0]["quote"] = "fabricated passage"
        self.assertTrue(
            any(
                "quote absent" in error
                for error in validate_assessment(wrong, self.root)
            )
        )

    def test_changed_source_bytes_fail(self):
        (self.root / "new.txt").write_text("different content", encoding="utf-8")
        self.assertTrue(
            any(
                "source bytes changed" in error
                for error in validate_assessment(self.record, self.root)
            )
        )


if __name__ == "__main__":
    unittest.main()
