"""Shared bibliography projection and direct-renderer binding tests."""
# ruff: noqa: E402 -- import the repository CLI without installing a package.

import copy
import json
import re
import sys
import tempfile
import unittest
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from stage2_check import export_selection, initialize_run, inspect_run
from stage2_check.report import render_proposal
from stage2_check.report_html import render_selection_html
from stage2_common import Stage2Error, stage1_projection_hash
from stage2_fixture_helpers import write_stage2_fixture


def _work(index, *, level, claim_ids=(), roles=()):
    return {
        "origin": "stage1",
        "work_id": f"work-{index}",
        "version_id": "v1",
        "title": "Bound study <one>" if index == 1 else "Saved metadata-only source",
        "authors": ["Ada <Author>" if index == 1 else "Metadata Author"],
        "year": 2024 if index == 1 else None,
        "venue": "Journal & Venue",
        "doi": "10.1000/example" if index == 1 else None,
        "url": "https://example.org/paper"
        if index == 1
        else "https://example.org/metadata",
        "evidence_level": level,
        "classification": dict.fromkeys(
            (
                "topic_cluster",
                "method",
                "geography",
                "population",
                "data_type",
                "domain",
            ),
            "Synthetic test classification",
        ),
        "findings": dict.fromkeys(
            (
                "question",
                "data",
                "method",
                "main_findings",
                "limitations",
                "relevance",
                "transferability",
            ),
            "Synthetic test content; no scientific conclusion",
        ),
        "source_ids": [f"src-{index}"],
        "claim_ids": list(claim_ids),
        "roles": list(roles),
    }


def with_v2_bibliography(selection, snapshots):
    """Build the reusable v2 report fixture for saved Markdown/HTML examples."""
    selection, snapshots = copy.deepcopy(selection), copy.deepcopy(snapshots)
    packet = selection["evaluation_packet"]
    packet["schema_version"] = "2.0.0"
    for row in [*packet["sources"], *snapshots, *packet["evidence"]]:
        row["origin"] = "stage1"
    packet["evidence"] = packet["evidence"][:1]
    packet["sources"][0]["evidence_level"] = "abstract"
    snapshots[0]["evidence_level"] = "abstract"
    packet["sources"][1]["evidence_level"] = "metadata"
    snapshots[1]["evidence_level"] = "metadata"
    role = {
        "role": "closest-work",
        "reason": "Recorded comparator <only>; not semantic proof.",
        "claim_ids": ["ev-1"],
    }
    packet["literature"] = [
        _work(1, level="full-text", claim_ids=["ev-1"], roles=[role]),
        _work(2, level="metadata"),
    ]
    packet["upstream"] = {
        "stage1_literature_sha256": stage1_projection_hash(packet["literature"])
    }
    return selection, snapshots


