"""Test externally pinned evidence attachment without admission or execution."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from test_research_workspace_body_review import fixture, seal
from research_workspace.body_completeness import assess_body_completeness
from research_workspace.body_review import verify_body_review
from research_workspace.literature_selection import _binding
from research_workspace.body_review_attachment import (
    attach_body_reviews,
    body_review_key,
    validate_body_reviews,
)
from stage1_deliverable.common import DeliverableError, canonical, sha


def bundle():
    row, artifacts, manifest, acceptance = fixture()
    expected = seal(row, artifacts, manifest, acceptance)
    evidence = verify_body_review(row, artifacts, expected)
    row["body_review_result_path"] = "evidence/result.json"
    artifacts[row["body_review_result_path"]] = canonical(evidence)
    hashes = {
        name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in artifacts.items()
    }
    return row, artifacts, hashes, expected


class BodyReviewAttachmentTests(unittest.TestCase):
    def test_cache_preserves_original_rows_and_pending_automatic_gate(self):
        row, artifacts, hashes, expected = bundle()
        before = deepcopy(row)
        cache = attach_body_reviews([row], artifacts, hashes, [expected])
        self.assertEqual(row, before)
        extension = {
            "data": {"rows": [row]},
            "artifact_hashes": hashes,
            "body_reviews": cache,
        }
        self.assertEqual(validate_body_reviews(extension), cache)
        self.assertEqual(
            cache[body_review_key(row)]["evidence"]["status"], "verified-body-text"
        )
        self.assertNotEqual(assess_body_completeness(row)["status"], "confirmed")

    def test_no_review_keeps_legacy_extension_and_unused_hash_rejects(self):
        self.assertEqual(
            attach_body_reviews([{"source_id": "legacy"}], {}, {}, None), {}
        )
        validate_body_reviews(
            {"data": {"rows": [{"source_id": "legacy"}]}, "artifact_hashes": {}}
        )
        with self.assertRaisesRegex(DeliverableError, "unused external"):
            attach_body_reviews([], {}, {}, ["0" * 64])

    def test_explicit_acceptance_and_exact_result_artifact_are_required(self):
        for change in (
            "absent-acceptance",
            "missing-result",
            "modified-result",
            "wrong-result-hash",
        ):
            row, artifacts, hashes, expected = bundle()
            pins = [] if change == "absent-acceptance" else [expected]
            name = row["body_review_result_path"]
            if change == "missing-result":
                del artifacts[name]
            elif change == "modified-result":
                artifacts[name] += b"changed"
            elif change == "wrong-result-hash":
                hashes[name]["sha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(DeliverableError):
                attach_body_reviews([row], artifacts, hashes, pins)

    def test_cache_result_source_membership_and_artifact_tampering_reject(self):
        for change in ("result", "reading", "membership", "artifact"):
            row, artifacts, hashes, expected = bundle()
            cache = attach_body_reviews([row], artifacts, hashes, [expected])
            extension = {
                "data": {"rows": [row]},
                "artifact_hashes": hashes,
                "body_reviews": cache,
            }
            if change == "result":
                cache[body_review_key(row)]["evidence"][
                    "official_stage2_import_eligible"
                ] = True
            elif change == "reading":
                row["reading"]["identity_status"] = "consistent"
            elif change == "membership":
                extension["body_reviews"] = {}
            else:
                hashes[row["raw_path"]]["sha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(DeliverableError):
                validate_body_reviews(extension)

    def test_shared_source_id_keeps_two_version_reviews_and_validates_both(self):
        row, artifacts, hashes, expected = bundle()
        rows = [deepcopy(row), deepcopy(row)]
        evidence = []
        for position, value in enumerate(rows):
            value["version_id"] = "synthetic-v" + str(position)
            value["original_attempts"] = [{"sequence": 1, "response_truncated": False}]
            value["selected_sequence"] = 1
            value["body_review_result_path"] = (
                "evidence/result" + str(position) + ".json"
            )
            proof = verify_body_review(row, artifacts, expected)
            proof["binding"]["version_id"] = value["version_id"]
            raw = canonical(proof)
            artifacts[value["body_review_result_path"]] = raw
            hashes[value["body_review_result_path"]] = {
                "sha256": sha(raw),
                "bytes": len(raw),
            }
            evidence.append(proof)
        # Isolate cache identity from the separately tested bundle verifier.
        with patch(
            "research_workspace.body_review_attachment.verify_body_review",
            side_effect=evidence,
        ):
            cache = attach_body_reviews(rows, artifacts, hashes, [expected])
        self.assertEqual(len(cache), 2)
        validate_body_reviews(
            {"data": {"rows": rows}, "artifact_hashes": hashes, "body_reviews": cache}
        )
        self.assertEqual(
            [
                cache[body_review_key(value)]["evidence"]["binding"]["version_id"]
                for value in rows
            ],
            ["synthetic-v0", "synthetic-v1"],
        )
        self.assertEqual(
            [
                _binding(value, hashes, cache)["independent_body_review"]["binding"][
                    "version_id"
                ]
                for value in rows
            ],
            ["synthetic-v0", "synthetic-v1"],
        )


if __name__ == "__main__":
    unittest.main()
