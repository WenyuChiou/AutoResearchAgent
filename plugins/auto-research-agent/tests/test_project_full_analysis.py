"""Synthetic full-analysis wrapper checks; no provider, SDK, or source I/O."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native import project_full_analysis as analysis
from research_workspace_native.project_semantic_drafts import full_source_snapshot
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_project_semantic_analysis import proposal


def fixture():
    needs = [
        {"need_id": "need-method", "question": "Which method was used?"},
        {"need_id": "need-result", "question": "What result was reported?"},
    ]
    brief = {
        "objective": "Assess the saved paper while preserving Unknown.",
        "needs": needs,
    }
    text = "prefix " + "x" * 10020 + " 尾端證據 Ω and second evidence"
    raw = text.encode("utf8")
    binding = {
        "project_id": "project-1",
        "input_version": 4,
        "brief_sha256": sha(canonical(brief) + b"\n"),
        "work_id": "work-1",
        "version_id": "version-1",
    }
    source = {
        "source_id": "source-1",
        "text_sha256": sha(raw),
        "text_bytes": len(raw),
        "text": text,
        "identity_status": "consistent",
        "scope": "full-text",
    }
    saved_source = {
        key: source[key]
        for key in ("source_id", "text_sha256", "text_bytes", "identity_status")
    } | {
        "source_observation_scope": "saved artifact; completeness Unknown",
    }
    reading = {
        "kind": "Stage1SavedFullSourceReadingInput",
        "schema_version": "1.0.0",
        "saved_reading": {
            "kind": "Stage1SavedTextReadingInput",
            "model_creates_core_claims": False,
            "scientific_acceptance": False,
            **binding,
            "discovery": {"title": "Synthetic paper", "authors": ["Unknown"]},
            "source_failures": [{"state": "Unknown", "reason": "none observed"}],
            "sources": [saved_source],
        },
        "full_source": full_source_snapshot(binding, [source]),
        "brief": brief,
    }
    return {
        "kind": "Stage1SavedFullSourceAnalysisInput",
        "schema_version": "1.0.0",
        "reading_input": reading,
    }


class FullAnalysisTests(unittest.TestCase):
    def test_prompt_has_tail_needs_scope_and_caveat_once(self):
        snapshot = fixture()
        prompt = analysis.full_analysis_prompt(snapshot)
        self.assertIn("尾端證據 Ω", prompt)
        self.assertIn("Which method was used?", prompt)
        self.assertIn("saved artifact; completeness Unknown", prompt)
        self.assertEqual(
            prompt.count("Complete saved text is not proof of a complete publication"),
            1,
        )
        self.assertEqual(prompt.count("尾端證據 Ω and second evidence"), 1)

    def test_prompt_cap_refuses_without_clipping(self):
        snapshot = fixture()
        complete = analysis.full_analysis_prompt(snapshot)
        size = len(complete.encode("utf8"))
        with patch.object(analysis, "FULL_SOURCE_INPUT_BYTES", size):
            self.assertEqual(analysis.full_analysis_prompt(snapshot), complete)
        with (
            patch.object(analysis, "FULL_SOURCE_INPUT_BYTES", size - 1),
            self.assertRaisesRegex(SessionApiError, "prompt-bound-exceeded"),
        ):
            analysis.full_analysis_prompt(snapshot)
        self.assertIn("second evidence", complete)

    def test_wrapper_fields_and_version_are_exact(self):
        for mutation in ("extra", "kind", "version"):
            snapshot = fixture()
            if mutation == "extra":
                snapshot["extra"] = True
            elif mutation == "kind":
                snapshot["kind"] = "Other"
            else:
                snapshot["schema_version"] = "2.0.0"
            with (
                self.subTest(mutation=mutation),
                self.assertRaisesRegex(
                    SessionApiError, "full-analysis-snapshot-fields"
                ),
            ):
                analysis.full_analysis_prompt(snapshot)

    def test_brief_and_source_tampering_are_rejected(self):
        for mutation in ("brief", "source"):
            snapshot = fixture()
            if mutation == "brief":
                snapshot["reading_input"]["brief"]["objective"] += " changed"
            else:
                snapshot["reading_input"]["full_source"]["sources"][0]["text"] += (
                    " changed"
                )
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                analysis.full_analysis_prompt(snapshot)

    def test_draft_rebinds_hashes_and_cannot_claim_authority(self):
        snapshot = fixture()
        value = proposal(snapshot["reading_input"]["full_source"])
        checked = analysis.full_analysis_draft(canonical(value), snapshot)
        self.assertEqual(checked["reading"], value["reading"])
        self.assertEqual(checked["screening"], value["screening"])
        self.assertEqual(checked["claims"], value["claims"])
        self.assertEqual(
            checked["full_source_sha256"],
            sha(canonical(snapshot["reading_input"]["full_source"])),
        )
        self.assertEqual(checked["snapshot_sha256"], sha(canonical(snapshot)))
        for field in (
            "core_claims_created",
            "human_review",
            "researcher_acceptance",
            "scientific_acceptance",
        ):
            self.assertIs(checked[field], False)

    def test_draft_fields_and_confirmed_needs_remain_strict(self):
        snapshot = fixture()
        for mutation in ("authority", "unknown-need"):
            value = proposal(snapshot["reading_input"]["full_source"])
            if mutation == "authority":
                value["scientific_acceptance"] = True
            else:
                value["screening"]["need_ids"] = ["unknown"]
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                analysis.full_analysis_draft(canonical(value), snapshot)

    def test_saved_snapshot_forwards_exact_args_and_preflights(self):
        reading = fixture()["reading_input"]
        deadline = object()
        with patch.object(
            analysis, "saved_full_reading_snapshot", return_value=reading
        ) as saved:
            snapshot = analysis.saved_full_analysis_snapshot(
                object(), "project-1", "work-1", check_deadline=deadline
            )
        saved.assert_called_once_with(
            unittest.mock.ANY,
            "project-1",
            "work-1",
            check_deadline=deadline,
        )
        self.assertIs(snapshot["reading_input"], reading)
        self.assertEqual(set(snapshot), {"kind", "schema_version", "reading_input"})

    def test_missing_records_uses_existing_typed_refusal(self):
        with self.assertRaisesRegex(SessionApiError, "reading-records-unconnected"):
            analysis.saved_full_analysis_snapshot(None, "project-1", "work-1")


if __name__ == "__main__":
    unittest.main()