class Stage2BibliographyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        sources, run = root / "sources", root / "run"
        packet = write_stage2_fixture(sources, candidate_count=1)
        packet_path = root / "packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        initialize_run(packet_path, sources, run)
        state = inspect_run(run)
        self.selection, self.snapshots = with_v2_bibliography(
            export_selection(run), state["packet"]["sources"]
        )

    def test_valid_imported_v2_packet_exports_a_readable_bound_bibliography(self):
        from test_stage1_stage2_handoff import Stage1Stage2HandoffTests

        upstream = Stage1Stage2HandoffTests()
        upstream.setUp()
        self.addCleanup(upstream.doCleanups)
        receipt = upstream.build()
        run = upstream.root / "report-run"
        initialize_run(
            upstream.output / "packet.json",
            upstream.output,
            run,
            expected_packet_sha256=receipt["packet_sha256"],
        )
        selection = export_selection(run)
        snapshots = inspect_run(run)["packet"]["sources"]
        html = render_selection_html(selection, snapshots).decode()
        self.assertIn("Synthetic household research", html)
        self.assertIn("Synthetic Author", html)
        self.assertIn("topic-core", html)
        self.assertRegex(html, r'href="#[^"]+">claim1</a>')
        self.assertNotIn("not recorded in this v1 packet", html)

    def _rebind(self, selection=None):
        packet = (selection or self.selection)["evaluation_packet"]
        packet["upstream"]["stage1_literature_sha256"] = stage1_projection_hash(
            packet["literature"]
        )

    def _markdown(self):
        return render_proposal(
            self.selection,
            self.snapshots,
            event_head="0" * 64,
            stored_packet_sha256="1" * 64,
        ).decode()

    def test_v2_metadata_role_uncited_source_and_hostile_values_share_projection(self):
        work = self.selection["evaluation_packet"]["literature"][0]
        work["title"] = '<script>alert("title")</script>'
        work["url"] = "javascript:alert(1)"
        work["roles"][0]["reason"] = '<a href="javascript:bad">reason</a>'
        self._rebind()
        markdown = self._markdown()
        html = render_selection_html(self.selection, self.snapshots).decode()
        readable_markdown = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", markdown).replace(
            "\\", ""
        )
        readable_html = unescape(re.sub(r"<[^>]*>", "", html))
        for value in (
            "javascript:alert(1)",
            "closest-work",
            "claims=ev-1",
            "Saved metadata-only source",
            "src-1 (level=abstract)",
            "src-2 (level=metadata)",
        ):
            self.assertIn(value, readable_markdown)
            self.assertIn(value, readable_html)
        self.assertIn("Recorded work evidence level: full-text", readable_markdown)
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('href="https://doi.org/10.1000/example"', html)
        self.assertIn('href="https://example.org/metadata"', html)
        self.assertNotIn("<script>", markdown)
        self.assertIn("excerpts=None recorded", readable_markdown)
        bibliography = html.split('<section id="bibliography">', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn('href="sources/source-1.txt"', bibliography)
        self.assertIn('href="sources/source-2.txt"', bibliography)
        self.assertRegex(bibliography, r'href="#[^"]+">ev-1</a>')
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for target in re.findall(r'href="#([^"]+)"', html):
            self.assertIn(target, ids)

    def test_duplicate_and_cross_bound_references_fail_closed(self):
        mutations = (
            (
                "duplicate work",
                "duplicate-literature",
                lambda p: p["literature"].append(copy.deepcopy(p["literature"][0])),
            ),
            (
                "wrong work",
                "source-binding-mismatch",
                lambda p: p["literature"][0].update(work_id="foreign"),
            ),
            (
                "wrong version",
                "source-binding-mismatch",
                lambda p: p["literature"][0].update(version_id="foreign"),
            ),
            (
                "wrong source",
                "source-binding-mismatch",
                lambda p: p["literature"][0].update(source_ids=["src-2"]),
            ),
            (
                "wrong claim",
                "claim-binding-mismatch",
                lambda p: p["literature"][0].update(claim_ids=["ev-2"]),
            ),
            (
                "foreign role claim",
                "role-claim-mismatch",
                lambda p: p["literature"][0]["roles"][0].update(claim_ids=["ev-2"]),
            ),
            (
                "duplicate role",
                "duplicate-literature-role",
                lambda p: p["literature"][0]["roles"].append(
                    copy.deepcopy(p["literature"][0]["roles"][0])
                ),
            ),
        )
        for label, expected, mutate in mutations:
            with self.subTest(label=label):
                selection = copy.deepcopy(self.selection)
                mutate(selection["evaluation_packet"])
                self._rebind(selection)
                with self.assertRaisesRegex(Stage2Error, expected):
                    render_selection_html(selection, self.snapshots)

    def test_stage1_metadata_binding_rejects_direct_tampering(self):
        self.selection["evaluation_packet"]["literature"][0]["title"] = "Substituted"
        with self.assertRaisesRegex(Stage2Error, "stage1-literature-binding-mismatch"):
            self._markdown()

    def test_malformed_metadata_cannot_inject_html_or_crash_the_projection(self):
        for key, value in (
            ("year", "</dd><script>bad</script>"),
            ("authors", {"name": "Wrong shape"}),
            ("roles", [True]),
            ("source_ids", [["src-1"]]),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.selection)
                changed["evaluation_packet"]["literature"][0][key] = value
                self._rebind(changed)
                with self.assertRaisesRegex(Stage2Error, "report-literature-schema"):
                    render_selection_html(changed, self.snapshots)
