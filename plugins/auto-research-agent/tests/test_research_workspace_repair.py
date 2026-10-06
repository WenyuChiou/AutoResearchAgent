"""Synthetic contract tests for accepted private repair overlays."""

from copy import deepcopy
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace.repair import apply_repair  # noqa: E402
from stage1_deliverable.common import (  # noqa: E402
    DeliverableError,
    canonical,
    sha,
    write_json,
)


class RepairProjectionTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(tempfile.gettempdir()).resolve()
        if any(
            (parent / ".git").exists() for parent in (temp_root, *temp_root.parents)
        ):
            temp_root = (
                Path(temp_root.anchor) / "temp"
                if os.name == "nt"
                else Path("/tmp").resolve()
            )
        temp_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="neutral-repair-", dir=temp_root
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repair"
        self.base = Path(self.temporary.name) / "base"
        text_path = self.base / "deliverable/sources/src-neutral/extracted/source.txt"
        text_path.parent.mkdir(parents=True)
        self.text = "Neutral source text contains an exact supported quotation."
        text_path.write_text(self.text, encoding="utf-8")
        (self.base / "package_manifest.json").write_bytes(b"neutral base manifest\n")
        self.index = {
            "kind": "WorkspaceIndex",
            "schema_version": "1.0.0",
            "papers": [{"work_id": "neutral-work", "version_id": "version-one"}],
            "sources": [
                {
                    "source_id": "src-neutral",
                    "work_id": "neutral-work",
                    "version_id": "version-one",
                    "receipt": {"extracted_text_sha256": sha(text_path.read_bytes())},
                }
            ],
            "claims": [
                {
                    "claim_id": "neutral-parent",
                    "work_id": "neutral-work",
                    "version_id": "version-one",
                    "relation": "unknown",
                }
            ],
            "coverage": [{"status": "unknown"}],
            "edges": [{"type": "claim-source"}],
            "bibliography": {"entries": []},
            "provenance": {
                "package_manifest_sha256": sha(
                    (self.base / "package_manifest.json").read_bytes()
                ),
                "deliverable_manifest_sha256": "1" * 64,
                "records_sha256": "2" * 64,
            },
            "supplement": {"status": "not-provided", "top3_status": "pending"},
        }
        quote = "exact supported quotation"
        start = self.text.index(quote)
        self.supplement = {
            "kind": "Stage1PrivateContentRepairSupplement",
            "schema_version": "1.0.0",
            "base_package_path": str(self.base),
            "base_package_manifest_sha256": self.index["provenance"][
                "package_manifest_sha256"
            ],
            "base_deliverable_manifest_sha256": "1" * 64,
            "base_records_sha256": "2" * 64,
            "original_canonical_claim_rows": 1,
            "original_compound_counts": {
                "supported": 0,
                "partial": 0,
                "unknown": 1,
                "denominator": 1,
            },
            "atomic_revision_denominator": {"cases": 1, "entries": 1},
            "source_reading": {
                "abstract": "success",
                "required_full_methods": "failure",
            },
            "papers": [{"work_id": "neutral-work", "version_id": "version-one"}],
            "atomic_revisions": [
                {
                    "atom_id": "neutral-atom",
                    "work_id": "neutral-work",
                    "parent_claim_id": "neutral-parent",
                    "assessment": "unresolved",
                    "evidence_ref": "../evidence/atoms.json",
                }
            ],
            "core_findings": [
                {
                    "finding_id": "neutral-finding",
                    "work_id": "neutral-work",
                    "evidence": [
                        {
                            "work_id": "neutral-work",
                            "version_id": "version-one",
                            "source_id": "src-neutral",
                            "text_path": str(text_path),
                            "text_sha256": sha(text_path.read_bytes()),
                            "start": start,
                            "end": start + len(quote),
                            "quote": quote,
                            "context_locator": "synthetic paragraph",
                        }
                    ],
                }
            ],
            "unresolved": {"original": "still unknown"},
            "all_original_obligations_retained": True,
            "official_stage2_import_eligible": False,
            "protected_execution_authorized": False,
            "scientific_scores_changed": False,
        }
        self._write_package()

    def _write_package(self):
        for name, value in {
            "integrated/repair_supplement.json": self.supplement,
            "evidence/atoms.json": {"atoms": ["neutral-atom"]},
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, value)
        rows = []
        for relative in ("integrated/repair_supplement.json", "evidence/atoms.json"):
            raw = (self.root / relative).read_bytes()
            rows.append({"path": relative, "bytes": len(raw), "sha256": sha(raw)})
        manifest = {
            "kind": "PrivateRepairCandidateManifest",
            "schema_version": "1.0.0",
            "files": rows,
            "member_count": len(rows),
        }
        path = self.root / "checks/candidate_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, manifest)
        self.manifest_sha = sha(path.read_bytes())
        prior_path = self.root / "acceptance/actual_content_review.json"
        prior_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            prior_path,
            {"verdict": "REQUEST_CHANGES", "failures": ["retained synthetic failure"]},
        )
        review = {
            "kind": "IndependentReview",
            "verdict": "PASS",
            "action_hash": self.manifest_sha,
            "prior_review": {
                "path": "acceptance/actual_content_review.json",
                "sha256": sha(prior_path.read_bytes()),
                "immutable_original_verdict": "REQUEST_CHANGES",
            },
        }
        path = self.root / "acceptance/actual_content_delta_review.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, review)
        self.review_sha = sha(path.read_bytes())
        write_json(
            self.root / "acceptance/final_delivery_receipt.json",
            {
                "candidate_manifest_sha256": self.manifest_sha,
                "independent_review_sha256": self.review_sha,
                "independent_verdict": "PASS",
                "prior_request_changes_review_retained": True,
                "official_stage2_import_eligible": False,
                "scientific_scores_changed": False,
            },
        )

    def apply(self):
        return apply_repair(self.index, self.root, self.manifest_sha, self.review_sha)

    def test_non_mutating_overlay_retains_original_unknown_and_base_edges(self):
        before = deepcopy(self.index)
        result = self.apply()
        self.assertEqual(self.index, before)
        self.assertEqual(result["claims"][0]["relation"], "unknown")
        self.assertEqual(result["coverage"], [{"status": "unknown"}])
        self.assertEqual(result["edges"], before["edges"])
        self.assertEqual(result["schema_version"], "2.0.0")
        self.assertEqual(result["supplement"]["status"], "accepted-scoped-private")
        self.assertEqual(
            {row["type"] for row in result["supplement"]["edges"]},
            {
                "atomic-revision-claim",
                "atomic-revision-source",
                "finding-work",
                "finding-source",
            },
        )

    def test_wrong_external_hash_and_missing_or_tampered_member_fail(self):
        with self.assertRaisesRegex(DeliverableError, "external|hash"):
            apply_repair(self.index, self.root, "0" * 64, self.review_sha)
        member = self.root / "evidence/atoms.json"
        member.unlink()
        with self.assertRaisesRegex(DeliverableError, "missing repair member"):
            self.apply()
        write_json(member, {"altered": True})
        with self.assertRaisesRegex(DeliverableError, "hash mismatch"):
            self.apply()

    def test_wrong_base_version_and_quote_fail_closed(self):
        original = deepcopy(self.supplement)
        for mutation, message in (
            ("base", "base records"),
            ("version", "work/version"),
            ("quote", "quote binding"),
        ):
            with self.subTest(mutation=mutation):
                changed = deepcopy(original)
                if mutation == "base":
                    changed["base_records_sha256"] = "9" * 64
                elif mutation == "version":
                    changed["papers"][0]["version_id"] = "collapsed-version"
                else:
                    changed["core_findings"][0]["evidence"][0]["quote"] = "wrong quote"
                self.supplement = changed
                self._write_package()
                with self.assertRaisesRegex(DeliverableError, message):
                    self.apply()
        self.supplement = original

    def test_abstract_cannot_become_full_methods_or_enable_stage2(self):
        original = deepcopy(self.supplement)
        for field, value in (
            (
                "source_reading",
                {"abstract": "success", "required_full_methods": "success"},
            ),
            ("official_stage2_import_eligible", True),
            ("protected_execution_authorized", True),
            ("scientific_scores_changed", True),
        ):
            with self.subTest(field=field):
                self.supplement = deepcopy(original)
                self.supplement[field] = value
                self._write_package()
                with self.assertRaises(DeliverableError):
                    self.apply()
        self.supplement = original

    def test_readback_validator_rejects_snapshot_and_edge_tampering(self):
        from research_workspace.repair import validate_repair_projection

        valid = self.apply()
        for mutation in ("snapshot", "edge"):
            with self.subTest(mutation=mutation):
                changed = deepcopy(valid)
                if mutation == "snapshot":
                    changed["supplement"]["evidence_files"][
                        "integrated/repair_supplement.json"
                    ]["text"] += " "
                else:
                    changed["supplement"]["edges"].pop()
                with self.assertRaises(DeliverableError):
                    validate_repair_projection(changed)

    def test_rehashed_content_cannot_retain_external_acceptance(self):
        from research_workspace.repair import validate_repair_projection

        valid = self.apply()
        changed = deepcopy(valid)
        overlay = changed["supplement"]
        overlay["data"]["atomic_revisions"][0]["assessment"] = "supported"
        overlay["data"]["core_findings"][0]["evidence"][0]["quote"] = "fabricated"
        for edge in overlay["edges"]:
            if edge["type"] == "atomic-revision-claim":
                edge["assessment"] = "supported"
            elif edge["type"] == "finding-source":
                edge["quote"] = "fabricated"
        raw = canonical(overlay["data"])
        overlay["evidence_files"]["integrated/repair_supplement.json"] = {
            "text": raw.decode("utf-8"),
            "sha256": sha(raw),
        }
        self.assertEqual(
            overlay["manifest_sha256"], valid["supplement"]["manifest_sha256"]
        )
        self.assertEqual(overlay["review_sha256"], valid["supplement"]["review_sha256"])
        with self.assertRaisesRegex(DeliverableError, "accepted manifest"):
            validate_repair_projection(changed)

    def test_manifest_requires_every_member_digest_and_exact_byte_count(self):
        for field, value in (
            ("sha256", None),
            ("sha256", "bad"),
            ("bytes", True),
            ("bytes", -1),
        ):
            with self.subTest(field=field, value=value):
                self._write_package()
                path = self.root / "checks/candidate_manifest.json"
                manifest = json.loads(path.read_bytes())
                manifest["files"][0][field] = value
                write_json(path, manifest)
                self.manifest_sha = sha(path.read_bytes())
                review_path = self.root / "acceptance/actual_content_delta_review.json"
                review = json.loads(review_path.read_bytes())
                review["action_hash"] = self.manifest_sha
                write_json(review_path, review)
                self.review_sha = sha(review_path.read_bytes())
                receipt_path = self.root / "acceptance/final_delivery_receipt.json"
                receipt = json.loads(receipt_path.read_bytes())
                receipt.update(
                    candidate_manifest_sha256=self.manifest_sha,
                    independent_review_sha256=self.review_sha,
                )
                write_json(receipt_path, receipt)
                with self.assertRaisesRegex(DeliverableError, "manifest member"):
                    self.apply()

    def test_quote_cannot_borrow_another_canonical_source(self):
        self.index["sources"][0]["receipt"]["extracted_text_sha256"] = "9" * 64
        with self.assertRaisesRegex(DeliverableError, "canonical source"):
            self.apply()


if __name__ == "__main__":
    unittest.main()
