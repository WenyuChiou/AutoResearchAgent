"""Localized reading controls preserve the saved research and its authority."""

# ruff: noqa: E402 -- use the authored, zero-model delivery fixture.
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).parents[1] / "cli"), str(Path(__file__).parent)]
import test_project_stage2_reading as reading_fixture
from stage2_workflow.decision_card_views import render_decision_cards_html
from stage2_workflow.decision_cards import derive_decision_cards


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


class Stage2ReadingLocaleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = reading_fixture.Stage2ReadingTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_three_fixed_pages_preserve_sources_and_return_language(self):
        before = reading_fixture.delivery_fixture._tree_hash(self.fixture.delivery)
        assets, refs = self.fixture.registry().snapshot()
        prefix = "/project-stage2-readings/saved-report/"
        cases = [
            ("en", "index.html", "Return to workspace", "Stage 2 decision cards"),
            ("zh-Hant", "index.zh-Hant.html", "返回工作台", "Stage 2 方向決策卡"),
            ("zh-Hans", "index.zh-Hans.html", "返回工作台", "Stage 2 方向决策卡"),
        ]
        for language, name, back, title in cases:
            with self.subTest(language=language):
                page = assets[prefix + name].decode()
                self.assertIn(f'<html lang="{language}">', page)
                self.assertIn(back, page)
                self.assertIn(title, page)
                self.assertNotIn("<form", page)
                self.assertNotIn("<script", page)
                parsed = _Links()
                parsed.feed(page)
                self.assertIn(
                    {"href": f"/projects.html#stage2-reading-language={language}"},
                    parsed.links,
                )
                locale_links = [row for row in parsed.links if "hreflang" in row]
                self.assertEqual(
                    {row["hreflang"] for row in locale_links}, {row[0] for row in cases}
                )
                self.assertEqual(
                    sum(row.get("aria-current") == "page" for row in locale_links), 1
                )
        self.assertNotIn(prefix + "index.fr.html", assets)
        self.assertEqual(refs[0]["recommendation_count"], 0)
        self.assertFalse(refs[0]["selection_authority"])
        for name in ("selection.json", "selection.md"):
            self.assertEqual(
                assets[prefix + name], (self.fixture.delivery / name).read_bytes()
            )
        self.assertEqual(
            before, reading_fixture.delivery_fixture._tree_hash(self.fixture.delivery)
        )
        self.assertEqual(self.fixture.projects.list(self.fixture.token), [])

    def test_only_fixed_labels_change_not_matching_research_words(self):
        selection = reading_fixture.json.loads(
            (self.fixture.delivery / "selection.json").read_bytes()
        )
        cards = deepcopy(derive_decision_cards(selection))
        cards["cards"][0]["candidate_question"] = "Scientific questions"
        original = deepcopy(cards)
        page = render_decision_cards_html(
            cards, ui_text={"Scientific questions": "科學問題", "Limitations": "限制"}
        )
        self.assertIn("<h3>科學問題</h3>", page)
        self.assertIn("<h3>限制</h3>", page)
        self.assertIn(
            "<strong>Candidate question:</strong> Scientific questions</p>", page
        )
        self.assertEqual(cards, original)
        escaped = render_decision_cards_html(
            cards, ui_text={"Scientific questions": "<script>not markup</script>"}
        )
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;script&gt;not markup&lt;/script&gt;", escaped)


if __name__ == "__main__":
    unittest.main()
