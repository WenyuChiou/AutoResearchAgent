"""Readable, inert projections of an authenticated Stage 2 attachment."""

import copy
from html import unescape
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from research_workspace.stage2_presentation import (  # noqa: E402
    render_stage2_card,
    stage2_wiki_notes,
)


_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "stage2_evaluation_fixture",
    Path(__file__).with_name("test_stage2_report_evaluation.py"),
)
evaluation_fixture = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(evaluation_fixture)


def attachment():
    evaluation = evaluation_fixture.completed_view()
    evaluation["evaluation_status"] = "audit-required"
    evaluation["rows"][0] = evaluation_fixture.row(
        evaluation_fixture.CRITERIA[0], 1, disagreement=True, adj=True
    )
    evaluation["rows"][1] = evaluation_fixture.row(evaluation_fixture.CRITERIA[1], None)
    evaluation["rows"][0]["final"]["audit_status"] = "named-audit-pending"
    evaluation["dimensions"] = evaluation_fixture.dimensions_for(evaluation["rows"])
    return {
        "kind": "WorkspaceStage2Attachment",
        "schema_version": "1.0.0",
        "project_id": "project-1",
        "stage1_index_sha256": "a" * 64,
        "bridge_receipt": {"receipt_id": "bridge-1"},
        "selection": {
            "current_options": [
                {
                    "candidate": {
                        "candidate_id": "direction-1",
                        "version": 4,
                        "question": "Can the bounded direction be answered with the recorded materials?",
                    },
                    "assessment": {
                        "disposition": "park",
                        "reason": "The direction awaits a bounded materials check.",
                        "checks": {
                            "materials": {
                                "status": "unknown",
                                "score": None,
                                "rationale": "Dataset access remains unknown.",
                                "evidence_ids": [],
                                "blocking": True,
                                "next_check": "Confirm the license and retained variables.",
                            }
                        },
                    },
                }
            ],
            "evaluation_packet": {
                "resources": "Use fixed compute; licensed data access is unknown."
            },
        },
        "evaluation": evaluation,
    }


