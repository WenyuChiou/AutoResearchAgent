"""Validated prior-work reviews stay candidate-bound across delivery views."""
# ruff: noqa: E402 -- load repository CLI and existing synthetic fixtures.

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote


HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from research_workspace.stage2_comparison import build_comparison_view
from research_workspace.stage2_comparison_html import render_comparison_workbench
from research_workspace.stage2_presentation import render_stage2_card
from stage2_check import apply_assessment, export_selection, initialize_run, inspect_run
from stage2_check.report import render_proposal
from stage2_check.report_html import render_selection_html
from stage2_common import (
    Stage2Error,
    canonical_hash,
    source_set_hash,
    validate_packet,
)
from stage2_eval.evaluation_v3 import (
    merge_judgments_v3,
    prepare_action_view_v3,
    prepare_content_view_v3,
)
from stage2_workflow.evaluation_delivery import build_evaluated_delivery
from test_stage2_checker import assessment
from test_stage2_evaluation_v3 import content_assessment, judge
import test_stage2_topic_tables_integration as topic_fixture


_EVALUATION_SPEC = importlib.util.spec_from_file_location(
    "stage2_evaluation_fixture",
    HERE / "test_stage2_report_evaluation.py",
)
evaluation_fixture = importlib.util.module_from_spec(_EVALUATION_SPEC)
_EVALUATION_SPEC.loader.exec_module(evaluation_fixture)


def _private_temp_root():
    """Keep upstream fixtures outside a repository without assuming a drive."""
    root = Path(tempfile.gettempdir()).resolve()
    if not any((parent / ".git").exists() for parent in (root, *root.parents)):
        return root
    fallback = Path(root.anchor) / ("temp" if root.drive else "tmp")
    fallback.mkdir(exist_ok=True)
    return fallback.resolve()


