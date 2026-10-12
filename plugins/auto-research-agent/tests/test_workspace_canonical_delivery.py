"""Authored saved-delivery projections; no network, model or native calls."""

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_research_workspace as workspace_fixture
from research_workspace import canonical_delivery
from research_workspace.canonical_delivery import (
    project_canonical_atlas,
    project_canonical_delivery,
)
from research_workspace.view import REFERENCE_COMMIT, write_workspace
from stage1_deliverable import sources
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    read_json,
    sha,
    write_json,
)
from test_stage1_core_records import core_case, produced


class CanonicalDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace_fixture.WorkspaceTests.setUpClass()

    def setUp(self):
        self.case = workspace_fixture.WorkspaceTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.fixture.output
        self.digest = sha((self.root / "provenance_manifest.json").read_bytes())

    def project(self):
        return project_canonical_delivery(self.root, "authored-project", self.digest)

    def rebind(self):
        path = self.root / "provenance_manifest.json"
        manifest = read_json(path)
        manifest["files"] = inventory(self.root)
        write_json(path, manifest)
        self.digest = sha(path.read_bytes())

    def test_bare_delivery_and_v6_assets_share_lossless_identity_and_mapping(self):
        before = inventory(self.root)
        manifest_before = (self.root / "provenance_manifest.json").read_bytes()
        with (
            patch("stage1_deliverable.package.build", side_effect=AssertionError),
            patch("stage1_deliverable.package.validate", side_effect=AssertionError),
            patch(
                "stage1_deliverable.sources.validate_archive",
                side_effect=AssertionError,
            ),
        ):
            index, files = project_canonical_atlas(
                self.root, "authored-project", self.digest
            )
            destination = self.case.fixture.root / "authored-atlas-view"
            reference = (
                Path(__file__).resolve().parents[1] / "references/research-workspace"
            )
            view = write_workspace(index, reference, destination, atlas=True)
            self.assertEqual(view["index_sha256"], sha(canonical(index)))
            self.assertEqual(
                (destination / "atlas-data.js").read_bytes(), files["atlas-data.js"]
            )
            self.assertTrue((destination / "index.html").is_file())
            self.assertTrue((destination / "view-manifest.json").is_file())
            self.assertEqual(
                view["rebuild"]["source_kind"], "Stage1ResearchDeliverable"
            )
            self.assertEqual(view["rebuild"]["entrypoint_kind"], "python-api")
            self.assertEqual(
                view["rebuild"]["entrypoint"],
                "research_workspace.canonical_delivery.project_canonical_delivery",
            )
            self.assertEqual(
                view["rebuild"]["reader_api"], view["rebuild"]["entrypoint"]
            )
            self.assertEqual(
                view["rebuild"]["renderer_api"],
                "research_workspace.view.write_workspace",
            )
            self.assertEqual(
                view["rebuild"]["manifest_path"], "provenance_manifest.json"
            )
            self.assertEqual(view["rebuild"]["manifest_sha256"], self.digest)
            self.assertEqual(view["rebuild"]["expected_manifest_sha256"], self.digest)
            self.assertEqual(
                view["adapter_sources"]["canonical_delivery.py"],
                sha(Path(canonical_delivery.__file__).read_bytes()),
            )
            legacy_index = self.case.project()
            legacy_view = write_workspace(
                legacy_index,
                reference,
                self.case.fixture.root / "legacy-atlas-view",
                atlas=True,
            )
            self.assertEqual(
                legacy_view["rebuild"],
                {
                    "entrypoint": "python -m research_workspace",
                    "project_id": legacy_index["project_id"],
                    "expected_manifest_sha256": self.case.digest,
                    "reference_commit": REFERENCE_COMMIT,
                    "reference_asset_policy": "use exact reference_assets hashes; commit is historical provenance",
                    "output_policy": "new directory outside Git",
                    "validation_mode": "byte-inventory",
                    "atlas": True,
                },
            )
            self.assertNotIn("canonical_delivery.py", legacy_view["adapter_sources"])
        for field in ("papers", "claims", "screening", "coverage"):
            self.assertEqual(index[field], self.case.records[field])
        self.assertEqual(index, self.project())
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(
            manifest_before, (self.root / "provenance_manifest.json").read_bytes()
        )
        self.assertFalse((self.root / "package_manifest.json").exists())
        for virtual, row in index["provenance"]["files"].items():
            self.assertEqual(virtual, "deliverable/" + row["physical_relative_path"])
            actual = (self.root / row["physical_relative_path"]).read_bytes()
            self.assertEqual((row["sha256"], row["bytes"]), (sha(actual), len(actual)))
        provenance = index["provenance"]
        self.assertEqual(provenance["package_manifest_sha256"], self.digest)
        self.assertEqual(provenance["deliverable_manifest_sha256"], self.digest)
        payload = json.loads(
            files["atlas-data.js"]
            .decode()
            .removeprefix("window.WORKSPACE_VIEW = ")
            .removesuffix(";\n")
        )
        self.assertEqual(payload["index"], index)
        self.assertEqual(payload["index_sha256"], sha(canonical(index)))
        self.assertEqual(len(payload["note_paths"]), len(index["papers"]))
        for note in payload["note_paths"]:
            paper = next(p for p in index["papers"] if p["work_id"] == note["work_id"])
            self.assertEqual(note["version_id"], paper["version_id"])
            self.assertIn(paper["title"].encode(), files[note["path"]])
        self.assertIn(b"physical_relative_path", files["wiki/README.md"])
        self.assertEqual(
            files["references.bib"], index["bibliography"]["all_bibtex"].encode()
        )
        atlas_binding = json.loads(files["atlas-binding.json"])
        self.assertEqual(atlas_binding["design_reference"], "reviewed-local-v6")
        self.assertEqual(atlas_binding["index_sha256"], payload["index_sha256"])
        self.assertFalse(atlas_binding["execution_authority"])
        for name, digest in atlas_binding["files"].items():
            self.assertEqual(sha(files[name]), digest)
        self.assertEqual(index["readiness"]["status"], "not-provided")
        self.assertFalse(index["readiness"]["stage2_execution_authorized"])
        self.assertTrue(all(not row["execution_enabled"] for row in index["stages"]))
        self.assertFalse(
            payload["literature_selection"]["official_stage2_import_eligible"]
        )

    def test_external_manifest_hash_extra_and_tampered_inventory_fail_closed(self):
        with self.assertRaisesRegex(DeliverableError, "external canonical manifest"):
            project_canonical_delivery(self.root, "authored-project", "0" * 64)
        extra = self.root / "not-listed.txt"
        extra.write_bytes(b"unlisted authored bytes")
        with self.assertRaisesRegex(DeliverableError, "inventory differs"):
            self.project()
        extra.unlink()
        source = next(self.root.glob("sources/*/extracted/*"))
        source.write_bytes(source.read_bytes() + b"tampered")
        with self.assertRaisesRegex(DeliverableError, "inventory differs"):
            self.project()

    def test_consumed_document_checked_against_external_snapshot(self):
        path = self.root / "search_and_screening.csv"
        approved = path.read_bytes()
        read = canonical_delivery._read
        replaced = False

        def transient(root, files, virtual):
            nonlocal replaced
            if virtual != "deliverable/search_and_screening.csv":
                return read(root, files, virtual)
            replaced = True
            path.write_bytes(b"unapproved replacement")
            try:
                return read(root, files, virtual)
            finally:
                path.write_bytes(approved)

        with (
            patch.object(canonical_delivery, "_read", side_effect=transient),
            self.assertRaisesRegex(DeliverableError, "artifact bytes differ"),
        ):
            self.project()
        self.assertTrue(replaced)
        self.assertEqual(path.read_bytes(), approved)

    def test_rehashed_quote_or_canonical_view_rewrite_still_refused(self):
        path = self.root / "provenance_manifest.json"
        original_manifest = path.read_bytes()
        original_records = (self.root / "records.original.json").read_bytes()
        bad = deepcopy(self.case.records)
        bad["claims"][0]["quote"] = "invented statement"
        manifest = json.loads(original_manifest)
        manifest["canonical_records"] = bad
        write_json(self.root / "records.original.json", bad)
        manifest["original_input_sha256"] = sha(
            (self.root / "records.original.json").read_bytes()
        )
        write_json(path, manifest)
        self.rebind()
        with self.assertRaises(DeliverableError):
            self.project()
        path.write_bytes(original_manifest)
        (self.root / "records.original.json").write_bytes(original_records)
        (self.root / "papers.jsonl").write_bytes(b"{}\n")
        self.rebind()
        with self.assertRaisesRegex(DeliverableError, "paper view differs"):
            self.project()

    def test_rehashed_manifest_version_and_unsafe_path_refused(self):
        path = self.root / "provenance_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        manifest["schema_version"] = "9.0.0"
        write_json(path, manifest)
        self.digest = sha(path.read_bytes())
        with self.assertRaisesRegex(DeliverableError, "unsupported"):
            self.project()
        manifest = json.loads(original)
        manifest["files"]["../outside.txt"] = "1" * 64
        write_json(path, manifest)
        self.digest = sha(path.read_bytes())
        with self.assertRaisesRegex(DeliverableError, "unsafe artifact path"):
            self.project()

    def test_identity_mismatch_requires_replay_but_adapter_never_launches_it(self):
        path = self.root / "provenance_manifest.json"
        records = deepcopy(self.case.records)
        records["papers"][0]["title"] = "Unmatched authored title"
        manifest = read_json(path)
        manifest["canonical_records"] = records
        write_json(self.root / "records.original.json", records)
        (self.root / "papers.jsonl").write_bytes(
            b"".join(canonical(p) + b"\n" for p in records["papers"])
        )
        manifest["original_input_sha256"] = sha(
            (self.root / "records.original.json").read_bytes()
        )
        write_json(path, manifest)
        self.rebind()
        with (
            patch(
                "stage1_deliverable.sources.validate_archive",
                side_effect=AssertionError,
            ),
            self.assertRaisesRegex(
                DeliverableError, "identity requires semantic replay"
            ),
        ):
            self.project()

    def test_core_11_bare_projection_preserves_nulls_history_and_stage2_gate(self):
        with core_case() as (case, fixture, _, _):
            _, original, records = produced(case, fixture)
            # Author the minimum saved byte inventory directly. This tests the
            # reader contract without invoking the package producer or changing
            # any real saved package or runtime/dependency guard.
            root = self.case.fixture.root / "authored-core-delivery"
            root.mkdir()
            attempts = []
            for source in records["sources"]:
                receipt_path = original.parent / source["result_path"]
                receipt = read_json(receipt_path)
                archive = root / "sources" / source["source_id"]
                archive.mkdir(parents=True)
                (archive / "original.json").write_bytes(receipt_path.read_bytes())
                mapping = sources.artifact_map(receipt)
                for physical, relative in mapping.items():
                    target = archive / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(Path(physical).read_bytes())
                for attempt in receipt["attempts"]:
                    attempts.append(
                        {
                            "source_id": source["source_id"],
                            "work_id": source["work_id"],
                            "version_id": source["version_id"],
                            "attempt": attempt["sequence"],
                            "archive_path": "sources/"
                            + source["source_id"]
                            + "/"
                            + mapping[attempt["raw_path"]]
                            if attempt["raw_path"]
                            else None,
                            "paper_path": None,
                            "sha256": attempt["raw_sha256"],
                            "state": receipt["status"],
                            "source_version": receipt["source_version"],
                        }
                    )
            for artifact in records["core_artifacts"]:
                target = root / artifact["artifact_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    (original.parent / artifact["artifact_path"]).read_bytes()
                )
            write_json(root / "records.original.json", records)
            for name, rows in (
                ("papers.jsonl", records["papers"]),
                ("paper_manifest.jsonl", attempts),
            ):
                (root / name).write_bytes(
                    b"".join(canonical(row) + b"\n" for row in rows)
                )
            write_json(
                root / "provenance_manifest.json",
                {
                    "kind": "Stage1ResearchDeliverable",
                    "schema_version": "1.1.0",
                    "canonical_records": records,
                    "original_input_sha256": sha(
                        (root / "records.original.json").read_bytes()
                    ),
                    "files": inventory(root),
                },
            )
            digest = sha((root / "provenance_manifest.json").read_bytes())
            before = inventory(root)
            with (
                patch("stage1_deliverable.package.build", side_effect=AssertionError),
                patch(
                    "stage1_deliverable.package.validate", side_effect=AssertionError
                ),
                patch(
                    "stage1_deliverable.sources.validate_archive",
                    side_effect=AssertionError,
                ),
            ):
                index, files = project_canonical_atlas(root, "authored-core", digest)
            self.assertEqual(before, inventory(root))
            for field in ("claims", "core_claim_history", "core_artifacts"):
                self.assertEqual(index[field], records[field])
            self.assertTrue(
                any(
                    c["locator"] is None and c["source_id"] is None
                    for c in index["claims"]
                )
            )
            self.assertEqual(
                index["stage2_canonical_consumer"]["status"], "unconnected"
            )
            self.assertNotIn(
                "stage2",
                json.loads(
                    files["atlas-data.js"]
                    .decode()
                    .removeprefix("window.WORKSPACE_VIEW = ")
                    .removesuffix(";\n")
                ),
            )
            self.assertIn(b"Original Core claim history", files["wiki/README.md"])
            case.runner.assert_not_called()
            artifact = root / records["core_artifacts"][0]["artifact_path"]
            artifact.write_bytes(artifact.read_bytes() + b"tampered")
            manifest_path = root / "provenance_manifest.json"
            manifest = read_json(manifest_path)
            manifest["files"] = inventory(root)
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(DeliverableError, "archive bytes differ"):
                project_canonical_delivery(
                    root, "authored-core", sha(manifest_path.read_bytes())
                )


if __name__ == "__main__":
    unittest.main()
