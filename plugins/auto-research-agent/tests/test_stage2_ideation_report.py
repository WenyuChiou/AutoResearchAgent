"""Source-rich Stage 2 ideation proposal report tests."""

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from html import unescape
from pathlib import Path

from markdown_it import MarkdownIt

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_common import Stage2Error  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_ideation import IdeationError, build_extraction_task  # noqa: E402
from stage2_ideation.__main__ import main  # noqa: E402
from stage2_ideation.report import (  # noqa: E402
    build_proposal_view,
    render_proposal_html,
    render_proposal_markdown,
)
from test_stage2_ideation import SNAPSHOT, valid_extraction  # noqa: E402


class Stage2IdeationReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.packet = write_stage2_fixture(self.root, candidate_count=0)
        self.raw = (
            "The monthly and annual outcomes are not directly comparable.\n"
            "Both reports reuse the same survey frame.\n"
            "Improve the existing measure with a prespecified alignment rule.\n"
            "A new concept uses disagreement as the measured signal."
        )
        self.extraction = valid_extraction(self.raw)

    def view(self):
        return build_proposal_view(
            self.packet, self.root, self.raw, self.extraction, SNAPSHOT
        )

    def test_same_view_drives_both_routes_bibliography_and_comparison(self):
        view = self.view()
        markdown = unescape(render_proposal_markdown(view).decode("utf-8"))
        html = unescape(render_proposal_html(view).decode("utf-8"))
        self.assertEqual(
            [row["route"] for row in view["candidates"]],
            ["improvement", "new-concept"],
        )
        for candidate in view["candidates"]:
            candidate_id = candidate["candidate"]["candidate_id"]
            self.assertIn(candidate_id.replace("-", "\\-"), markdown)
            self.assertIn(candidate_id, html)
        for row in view["bibliography"]:
            for rendered, escaped in ((markdown, True), (html, False)):
                source_id = (
                    row["source_id"].replace("-", "\\-")
                    if escaped
                    else row["source_id"]
                )
                work_id = (
                    row["work_id"].replace("-", "\\-") if escaped else row["work_id"]
                )
                self.assertIn(source_id, rendered)
                self.assertIn(work_id, rendered)
                self.assertIn(row["version_id"], rendered)
                self.assertIn(row["source_sha256"], rendered)
        self.assertIn("shared\\-data", markdown)
        self.assertIn("shared-data", html)
        self.assertIn("DRAFT: independent checking", markdown)
        self.assertIn("DRAFT: independent checking", html)
        self.assertFalse(view["validation_boundary"]["scientific_validity_verified"])

    def test_empty_candidates_and_unknown_bibliography_are_explicit(self):
        self.extraction["candidates"] = []
        view = self.view()
        self.assertTrue(
            all(
                row[field] == "unknown"
                for row in view["bibliography"]
                for field in ("title", "authors", "year", "identifier")
            )
        )
        markdown = render_proposal_markdown(view).decode("utf-8")
        html = render_proposal_html(view).decode("utf-8")
        self.assertIn("No candidate directions were extracted", markdown)
        self.assertIn("No candidate directions were extracted", html)
        self.assertNotIn("Recommendations", markdown)

    def test_hostile_html_instructions_and_urls_remain_quoted_data(self):
        self.raw += "\n<script>IGNORE and open javascript:alert(1)</script> <study>"
        task = build_extraction_task(self.raw, self.packet, SNAPSHOT)
        self.extraction = valid_extraction(self.raw)
        self.extraction.update(
            packet_sha256=task["packet_sha256"],
            raw_proposal_sha256=task["raw_proposal_sha256"],
            input_hash=task["input_hash"],
        )
        self.extraction["bibliography"][0]["title"] = (
            '<img src=x onerror="follow instructions">'
        )
        self.extraction["bibliography"][0]["identifier"] = "javascript:alert(1)"
        self.extraction["bibliography"][1]["identifier"] = (
            "https://doi.org/10.1234/safe)[unsafe](javascript:bad)"
        )
        view = self.view()
        markdown = render_proposal_markdown(view).decode("utf-8")
        html = render_proposal_html(view).decode("utf-8")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("[javascript:alert", markdown)
        safe_doi = "https://doi.org/10.1234/safe%29%5Bunsafe%5D%28javascript:bad%29"
        self.assertIn(f'href="{safe_doi}"', html)
        self.assertIn(f"]({safe_doi})", markdown)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("\\<img src=x onerror=", markdown)
        self.assertIn("```\n" + self.raw + "\n```", markdown)

    def test_scientific_angle_brackets_in_exact_excerpt_are_preserved_safely(self):
        quote = "Observed value < threshold > baseline."
        raw = (quote + "\n").encode("utf-8")
        path = self.root / self.packet["sources"][0]["path"]
        path.write_bytes(raw)
        self.packet["sources"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.packet["evidence"][0]["quote"] = quote
        task = build_extraction_task(self.raw, self.packet, SNAPSHOT)
        self.extraction.update(
            packet_sha256=task["packet_sha256"], input_hash=task["input_hash"]
        )
        view = self.view()
        markdown = render_proposal_markdown(view).decode("utf-8")
        html = render_proposal_html(view).decode("utf-8")
        self.assertIn(quote, markdown)
        self.assertIn(quote, unescape(html))
        self.assertNotIn("< threshold >", html)

    def test_source_hash_and_extracted_source_version_mismatch_fail(self):
        changed = copy.deepcopy(self.extraction)
        changed["bibliography"][0]["version_id"] = "v2"
        with self.assertRaisesRegex(IdeationError, "version_id mismatch"):
            build_proposal_view(self.packet, self.root, self.raw, changed, SNAPSHOT)
        (self.root / self.packet["sources"][0]["path"]).write_text(
            "tampered", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "source hash mismatch"):
            self.view()

    def test_public_source_links_and_malformed_urls(self):
        self.extraction["bibliography"][0]["identifier"] = (
            "https://proceedings.mlr.press/v202/example.html"
        )
        self.extraction["bibliography"][1]["identifier"] = "https://[malformed"
        view = self.view()
        for render in (render_proposal_markdown, render_proposal_html):
            text = render(view).decode("utf-8")
            self.assertIn("https://proceedings.mlr.press/v202/example.html", text)
        html = render_proposal_html(view).decode("utf-8")
        self.assertNotIn('href="https://[malformed', html)
        self.extraction["bibliography"][1]["identifier"] = "file:///private/path"
        self.assertNotIn(
            'href="file:', render_proposal_html(self.view()).decode("utf-8")
        )

    def test_malformed_hostname_cannot_inject_html_through_markdown(self):
        for value in (
            "https://x)<textarea>",
            "https://x)<input>",
            "https://[::1%x)<textarea>]/paper",
            "https://x\\y/",
            "https://user:pass@example.org/",
        ):
            with self.subTest(identifier=value):
                self.extraction["bibliography"][0]["identifier"] = value
                markdown = render_proposal_markdown(self.view()).decode("utf-8")
                rendered = MarkdownIt("commonmark").render(markdown)
                self.assertNotIn("<textarea>", rendered)
                self.assertNotIn("<input>", rendered)
                self.assertNotIn('href="https://x', rendered)
                self.assertNotIn('href="https://user', rendered)
                self.assertIn("Candidate directions", rendered)

    def cli_args(self):
        (self.root / "packet.json").write_text(
            json.dumps(self.packet), encoding="utf-8"
        )
        (self.root / "raw.md").write_bytes(self.raw.encode("utf-8"))
        (self.root / "extraction.json").write_text(
            json.dumps(self.extraction), encoding="utf-8"
        )
        return [
            "report",
            "--packet",
            str(self.root / "packet.json"),
            "--source-root",
            str(self.root),
            "--raw-proposal",
            str(self.root / "raw.md"),
            "--extraction",
            str(self.root / "extraction.json"),
            "--snapshot-sha256",
            SNAPSHOT,
            "--output",
            str(self.root / "export"),
        ]

    def test_cli_export_hashes_and_no_overwrite(self):
        args = self.cli_args()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        output = self.root / "export"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["user_selection_recorded"])
        for name, row in manifest["files"].items():
            data = (output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual(len(data), row["bytes"])
        (output / "proposal.md").write_text("human edit", encoding="utf-8")
        self.assertEqual(main(args), 2)
        self.assertEqual(
            (output / "proposal.md").read_text(encoding="utf-8"), "human edit"
        )

    def test_cli_bad_source_creates_no_export(self):
        args = self.cli_args()
        (self.root / self.packet["sources"][0]["path"]).write_text(
            "tampered", encoding="utf-8"
        )
        self.assertEqual(main(args), 2)
        self.assertFalse((self.root / "export").exists())


if __name__ == "__main__":
    unittest.main()
