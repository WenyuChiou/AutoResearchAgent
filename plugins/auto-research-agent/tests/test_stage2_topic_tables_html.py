"""Recorded topic-table presentation without scientific inference."""

from copy import deepcopy
from html import unescape
import unittest

from test_stage2_comparison_view import attachment
from research_workspace.stage2_comparison import build_comparison_view
from research_workspace.stage2_comparison_html import render_comparison_workbench


def prepared_attachment():
    value = attachment()
    packet = value["selection"]["evaluation_packet"]
    packet["literature"] = []
    packet["evidence"] = []
    statuses = (
        "present",
        "described",
        "absent",
        "partial",
        "unknown",
        "not-applicable",
    )
    dimensions = [
        {
            "dimension_id": "topic-measurement",
            "label": "Measurement frame",
            "research_need": "Compare how the topic is measured.",
            "rationale": "Measurement changes interpretation.",
            "definition": "Inspect each recorded operational definition.",
            "value_kind": "feature",
            "conditions": ["Use the paper's own scope."],
            "spans": [],
        },
        {
            "dimension_id": "topic-time",
            "label": "Time horizon",
            "research_need": "Compare the topic-specific time horizon.",
            "rationale": "The brief requires temporal comparability.",
            "definition": "Record the reported duration or uncertainty.",
            "value_kind": "text",
            "conditions": ["Do not infer an unstated duration."],
            "spans": [],
        },
    ]
    work_refs = []
    cells = []
    for index in range(3):
        work_id = f"work-{index + 1}"
        version_id = f"v{index + 1}"
        evidence_id = f"ev-{index + 1}"
        source_id = f"src-{index + 1}"
        packet["literature"].append(
            {
                "work_id": work_id,
                "version_id": version_id,
                "title": f"Topic paper {index + 1}",
                "authors": [f"Author {index + 1}"],
                "year": 2020 + index,
                "roles": [],
                "evidence_level": "full-text",
                "source_ids": [source_id],
                "findings": {},
                "classification": {},
            }
        )
        packet["evidence"].append(
            {
                "evidence_id": evidence_id,
                "source_id": source_id,
                "work_id": work_id,
                "version_id": version_id,
                "locator": f"p. {index + 4}",
                "quote": f"Bound quote {index + 1}.",
                "evidence_level": "full-text",
            }
        )
        work_refs.append({"work_id": work_id, "version_id": version_id})
        for dimension_index, dimension in enumerate(dimensions):
            status = statuses[index * 2 + dimension_index]
            cells.append(
                {
                    "dimension_id": dimension["dimension_id"],
                    "work_id": work_id,
                    "version_id": version_id,
                    "status": status,
                    "value": None if status == "unknown" else f"Recorded {status}",
                    "reason": f"Recorded reason for {status}.",
                    "inspection_scope": "Bounded recorded passage.",
                    "negative_basis": (
                        "explicit-statement" if status == "absent" else None
                    ),
                    "evidence_ids": [] if status == "unknown" else [evidence_id],
                    "spans": [],
                }
            )
    packet["research_tables"] = {
        "kind": "Stage2ResearchTables",
        "schema_version": "1.0.0",
        "brief_sha256": "1" * 64,
        "input_packet_sha256": "2" * 64,
        "input_snapshot_sha256": "3" * 64,
        "raw_proposal": "Recorded proposal.",
        "raw_proposal_sha256": "4" * 64,
        "dimensions": dimensions,
        "work_refs": work_refs,
        "cells": cells,
        "direction_resources": [
            {
                "resource_id": "resource-current",
                "candidate_id": "candidate-1",
                "candidate_version": 2,
                "category": "dataset",
                "name": "Current dataset",
                "purpose": "Measure the current direction.",
                "url": "https://example.test/current",
                "version": "2026.1",
                "required": True,
                "status": "available",
                "access_conditions": "Registration required.",
                "license": "Recorded license",
                "cost_basis": "Recorded cost basis",
                "limitations": ["Recorded limitation"],
                "alternatives": ["Recorded alternative"],
                "evidence_ids": ["ev-1"],
                "checked_at": "2026-10-06T12:00:00Z",
                "spans": [],
            },
            {
                "resource_id": "resource-old",
                "candidate_id": "candidate-1",
                "candidate_version": 1,
                "category": "tool",
                "name": "Old-version tool",
                "purpose": "Recorded for the old candidate.",
                "url": "javascript:alert(1)",
                "version": None,
                "required": False,
                "status": "unknown",
                "access_conditions": None,
                "license": None,
                "cost_basis": None,
                "limitations": [],
                "alternatives": [],
                "evidence_ids": [],
                "checked_at": None,
                "spans": [],
            },
        ],
    }
    packet["evidence"].append(
        {
            "evidence_id": "ev-wrong-source",
            "source_id": "src-not-bound-to-work",
            "work_id": "work-1",
            "version_id": "v1",
            "locator": "p. 99",
            "quote": "FOREIGN SOURCE QUOTE",
            "evidence_level": "full-text",
        }
    )
    packet["research_tables"]["cells"][0]["evidence_ids"].append("ev-wrong-source")
    return value


