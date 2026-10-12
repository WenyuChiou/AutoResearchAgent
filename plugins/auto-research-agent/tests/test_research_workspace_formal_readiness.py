"""Explicit source admission and bounded formal-progress regressions."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.formal_readiness import derive_formal_readiness
from research_workspace.literature_selection import selection_files
from stage1_brief.formal_target import prepare_formal_intake, submit_formal_target
from stage1_deliverable.common import DeliverableError, canonical, sha
from test_research_brief import brief
from test_research_brief_formal_target import answer
from test_research_workspace_literature_selection import attached_index
from test_research_workspace_source_rerun_exports import RAW, TEXT


class FormalReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary, self.index = attached_index()
        self.addCleanup(temporary.cleanup)
        self.brief = prepare_formal_intake(
            brief("unrestricted"),
            project_id=self.index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        submitted = answer(1)
        submitted.update(
            project_id=self.index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        self.brief = submit_formal_target(self.brief, submitted)
        self.brief["needs"] = [
            {"need_id": "synthetic-need", "question": "Synthetic source need?"}
        ]

    def qualified_index(
        self,
        *,
        coverage_status=None,
        coverage_evidence=True,
        finding_changes=None,
        **changes,
    ):
        def qualified(index):
            target = index["papers"][0]
            target["input_version"] = "fresh-1"
            declaration = {
                "status": "qualified",
                "work_id": target["work_id"],
                "version_id": target["version_id"],
                "source_id": "source-0",
                "raw_sha256": sha(RAW["source-0"]),
                "text_sha256": sha(TEXT["source-0"]),
                "identity_checked": True,
                "body_checked": True,
                "reading_order_checked": True,
                "relevance_checked": True,
                "evidence_refs": ["synthetic-review:1"],
            }
            declaration.update(changes)
            target["fresh_note"] = {
                "paper_note_status": "complete",
                "source_qualification": declaration,
            }
            target["findings"] = {
                name: "Substantial synthetic source evidence."
                for name in (
                    "question",
                    "data",
                    "method",
                    "main_findings",
                    "limitations",
                    "relevance",
                )
            }
            target["findings"].update(finding_changes or {})
            if coverage_status is not None:
                index["coverage"][0]["status"] = coverage_status
                if coverage_status == "qualified":
                    index["coverage"][0]["work_ids"] = [target["work_id"]]
                    if coverage_evidence:
                        index["coverage"][0]["evidence_refs"] = [
                            "synthetic-need-review:1"
                        ]

        temporary, index = attached_index(base_change=qualified)
        self.addCleanup(temporary.cleanup)
        return index

    def test_technical_fulltext_stays_formally_pending(self):
        report = derive_formal_readiness(self.index, self.brief)
        self.assertEqual(report["technical_eligible_distinct_works"], 1)
        self.assertEqual(report["formally_usable_distinct_works"], 0)
        self.assertEqual(report["decision"], "review-saved-backlog")
        self.assertFalse(report["stage1_completed"])

    def test_checked_source_qualifies_despite_unknown_claim(self):
        index = self.qualified_index(coverage_status="qualified")
        report = derive_formal_readiness(index, self.brief)
        self.assertEqual(report["formally_usable_distinct_works"], 1)
        self.assertEqual(report["note_complete_versions"], 1)
        self.assertEqual(report["decision"], "stop-count-target-and-covered")
        self.assertEqual(index["claims"][0]["support"], "Unknown")

    def test_mismatched_or_incomplete_receipt_fails_closed(self):
        for field, value, message in (
            ("source_id", "wrong", "technically eligible"),
            ("version_id", "wrong", "work/version"),
            ("raw_sha256", "a" * 64, "raw_sha256"),
            ("body_checked", False, "body_checked"),
            ("reading_order_checked", False, "reading_order_checked"),
        ):
            with self.subTest(field=field):
                index = self.qualified_index(**{field: value})
                with self.assertRaisesRegex(DeliverableError, message):
                    derive_formal_readiness(index, self.brief)

    def test_note_pending_is_separate_from_formal_admission(self):
        index = self.qualified_index(finding_changes={"method": "Unknown"})
        report = derive_formal_readiness(index, self.brief)
        self.assertEqual(report["formally_usable_distinct_works"], 1)
        self.assertEqual(report["note_complete_versions"], 0)
        self.assertEqual(report["note_pending_versions"], 2)

    def test_coverage_precedes_stop_and_backlog_precedes_search(self):
        index = self.qualified_index()
        report = derive_formal_readiness(
            index,
            self.brief,
            resources={
                "queries": {"used": 0, "limit": 2},
                "acquisitions": {"used": 0, "limit": 2},
            },
        )
        self.assertEqual(report["decision"], "coverage-directed-work")
        index = self.index
        self.assertEqual(
            derive_formal_readiness(
                index,
                self.brief,
                resources={
                    "queries": {"used": 0, "limit": 2},
                    "acquisitions": {"used": 0, "limit": 2},
                },
            )["decision"],
            "review-saved-backlog",
        )

    def test_exhausted_and_malformed_resources(self):
        def missing_extent(manifest):
            manifest["data"]["rows"][0]["reading"]["diagnostics"] = {}

        temporary, index = attached_index(change=missing_extent)
        self.addCleanup(temporary.cleanup)
        exhausted = {
            "queries": {"used": 2, "limit": 2},
            "acquisitions": {"used": 0, "limit": 2},
        }
        self.assertEqual(
            derive_formal_readiness(index, self.brief, resources=exhausted)["decision"],
            "diagnose-saved-backlog",
        )
        with self.assertRaisesRegex(DeliverableError, "resource values invalid"):
            derive_formal_readiness(
                index,
                self.brief,
                resources={
                    "queries": {"used": True, "limit": 2},
                    "acquisitions": {"used": 0, "limit": 2},
                },
            )

    def test_wrong_brief_lineage_rejected(self):
        wrong = deepcopy(self.brief)
        wrong["project_id"] = "wrong-project"
        wrong["formal_final_count"]["decisions"][0]["project_id"] = "wrong-project"
        with self.assertRaisesRegex(DeliverableError, "wrong brief project"):
            derive_formal_readiness(self.index, wrong)

    def test_parser_failure_with_saved_bytes_precedes_resource_decision(self):
        for saved in (True, False):
            for used in (0, 2):
                with self.subTest(saved=saved, used=used):

                    def base_change(index):
                        if not saved:
                            source = index["sources"][0]
                            source["receipt"]["attempts"][0].update(
                                raw_path=None, raw_sha256=None
                            )
                            source["result_sha256"] = sha(canonical(source["receipt"]))

                    def failed(manifest):
                        row = manifest["data"]["rows"][0]
                        manifest["files"].pop(row.pop("extracted_path"))
                        row["reading"].update(
                            status="failed-engineering",
                            evidence_level="metadata",
                            characters=0,
                            text_sha256=None,
                            locators=[],
                            error={
                                "type": "SyntheticError",
                                "message": "parser failure",
                            },
                        )
                        row["reading"]["diagnostics"] = {}
                        if not saved:
                            manifest["files"].pop(row.pop("raw_path"))
                            row.update(
                                raw_sha256=None,
                                source_version=None,
                                selected_sequence=None,
                                final_url=None,
                            )
                            row["attempt_id"] = sha(
                                canonical(
                                    {
                                        "base": manifest["data"]["base_index_sha256"],
                                        "parser": manifest["data"]["parser_runtime"][
                                            "parser_sha256"
                                        ],
                                        "work": row["work_id"],
                                        "version": row["version_id"],
                                        "raw": None,
                                    }
                                )
                            )

                    temporary, index = attached_index(failed, base_change)
                    self.addCleanup(temporary.cleanup)
                    resources = {
                        name: {"used": used, "limit": 2}
                        for name in ("queries", "acquisitions")
                    }
                    report = derive_formal_readiness(
                        index, self.brief, resources=resources
                    )
                    expected = (
                        "diagnose-saved-backlog"
                        if saved
                        else "partial-resource-exhausted"
                        if used == 2
                        else "continue-bounded"
                    )
                    self.assertEqual(report["decision"], expected)
                    self.assertEqual(
                        report["parser_or_identity_distinct_backlog"], int(saved)
                    )

    def test_selection_markdown_identifies_technical_counts(self):
        markdown = selection_files(self.index)["literature/selection.md"].decode(
            "utf-8"
        )
        self.assertTrue(markdown.startswith("# Source selection\n"))
        self.assertIn("Technically eligible versions: 1", markdown)
        self.assertNotIn("Formal literature selection", markdown)

    def test_stale_input_and_missing_need_cannot_finish(self):
        index = self.qualified_index(coverage_status="qualified")
        wrong = deepcopy(self.brief)
        wrong["input_version"] = "stale"
        wrong["formal_final_count"]["decisions"][0]["input_version"] = "stale"
        with self.assertRaisesRegex(DeliverableError, "input version"):
            derive_formal_readiness(index, wrong)
        self.brief["needs"].append({"need_id": "missing", "question": "Another need?"})
        report = derive_formal_readiness(index, self.brief)
        self.assertEqual(report["unresolved_need_ids"], ["missing"])
        self.assertEqual(report["decision"], "coverage-directed-work")

    def test_long_placeholder_is_not_a_complete_note(self):
        index = self.qualified_index(
            finding_changes={"method": "pending; no transfer authorized"}
        )
        self.assertEqual(
            derive_formal_readiness(index, self.brief)["note_complete_versions"], 0
        )

    def test_status_without_qualified_work_evidence_does_not_stop(self):
        index = self.qualified_index(
            coverage_status="qualified", coverage_evidence=False
        )
        report = derive_formal_readiness(index, self.brief)
        self.assertFalse(report["qualified_coverage"])
        self.assertEqual(report["decision"], "coverage-directed-work")

    def test_exhaustion_with_no_saved_backlog_is_partial(self):
        index = self.qualified_index(coverage_status="qualified")
        submitted = answer(30)
        submitted.update(
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        fresh = prepare_formal_intake(
            brief("unrestricted"),
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        fresh = submit_formal_target(fresh, submitted)
        fresh["needs"] = deepcopy(self.brief["needs"])
        resources = {
            name: {"used": 2, "limit": 2} for name in ("queries", "acquisitions")
        }
        report = derive_formal_readiness(index, fresh, resources=resources)
        self.assertEqual(report["target_shortfall"], 29)
        self.assertEqual(report["decision"], "partial-resource-exhausted")


if __name__ == "__main__":
    unittest.main()
