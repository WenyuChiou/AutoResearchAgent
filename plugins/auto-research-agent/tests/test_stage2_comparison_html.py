"""Presentation invariants for existing records, not scientific score gains."""

from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import json
import unittest

from test_stage2_comparison_view import attachment
from research_workspace.stage2_comparison import build_comparison_view
from research_workspace.stage2_comparison_html import render_comparison_workbench


class PayloadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.payload = ""

    def handle_starttag(self, tag, attrs):
        self.inside = tag == "script" and "data-s2w-view" in dict(attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.payload += data


class Stage2ComparisonHtmlTests(unittest.TestCase):
    def test_exact_qualifications_payload_and_unknowns_survive(self):
        view = build_comparison_view(attachment())
        view["literature"][0]["cells"]["findings"]["text"] = (
            "Saved assertion; audit=partial; not a confirmed premise. " * 8
        )
        before = deepcopy(view)
        html = render_comparison_workbench(view)
        parser = PayloadParser()
        parser.feed(html)
        self.assertEqual(json.loads(parser.payload), view)
        self.assertEqual(view, before)
        self.assertIn(view["literature"][0]["cells"]["findings"]["text"], html)
        self.assertIn("Unknown", html)
        self.assertIn("Original qualifications and judgments remain unchanged", html)
        self.assertNotIn("0/6", html)

    def test_foreign_evidence_work_version_and_source_are_never_displayed(self):
        value = attachment()
        value["selection"]["evaluation_packet"]["evidence"][1].update(
            quote="WRONG VERSION QUOTE"
        )
        value["selection"]["evaluation_packet"]["evidence"][2].update(
            quote="WRONG SOURCE QUOTE"
        )
        html = render_comparison_workbench(build_comparison_view(value))
        visible = html.split('<script type="application/json"', 1)[0]
        self.assertIn("Recorded quote.", visible)
        self.assertNotIn("WRONG VERSION QUOTE", visible)
        self.assertNotIn("WRONG SOURCE QUOTE", visible)
        self.assertIn("not proof for every comparison cell", visible)

    def test_hostile_data_cannot_break_html_or_json_script(self):
        value = build_comparison_view(attachment())
        attack = '</script><img src=x onerror="alert(1)"><script>alert(1)</script>'
        value["literature"][0]["title"] = attack
        value["directions"][0]["question"] = attack
        value["evidence"][0]["quote"] = attack
        value["resources"] = attack
        html = render_comparison_workbench(value)
        self.assertEqual(html.count("<script"), 1)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        parser = PayloadParser()
        parser.feed(html)
        self.assertEqual(json.loads(parser.payload), value)

    def test_table_modes_are_generic_and_legacy_absence_is_explicit(self):
        html = unescape(render_comparison_workbench(build_comparison_view({})))
        for title in ("Research overview", "Concepts & methods", "Detailed evidence"):
            self.assertIn(title, html)
        self.assertIn("No literature records", html)
        self.assertIn("No research directions", html)
        self.assertNotIn("South Korea", html)
        self.assertNotIn("reflection", html)


if __name__ == "__main__":
    unittest.main()
