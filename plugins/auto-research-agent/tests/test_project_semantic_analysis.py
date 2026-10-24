"""Synthetic semantic proposal checks; no model, source, or runtime I/O."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_semantic_analysis import (
    MAX_PROMPT_BYTES,
    analysis_prompt,
    validate_analysis_draft,
)
from research_workspace_native.project_semantic_drafts import full_source_snapshot
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from stage1_ledger.journal import LedgerError


def fixture():
    text = "prefix " + "x" * 10020 + " 尾端證據 Ω and second evidence"
    raw = text.encode("utf8")
    snapshot = full_source_snapshot(
        {
            "project_id": "project-1",
            "input_version": 4,
            "brief_sha256": "a" * 64,
            "work_id": "work-1",
            "version_id": "version-1",
        },
        [
            {
                "source_id": "source-1",
                "text_sha256": sha(raw),
                "text_bytes": len(raw),
                "text": text,
                "identity_status": "consistent",
                "scope": "full-text",
            }
        ],
    )
    needs = [
        {"need_id": "need-method", "question": "Which method was used?"},
        {"need_id": "need-result", "question": "What result was reported?"},
    ]
    return snapshot, needs


def reading(snapshot):
    evidence = []
    raw = snapshot["sources"][0]["text"].encode("utf8")
    for quote in ("尾端證據 Ω", "second evidence"):
        start = raw.index(quote.encode("utf8"))
        evidence.append(
            {
                "source_id": "source-1",
                "text_sha256": snapshot["sources"][0]["text_sha256"],
                "start_byte": start,
                "end_byte": start + len(quote.encode("utf8")),
                "quote": quote,
                "claim_id": None,
            }
        )
    return {
        "summary": "A bounded reading proposal.",
        "classification": {name: "Unknown" for name in CLASSIFICATION},
        "findings": {name: "Unknown" for name in FINDINGS},
        "limitations": ["Semantic support requires review."],
        "open_questions": ["The confirmed needs remain authoritative."],
        "evidence": evidence,
    }


def proposal(snapshot):
    return {
        "kind": "Stage1FullSourceAnalysisProposal",
        "schema_version": "1.0.0",
        "reading": reading(snapshot),
        "screening": {
            "decision": "include",
            "need_ids": ["need-method", "need-result"],
            "reason_code": "source-addresses-needs",
            "rationale": "The proposal points to passages for both confirmed needs.",
            "missing_information": [],
        },
        "claims": [
            {
                "claim_key": "method-proposal",
                "claim_text": "The source contains a method-related passage.",
                "relation": "supports",
                "evidence_index": 0,
                "section": "Results Ω",
                "assessment": {
                    "reason_code": "exact-source-span",
                    "rationale": "The cited UTF-8 span is mechanically exact.",
                },
            },
            {
                "claim_key": "result-proposal",
                "claim_text": "The source contains a second proposed result.",
                "relation": "unclear",
                "evidence_index": 1,
                "section": "Discussion",
                "assessment": {
                    "reason_code": "meaning-needs-review",
                    "rationale": "The quote exists, while its meaning remains unaccepted.",
                },
            },
        ],
    }


class SemanticAnalysisTests(unittest.TestCase):
    def test_unicode_tail_needs_hash_and_multiple_claims(self):
        snapshot, needs = fixture()
        prompt = analysis_prompt(snapshot, needs, max_prompt_bytes=MAX_PROMPT_BYTES)
        self.assertIn("尾端證據 Ω", prompt)
        self.assertIn("Which method was used?", prompt)
        checked = validate_analysis_draft(
            canonical(proposal(snapshot)), snapshot, needs
        )
        self.assertEqual(checked["snapshot_sha256"], sha(canonical(snapshot)))
        self.assertEqual(checked["needs_sha256"], sha(canonical(needs)))
        self.assertEqual(len(checked["claims"]), 2)

    def test_result_is_independent_and_cannot_promote_authority(self):
        snapshot, needs = fixture()
        value = proposal(snapshot)
        checked = validate_analysis_draft(canonical(value), snapshot, needs)
        value["claims"][0]["claim_text"] = "changed"
        needs[0]["question"] = "changed"
        snapshot["sources"][0]["text"] = "changed"
        self.assertNotEqual(checked["claims"][0]["claim_text"], "changed")
        for field in (
            "core_claims_created",
            "human_review",
            "researcher_acceptance",
            "scientific_acceptance",
        ):
            self.assertIs(checked[field], False)
        self.assertIs(checked["agent_proposals"], True)

    def test_need_binding_and_fields_are_strict(self):
        snapshot, needs = fixture()
        bad = proposal(snapshot)
        bad["screening"]["need_ids"] = ["unknown"]
        with self.assertRaisesRegex(SessionApiError, "screening-needs"):
            validate_analysis_draft(canonical(bad), snapshot, needs)
        for changed in (
            needs + [deepcopy(needs[0])],
            [{**needs[0], "extra": True}],
            [{"need_id": True, "question": "q"}],
        ):
            with self.assertRaises(SessionApiError):
                analysis_prompt(snapshot, changed, max_prompt_bytes=MAX_PROMPT_BYTES)

    def test_changed_needs_are_rehashed(self):
        snapshot, needs = fixture()
        checked = validate_analysis_draft(
            canonical(proposal(snapshot)), snapshot, needs
        )
        changed = deepcopy(needs)
        changed[0]["question"] += " changed"
        rehashed = validate_analysis_draft(
            canonical(proposal(snapshot)), snapshot, changed
        )
        self.assertNotEqual(checked["needs_sha256"], rehashed["needs_sha256"])
        self.assertEqual(rehashed["needs_sha256"], sha(canonical(changed)))

    def test_duplicate_nonfinite_and_oversize_refuse_before_decode(self):
        snapshot, needs = fixture()
        with self.assertRaises(LedgerError):
            validate_analysis_draft(b'{"kind":1,"kind":2}', snapshot, needs)
        with self.assertRaises(LedgerError):
            validate_analysis_draft(b'{"value":NaN}', snapshot, needs)
        with self.assertRaisesRegex(SessionApiError, "draft-byte-bound"):
            validate_analysis_draft(b"{" + b"x" * (1024 * 1024), snapshot, needs)

    def test_top_screening_and_claim_fields_are_exact(self):
        snapshot, needs = fixture()
        for mutation in ("top", "screening", "claim"):
            bad = proposal(snapshot)
            if mutation == "top":
                target = bad
            elif mutation == "screening":
                target = bad["screening"]
            else:
                target = bad["claims"][0]
            target["extra"] = True
            with self.assertRaises(SessionApiError):
                validate_analysis_draft(canonical(bad), snapshot, needs)

    def test_claim_index_key_relation_and_types_are_strict(self):
        snapshot, needs = fixture()
        changes = (
            ("evidence_index", True),
            ("evidence_index", 2),
            ("relation", "pending"),
            ("claim_key", ""),
        )
        for field, value in changes:
            bad = proposal(snapshot)
            bad["claims"][0][field] = value
            with self.assertRaises(SessionApiError):
                validate_analysis_draft(canonical(bad), snapshot, needs)
        bad = proposal(snapshot)
        bad["claims"][1]["claim_key"] = bad["claims"][0]["claim_key"]
        with self.assertRaisesRegex(SessionApiError, "claim-key-duplicate"):
            validate_analysis_draft(canonical(bad), snapshot, needs)

    def test_utf8_assessment_and_text_bounds(self):
        snapshot, needs = fixture()
        for field, value in (
            ("section", "界" * 342),
            ("claim_text", "界" * 2731),
        ):
            bad = proposal(snapshot)
            bad["claims"][0][field] = value
            with self.assertRaises(SessionApiError):
                validate_analysis_draft(canonical(bad), snapshot, needs)
        bad = proposal(snapshot)
        bad["claims"][0]["assessment"]["rationale"] = "界" * 342
        with self.assertRaisesRegex(SessionApiError, "claim-assessment"):
            validate_analysis_draft(canonical(bad), snapshot, needs)
        bad = proposal(snapshot)
        bad["claims"][0]["assessment"]["reason_code"] = "Not Valid"
        with self.assertRaisesRegex(SessionApiError, "claim-assessment"):
            validate_analysis_draft(canonical(bad), snapshot, needs)

    def test_pending_requires_real_missing_information(self):
        snapshot, needs = fixture()
        bad = proposal(snapshot)
        bad["screening"]["decision"] = "pending"
        with self.assertRaisesRegex(SessionApiError, "pending-needs-information"):
            validate_analysis_draft(canonical(bad), snapshot, needs)
        bad["screening"]["missing_information"] = ["Need a population description."]
        self.assertEqual(
            validate_analysis_draft(canonical(bad), snapshot, needs)["screening"][
                "decision"
            ],
            "pending",
        )

    def test_prompt_cap_refuses_without_truncation(self):
        snapshot, needs = fixture()
        complete = analysis_prompt(snapshot, needs, max_prompt_bytes=MAX_PROMPT_BYTES)
        size = len(complete.encode("utf8"))
        self.assertEqual(
            analysis_prompt(snapshot, needs, max_prompt_bytes=size), complete
        )
        with self.assertRaisesRegex(SessionApiError, "prompt-bound-exceeded"):
            analysis_prompt(snapshot, needs, max_prompt_bytes=size - 1)
        self.assertIn("second evidence", complete)


if __name__ == "__main__":
    unittest.main()
