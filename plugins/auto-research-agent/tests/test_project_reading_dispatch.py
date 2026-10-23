"""Pure three-route reading dispatcher tests; no provider or source I/O."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native import project_full_reading as full_reading
from research_workspace_native import project_reading_dispatch as dispatch
from research_workspace_native.project_full_analysis import (
    ANALYZE_OPERATION,
    ANALYZE_SCOPE,
    full_analysis_draft,
    full_analysis_prompt,
)
from research_workspace_native.project_model_reading import (
    READ_OPERATION,
    READ_SCOPE,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from test_project_full_analysis import fixture as analysis_fixture
from test_project_semantic_analysis import proposal, reading


def legacy_fixture():
    text = "legacy exact evidence Ω"
    raw = text.encode("utf8")
    source = {
        "source_id": "legacy-source",
        "text_sha256": sha(raw),
        "text_ref": {
            "sha256": sha(raw),
            "bytes": len(raw),
            "producer": "legacy-source",
        },
        "excerpt": text,
        "excerpt_start_byte": 0,
        "excerpt_end_byte": len(raw),
    }
    snapshot = {
        "kind": "Stage1SavedTextReadingInput",
        "schema_version": "1.0.0",
        "principal": "researcher-1",
        "project_ref": "project-ref-1",
        "project_id": "project-1",
        "input_version": 4,
        "brief_sha256": "a" * 64,
        "basis": {"input_version": 4},
        "ledger_state_sha256": "b" * 64,
        "checkpoint": None,
        "work_id": "work-1",
        "version_id": "version-1",
        "candidate_event_id": "e000001",
        "decision_event_id": "e000002",
        "review_event_id": None,
        "discovery": {"title": "Legacy paper"},
        "sources": [source],
        "source_failures": [],
        "existing_claims": [],
        "model_creates_core_claims": False,
        "entire_work_read": False,
        "scientific_acceptance": False,
    }
    quote = "evidence Ω"
    start = raw.index(quote.encode("utf8"))
    draft = {
        "summary": "A legacy reading proposal.",
        "classification": {name: "Unknown" for name in CLASSIFICATION},
        "findings": {name: "Unknown" for name in FINDINGS},
        "limitations": ["Only the shown excerpt was read."],
        "open_questions": ["Applicability remains Unknown."],
        "evidence": [
            {
                "source_id": source["source_id"],
                "text_sha256": source["text_sha256"],
                "start_byte": start,
                "end_byte": start + len(quote.encode("utf8")),
                "quote": quote,
                "claim_id": None,
            }
        ],
    }
    return snapshot, draft


class ReadingDispatchTests(unittest.TestCase):
    def test_json_shaped_kind_and_operation_refuse_with_typed_error(self):
        for value in ([], {}, True, 1, None):
            with self.subTest(operation=value), self.assertRaises(SessionApiError):
                dispatch.reading_scope(value)
            for function in (
                dispatch.model_reading_prompt,
                lambda snap: dispatch.model_reading_draft(b"{}", snap),
                dispatch.reading_metadata,
            ):
                with (
                    self.subTest(kind=value, function=function),
                    self.assertRaises(SessionApiError),
                ):
                    function({"kind": value, "schema_version": "1.0.0"})

    def test_operations_and_scopes_are_explicit(self):
        self.assertEqual(
            dispatch.READING_OPERATIONS,
            {READ_OPERATION, full_reading.FULL_READ_OPERATION, ANALYZE_OPERATION},
        )
        self.assertEqual(
            dispatch.FULL_SOURCE_OPERATIONS,
            {full_reading.FULL_READ_OPERATION, ANALYZE_OPERATION},
        )
        self.assertEqual(dispatch.reading_scope(READ_OPERATION), READ_SCOPE)
        self.assertEqual(
            dispatch.reading_scope(full_reading.FULL_READ_OPERATION),
            full_reading.FULL_READ_SCOPE,
        )
        self.assertEqual(dispatch.reading_scope(ANALYZE_OPERATION), ANALYZE_SCOPE)
        with self.assertRaisesRegex(SessionApiError, "reading-dispatch-operation"):
            dispatch.reading_scope("unknown")

    def test_legacy_route_preserves_prompt_draft_and_metadata(self):
        snapshot, value = legacy_fixture()
        raw = canonical(value)
        self.assertEqual(
            dispatch.model_reading_prompt(snapshot),
            full_reading.model_reading_prompt(snapshot),
        )
        self.assertEqual(
            dispatch.model_reading_draft(raw, snapshot),
            full_reading.model_reading_draft(raw, snapshot),
        )
        self.assertIs(dispatch.reading_metadata(snapshot), snapshot)

    def test_full_route_preserves_tail_prompt_draft_and_metadata(self):
        snapshot = analysis_fixture()["reading_input"]
        raw = canonical(reading(snapshot["full_source"]))
        prompt = dispatch.model_reading_prompt(snapshot)
        self.assertEqual(prompt, full_reading.model_reading_prompt(snapshot))
        self.assertIn("尾端證據 Ω", prompt)
        self.assertEqual(
            dispatch.model_reading_draft(raw, snapshot),
            full_reading.model_reading_draft(raw, snapshot),
        )
        self.assertIs(dispatch.reading_metadata(snapshot), snapshot["saved_reading"])

    def test_analysis_route_preserves_needs_and_no_authority(self):
        snapshot = analysis_fixture()
        raw = canonical(proposal(snapshot["reading_input"]["full_source"]))
        prompt = dispatch.model_reading_prompt(snapshot)
        self.assertEqual(prompt, full_analysis_prompt(snapshot))
        self.assertIn("Which method was used?", prompt)
        checked = dispatch.model_reading_draft(raw, snapshot)
        self.assertEqual(checked, full_analysis_draft(raw, snapshot))
        for field in (
            "core_claims_created",
            "human_review",
            "researcher_acceptance",
            "scientific_acceptance",
        ):
            self.assertIs(checked[field], False)
        self.assertIs(
            dispatch.reading_metadata(snapshot),
            snapshot["reading_input"]["saved_reading"],
        )

    def test_unknown_kind_and_schema_are_typed_refusals(self):
        for snapshot in (
            {"kind": "Unknown", "schema_version": "1.0.0"},
            {"kind": "Stage1SavedTextReadingInput", "schema_version": "2.0.0"},
            [],
        ):
            with self.subTest(snapshot=snapshot), self.assertRaises(SessionApiError):
                dispatch.model_reading_prompt(snapshot)

    def test_cross_kind_retagging_never_falls_back(self):
        analysis_snapshot = analysis_fixture()
        for wrong_kind in (
            "Stage1SavedTextReadingInput",
            "Stage1SavedFullSourceReadingInput",
        ):
            changed = deepcopy(analysis_snapshot)
            changed["kind"] = wrong_kind
            with (
                self.subTest(wrong_kind=wrong_kind),
                self.assertRaises(SessionApiError),
            ):
                dispatch.model_reading_prompt(changed)
        legacy, _ = legacy_fixture()
        legacy["kind"] = "Stage1SavedFullSourceAnalysisInput"
        with self.assertRaises(SessionApiError):
            dispatch.model_reading_prompt(legacy)


if __name__ == "__main__":
    unittest.main()