class Stage2TopicTablesHtmlTests(unittest.TestCase):
    def test_provenance_notes_are_collapsed_and_preserve_unknown_language(self):
        html = render_comparison_workbench(build_comparison_view(prepared_attachment()))
        opening_tag = html.split('<details class="s2w-notes"', 1)[1].split(">", 1)[0]
        notes = html.split('<details class="s2w-notes"', 1)[1].split("</details>", 1)[0]

        self.assertNotIn(" open", opening_tag)
        self.assertIn("Provenance and interpretation notes", notes)
        self.assertIn("Source level does not verify every field", notes)
        self.assertIn("missing fields stay Unknown", notes)
        self.assertIn("Access does not certify feasibility", notes)
        self.assertIn('aria-label="Status: Unknown"', html)

    def test_view_deepcopies_research_tables_and_renders_dynamic_axes_and_statuses(
        self,
    ):
        value = prepared_attachment()
        original = deepcopy(value)
        view = build_comparison_view(value)
        view["research_tables"]["dimensions"][0]["label"] = "View-only change"
        self.assertEqual(value, original)

        html = unescape(render_comparison_workbench(build_comparison_view(value)))
        self.assertIn("Measurement frame", html)
        self.assertIn("Time horizon", html)
        self.assertIn("How papers are assessed", html)
        for label in (
            "Present",
            "Absent",
            "Partial",
            "Described",
            "Unknown",
            "Not applicable",
        ):
            self.assertIn(f'aria-label="Status: {label}"', html)
        self.assertIn("✓", html)
        self.assertIn("✕", html)
        self.assertIn("Bound quote 1.", html)
        visible = html.split('<script type="application/json"', 1)[0]
        self.assertNotIn("FOREIGN SOURCE QUOTE", visible)
        self.assertIn("Topic paper 3", html)

    def test_resources_match_current_version_and_keep_history_separate(self):
        html = unescape(
            render_comparison_workbench(build_comparison_view(prepared_attachment()))
        )
        current = html.split("Current direction · candidate-1 · version 2", 1)[1]
        current = current.split("Historical candidate-version associations", 1)[0]
        self.assertIn("Current dataset", current)
        self.assertNotIn("Old-version tool", current)
        self.assertIn("older or non-current candidate versions", html)
        self.assertIn("Old-version tool", html)
        self.assertIn('href="https://example.test/current"', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn("javascript:alert(1)", html)

    def test_legacy_null_tables_have_explicit_unprepared_state(self):
        value = attachment()
        value["selection"]["evaluation_packet"]["research_tables"] = None
        html = render_comparison_workbench(build_comparison_view(value))
        self.assertIn("Topic comparison is unprepared", html)
        self.assertIn(
            "No comparison cells or feature statuses have been inferred", html
        )
        self.assertIn("Research overview", html)
        self.assertIn("Exact packet-level comparison", html)

    def test_malformed_resource_urls_are_readable_without_links(self):
        for url in (
            "https://[bad",
            "https://[not-ipv6]/",
            "https://example.\uff0fcom/",
        ):
            with self.subTest(url=url):
                value = prepared_attachment()
                resources = value["selection"]["evaluation_packet"]["research_tables"][
                    "direction_resources"
                ]
                resources[0]["url"] = url
                html = render_comparison_workbench(build_comparison_view(value))
                self.assertIn(url, unescape(html))
                self.assertNotIn('href="' + url + '"', html)

    def test_hostile_table_content_is_escaped_and_never_becomes_authority(self):
        value = prepared_attachment()
        attack = '</script><img src=x onerror="alert(1)"><script>alert(1)</script>'
        tables = value["selection"]["evaluation_packet"]["research_tables"]
        tables["dimensions"][0]["label"] = attack
        tables["cells"][0]["reason"] = attack
        tables["direction_resources"][0]["name"] = attack
        tables["direction_resources"][0]["url"] = "JaVaScRiPt:alert(2)"
        html = render_comparison_workbench(build_comparison_view(value))
        visible = html.split('<script type="application/json"', 1)[0]
        self.assertNotIn("<img", visible)
        self.assertIn("&lt;img", visible)
        self.assertNotIn('href="JaVaScRiPt:', visible)
        self.assertNotIn("onclick=", visible)


if __name__ == "__main__":
    unittest.main()
