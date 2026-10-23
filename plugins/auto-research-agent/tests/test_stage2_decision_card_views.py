"""Readable and escaped views for Stage 2 decision cards."""

import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_workflow.decision_card_views import (  # noqa: E402
    render_decision_cards_html,
    render_decision_cards_markdown,
)
from stage2_workflow.decision_cards import derive_decision_cards  # noqa: E402
import test_stage2_decision_cards as decision_fixtures  # noqa: E402


class _TagCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class Stage2DecisionCardViewTests(unittest.TestCase):
    def selection(self):
        fixture = decision_fixtures.Stage2DecisionCardsTests(
            "test_current_version_mapping_preserves_recorded_metadata"
        )
        return fixture.selection()

    def test_views_show_every_question_unknown_and_unused_resources(self):
        cards = derive_decision_cards(self.selection())

        markdown = render_decision_cards_markdown(cards)
        html = render_decision_cards_html(cards)

        for question in (
            "What explains question-mapped?",
            "What explains question-unmapped?",
            "What explains question-unknown?",
        ):
            self.assertIn(question, markdown)
            self.assertIn(question, html)
        self.assertIn("Resource resource-unused", markdown)
        self.assertIn("Resource resource-unused", html)
        self.assertIn("Access remains unknown", markdown)
        self.assertIn("Access remains unknown", html)
        self.assertIn("does not exist", markdown)
        self.assertIn("does not establish feasibility or availability", html)
        for text in (
            "Required: false",
            "Question-specific purpose: Evaluate the recorded relation.",
            "Resource purpose: Recorded purpose only.",
            "License: Not recorded",
            "Cost basis: Cost unknown",
            "Checked at: Not recorded",
            "Question evidence IDs: evidence-fit",
            "Resource evidence IDs: evidence-resource",
            "Resource-ref source: scientific\_argument.resource\_refs\[0\]",
            "Resource source: evaluation\_packet.research\_tables.direction\_resources\[1\]",
        ):
            self.assertIn(text, markdown)
        for label in (
            "Required",
            "Question-specific purpose",
            "Resource purpose",
            "License",
            "Cost basis",
            "Checked at",
            "Question evidence IDs",
            "Resource evidence IDs",
            "Resource-ref source",
            "Resource source",
        ):
            self.assertIn(f"<dt>{label}</dt>", html)
        for detail in (
            "<dt>Required</dt><dd>false</dd>",
            "<dt>Question-specific purpose</dt><dd>Evaluate the recorded relation.</dd>",
            "<dt>Resource purpose</dt><dd>Recorded purpose only.</dd>",
            "<dt>License</dt><dd>Not recorded</dd>",
            "<dt>Cost basis</dt><dd>Cost unknown</dd>",
            "<dt>Checked at</dt><dd>Not recorded</dd>",
            "<dt>Question evidence IDs</dt><dd>evidence-fit</dd>",
            "<dt>Resource evidence IDs</dt><dd>evidence-resource</dd>",
        ):
            self.assertIn(detail, html)

    def test_unknown_and_unassigned_contributions_retain_status_without_links(self):
        selection = self.selection()
        claims = selection["current_options"][0]["candidate"]["scientific_argument"][
            "contribution_claims"
        ]
        claims[0]["status"] = "unknown"
        claims.append(
            {
                "text": "Unassigned <claim> remains unknown.",
                "question_ids": [],
                "status": "unknown",
            }
        )
        cards = derive_decision_cards(selection)

        markdown = render_decision_cards_markdown(cards)
        html = render_decision_cards_html(cards)

        self.assertIn("### Unassigned contribution claims", markdown)
        self.assertIn("Unassigned &lt;claim&gt; remains unknown.", markdown)
        self.assertIn("Status: unknown", markdown)
        self.assertIn("Question IDs: Not recorded", markdown)
        self.assertIn("<h3>Unassigned contribution claims</h3>", html)
        self.assertIn("Unassigned &lt;claim&gt; remains unknown.", html)
        self.assertGreaterEqual(html.count("<dt>Status</dt><dd>unknown</dd>"), 2)
        self.assertIn("<dt>Question IDs</dt><dd>Not recorded</dd>", html)

    def test_html_escapes_all_attacker_text_and_contains_no_script(self):
        selection = self.selection()
        attack = '<script>alert("x")</script><img src=x onerror=alert(2)>'
        candidate = selection["current_options"][0]["candidate"]
        candidate["question"] = attack
        candidate["scientific_argument"]["questions"][0]["text"] = attack
        candidate["scientific_argument"]["contribution_claims"][0]["text"] = attack
        selection["evaluation_packet"]["research_tables"]["direction_resources"][1][
            "name"
        ] = attack
        selection["evaluation_packet"]["research_tables"]["direction_resources"][1][
            "url"
        ] = "javascript:alert(3)"

        rendered = render_decision_cards_html(derive_decision_cards(selection))
        collector = _TagCollector()
        collector.feed(rendered)

        self.assertNotIn("script", [tag for tag, _ in collector.tags])
        self.assertNotIn("img", [tag for tag, _ in collector.tags])
        self.assertFalse(any("onerror" in attrs for _, attrs in collector.tags))
        self.assertNotIn("href=", rendered.lower())
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", rendered)
        self.assertIn("javascript:alert(3)", rendered)

    def test_legacy_candidate_renders_explicit_not_recorded_state(self):
        selection = self.selection()
        del selection["current_options"][0]["candidate"]["scientific_argument"]
        cards = derive_decision_cards(selection)

        markdown = render_decision_cards_markdown(cards)
        html = render_decision_cards_html(cards)

        self.assertIn("Scientific argument:** not-recorded", markdown)
        self.assertIn(
            "No scientific questions are recorded for this candidate version.",
            markdown,
        )
        self.assertIn("Scientific argument:</strong> not-recorded", html)
        self.assertIn("Resource resource-current", html)

    def test_rendering_is_deterministic_and_does_not_mutate_cards(self):
        cards = derive_decision_cards(self.selection())
        original = copy.deepcopy(cards)

        markdown = render_decision_cards_markdown(cards)
        html = render_decision_cards_html(cards)

        self.assertEqual(markdown, render_decision_cards_markdown(cards))
        self.assertEqual(html, render_decision_cards_html(cards))
        self.assertEqual(cards, original)


if __name__ == "__main__":
    unittest.main()
