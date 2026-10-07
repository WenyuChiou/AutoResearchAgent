"""Offline view guards; opt-in browser fixture reuses the pinned #88 assets."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace.projection import validate_index
from research_workspace.view import REFERENCE_HASHES, render_view, write_workspace
from research_workspace.stages import stage_registry
from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.views import bibtex


def fixture_index():
    papers = []
    for number, title in enumerate(
        ["Evidence", '<img src=x onerror="alert(1)"> literal title']
    ):
        papers.append(
            {
                "work_id": f"fixture-{number}",
                "version_id": f"version-{number}",
                "title": title,
                "authors": ["Test Author"],
                "year": None,
                "venue": "Unknown",
                "doi": None,
                "url": None,
                "evidence_level": "metadata",
                "classification": {"topic_cluster": "fixture classification"},
                "roles": [],
                "source_ids": [f"source-{number}"],
                "claim_ids": [],
                "findings": {
                    "limitations": "UI regression fixture; not research evidence."
                },
            }
        )
    return {
        "kind": "WorkspaceIndex",
        "schema_version": "1.0.0",
        "project_id": "browser-contract-fixture",
        "topic": "Synthetic interface checks only",
        "as_of": "2026-10-04",
        "status": "partial-review-only",
        "papers": papers,
        "stages": stage_registry(),
        "sources": [{"source_id": "source-0", "artifact_id": "javascript:alert(1)"}],
        "claims": [],
        "edges": [],
        "screening": [],
        "coverage": [],
        "search": [],
        "coverage_documents": [],
        "audit_documents": [],
        "missing_fields": [],
        "readiness": {"execution_authorized": False},
        "supplement": {"status": "not-provided", "top3_status": "pending"},
        "native_session": {"status": "not-connected", "thread_id": None},
        "evaluations": {"status": "not-provided", "items": []},
        "provenance": {
            "package_manifest_sha256": "0" * 64,
            "deliverable_manifest_sha256": "0" * 64,
            "records_sha256": "0" * 64,
            "files": {},
            "validation": {
                "mode": "byte-inventory",
                "byte_inventory": "passed",
                "canonical_bindings": "passed",
                "semantic_replay": "not-performed",
                "scientific_quality_scored": False,
            },
        },
        "bibliography": {
            "records_sha256": "0" * 64,
            "entries": [
                {
                    "work_id": p["work_id"],
                    "version_id": p["version_id"],
                    "bibtex": bibtex({"papers": [p]}).decode(),
                }
                for p in papers
            ],
            "all_bibtex": bibtex({"papers": papers}).decode(),
            "producer": "stage1_deliverable.views.bibtex",
        },
    }


class WorkspaceViewTests(unittest.TestCase):
    def test_graph_assets_are_hash_bound_and_exported(self):
        reference_root = Path(__file__).parents[1] / "references/research-workspace"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "view"
            with patch("research_workspace.view.private_output", side_effect=Path):
                manifest = write_workspace(fixture_index(), reference_root, output)
            graph_source = (output / "literature-reference.js").read_text(
                encoding="utf-8"
            )
            stylesheet = (output / "workspace.css").read_text(encoding="utf-8")
            self.assertEqual(
                manifest["files"]["literature-reference.js"],
                sha(graph_source.encode()),
            )
            self.assertEqual(
                manifest["reference_assets"],
                REFERENCE_HASHES,
            )
            self.assertFalse(
                manifest["reference_provenance"]["commit_alone_reconstructs_assets"]
            )
            self.assertIn(
                "reference_assets", manifest["rebuild"]["reference_asset_policy"]
            )
            self.assertIn("function layoutGraph", graph_source)
            self.assertIn(
                'zoomReset.dataset.literatureAction = "layout-reset"', graph_source
            )
            self.assertNotIn("paper.keywords", graph_source)
            self.assertIn("paper.classifications.map", graph_source)
            self.assertIn("Recorded classification assignment", graph_source)
            self.assertIn("height:clamp(360px,58vh,620px)", stylesheet)

    def test_existing_output_is_rejected_before_reading_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            # Test-owned roots use their physical location on macOS (/var alias).
            folder = Path(folder).resolve()
            with self.assertRaisesRegex(DeliverableError, "new directory"):
                write_workspace(fixture_index(), ".", folder)

    def test_git_output_is_rejected_before_reading_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            # Test-owned roots use their physical location on macOS (/var alias).
            folder = Path(folder).resolve()
            (Path(folder) / ".git").mkdir()
            with self.assertRaisesRegex(DeliverableError, "Git"):
                write_workspace(fixture_index(), ".", Path(folder) / "view")
            self.assertFalse((Path(folder) / "view").exists())

    def test_linked_output_is_rejected_before_reading_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / "physical"
            target.mkdir()
            link = root / "linked"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory symlinks are unavailable: {error}")
            index = canonical(fixture_index())
            (target / "index.json").write_bytes(index)
            with self.assertRaisesRegex(DeliverableError, "linked artifact"):
                write_workspace(fixture_index(), ".", link / "view")
            with self.assertRaisesRegex(DeliverableError, "linked artifact"):
                render_view(link / "index.json", root / "view", ".", sha(index))
            self.assertFalse((target / "view").exists())
            self.assertFalse((root / "view").exists())

    def test_execution_enabled_index_is_rejected(self):
        index = fixture_index()
        index["stages"][0]["execution_enabled"] = True
        with self.assertRaisesRegex(DeliverableError, "workspace index schema"):
            write_workspace(index, ".", "unused-view")

    def test_external_index_hash_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            # Test-owned roots use their physical location on macOS (/var alias).
            folder = Path(folder).resolve()
            path = Path(folder) / "index.json"
            original = canonical(fixture_index())
            path.write_bytes(original + b" ")
            with self.assertRaisesRegex(DeliverableError, "hash differs"):
                render_view(path, Path(folder) / "view", folder, sha(original))
            self.assertFalse((Path(folder) / "view").exists())

    def test_file_replaced_after_hash_uses_only_the_approved_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "index.json"
            approved_index = fixture_index()
            path.write_bytes(canonical(approved_index) + b"\n")
            approved_raw = path.read_bytes()
            expected_hash = sha(approved_raw)
            replacement = dict(approved_index, topic="Unapproved replacement")
            replacement_raw = canonical(replacement) + b"\n"
            replacement_path = root / "replacement.json"
            replacement_path.write_bytes(replacement_raw)
            actual_read_bytes = Path.read_bytes
            reads = []

            def read_bytes(candidate):
                if candidate == path:
                    reads.append(candidate)
                return actual_read_bytes(candidate)

            def hash_then_replace(raw):
                digest = sha(raw)
                self.assertEqual(raw, approved_raw)
                replacement_path.replace(path)
                return digest

            def capture(index, raw, reference_root, output):
                validate_index(index)
                return {"index": index, "raw": raw}

            with (
                patch.object(Path, "read_bytes", read_bytes),
                patch("research_workspace.view.sha", side_effect=hash_then_replace),
                patch(
                    "research_workspace.view._write_view", side_effect=capture
                ) as writer,
            ):
                result = render_view(path, root / "view", root, expected_hash)
            self.assertEqual(result, {"index": approved_index, "raw": approved_raw})
            writer.assert_called_once_with(
                approved_index, approved_raw, root, root / "view"
            )
            self.assertEqual(reads, [path])
            self.assertEqual(path.read_bytes(), replacement_raw)
            self.assertFalse((root / "view").exists())

    def test_hash_bound_duplicate_json_keys_are_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "index.json"
            original = canonical(fixture_index())
            for key, replacement in (
                (b'"project_id":', b'"project_id":"duplicate", "project_id":'),
                (b'"limitations":', b'"limitations":"duplicate", "limitations":'),
            ):
                with self.subTest(key=key):
                    self.assertIn(key, original)
                    path.write_bytes(original.replace(key, replacement, 1))
                    approved_raw = path.read_bytes()
                    with patch("research_workspace.view._write_view") as writer:
                        with self.assertRaisesRegex(
                            DeliverableError, "duplicate JSON key"
                        ):
                            render_view(path, root / "view", root, sha(approved_raw))
                        writer.assert_not_called()
                    self.assertFalse((root / "view").exists())

    def test_template_drift_rejected_before_private_output(self):
        with tempfile.TemporaryDirectory() as folder:
            # Test-owned roots use their physical location on macOS (/var alias).
            folder = Path(folder).resolve()
            (Path(folder) / "prototype.html").write_text("unreviewed template")
            with self.assertRaisesRegex(
                DeliverableError, "reference asset hash differs"
            ):
                write_workspace(fixture_index(), folder, Path(folder) / "view")
            self.assertFalse((Path(folder) / "view").exists())

    def test_work_version_identity_not_title_is_unique(self):
        index = fixture_index()
        index["papers"].append(dict(index["papers"][0], title="Another title"))
        with self.assertRaisesRegex(DeliverableError, "duplicate work/version"):
            write_workspace(index, ".", "unused-view")


def build_browser_fixture(reference_root, output):
    """Generate test-only output outside Git; open browser-tests.html with CUA."""
    receipt = write_workspace(fixture_index(), reference_root, output)
    destination = Path(output)
    runner = Path(__file__).parent / "browser/workspace-records.js"
    (destination / "browser-regression.js").write_bytes(runner.read_bytes())
    page = (destination / "index.html").read_text(encoding="utf-8")
    page = page.replace(
        "</body>", '<script src="./browser-regression.js"></script></body>'
    )
    (destination / "browser-tests.html").write_text(page, encoding="utf-8")
    return receipt


if __name__ == "__main__":
    if "--reference-root" in sys.argv:
        import argparse

        parser = argparse.ArgumentParser(description=build_browser_fixture.__doc__)
        parser.add_argument("--reference-root", required=True)
        parser.add_argument("--output", required=True)
        args = parser.parse_args()
        print(json.dumps(build_browser_fixture(args.reference_root, args.output)))
    else:
        unittest.main()
