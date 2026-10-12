"""Synthetic saved-delivery checks must never mint final Stage 1 acceptance."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.final_delivery import inspect_final_delivery
from research_workspace.view import write_workspace
from stage1_brief.formal_target import prepare_formal_intake, submit_formal_target
from stage1_deliverable.common import DeliverableError, canonical, sha
from test_research_brief import brief
from test_research_brief_formal_target import answer
from test_research_workspace_literature_selection import attached_index, change_second


class FinalDeliveryTests(unittest.TestCase):
    def setup_view(self, change=None, base_change=None, target=30, confirmed=True):
        temporary, index = attached_index(change, base_change)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.view = self.root / "view"
        reference = Path(__file__).parents[1] / "references/research-workspace"
        write_workspace(index, reference, self.view, source_rerun_root=self.root)
        self.manifest_hash = sha((self.view / "view-manifest.json").read_bytes())
        self.brief = prepare_formal_intake(
            brief("unrestricted"),
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        if confirmed:
            submitted = answer(target)
            submitted.update(
                project_id=index["project_id"],
                input_version="fresh-1",
                request_id="count-1",
            )
            self.brief = submit_formal_target(self.brief, submitted)
        self.brief["needs"] = [
            {"need_id": "synthetic-need", "question": "Synthetic source need?"}
        ]
        self.brief_path = self.root / "brief.json"
        self.brief_path.write_bytes(canonical(self.brief))
        return index

    def inspect(self, **options):
        return inspect_final_delivery(
            self.view,
            self.manifest_hash,
            self.brief_path,
            sha(self.brief_path.read_bytes()),
            **options,
        )

    def rehash_view(self):
        path = self.view / "view-manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"] = {
            p.relative_to(self.view).as_posix(): sha(p.read_bytes())
            for p in self.view.rglob("*")
            if p.is_file() and p != path
        }
        path.write_bytes(canonical(manifest))
        self.manifest_hash = sha(path.read_bytes())

    def test_candidate_package_is_partial_and_preserves_unknowns(self):
        index = self.setup_view()
        before = canonical(index)
        report = self.inspect()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(
            report["formal_progress"]["technical_eligible_distinct_works"], 1
        )
        self.assertEqual(report["formal_progress"]["formally_usable_distinct_works"], 0)
        self.assertEqual(report["formal_progress"]["target_shortfall"], 30)
        self.assertEqual(report["source_selection_counts"]["excluded"], 1)
        self.assertFalse(report["stage1_completed"])
        self.assertFalse(report["official_stage2_import_eligible"])
        self.assertEqual(report["html_execution"], "not-performed")
        self.assertEqual(canonical(index), before)
        self.assertEqual(index["claims"][0]["support"], "Unknown")

    def test_explicit_small_target_cannot_make_static_view_final(self):
        from test_research_workspace_source_rerun_exports import RAW, TEXT

        def qualified(index):
            for item in index["papers"]:
                item["input_version"] = "fresh-1"
            paper = index["papers"][0]
            paper["fresh_note"] = {
                "paper_note_status": "complete",
                "source_qualification": {
                    "status": "qualified",
                    "work_id": paper["work_id"],
                    "version_id": paper["version_id"],
                    "source_id": "source-0",
                    "raw_sha256": sha(RAW["source-0"]),
                    "text_sha256": sha(TEXT["source-0"]),
                    "identity_checked": True,
                    "body_checked": True,
                    "reading_order_checked": True,
                    "relevance_checked": True,
                    "evidence_refs": ["synthetic-review:1"],
                },
            }
            paper["findings"] = {
                name: "Substantial synthetic evidence rationale."
                for name in (
                    "question",
                    "data",
                    "method",
                    "main_findings",
                    "limitations",
                    "relevance",
                )
            }
            index["papers"][1]["fresh_note"] = {"paper_note_status": "pending"}
            index["coverage"][0]["status"] = "qualified"
            index["coverage"][0]["work_ids"] = [paper["work_id"]]
            index["coverage"][0]["evidence_refs"] = ["synthetic-need-review:1"]

        self.setup_view(base_change=qualified, target=1)
        report = self.inspect()
        self.assertEqual(
            report["status"], "ready-for-final-checks", report["formal_progress"]
        )
        self.assertFalse(report["stage1_completed"])
        self.assertIn(
            "accepted-stage1-to-stage2-handoff", report["final_checks_required"]
        )
        self.assertIn(
            "actual-html-operation-acceptance", report["final_checks_required"]
        )
        self.assertIn("coverage-and-claim-review", report["final_checks_required"])

    def test_unsubmitted_default_stays_pending(self):
        self.setup_view(confirmed=False)
        report = self.inspect()
        self.assertIsNone(report["formal_progress"]["target"])
        self.assertFalse(report["formal_progress"]["formal_target_met"])
        self.assertEqual(report["status"], "partial")

    def test_two_versions_cannot_inflate_distinct_work_target(self):
        def two_versions(index):
            from test_research_workspace_source_rerun_exports import (
                refresh_bibliography,
            )

            index["papers"][1]["work_id"] = "fixture-0"
            index["sources"][1]["work_id"] = "fixture-0"
            refresh_bibliography(index)

        self.setup_view(change_second("extracted", "full-text"), two_versions, target=2)
        report = self.inspect()
        self.assertEqual(report["source_selection_counts"]["included"], 2)
        self.assertEqual(
            report["formal_progress"]["technical_eligible_distinct_works"], 1
        )
        self.assertEqual(report["formal_progress"]["formally_usable_distinct_works"], 0)
        self.assertEqual(report["formal_progress"]["target_shortfall"], 2)

    def test_wrong_project_or_external_hash_is_rejected(self):
        self.setup_view()
        with self.assertRaisesRegex(DeliverableError, "external artifact hash"):
            inspect_final_delivery(
                self.view, "0" * 64, self.brief_path, sha(self.brief_path.read_bytes())
            )
        wrong = deepcopy(self.brief)
        wrong["project_id"] = "different-project"
        wrong["formal_final_count"]["decisions"][0]["project_id"] = wrong["project_id"]
        self.brief_path.write_bytes(canonical(wrong))
        with self.assertRaisesRegex(DeliverableError, "wrong brief project"):
            self.inspect()

    def test_non_object_manifest_and_payload_reject_with_deliverable_error(self):
        for value in (None, []):
            for target in ("view-manifest.json", "workspace-data.js"):
                with self.subTest(value=value, target=target):
                    self.setup_view()
                    path = self.view / target
                    data = canonical(value)
                    if target == "workspace-data.js":
                        data = b"window.WORKSPACE_VIEW = " + data + b";\n"
                    path.write_bytes(data)
                    if target == "view-manifest.json":
                        self.manifest_hash = sha(data)
                    else:
                        self.rehash_view()
                    with self.assertRaisesRegex(DeliverableError, "must be an object"):
                        self.inspect()

    def test_rehashed_or_missing_artifacts_cannot_pass(self):
        for mode in ("count", "note", "missing-source", "modified-source"):
            with self.subTest(mode=mode):
                self.setup_view()
                if mode == "count":
                    path = self.view / "literature/selection.json"
                    value = json.loads(path.read_bytes())
                    value["counts"]["included"] = 30
                    path.write_bytes(canonical(value))
                    self.rehash_view()
                elif mode == "note":
                    note = next(
                        p
                        for p in (self.view / "wiki").glob("*.md")
                        if p.name != "README.md"
                    )
                    note.write_bytes(b"Unbound replacement note")
                    self.rehash_view()
                else:
                    source = next(
                        (self.view / "source-rerun/sources").rglob("raw.html")
                    )
                    if mode == "missing-source":
                        source.unlink()
                    else:
                        source.write_bytes(b"changed source")
                with self.assertRaises(DeliverableError):
                    self.inspect()

    def test_view_change_during_inspection_is_rejected(self):
        from research_workspace.wiki import wiki_files

        self.setup_view()

        def changing_notes(index):
            (self.view / "index.html").write_bytes(b"changed during read")
            return wiki_files(index)

        with patch("research_workspace.final_delivery.wiki_files", changing_notes):
            with self.assertRaisesRegex(DeliverableError, "changed during inspection"):
                self.inspect()

    def test_bound_timing_keeps_unfinished_full_process_unknown(self):
        index = self.setup_view()
        path = self.root / "timing.json"
        record = {
            "kind": "Stage1RunTiming",
            "schema_version": "1.0.0",
            "project_id": self.brief["project_id"],
            "input_version": "fresh-1",
            "index_sha256": sha(canonical(index)),
            "started_at": "2026-10-08T20:10:00Z",
            "ended_at": None,
            "observed_at": "2026-10-08T22:02:00Z",
            "intervals": [],
        }
        path.write_bytes(canonical(record))
        report = self.inspect(
            timing_path=path, expected_timing_sha256=sha(path.read_bytes())
        )
        self.assertIsNone(report["timing"]["finished_run_seconds"])
        self.assertIsNone(report["timing"]["phases"]["handoff"]["duration_seconds"])
        self.assertFalse(report["stage1_completed"])
        record["input_version"] = "stale"
        path.write_bytes(canonical(record))
        with self.assertRaisesRegex(DeliverableError, "stale or wrong input_version"):
            self.inspect(
                timing_path=path, expected_timing_sha256=sha(path.read_bytes())
            )


if __name__ == "__main__":
    unittest.main()