class Stage2PriorWorkDeliveryTests(unittest.TestCase):
    def setUp(self):
        upstream = topic_fixture.Stage2TopicTablesIntegrationTests()
        with mock.patch.object(tempfile, "tempdir", str(_private_temp_root())):
            upstream.setUp()
        self.addCleanup(upstream.doCleanups)
        self.root = upstream.root
        self.sources = upstream.sources
        packet, _ = upstream.prepared()
        packet["schema_version"] = "2.4.0"
        packet.setdefault("supplemental_literature", [])
        self.candidate = max(
            packet["candidates"], key=lambda row: (row["candidate_id"], row["version"])
        )
        self.work = packet["literature"][0]
        self.evidence = next(
            row
            for row in packet["evidence"]
            if row["work_id"] == self.work["work_id"]
            and row["version_id"] == self.work["version_id"]
            and row["evidence_level"] != "metadata"
        )
        self.receipt_path = "prior-work/search-1.json"
        self.query = "closest method <script>query()</script>"
        receipt = {
            "query": self.query,
            "tool_ref": "saved-tool-call-1",
            "outcome": "results",
            "work_refs": [
                {
                    "work_id": self.work["work_id"],
                    "version_id": self.work["version_id"],
                }
            ],
            "raw_output": {"untrusted": "<script>raw()</script>"},
        }
        raw = json.dumps(receipt, sort_keys=True).encode("utf-8")
        target = self.sources / self.receipt_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        review = {
            "kind": "Stage2PriorWorkReview",
            "schema_version": "1.0.0",
            "candidate_id": self.candidate["candidate_id"],
            "candidate_version": self.candidate["version"],
            "candidate_sha256": canonical_hash(self.candidate),
            "source_set_sha256": source_set_hash(packet),
            "positioning": "Bounded <script>position()</script> precedent positioning.",
            "review_status": "bounded-complete",
            "stop_reason": "The declared query and source limits were reached.",
            "search_limits": ["One database; records through the saved cutoff."],
            "unresolved": ["Direct provider access remains unavailable."],
            "searches": [
                {
                    "search_id": "search-1",
                    "need": "Locate the closest recorded method.",
                    "query": self.query,
                    "status": "executed",
                    "tool_ref": receipt["tool_ref"],
                    "raw_path": self.receipt_path,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "outcome": receipt["outcome"],
                    "work_refs": receipt["work_refs"],
                }
            ],
            "comparisons": [
                {
                    "work_id": self.work["work_id"],
                    "version_id": self.work["version_id"],
                    "role": "closest",
                    "established": "The saved excerpt establishes the recorded baseline.",
                    "overlap": "Both use the recorded bounded comparison.",
                    "difference": "The candidate changes <img src=x onerror=bad()> handling.",
                    "evidence_ids": [self.evidence["evidence_id"]],
                    "limitations": ["The excerpt does not prove field-wide novelty."],
                }
            ],
        }
        packet["prior_work_reviews"] = [review]
        review["source_set_sha256"] = source_set_hash(packet)
        validate_packet(packet, self.sources)
        packet_path = self.root / "packet-2.4.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        self.run = self.root / "checker-2.4"
        initialize_run(
            packet_path,
            self.sources,
            self.run,
            expected_packet_sha256=canonical_hash(packet),
        )
        check = assessment(packet, disposition="park")
        check.update(
            candidate_id=self.candidate["candidate_id"],
            candidate_version=self.candidate["version"],
        )
        for finding in check["checks"].values():
            finding["evidence_ids"] = [self.evidence["evidence_id"]]
        check_path = self.root / "assessment-2.4.json"
        check_path.write_text(json.dumps(check), encoding="utf-8")
        apply_assessment(self.run, check_path)
        self.state = inspect_run(self.run)
        self.selection = export_selection(self.run)
        self.snapshots = self.state["packet"]["sources"]

    def _markdown(self, selection=None):
        return render_proposal(
            selection or self.selection,
            self.snapshots,
            event_head=self.state["event_head_sha256"],
            stored_packet_sha256=self.state["manifest"]["stored_packet_sha256"],
            receipt_prefix="prior_work_receipts",
        ).decode("utf-8")

    def _attachment(self, selection=None):
        return {
            "kind": "WorkspaceStage2Attachment",
            "schema_version": "1.0.0",
            "project_id": "prior-work-test",
            "stage1_index_sha256": "a" * 64,
            "bridge_receipt": {
                "human_selection": "pending",
                "stage3_authorized": False,
            },
            "selection": selection or self.selection,
            "evaluation": evaluation_fixture.completed_view(),
        }

    def _evaluation_bundle(self):
        packet = self.selection["evaluation_packet"]
        content = prepare_content_view_v3(
            packet, "anonymous", canonical_hash(self.selection), "a" * 64
        )
        initial = content_assessment(
            content, evidence_ids=[self.evidence["evidence_id"]]
        )
        action = prepare_action_view_v3(
            packet, content, initial, self.selection["action_record"]
        )
        judgments = {
            role: judge(content, action, packet, role) for role in ("R1", "R2")
        }
        for judgment in judgments.values():
            for row in judgment["criteria"]:
                row["evidence_ids"] = [self.evidence["evidence_id"]]
        merged = merge_judgments_v3(
            judgments["R1"], judgments["R2"], content, action, packet
        )
        return {
            "kind": "Stage2EvaluationBundle",
            "schema_version": "3.0.0",
            "status": "complete",
            "core_selection_sha256": canonical_hash(self.selection),
            "sources_sha256": canonical_hash(packet["sources"]),
            "rubric_sha256": content["rubric_sha256"],
            "content_view": content,
            "judgments": judgments,
            "action_views": {role: action for role in judgments},
            "merged": merged,
        }

    def test_markdown_html_and_wiki_share_bound_review_and_limits(self):
        markdown = self._markdown()
        html = render_selection_html(
            self.selection,
            self.snapshots,
            receipt_prefix="prior_work_receipts",
        ).decode("utf-8")
        wiki = render_stage2_card(self._attachment())
        identity = f"{self.candidate['candidate_id']} v{self.candidate['version']}"
        work_version = f"{self.work['work_id']} / {self.work['version_id']}"
        for rendered in (markdown, html, wiki):
            readable = rendered.replace("\\", "")
            self.assertIn(identity, readable)
            self.assertIn(work_version, readable)
            self.assertIn("bounded-complete", readable)
            self.assertIn("One database; records through the saved cutoff.", readable)
            self.assertIn("Direct provider access remains unavailable.", readable)
            self.assertIn(self.evidence["locator"], readable)
            self.assertIn(self.evidence["evidence_level"], readable)
            self.assertIn("The excerpt does not prove field-wide novelty.", readable)
        self.assertIn("Search queries and saved receipts", markdown)
        self.assertIn("Search scope, raw queries, evidence receipts and limits", wiki)
        self.assertIn("prior_work_receipts/prior-work/search-1.json", html)
        self.assertIn("prior-work/search-1.json", wiki)
        self.assertNotIn('href="prior-work/search-1.json"', wiki)
        self.assertNotIn("2/2", markdown)
        self.assertNotIn("2/2", html)

    def test_html_views_escape_untrusted_review_and_query_content(self):
        html = render_selection_html(
            self.selection,
            self.snapshots,
            receipt_prefix="prior_work_receipts",
        ).decode("utf-8")
        wiki = render_comparison_workbench(build_comparison_view(self._attachment()))
        for rendered in (html, wiki):
            self.assertNotIn("<script>position()</script>", rendered)
            self.assertNotIn("<script>query()</script>", rendered)
            self.assertNotIn("<img src=x onerror=bad()>", rendered)
            self.assertIn("&lt;script&gt;position()&lt;/script&gt;", rendered)
            self.assertIn("&lt;script&gt;query()&lt;/script&gt;", rendered)
            self.assertIn("&lt;img src=x onerror=bad()&gt;", rendered)

    def test_stale_candidate_binding_fails_all_direct_projections(self):
        stale = copy.deepcopy(self.selection)
        stale["evaluation_packet"]["candidates"][-1]["question"] += " changed"
        stale["current_options"][-1]["candidate"]["question"] += " changed"
        for render in (
            lambda: self._markdown(stale),
            lambda: render_selection_html(
                stale, self.snapshots, receipt_prefix="prior_work_receipts"
            ),
            lambda: build_comparison_view(self._attachment(stale)),
        ):
            with self.subTest(render=render):
                with self.assertRaisesRegex(
                    Stage2Error, "prior-work candidate hash mismatch"
                ):
                    render()

    def test_wiki_retains_all_independent_reviewer_reasons(self):
        rendered = render_stage2_card(self._attachment())
        for criterion_id in evaluation_fixture.CRITERIA:
            self.assertIn(f"R1 reason for {criterion_id}", rendered)
            self.assertIn(f"R2 reason for {criterion_id}", rendered)
        self.assertIn("Prior-work positioning", rendered)

    def test_legacy_projection_has_no_prior_work_surface(self):
        legacy = copy.deepcopy(self.selection)
        packet = legacy["evaluation_packet"]
        packet["schema_version"] = "2.3.0"
        packet.pop("prior_work_reviews")
        view = build_comparison_view(self._attachment(legacy))
        self.assertNotIn("prior_work_reviews", view)
        self.assertTrue(
            all("prior_work_review" not in row for row in view["directions"])
        )

    def test_checker_and_evaluated_receipt_links_resolve_inside_delivery(self):
        checker_markdown = (self.run / "selection.md").read_text(encoding="utf-8")
        checker_href = re.search(
            r"\]\(([^)]+prior-work/search-1\.json)\)", checker_markdown
        ).group(1)
        self.assertEqual(
            unquote(checker_href), "prior_work_receipts/prior-work/search-1.json"
        )
        self.assertTrue((self.run / Path(unquote(checker_href))).is_file())

        bundle = self._evaluation_bundle()
        output = self.root / "evaluated-prior-work"
        source_snapshots = [
            {**row, "path": "sources/" + row["path"]}
            for row in self.selection["evaluation_packet"]["sources"]
        ]
        build_evaluated_delivery(
            self.selection,
            source_snapshots,
            self.sources,
            bundle,
            output,
            expected_bundle_sha256=canonical_hash(bundle),
            event_head=self.state["event_head_sha256"],
            stored_packet_sha256=self.state["manifest"]["stored_packet_sha256"],
        )
        markdown = (output / "selection.md").read_text(encoding="utf-8")
        html = (output / "selection.html").read_text(encoding="utf-8")
        markdown_href = re.search(
            r"\]\(([^)]+prior-work/search-1\.json)\)", markdown
        ).group(1)
        html_href = re.search(
            r'<a href="([^"]+)">prior-work/search-1\.json</a>', html
        ).group(1)
        for href in (markdown_href, html_href):
            self.assertEqual(unquote(href), "sources/prior-work/search-1.json")
            self.assertTrue((output / Path(unquote(href))).is_file())

    def test_receipt_links_require_an_explicit_safe_artifact_prefix(self):
        html = render_selection_html(self.selection, self.snapshots).decode("utf-8")
        self.assertIn("<code>prior-work/search-1.json</code>", html)
        self.assertNotIn('href="prior-work/search-1.json"', html)
        for prefix in ("", "../outside", "C:/absolute", "bad\\path"):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(Stage2Error, "unsafe-report-source-path"):
                    render_selection_html(
                        self.selection, self.snapshots, receipt_prefix=prefix
                    )


if __name__ == "__main__":
    unittest.main()
