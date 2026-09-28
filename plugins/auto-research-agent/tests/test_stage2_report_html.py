"""Focused tests for the standalone Stage 2 HTML renderer."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from html import unescape
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_check import apply_assessment, export_selection, initialize_run, inspect_run  # noqa: E402
from stage2_common import Stage2Error  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from test_stage2_checker import assessment, finding  # noqa: E402

from stage2_check.report_html import render_selection_html  # noqa: E402


class Stage2HtmlReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _render(self, packet, sources, assessments=()):
        packet_path = self.root / "packet.json"
        run = self.root / "run"
        self._write(packet_path, packet)
        initialize_run(packet_path, sources, run)
        for index, value in enumerate(assessments, 1):
            path = self.root / f"assessment-{index}.json"
            self._write(path, value)
            apply_assessment(run, path)
        state = inspect_run(run)
        selection = export_selection(run)
        rendered = render_selection_html(selection, state["packet"]["sources"])
        return state, selection, rendered

    def test_complete_content_navigation_history_and_statuses(self):
        sources = self.root / "sources"
        packet = write_stage2_fixture(sources, candidate_count=1)
        revise = assessment(packet, disposition="revise")
        revised = copy.deepcopy(packet["candidates"][0])
        revised.update(version=2, parent_version=1, question="Revised exact question")
        revise["revised_candidate"] = revised
        parked = assessment(packet, event_id="check-2", disposition="park", version=2)
        parked["checks"]["answerability"] = finding("unknown", None, evidence_ids=[])
        parked["checks"]["materials"] = finding("not-applicable", None, evidence_ids=[])
        state, selection, raw = self._render(packet, sources, (revise, parked))
        text = raw.decode("utf-8")
        readable = unescape(text)
        self.assertTrue(text.startswith("<!doctype html>"))
        for anchor in (
            "summary",
            "brief",
            "comparison",
            "options",
            "questions",
            "history",
            "sources",
            "audit",
        ):
            self.assertIn(f'href="#{anchor}"', text)
        self.assertIn("<td>unknown</td><td>Unknown</td>", text)
        self.assertIn("<td>not-applicable</td><td>N/A</td>", text)
        self.assertIn("candidate-1 v1", readable)
        self.assertIn("candidate-1 v2", readable)
        self.assertIn("Revised exact question", readable)
        for history in selection["candidate_histories"].values():
            for candidate in history:
                for field in ("question", "opportunity", "value", "approach"):
                    self.assertIn(candidate[field], readable)
        self.assertIn(selection["assessment_history"][0]["event_sha256"], readable)
        self.assertEqual(
            raw, render_selection_html(selection, state["packet"]["sources"])
        )

    def test_hostile_html_uri_and_exact_quote_are_inert(self):
        sources = self.root / "sources-hostile"
        packet = write_stage2_fixture(sources, candidate_count=1)
        hostile = '<script>alert("x")</script><a href="javascript:bad">bad</a>'
        quote = '<img src=x onerror=alert(1)> exact "quote" & evidence'
        source = sources / "source-1.txt"
        raw_source = (quote + "\n").encode("utf-8")
        source.write_bytes(raw_source)
        packet["sources"][0]["sha256"] = hashlib.sha256(raw_source).hexdigest()
        packet["evidence"][0]["quote"] = quote
        packet["candidates"][0]["question"] = hostile
        _, _, raw = self._render(packet, sources)
        text = raw.decode("utf-8")
        self.assertNotIn("<script>", text)
        self.assertNotIn('href="javascript:', text)
        self.assertNotIn("<img src=x", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", text)
        self.assertIn(quote, unescape(text))
        self.assertIn('href="sources/source-1.txt"', text)

    def test_mismatched_source_binding_fails_closed(self):
        sources = self.root / "sources-binding"
        packet = write_stage2_fixture(sources, candidate_count=1)
        state, selection, _ = self._render(packet, sources)
        bad_sources = copy.deepcopy(state["packet"]["sources"])
        bad_sources[0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(Stage2Error, "source-binding-mismatch"):
            render_selection_html(selection, bad_sources)


if __name__ == "__main__":
    unittest.main()
