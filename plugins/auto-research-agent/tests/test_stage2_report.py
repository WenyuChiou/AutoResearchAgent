"""Proposal report coverage using real initialized and applied Stage 2 runs."""

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_check import apply_assessment, export_selection, initialize_run, inspect_run
from stage2_check.report import render_proposal
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from test_stage2_checker import assessment, finding


class Stage2ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _run(self, packet, sources, assessments=()):
        packet_path = self.root / f"packet-{len(list(self.root.glob('run-*')))}.json"
        run = self.root / f"run-{len(list(self.root.glob('run-*')))}"
        self._write(packet_path, packet)
        initialize_run(packet_path, sources, run)
        for index, value in enumerate(assessments, 1):
            path = self.root / f"assessment-{run.name}-{index}.json"
            self._write(path, value)
            apply_assessment(run, path)
        state = inspect_run(run)
        selection = export_selection(run)
        rendered = render_proposal(
            selection,
            state["packet"]["sources"],
            event_head=state["event_head_sha256"],
            stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
        )
        return run, state, selection, rendered

    def test_complete_report_uses_snapshots_and_separates_current_from_history(self):
        sources = self.root / "sources-history"
        packet = write_stage2_fixture(sources, candidate_count=1)
        revise = assessment(packet, disposition="revise")
        revised = copy.deepcopy(packet["candidates"][0])
        revised.update(
            version=2,
            parent_version=1,
            question="Can the revised bounded question be answered?",
            evidence_ids=["ev-1", "ev-2"],
        )
        revise["revised_candidate"] = revised
        accepted = assessment(packet, event_id="check-2", version=2)
        run, state, _, raw = self._run(packet, sources, (revise, accepted))
        text = raw.decode("utf-8")
        current = text.split("## Current candidate options", 1)[1].split(
            "## Global unresolved", 1
        )[0]
        history = text.split("## Full candidate version history", 1)[1].split(
            "## Full assessment", 1
        )[0]
        self.assertIn(r"candidate\-1 v2", current)
        self.assertNotIn(r"candidate\-1 v1", current)
        self.assertIn(r"candidate\-1 v1", history)
        self.assertIn(r"candidate\-1 v2", history)
        self.assertIn("](sources/source-1.txt)", text)
        self.assertNotIn("](source-1.txt)", text)
        self.assertIn(state["event_head_sha256"], text)
        original_hash = canonical_hash(packet)
        stored_hash = canonical_hash(
            json.loads((run / "packet.json").read_text(encoding="utf-8"))
        )
        self.assertNotEqual(original_hash, stored_hash)
        self.assertIn(f"Original input packet SHA-256: ```{original_hash}```", text)
        self.assertIn(f"Stored packet.json SHA-256: ```{stored_hash}```", text)
        self.assertIn("Bibliographic title: not recorded", text)
        self.assertIn("Claim-specific literature role: not recorded", text)
        local_links = [
            target
            for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text)
            if not target.startswith("#")
        ]
        self.assertTrue(local_links)
        self.assertTrue(all((run / target).is_file() for target in local_links))

    def test_export_accepts_omitted_optional_brief_history(self):
        optional_fields = ("previous_sha256", "suggestions", "decisions")
        for index, omitted in enumerate(
            [*((field,) for field in optional_fields), optional_fields]
        ):
            with self.subTest(omitted=omitted):
                sources = self.root / f"minimal-brief-{index}"
                packet = write_stage2_fixture(sources, candidate_count=0)
                for field in omitted:
                    del packet["brief"][field]
                _, _, _, rendered = self._run(packet, sources)
                self.assertIn(b"Prehuman status: human selection pending.", rendered)

    def test_revised_current_version_stays_pending_until_reassessed(self):
        sources = self.root / "sources-pending-revision"
        packet = write_stage2_fixture(sources, candidate_count=1)
        revise = assessment(packet, disposition="revise")
        revised = copy.deepcopy(packet["candidates"][0])
        revised.update(version=2, parent_version=1)
        revise["revised_candidate"] = revised
        _, _, _, raw = self._run(packet, sources, (revise,))
        current = (
            raw.decode("utf-8")
            .split("## Current candidate options", 1)[1]
            .split("## Global unresolved", 1)[0]
        )
        self.assertIn(r"candidate\-1 v2", current)
        self.assertIn("Disposition: pending assessment", current)
        self.assertNotIn("Disposition: recommend", current)

    def test_unknown_and_not_applicable_remain_distinct(self):
        sources = self.root / "sources-status"
        packet = write_stage2_fixture(sources, candidate_count=1)
        parked = assessment(packet, disposition="park")
        parked["checks"]["answerability"] = finding("unknown", None, evidence_ids=[])
        parked["checks"]["materials"] = finding("not-applicable", None, evidence_ids=[])
        _, _, _, raw = self._run(packet, sources, (parked,))
        text = raw.decode("utf-8")
        self.assertIn("| answerability | unknown | Unknown |", text)
        self.assertIn("| materials | not-applicable | N/A |", text)

    def test_empty_report_is_deterministic_and_honest(self):
        sources = self.root / "sources-empty"
        packet = write_stage2_fixture(sources, candidate_count=0)
        packet["sources"] = []
        packet["evidence"] = []
        run, state, selection, first = self._run(packet, sources)
        second = render_proposal(
            selection,
            state["packet"]["sources"],
            event_head=state["event_head_sha256"],
            stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
        )
        self.assertEqual(first, second)
        text = first.decode("utf-8")
        self.assertIn("Recommendations: 0", text)
        self.assertIn("No direction is currently recommended", text)
        self.assertIn("No assessments or actions are recorded", text)
        self.assertIn("Stage 3: not started; execution is not authorized", text)
        self.assertTrue((run / "selection.json").is_file())

    def test_hostile_prose_is_inert_and_exact_quote_uses_safe_fence(self):
        sources = self.root / "sources-hostile"
        packet = write_stage2_fixture(sources, candidate_count=1)
        hostile_quote = "Exact ``` quote <script>alert(1)</script>\n# still quoted"
        source_path = sources / "source-1.txt"
        source_path.write_bytes((hostile_quote + "\n").encode("utf-8"))
        packet["sources"][0]["sha256"] = hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest()
        packet["evidence"][0]["quote"] = hostile_quote
        packet["candidates"][0]["question"] = "# heading\n[click](https://bad) <b>x</b>"
        _, _, _, raw = self._run(packet, sources)
        text = raw.decode("utf-8")
        self.assertIn(
            "Question: \\# heading \\[click\\]\\(https://bad\\) \\<b\\>x\\</b\\>", text
        )
        self.assertNotIn("[click](https://bad)", text)
        self.assertIn("````\n" + hostile_quote + "\n````", text)

    def test_missing_or_mismatched_bindings_fail_closed(self):
        sources = self.root / "sources-failure"
        packet = write_stage2_fixture(sources, candidate_count=1)
        _, state, selection, _ = self._run(packet, sources)
        with self.assertRaisesRegex(Stage2Error, "source-set-mismatch"):
            render_proposal(
                selection,
                state["packet"]["sources"][:-1],
                event_head=state["event_head_sha256"],
                stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
            )
        broken = copy.deepcopy(selection)
        broken["candidate_histories"]["candidate-1"][0]["evidence_ids"] = [
            "missing-evidence"
        ]
        with self.assertRaisesRegex(Stage2Error, "unknown-evidence"):
            render_proposal(
                broken,
                state["packet"]["sources"],
                event_head=state["event_head_sha256"],
                stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
            )
        escaped = copy.deepcopy(state["packet"]["sources"])
        escaped[0]["path"] = "../source-1.txt"
        with self.assertRaisesRegex(Stage2Error, "unsafe-report-source-path"):
            render_proposal(
                selection,
                escaped,
                event_head=state["event_head_sha256"],
                stored_packet_sha256=state["manifest"]["stored_packet_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