class Stage2PresentationTests(unittest.TestCase):
    def test_card_keeps_disposition_materials_and_all_comments_visible(self):
        value = attachment()
        rendered = unescape(render_stage2_card(value))
        self.assertIn('<section id="stage2-delivery">', rendered)
        question = "Can the bounded direction be answered with the recorded materials?"
        self.assertIn(question, rendered)
        self.assertLess(rendered.index(question), rendered.index("direction-1 v4"))
        self.assertIn("Parked pending more evidence or resources", rendered)
        self.assertIn("Dataset access remains unknown.", rendered)
        self.assertIn(
            "<p>Use fixed compute; licensed data access is unknown.</p>", rendered
        )
        self.assertNotIn('class="stage2-resources"', rendered)
        self.assertIn("Named audit pending", rendered)
        self.assertIn("provisional", rendered)
        self.assertIn("P4</th><td>Unknown (2/3 criteria assessed)", rendered)
        self.assertIn("P5</th><td>50.0% (3/6) (provisional)", rendered)
        self.assertIn("Provisional recorded evaluation", rendered)
        self.assertNotIn("Final recorded evaluation", rendered)
        self.assertNotIn("Total", rendered)
        self.assertEqual(rendered.count('<details class="stage2-criterion">'), 9)
        for criterion_id in evaluation_fixture.CRITERIA:
            self.assertIn(criterion_id, rendered)
            self.assertIn(f"R1 reason for {criterion_id}", rendered)
            self.assertIn(f"R2 reason for {criterion_id}", rendered)
        self.assertIn(f"ADJ reason for {evaluation_fixture.CRITERIA[0]}", rendered)
        self.assertIn("evidence unavailable", rendered)
        self.assertIn('href="stage2/report-reader.html#source-ev-1"', rendered)

    def test_zero_materials_score_stays_blocking_without_availability_claim(self):
        value = attachment()
        material = value["selection"]["current_options"][0]["assessment"]["checks"][
            "materials"
        ]
        material.update(
            status="assessed",
            score=0,
            blocking=True,
            rationale="The required variable is absent from the bound snapshot.",
            next_check=None,
        )
        rendered = unescape(render_stage2_card(value))
        self.assertIn(
            "assessed — feasibility support 0/2; blocks detailed design", rendered
        )
        self.assertIn(
            "The required variable is absent from the bound snapshot.", rendered
        )
        self.assertNotIn("materials available", rendered.lower())
        self.assertNotIn(": available", rendered.lower())

    def test_final_unknown_confidence_reason_and_evidence_are_preserved(self):
        value = attachment()
        final_unknown = value["evaluation"]["rows"][1]["final"]
        final_unknown.update(
            rationale="Distinct final unknown rationale.",
            confidence="low",
            unknown_reason="Distinct final source gap.",
        )
        final_evidence = value["evaluation"]["rows"][0]["final"]["evidence_refs"][0]
        final_evidence.update(
            evidence_id="final-evidence",
            locator="final page 7",
            href="#final-evidence",
        )
        rendered = unescape(render_stage2_card(value))
        self.assertIn("Distinct final unknown rationale.", rendered)
        self.assertIn("<dt>Confidence</dt><dd>low</dd>", rendered)
        self.assertIn(
            "<dt>Unknown reason</dt><dd>Distinct final source gap.</dd>", rendered
        )
        self.assertIn("final-evidence — final page 7", rendered)
        self.assertIn('href="stage2/report-reader.html#final-evidence"', rendered)

    def test_hostile_source_text_is_escaped_and_only_fixed_links_are_clickable(self):
        value = attachment()
        attack = '<script>alert("owned")</script><a href="https://bad">bad</a>'
        value["selection"]["current_options"][0]["assessment"]["reason"] = attack
        value["selection"]["current_options"][0]["candidate"]["question"] = attack
        value["selection"]["evaluation_packet"]["resources"] = attack
        value["evaluation"]["rows"][0]["judges"]["R1"]["rationale"] = attack
        value["evaluation"]["rows"][0]["judges"]["R1"]["evidence_refs"][0]["href"] = (
            "sources/untrusted.html"
        )
        rendered = render_stage2_card(value)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn('<a href="https://bad">', rendered)
        self.assertNotIn('href="sources/untrusted.html"', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        hrefs = re.findall(r'<a href="([^"]+)">', rendered)
        self.assertTrue(hrefs)
        self.assertTrue(
            all(
                href == "stage2/selection.md"
                or href.startswith("stage2/report-reader.html")
                for href in hrefs
            )
        )
        self.assertIn('href="stage2/report-reader.html"', rendered)
        self.assertIn('href="stage2/selection.md"', rendered)

    def test_notes_are_deterministic_canonical_and_do_not_mutate_attachment(self):
        value = attachment()
        value["selection"]["raw_comment"] = "```` hostile fence\nnull stays null"
        original = copy.deepcopy(value)
        first = stage2_wiki_notes(value)
        second = stage2_wiki_notes(value)
        self.assertEqual(first, second)
        self.assertEqual(value, original)
        self.assertEqual(
            set(first),
            {
                "stage2/README.md",
                "stage2/workspace-attachment.json",
                "stage2/report-reader.html",
                "stage2/report-reader.js",
            },
        )
        self.assertEqual(json.loads(first["stage2/workspace-attachment.json"]), value)
        self.assertEqual(
            first["stage2/workspace-attachment.json"],
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        readme = first["stage2/README.md"].decode("utf-8")
        for text in (
            "Private, read-only",
            "no approval",
            "Stage 3 authorization",
            "formal-improvement claim",
            "licensed data access is unknown",
            '"score": null',
            '"version": 4',
            "R1 reason for P4V3.FIDELITY",
        ):
            self.assertIn(text, readme)
        self.assertIn("`````\n", readme)

    def test_original_report_reader_has_no_source_script_authority(self):
        files = stage2_wiki_notes(attachment())
        reader = files["stage2/report-reader.html"].decode("utf-8")
        script = files["stage2/report-reader.js"].decode("utf-8")
        self.assertIn('<iframe sandbox="" src="selection.html"', reader)
        self.assertNotIn("allow-scripts", reader)
        self.assertNotIn("allow-same-origin", reader)
        self.assertNotIn("allow-popups", reader)
        self.assertIn('report.src = "selection.html" + window.location.hash', script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
