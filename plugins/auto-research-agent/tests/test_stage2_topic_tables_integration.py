"""Synthetic binding E2E; no live research, scientific attestation or selection."""

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cli"))

import test_stage1_stage2_handoff as upstream_fixture  # noqa: E402
from stage2_check import inspect_run  # noqa: E402
from stage2_check.run import build_selection  # noqa: E402
from stage2_check.report import render_proposal  # noqa: E402
from stage2_check.report_html import render_selection_html  # noqa: E402
from stage2_common import Stage2Error, canonical_hash, validate_packet  # noqa: E402
from stage2_eval.evaluation_v3 import prepare_content_view_v3  # noqa: E402
from stage2_ideation.__main__ import main  # noqa: E402
from stage2_ideation.integration import build_next_packet  # noqa: E402
from stage2_ideation.prompts import build_extraction_task, build_research_task  # noqa: E402
from stage2_ideation.report import (  # noqa: E402
    build_proposal_view,
    render_proposal_html,
    render_proposal_markdown,
)
from stage2_live.extraction import (  # noqa: E402
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_workflow import initialize_workflow, inspect_workflow, add_snapshot  # noqa: E402
from research_workspace.stage2_comparison import build_comparison_view  # noqa: E402
from research_workspace.stage2_comparison_html import render_comparison_workbench  # noqa: E402
from test_stage2_topic_tables import candidate  # noqa: E402


RAW = "\n".join(
    [
        "Compare scenario representation because the brief asks about consumption.",
        "The synthetic source describes a scenario; its duration is unknown.",
        "Propose a bounded comparison; empirical effectiveness remains unknown.",
        "Reports and data can inform the comparison but access has not been checked.",
    ]
)


def _span(quote):
    start = RAW.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote}


def fixture_extraction(packet, snapshot):
    task = build_extraction_task(RAW, packet, snapshot)
    axis_span = _span(RAW.splitlines()[0])
    source_span = _span(RAW.splitlines()[1])
    resources = []
    for category in ("dataset", "report", "reference", "model", "tool"):
        resources.append(
            {
                "resource_id": "resource-" + category,
                "candidate_index": 0,
                "category": category,
                "name": "Synthetic " + category,
                "purpose": "Inform the bounded comparison; not an access claim.",
                "url": "https://example.org/" + category,
                "version": None,
                "required": category == "dataset",
                "status": "unknown",
                "access_conditions": None,
                "license": None,
                "cost_basis": None,
                "limitations": ["Access and fit remain unknown"],
                "alternatives": ["Check an alternative if unavailable"],
                "evidence_ids": [],
                "checked_at": None,
                "spans": [_span(RAW.splitlines()[3])],
            }
        )
    c = candidate()
    c["evidence_ids"] = [packet["evidence"][0]["evidence_id"]]
    return {
        "kind": "Stage2IdeationExtraction",
        "schema_version": "1.1.0",
        "snapshot_sha256": snapshot,
        "packet_sha256": task["packet_sha256"],
        "raw_proposal_sha256": task["raw_proposal_sha256"],
        "input_hash": task["input_hash"],
        "receipt": {
            "policy_boundary": "declared-task-policy",
            "tools_policy": "none",
            "tool_calls": [],
            "isolation_verified": False,
        },
        "bibliography": [],
        "comparison_rows": [],
        "candidates": [
            {
                "candidate": c,
                "route": "improvement",
                "mechanism": "Compare the scenario representation.",
                "closest_work_refs": [],
                "strong_alternatives": ["Keep current measure"],
                "change_mind_conditions": ["No distinguishable observation exists"],
                "claim_labels": [
                    {
                        "text": "Benefit untested",
                        "status": "untested-benefit",
                        "evidence_ids": [],
                    }
                ],
                "spans": [_span(RAW.splitlines()[2])],
            }
        ],
        "unresolved": ["Resources and duration remain unknown"],
        "research_tables": {
            "dimensions": [
                {
                    "dimension_id": "scenario",
                    "label": "Scenario representation",
                    "research_need": packet["brief"]["needs"][0]["question"],
                    "rationale": "The brief concerns scenario-dependent consumption.",
                    "definition": "Inspect the recorded scenario statement.",
                    "value_kind": "feature",
                    "conditions": ["Synthetic fixture only"],
                    "spans": [axis_span],
                },
                {
                    "dimension_id": "duration",
                    "label": "Scenario duration",
                    "research_need": "Check whether time horizons are comparable.",
                    "rationale": "A horizon can change interpretation.",
                    "definition": "Record duration or preserve unknown.",
                    "value_kind": "quantity",
                    "conditions": [],
                    "spans": [axis_span],
                },
            ],
            "work_refs": [{"work_id": "work1", "version_id": "v1"}],
            "cells": [
                {
                    "dimension_id": "scenario",
                    "work_id": "work1",
                    "version_id": "v1",
                    "status": "present",
                    "value": True,
                    "reason": "Recorded scenario statement; semantic interpretation still needs review.",
                    "inspection_scope": "Saved synthetic excerpt",
                    "negative_basis": None,
                    "evidence_ids": [packet["evidence"][0]["evidence_id"]],
                    "spans": [source_span],
                },
                {
                    "dimension_id": "duration",
                    "work_id": "work1",
                    "version_id": "v1",
                    "status": "unknown",
                    "value": None,
                    "reason": "No duration checked; inspect design next.",
                    "inspection_scope": None,
                    "negative_basis": None,
                    "evidence_ids": [],
                    "spans": [source_span],
                },
            ],
            "direction_resources": resources,
        },
    }


