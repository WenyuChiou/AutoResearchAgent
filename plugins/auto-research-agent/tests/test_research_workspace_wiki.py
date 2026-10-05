"""Neutral, lossless and injection-safe private Wiki rendering checks."""

from copy import deepcopy
import json
from pathlib import PurePosixPath
import unittest

from markdown_it import MarkdownIt

import test_research_workspace_view as fixture
from research_workspace.wiki import FINDINGS, wiki_files
from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.views import bibtex


def bind_bibliography(index):
    index["bibliography"]["all_bibtex"] = bibtex(index).decode()
    index["bibliography"]["entries"] = [
        {
            "work_id": paper["work_id"],
            "version_id": paper["version_id"],
            "bibtex": bibtex({"papers": [paper]}).decode(),
        }
        for paper in index["papers"]
    ]


class WorkspaceWikiTests(unittest.TestCase):
    def test_safe_identity_paths_equal_titles_and_duplicate_rejection(self):
        index = fixture.fixture_index()
        for paper in index["papers"]:
            paper["title"] = "Same title"
        index["papers"][0]["work_id"] = "../../escape/CON"
        index["papers"][0]["version_id"] = "\\unsafe:<version>"
        bind_bibliography(index)
        output = wiki_files(index)
        self.assertEqual(len(output), 3)
        for paper in index["papers"]:
            name = sha(canonical([paper["work_id"], paper["version_id"]])) + ".md"
            path = "wiki/" + name
            self.assertIn(path, output)
            self.assertRegex(name, r"^[0-9a-f]{64}\.md$")
            self.assertEqual(PurePosixPath(path).parts, ("wiki", name))
        index["papers"].append(dict(index["papers"][0], title="Changed title"))
        with self.assertRaisesRegex(DeliverableError, "duplicate work/version"):
            wiki_files(index)

    def test_lossless_findings_bindings_relationships_and_no_mutation(self):
        index = fixture.fixture_index()
        paper = index["papers"][0]
        paper["findings"] = {key: "Original " + key + "\n研究" for key, _ in FINDINGS}
        paper["claim_ids"] = ["claim-neutral"]
        index["claims"] = [{"claim_id": "claim-neutral", "relation": "partial"}]
        index["edges"] = [
            {
                "type": "claim-source",
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "relation": "unverified",
                "reason": "Recorded reason",
                "provenance": {
                    "path": "deliverable/records.original.json",
                    "sha256": "0" * 64,
                    "pointer": "/claims/0",
                },
            }
        ]
        index["screening"] = [{"work_id": paper["work_id"], "decision": "unknown"}]
        before = deepcopy(index)
        output = wiki_files(index)
        self.assertEqual(output, wiki_files(index))
        self.assertEqual(index, before)
        note = next(
            value.decode() for key, value in output.items() if key != "wiki/README.md"
        )
        blocks = [
            token.content for token in MarkdownIt().parse(note) if token.type == "fence"
        ]
        structured = [
            json.loads(text) for text in blocks if text.startswith(("{", "["))
        ]
        self.assertIn(paper, structured)
        self.assertIn(index["claims"], structured)
        self.assertIn(index["edges"], structured)
        self.assertIn(index["sources"], structured)
        self.assertIn(index["screening"], structured)
        binding = structured[0]
        self.assertEqual(binding["pointer"], "/papers/0")
        self.assertEqual(binding["sha256"], index["provenance"]["records_sha256"])
        self.assertEqual(binding["claim_ids"], paper["claim_ids"])
        for text in paper["findings"].values():
            self.assertIn(text + "\n", blocks)

    def test_untrusted_markdown_cannot_escape_fences_and_missing_is_explicit(self):
        index = fixture.fixture_index()
        hostile = "Original\n````````\n# Injected\n<script>alert(1)</script>\n`````"
        index["papers"][0]["title"] = hostile
        index["papers"][0]["findings"] = {"question": hostile, "data": None}
        index["audit_documents"] = [
            {"path": hostile, "sha256": "0" * 64, "text": hostile}
        ]
        bind_bibliography(index)
        output = wiki_files(index)
        bodies = []
        for content in output.values():
            tokens = MarkdownIt().parse(content.decode())
            self.assertFalse(
                any(token.type in {"html_block", "html_inline"} for token in tokens)
            )
            self.assertFalse(
                any(
                    token.type == "inline" and "Injected" in token.content
                    for token in tokens
                )
            )
            bodies.extend(token.content for token in tokens if token.type == "fence")
        self.assertIn(hostile + "\n", bodies)
        self.assertIn("Not recorded\n", bodies)


if __name__ == "__main__":
    unittest.main()
