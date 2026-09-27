import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage1_eval.audit_source_evidence import (
    materialize_audit_sources,
    verify_audit_materialization,
)  # noqa: E402
from stage1_eval.common import EvaluationError, canonical, sha  # noqa: E402
from stage1_eval.extraction_v31 import work_id_for  # noqa: E402
from stage1_eval.judging import make_packet  # noqa: E402
from stage1_eval.spans import index_evidence  # noqa: E402


class AuditSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        work = {"title": "A synthetic study", "identifier": "10.1000/example"}
        work["work_id"] = work_id_for(work)
        self.tail = "\r\n末尾反证：the contrary result is here."
        self.record = {
            "source_id": "source",
            "subject_work_id": work["work_id"],
            "work_key": "doi:10.1000/example",
            "version_id": "metadata-v1",
            "title": work["title"],
            "doi": work["identifier"],
            "authors": ["Synthetic Author"],
            "year": 2025,
            "url": "https://example.org/article",
            "abstract": "Ordinary context. " * 200 + self.tail,
            "source_level": "abstract",
            "date_status": "within-year-cutoff",
            "receipt_id": "synthetic",
            "raw_sha256": "a" * 64,
        }
        subject = {
            "status": "complete",
            "evidence": {
                "answer": {
                    "text": "Synthetic answer.",
                    "sha256": sha(b"Synthetic answer."),
                    "origin": "subject-answer",
                }
            },
        }
        extraction = {
            "works": [work],
            "central_claims": [],
            "extraction_complete": True,
            "unextracted_reason": None,
        }
        self.packet = make_packet(
            "Synthetic diagnostic.",
            {"draft": {"needs": [], "roles": []}},
            subject,
            extraction,
            None,
            {"sources": [self.record], "receipts": []},
            mode="packet-only",
        )

    def test_all_abstract_bytes_and_contrary_tail_retained_with_metadata_separate(self):
        before = canonical(self.packet)
        self.assertNotIn(self.tail, self.packet["content_evidence"]["source"]["text"])
        result, receipt = materialize_audit_sources(self.packet, [self.record])
        self.assertEqual(canonical(self.packet), before)
        abstract = result["content_evidence"]["source"]
        self.assertEqual(abstract["text"], self.record["abstract"])
        self.assertEqual(
            abstract["sha256"], sha(self.record["abstract"].encode("utf-8"))
        )
        self.assertEqual(abstract["source_version"], "metadata-v1")
        self.assertEqual(
            result["sources"]["source:identity"]["source_level"], "metadata"
        )
        spans = index_evidence({"source": abstract})
        self.assertEqual(
            "".join(row["text"] for row in spans.values()), self.record["abstract"]
        )
        self.assertFalse(receipt["semantic_audit_completed"])
        self.assertTrue(
            verify_audit_materialization(self.packet, [self.record], result, receipt)
        )

    def test_changed_work_version_or_metadata_record_fails_closed(self):
        for key, value in (
            ("subject_work_id", "other-work"),
            ("version_id", "other-version"),
            ("title", "Other study"),
            ("year", 2025.0),
        ):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(EvaluationError, "metadata or version differs"),
            ):
                materialize_audit_sources(self.packet, [{**self.record, key: value}])
        with self.assertRaisesRegex(EvaluationError, "conflicting"):
            materialize_audit_sources(
                self.packet, [self.record, {**self.record, "abstract": "different"}]
            )

    def test_rehash_tamper_rejected_by_reconstruction(self):
        result, receipt = materialize_audit_sources(self.packet, [self.record])
        result["content_evidence"]["source"]["text"] = "Invented replacement."
        result["content_evidence"]["source"]["sha256"] = sha(b"Invented replacement.")
        receipt["materialized_packet_sha256"] = sha(canonical(result))
        with self.assertRaisesRegex(EvaluationError, "failed reconstruction"):
            verify_audit_materialization(self.packet, [self.record], result, receipt)

    def test_missing_catalogue_collision_and_unknown_contract_fail(self):
        with self.assertRaisesRegex(
            EvaluationError, "complete source record is missing"
        ):
            materialize_audit_sources(self.packet, [])
        packet = deepcopy(self.packet)
        packet["content_evidence"]["source:identity"] = {"text": "existing"}
        with self.assertRaisesRegex(EvaluationError, "ID collision"):
            materialize_audit_sources(packet, [self.record])
        result, receipt = materialize_audit_sources(self.packet, [self.record])
        receipt["kind"] = "unknown"
        with self.assertRaises(EvaluationError):
            verify_audit_materialization(self.packet, [self.record], result, receipt)

    def test_occurrences_and_cutoff_exclusions_are_explicit(self):
        excluded = {**self.record, "source_id": "after", "date_status": "after-cutoff"}
        _, receipt = materialize_audit_sources(
            self.packet, [self.record, self.record, excluded]
        )
        self.assertEqual(
            receipt["derivations"][0]["catalogue_occurrence_indices"], [0, 1]
        )
        self.assertEqual(receipt["exclusions"][0]["reason"], "after-cutoff")

    def test_metadata_stays_metadata_and_missing_version_is_rejected(self):
        record = {**self.record, "source_level": "metadata"}
        packet = deepcopy(self.packet)
        packet["sources"]["source"]["source_level"] = "metadata"
        result, _ = materialize_audit_sources(packet, [record])
        self.assertEqual(
            result["content_evidence"]["source"]["source_level"], "metadata"
        )
        self.assertNotIn("source:identity", result["sources"])
        for version in (None, ""):
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(EvaluationError, "source version is missing"),
            ):
                record = {**self.record, "version_id": version}
                packet = deepcopy(self.packet)
                packet["sources"]["source"]["version_id"] = version
                materialize_audit_sources(packet, [record])


if __name__ == "__main__":
    unittest.main()