class Stage2TopicTablesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.upstream = upstream_fixture.Stage1Stage2HandoffTests()
        self.upstream.setUp()
        self.addCleanup(self.upstream.doCleanups)
        self.upstream.build()
        self.root = self.upstream.root
        self.sources = self.upstream.output
        self.original = self.upstream.packet()
        self.packet = copy.deepcopy(self.original)
        self.packet.update(schema_version="2.2.0", research_tables=None)
        self.seed_path = self.root / "tables-seed.json"
        self.seed_path.write_text(json.dumps(self.packet), encoding="utf-8")

    def workflow(self):
        path = self.root / "workflow"
        initialize_workflow(
            self.seed_path,
            self.sources,
            path,
            {},
            {},
            expected_packet_sha256=canonical_hash(self.packet),
        )
        state = inspect_workflow(path)
        snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        return path, state, snapshot

    def prepared(self, snapshot="a" * 64):
        extraction = fixture_extraction(self.packet, snapshot)
        result = build_next_packet(self.packet, self.sources, RAW, extraction, snapshot)
        validate_packet(result["packet"], self.sources)
        return result["packet"], extraction

    def test_seed_command_preserves_input_and_does_not_promote(self):
        original_path = self.sources / "packet.json"
        original_bytes = original_path.read_bytes()
        output = self.root / "enabled.json"
        stream = io.StringIO()
        arguments = [
            "enable-tables",
            "--packet",
            str(original_path),
            "--source-root",
            str(self.sources),
            "--output",
            str(output),
        ]
        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(arguments), 0)
        receipt = json.loads(stream.getvalue())
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(value, self.packet)
        self.assertEqual(original_path.read_bytes(), original_bytes)
        self.assertTrue(receipt["requires_new_run"])
        self.assertFalse(receipt["scientific_quality_verified"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(arguments), 2)

    def test_native_generation_restores_spans_and_assigns_resource_candidate_version(
        self,
    ):
        index = build_span_index(RAW)
        schema = generation_schema(index, self.packet)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1.0")
        generated = fixture_extraction(self.packet, "a" * 64)
        candidate_row = generated["candidates"][0]
        candidate_row["existing_candidate_id"] = None
        for key in ("candidate_id", "version", "parent_version"):
            candidate_row["candidate"].pop(key)
        for row in [
            candidate_row,
            *generated["research_tables"]["dimensions"],
            *generated["research_tables"]["cells"],
            *generated["research_tables"]["direction_resources"],
        ]:
            row["spans"] = [
                {
                    "span_id": next(
                        s["span_id"]
                        for s in index["spans"]
                        if row["spans"][0]["quote"] in s["quote"]
                    )
                }
            ]
        expanded = expand_span_ids(generated, RAW, index, self.packet)
        result = build_next_packet(self.packet, self.sources, RAW, expanded, "a" * 64)
        tables = result["packet"]["research_tables"]
        self.assertEqual(
            tables["direction_resources"][0]["candidate_id"],
            expanded["candidates"][0]["candidate"]["candidate_id"],
        )
        self.assertEqual(tables["raw_proposal"], RAW)
        generated["research_tables"]["cells"][0]["spans"] = [{"span_id": "foreign"}]
        with self.assertRaises(ValueError):
            expand_span_ids(generated, RAW, index, self.packet)

    def test_seed_extraction_snapshot_checked_proposal_and_wiki_use_same_tables(self):
        path, state, snapshot = self.workflow()
        packet, extraction = self.prepared(snapshot)
        next_path = self.root / "next.json"
        next_path.write_text(json.dumps(packet), encoding="utf-8")
        add_snapshot(
            path,
            next_path,
            self.sources,
            "Synthetic topic-table preparation",
            {
                "candidate-table": {
                    "status": "affected",
                    "reason": "New candidate and tables need independent checks",
                }
            },
            state["head_sha256"],
        )
        inspected = inspect_workflow(path)
        self.assertEqual(len(inspected["snapshots"]), 2)
        checker_root = path / "snapshots/000002/checker"
        checker = inspect_run(checker_root)
        selection = build_selection(checker)
        projected = build_comparison_view({"selection": selection})
        self.assertEqual(projected["research_tables"], packet["research_tables"])
        wiki = render_comparison_workbench(projected)
        markdown = render_proposal(
            selection,
            checker["packet"]["sources"],
            event_head=checker["event_head_sha256"],
            stored_packet_sha256=checker["manifest"]["stored_packet_sha256"],
        ).decode()
        html = render_selection_html(selection, checker["packet"]["sources"]).decode()
        draft = build_proposal_view(
            self.packet, self.sources, RAW, extraction, snapshot
        )
        for rendered in (
            wiki,
            markdown,
            html,
            render_proposal_markdown(draft).decode(),
            render_proposal_html(draft).decode(),
        ):
            self.assertIn("Scenario representation", rendered)
            self.assertIn("Synthetic dataset", rendered)
            self.assertIn("Unknown" if rendered != markdown else "unknown", rendered)
        self.assertIn('href="https://example.org/dataset"', html)
        self.assertFalse(draft["validation_boundary"]["scientific_validity_verified"])

    def test_wrong_table_parent_hash_is_rejected_before_journal_changes(self):
        path, state, snapshot = self.workflow()
        packet, _ = self.prepared(snapshot)
        before = state["head_sha256"]
        for field in ("input_snapshot_sha256", "input_packet_sha256"):
            changed = copy.deepcopy(packet)
            changed["research_tables"][field] = "b" * 64
            target = self.root / (field + ".json")
            target.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(
                Stage2Error, "parent-(packet|snapshot)-mismatch"
            ):
                add_snapshot(
                    path,
                    target,
                    self.sources,
                    "Wrong parent",
                    {"candidate-table": {"status": "affected", "reason": "New"}},
                    before,
                )
            self.assertEqual(inspect_workflow(path)["head_sha256"], before)

    def test_canonical_resources_show_required_and_malformed_urls_without_links(self):
        from stage2_ideation.tables_report import (
            render_tables_html,
            render_tables_markdown,
        )

        packet, _ = self.prepared()
        tables = packet["research_tables"]
        yes_html = render_tables_html(tables, packet)
        yes_md = render_tables_markdown(tables, packet)
        self.assertNotIn("present · True", yes_html)
        self.assertNotIn("present · True", yes_md)
        tables["direction_resources"][0]["required"] = False
        no_html = render_tables_html(tables, packet)
        no_md = render_tables_markdown(tables, packet)
        self.assertIn("Required", yes_html)
        self.assertIn("Required", yes_md)
        self.assertNotEqual(yes_html, no_html)
        self.assertNotEqual(yes_md, no_md)
        for url in (
            "https://[bad",
            "https://[not-ipv6]/",
            "https://example.\uff0fcom/",
        ):
            with self.subTest(url=url):
                tables["direction_resources"][0]["url"] = url
                rendered = render_tables_html(tables, packet)
                self.assertIn(url, rendered)
                self.assertNotIn('href="' + url + '"', rendered)
                self.assertIn(
                    url, render_tables_markdown(tables, packet).replace("\\", "")
                )

    def test_old_run_cannot_change_packet_version_in_place(self):
        old = self.sources / "packet.json"
        path = self.root / "old-workflow"
        initialize_workflow(
            old,
            self.sources,
            path,
            {},
            {},
            expected_packet_sha256=canonical_hash(self.original),
        )
        state = inspect_workflow(path)
        with self.assertRaisesRegex(Stage2Error, "version-change-requires-new-run"):
            add_snapshot(
                path,
                self.seed_path,
                self.sources,
                "Invalid in-place opt-in",
                {},
                state["head_sha256"],
            )

    def test_research_task_keeps_native_tools_and_topic_axes_are_not_fixed(self):
        task = build_research_task(self.packet, "a" * 64)
        self.assertEqual(task["tools_policy"], "native")
        self.assertIn("research", task["prompt"])
        self.assertNotIn("South Korea", task["prompt"])
        self.assertIn("research_tables_contract", task["prompt"])

    def test_quantity_cells_render_numbers_and_reject_nonfinite_values(self):
        extraction = fixture_extraction(self.packet, "a" * 64)
        cell = extraction["research_tables"]["cells"][1]
        cell.update(
            status="described",
            value=12,
            reason="Synthetic numeric binding test",
            inspection_scope="Synthetic excerpt",
            evidence_ids=[self.packet["evidence"][0]["evidence_id"]],
        )
        result = build_next_packet(self.packet, self.sources, RAW, extraction, "a" * 64)
        from stage2_ideation.tables_report import render_tables_html

        self.assertIn(
            "described · 12",
            render_tables_html(result["packet"]["research_tables"], result["packet"]),
        )
        for value in (True, "twelve", float("nan")):
            cell["value"] = value
            with self.assertRaises((Stage2Error, ValueError)):
                build_next_packet(self.packet, self.sources, RAW, extraction, "a" * 64)

    def test_judge_content_includes_tables_without_internal_decisions_or_raw_receipts(
        self,
    ):
        packet, _ = self.prepared()
        view = prepare_content_view_v3(packet, "opaque-subject", "a" * 64, "b" * 64)
        content = view["scientific_content"]
        self.assertEqual(content["topic_comparison"]["cells"][1]["status"], "unknown")
        self.assertEqual(len(content["direction_resources"]), 5)
        self.assertEqual(content["literature"], packet["literature"])
        for key in (
            "raw_proposal",
            "input_snapshot_sha256",
            "internal_score",
            "disposition",
            "spans",
        ):
            self.assertNotIn('"' + key + '"', json.dumps(content))
        legacy = prepare_content_view_v3(
            self.original, "opaque-subject", "a" * 64, "b" * 64
        )
        self.assertNotIn("topic_comparison", legacy["scientific_content"])


if __name__ == "__main__":
    unittest.main()
