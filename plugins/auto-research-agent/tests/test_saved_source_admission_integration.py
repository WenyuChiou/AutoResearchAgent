"""Real offline package/view validation of a blocked saved-source handoff.

Only the authored SDK HTTP fixture is simulated. Admission, package, source,
view, qualification and handoff validators run unchanged; no research occurs.
"""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace.saved_admission import (
    CORE_CHECKS,
    check_handoff,
    inspect_saved_admission,
)
from research_workspace.source_rerun import attach_rerun
from research_workspace.view import write_workspace
from stage1_brief.formal_target import prepare_formal_intake, submit_formal_target
from stage1_deliverable import package as deliverable_package
from stage1_deliverable.common import canonical, sha
from test_research_brief import brief
from test_research_brief_formal_target import answer
from test_research_workspace_literature_selection import complete_document
import test_research_workspace_source_rerun_exports as rerun
from test_saved_source_admission import snapshot_fixture
import test_stage1_deliverable as deliverable_fixture


class SavedAdmissionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        deliverable_fixture.ResearchDeliverableTests.setUpClass()

    def setUp(self):
        fixture = deliverable_fixture.ResearchDeliverableTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        records = fixture.make_records()
        replacements = {
            "work1": "fixture-0",
            "v1": "version-0",
            "src1": "source-0",
        }

        def rename(value):
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        records = rename(records)
        fixture.build(records)
        package_ref = self.ref(fixture.output / "provenance_manifest.json")
        original = fixture.inputs / "source/source-fetch-result.json"
        receipt = json.loads(original.read_bytes())
        raw = Path(receipt["raw_path"]).read_bytes()
        text = Path(receipt["extracted_text_path"]).read_bytes()
        note = self.save("note.json", {"fixture": "A complete authored source note."})
        companion = self.save("companion.json", {"notes": [note]})
        provenance = self.ref(original)
        with (
            patch.dict(rerun.RAW, {"source-0": raw}),
            patch.dict(rerun.TEXT, {"source-0": text}),
        ):
            index = rerun.fixture_index()
            index["provenance"]["deliverable_manifest_sha256"] = package_ref["sha256"]
            paper = copy.deepcopy(records["papers"][0])
            paper.update(
                input_version="fresh-1",
                fresh_note={
                    "paper_note_status": "complete",
                    "companion_binding": {
                        **note,
                        "companion_manifest_sha256": companion["sha256"],
                    },
                    "source_qualification": {
                        "status": "qualified",
                        "work_id": paper["work_id"],
                        "version_id": paper["version_id"],
                        "source_id": "source-0",
                        "raw_sha256": sha(raw),
                        "text_sha256": sha(text),
                        "identity_checked": True,
                        "body_checked": True,
                        "reading_order_checked": True,
                        "relevance_checked": True,
                        "evidence_refs": ["synthetic-review:1"],
                    },
                },
            )
            index["papers"][0] = paper
            index["sources"][0].update(
                receipt=receipt,
                result_sha256=provenance["sha256"],
                attempts=[
                    json.loads(line)
                    for line in (fixture.output / "paper_manifest.jsonl")
                    .read_bytes()
                    .splitlines()
                ],
            )
            manifest = rerun.fixture_manifest(index)
            index["papers"] = index["papers"][:1]
            index["sources"] = index["sources"][:1]
            index["coverage"] = [
                {
                    "need_id": "synthetic-need",
                    "status": "qualified",
                    "work_ids": ["fixture-0"],
                    "evidence_refs": ["synthetic-need:1"],
                }
            ]
            rerun.refresh_bibliography(index)
            manifest["data"]["rows"] = manifest["data"]["rows"][:1]
            manifest["data"]["rows"][0]["final_url"] = receipt["final_url"]
            manifest["data"]["rows"][0]["metadata"]["journal"] = paper["venue"]
            manifest["data"]["rows"][0]["metadata_provenance"]["journal"]["value"] = (
                paper["venue"]
            )
            manifest["data"]["base_index_sha256"] = sha(canonical(index))
            manifest["data"]["rows"][0]["attempt_id"] = sha(
                canonical(
                    {
                        "base": manifest["data"]["base_index_sha256"],
                        "parser": manifest["data"]["parser_runtime"]["parser_sha256"],
                        "work": "fixture-0",
                        "version": "version-0",
                        "raw": sha(raw),
                    }
                )
            )
            complete_document(manifest["data"]["rows"][0])
            manifest["files"] = {
                name: row
                for name, row in manifest["files"].items()
                if name.startswith("sources/source-0/")
            }
            rerun_root = self.root / "rerun"
            rerun_root.mkdir()
            digest = rerun.write_manifest(rerun_root, manifest)
            self.base_index = copy.deepcopy(index)
            self.rerun_manifest = copy.deepcopy(manifest)
            index = attach_rerun(index, rerun_root, digest)
        view = self.root / "view"
        write_workspace(
            index,
            Path(__file__).parents[1] / "references/research-workspace",
            view,
            source_rerun_root=rerun_root,
        )
        intake = prepare_formal_intake(
            brief("unrestricted"),
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        submission = answer(1)
        submission.update(
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        intake = submit_formal_target(intake, submission)
        intake["needs"] = [{"need_id": "synthetic-need", "question": "Synthetic need?"}]
        snapshot = snapshot_fixture(count=1)
        snapshot.update(project_id=index["project_id"], input_version="fresh-1")
        snapshot["bindings"] = {
            "original_request": self.save(
                "request.txt", b"Synthetic saved source request"
            ),
            "brief": self.save("brief.json", intake),
            "resources": self.save(
                "resources.json",
                {
                    "project_id": index["project_id"],
                    "input_version": "fresh-1",
                    "no_resource_reset": True,
                    "current_round_used": {
                        "queries": 1,
                        "full_source_acquisition_attempts": 1,
                    },
                    "previous_cumulative_used": {
                        "queries": 2,
                        "full_source_acquisition_attempts": 2,
                    },
                    "total_authorized_limits": {
                        "queries": 3,
                        "full_source_acquisition_attempts": 3,
                    },
                },
            ),
            "deliverable": package_ref,
            "view": self.ref(view / "view-manifest.json"),
            "companion": companion,
        }
        row = manifest["data"]["rows"][0]
        snapshot["rows"] = [
            {
                "work_id": "fixture-0",
                "version_id": "version-0",
                "source_id": "source-0",
                "raw_source": self.ref(rerun_root / row["raw_path"]),
                "extracted_text": self.ref(rerun_root / row["extracted_path"]),
                "full_note": note,
                "acquisition_provenance": provenance,
                "original_acquired_at": None,
            }
        ]
        self.snapshot_ref = self.save("snapshot.json", snapshot)
        self.view = view
        self.package = fixture.output
        self.fixture = fixture
        self.records = records
        self.index = index
        self.rerun_root = rerun_root

    def test_valid_same_identity_packages_cannot_replace_the_view_delivery(self):
        records = copy.deepcopy(self.records)
        records["claims"][0]["text"] = "A different unverified authored claim."
        self.fixture.output = self.root / "other-delivery"
        self.fixture.build(records)
        other = self.ref(self.fixture.output / "provenance_manifest.json")
        self.assertEqual(
            deliverable_package.validate(self.fixture.output, other["sha256"])[
                "status"
            ],
            "passed",
        )
        snapshot = json.loads((self.root / "snapshot.json").read_bytes())
        snapshot["bindings"]["deliverable"] = other
        with self.assertRaisesRegex(ValueError, "view deliverable manifest"):
            inspect_saved_admission(self.root, self.save("snapshot.json", snapshot))

    def test_view_cannot_substitute_a_receipt_under_the_package_source_identity(self):
        # Change the actual SDK response, preserving all work/version/source IDs.
        fixture = deliverable_fixture.ResearchDeliverableTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        records = fixture.make_records(
            raw=deliverable_fixture.HTML + b"<!-- alternative saved bytes -->"
        )
        replacements = {"work1": "fixture-0", "v1": "version-0", "src1": "source-0"}

        def rename(value):
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        fixture.output = self.root / "other-delivery"
        fixture.build(rename(records))
        other = self.ref(fixture.output / "provenance_manifest.json")
        self.assertEqual(
            deliverable_package.validate(fixture.output, other["sha256"])["status"],
            "passed",
        )
        index = copy.deepcopy(self.base_index)
        index["provenance"]["deliverable_manifest_sha256"] = other["sha256"]
        manifest = copy.deepcopy(self.rerun_manifest)
        manifest["data"]["base_index_sha256"] = sha(canonical(index))
        row = manifest["data"]["rows"][0]
        row["attempt_id"] = sha(
            canonical(
                {
                    "base": manifest["data"]["base_index_sha256"],
                    "parser": manifest["data"]["parser_runtime"]["parser_sha256"],
                    "work": row["work_id"],
                    "version": row["version_id"],
                    "raw": row["raw_sha256"],
                }
            )
        )
        rerun_root = self.root / "other-rerun"
        rerun_root.mkdir()
        with (
            patch.dict(
                rerun.RAW,
                {"source-0": (self.rerun_root / row["raw_path"]).read_bytes()},
            ),
            patch.dict(
                rerun.TEXT,
                {"source-0": (self.rerun_root / row["extracted_path"]).read_bytes()},
            ),
        ):
            digest = rerun.write_manifest(rerun_root, manifest)
            index = attach_rerun(index, rerun_root, digest)
        view = self.root / "other-view"
        write_workspace(
            index,
            Path(__file__).parents[1] / "references/research-workspace",
            view,
            source_rerun_root=rerun_root,
        )
        snapshot = json.loads((self.root / "snapshot.json").read_bytes())
        snapshot["bindings"].update(
            deliverable=other, view=self.ref(view / "view-manifest.json")
        )
        with self.assertRaisesRegex(ValueError, "deliverable source receipt"):
            inspect_saved_admission(self.root, self.save("snapshot.json", snapshot))

    def ref(self, path):
        raw = path.read_bytes()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": sha(raw),
            "bytes": len(raw),
        }

    def save(self, name, value):
        path = self.root / name
        path.write_bytes(value if isinstance(value, bytes) else canonical(value))
        return self.ref(path)

    def test_real_validators_emit_a_blocked_handoff_and_preserve_unknowns(self):
        result = inspect_saved_admission(self.root, self.snapshot_ref)
        check_handoff(result)
        self.assertEqual(result["stage1_gate"]["status"], "blocked")
        self.assertEqual(
            result["stage1_gate"]["remaining"],
            [*CORE_CHECKS, "actual-html-operation-acceptance"],
        )
        self.assertFalse(result["eligible_for_stage2"])
        self.assertFalse(result["stage1_completed"])
        self.assertEqual(
            result["stage2"], {"status": "not-started", "execution_authorized": False}
        )
        self.assertEqual(result["resources_preserved"]["queries"]["used"], 3)
        index = json.loads((self.view / "workspace-index.json").read_bytes())
        self.assertEqual(index["claims"][0]["support"], "Unknown")
        self.assertIsNone(
            json.loads((self.root / "snapshot.json").read_bytes())["rows"][0][
                "original_acquired_at"
            ]
        )

    def test_real_view_and_package_tampering_are_rejected(self):
        for path in (
            self.view / "workspace-data.js",
            self.package / "literature_review.md",
        ):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"changed bytes")
                    with self.assertRaises(ValueError):
                        inspect_saved_admission(self.root, self.snapshot_ref)
                finally:
                    path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
