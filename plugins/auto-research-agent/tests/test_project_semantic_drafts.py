"""Synthetic checks for opt-in complete-source draft helpers; no I/O."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_semantic_drafts import (
    MAX_PROMPT_BYTES,
    full_source_prompt,
    full_source_snapshot,
    validate_full_source_draft,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from stage1_ledger.journal import LedgerError


def binding():
    return {
        "project_id": "project-1",
        "input_version": 7,
        "brief_sha256": "1" * 64,
        "work_id": "work-1",
        "version_id": "version-1",
    }


def source(text=None, source_id="source-1"):
    text = text if text is not None else "prefix " + ("x" * 10020) + " 後段證據 Ω"
    raw = text.encode("utf8")
    return {
        "source_id": source_id,
        "text_sha256": sha(raw),
        "text_bytes": len(raw),
        "text": text,
        # The real saved-source fixture carries the parser receipt's
        # non-promoting title/metadata agreement state unchanged.
        "identity_status": "consistent",
        "scope": "full-text",
    }


def draft(snapshot, quote="後段證據"):
    row = snapshot["sources"][0]
    raw = row["text"].encode("utf8")
    start = raw.index(quote.encode("utf8"))
    return {
        "summary": "The supplied text contains a mechanically located passage.",
        "classification": {name: "Unknown" for name in CLASSIFICATION},
        "findings": {name: "Unknown" for name in FINDINGS},
        "limitations": [
            "Mechanical quote validation does not establish semantic support."
        ],
        "open_questions": ["Researcher assessment remains required."],
        "evidence": [
            {
                "source_id": row["source_id"],
                "text_sha256": row["text_sha256"],
                "start_byte": start,
                "end_byte": start + len(quote.encode("utf8")),
                "quote": quote,
                "claim_id": None,
            }
        ],
    }


class FullSourceDraftTests(unittest.TestCase):
    def test_long_nonascii_tail_is_fully_prompted_and_validated(self):
        original_binding = binding()
        original_sources = [source()]
        snapshot = full_source_snapshot(original_binding, original_sources)
        prompt = full_source_prompt(snapshot, max_prompt_bytes=MAX_PROMPT_BYTES)
        self.assertGreater(len(prompt.encode("utf8")), 10000)
        self.assertIn("後段證據 Ω", prompt)
        visible = json.loads(
            prompt.split("BEGIN FULL SOURCE INPUT JSON\n", 1)[1].rsplit(
                "\nEND FULL SOURCE INPUT JSON", 1
            )[0]
        )
        self.assertEqual(visible, snapshot)
        checked = validate_full_source_draft(canonical(draft(snapshot)), snapshot)
        self.assertEqual(checked["input_sha256"], sha(canonical(snapshot)))
        self.assertEqual(
            (checked["work_id"], checked["version_id"]), ("work-1", "version-1")
        )
        self.assertTrue(checked["entire_source_text_supplied"])
        self.assertFalse(checked["entire_work_read"])
        self.assertFalse(checked["core_claims_created"])
        self.assertFalse(checked["researcher_acceptance"])
        self.assertFalse(checked["scientific_acceptance"])

    def test_snapshot_returns_independent_unchanged_copies(self):
        original_binding = binding()
        original_sources = [source("complete text")]
        expected_binding = deepcopy(original_binding)
        expected_sources = deepcopy(original_sources)
        snapshot = full_source_snapshot(original_binding, original_sources)
        original_binding["project_id"] = "changed"
        original_sources[0]["text"] = "changed"
        self.assertEqual(snapshot["binding"], expected_binding)
        self.assertEqual(snapshot["sources"], expected_sources)
        snapshot["binding"]["work_id"] = "snapshot-change"
        snapshot["sources"][0]["text"] = "snapshot-change"
        self.assertEqual(expected_binding["work_id"], "work-1")
        self.assertEqual(expected_sources[0]["text"], "complete text")

    def test_binding_exact_fields_hash_strings_and_positive_real_int(self):
        cases = []
        extra = binding()
        extra["extra"] = True
        cases.append(extra)
        for field, value in (
            ("project_id", ""),
            ("work_id", "x" * 257),
            ("version_id", 1),
            ("brief_sha256", "A" * 64),
            ("brief_sha256", "0" * 63),
            ("input_version", 0),
            ("input_version", True),
            ("input_version", 1.0),
        ):
            bad = binding()
            bad[field] = value
            cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(SessionApiError):
                full_source_snapshot(bad, [source("text")])

    def test_source_shape_count_ids_status_scope_and_scalar_types(self):
        with self.assertRaises(SessionApiError):
            full_source_snapshot(binding(), [])
        with self.assertRaises(SessionApiError):
            full_source_snapshot(
                binding(), [source(str(i), f"s-{i}") for i in range(9)]
            )
        duplicate = [source("one", "same"), source("two", "same")]
        with self.assertRaises(SessionApiError):
            full_source_snapshot(binding(), duplicate)
        for field, value in (
            ("identity_status", "mismatch"),
            ("identity_status", "match"),
            ("scope", "abstract"),
            ("scope", "metadata"),
            ("text_bytes", True),
            ("text_bytes", 4.0),
        ):
            bad = source("text")
            bad[field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(SessionApiError),
            ):
                full_source_snapshot(binding(), [bad])
        unknown = source("text")
        unknown["extra"] = None
        with self.assertRaises(SessionApiError):
            full_source_snapshot(binding(), [unknown])
        for status in ("consistent", "verified", "unverified"):
            saved = source("text")
            saved["identity_status"] = status
            with self.subTest(saved_identity_status=status):
                self.assertEqual(
                    full_source_snapshot(binding(), [saved])["sources"], [saved]
                )

    def test_text_bytecount_hash_individual_and_aggregate_bounds(self):
        for field, value in (("text_bytes", 3), ("text_sha256", "0" * 64)):
            bad = source("text")
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                full_source_snapshot(binding(), [bad])
        with self.assertRaises(SessionApiError):
            full_source_snapshot(binding(), [source("x" * (2 * 1024 * 1024 + 1))])
        first = source("x" * (1024 * 1024 + 1), "first")
        second = source("y" * (1024 * 1024), "second")
        with self.assertRaises(SessionApiError):
            full_source_snapshot(binding(), [first, second])

    def test_prompt_bound_overflow_and_snapshot_tail_tamper_refuse_without_mutation(
        self,
    ):
        snapshot = full_source_snapshot(binding(), [source()])
        frozen = canonical(snapshot)
        for bound in (0, True, 1.0, MAX_PROMPT_BYTES + 1):
            with self.subTest(bound=bound), self.assertRaises(SessionApiError):
                full_source_prompt(snapshot, max_prompt_bytes=bound)
        with self.assertRaises(SessionApiError):
            full_source_prompt(snapshot, max_prompt_bytes=128)
        self.assertEqual(canonical(snapshot), frozen)
        tampered = deepcopy(snapshot)
        tampered["sources"][0]["text"] += " altered tail"
        with self.assertRaises(SessionApiError):
            full_source_prompt(tampered, max_prompt_bytes=MAX_PROMPT_BYTES)

    def test_duplicate_and_nonfinite_json_are_rejected_by_strict_decoder(self):
        snapshot = full_source_snapshot(binding(), [source()])
        good = canonical(draft(snapshot)).decode("utf8")
        duplicate = good[:-1] + ',"summary":"duplicate"}'
        nonfinite = good.replace('"summary":', '"unexpected":NaN,"summary":', 1)
        for raw in (duplicate, nonfinite):
            with self.subTest(raw=raw[-80:]), self.assertRaises(LedgerError):
                validate_full_source_draft(raw.encode("utf8"), snapshot)

    def test_output_fields_text_arrays_and_exact_record_keys_are_bounded(self):
        snapshot = full_source_snapshot(binding(), [source()])
        cases = []
        extra = draft(snapshot)
        extra["accept"] = True
        cases.append(extra)
        missing = draft(snapshot)
        del missing["summary"]
        cases.append(missing)
        wrong_classification = draft(snapshot)
        wrong_classification["classification"]["invented"] = "value"
        cases.append(wrong_classification)
        empty_text = draft(snapshot)
        empty_text["findings"]["method"] = " "
        cases.append(empty_text)
        long_text = draft(snapshot)
        long_text["summary"] = "x" * 8193
        cases.append(long_text)
        long_list = draft(snapshot)
        long_list["limitations"] = ["item"] * 33
        cases.append(long_list)
        for bad in cases:
            with self.subTest(keys=bad.keys()), self.assertRaises(SessionApiError):
                validate_full_source_draft(canonical(bad), snapshot)

    def test_evidence_requires_exact_complete_utf8_span_hash_and_null_claim(self):
        snapshot = full_source_snapshot(binding(), [source()])
        good = draft(snapshot)
        span = good["evidence"][0]
        cases = []
        for change in (
            {"source_id": "missing"},
            {"text_sha256": "0" * 64},
            {"start_byte": True},
            {"end_byte": 1.0},
            {"start_byte": span["end_byte"]},
            {"quote": "invented"},
            {"claim_id": "invented-canonical-claim"},
        ):
            bad = deepcopy(good)
            bad["evidence"][0].update(change)
            cases.append(bad)
        split = deepcopy(good)
        nonascii_start = (
            snapshot["sources"][0]["text"].encode("utf8").index("後".encode("utf8"))
        )
        split["evidence"][0].update(
            start_byte=nonascii_start + 1, end_byte=nonascii_start + 3, quote="後"
        )
        cases.append(split)
        for bad in cases:
            with (
                self.subTest(span=bad["evidence"][0]),
                self.assertRaises(SessionApiError),
            ):
                validate_full_source_draft(canonical(bad), snapshot)

    def test_evidence_cardinality_and_semantic_language_never_set_acceptance(self):
        snapshot = full_source_snapshot(binding(), [source()])
        empty = draft(snapshot)
        empty["evidence"] = []
        with self.assertRaises(SessionApiError):
            validate_full_source_draft(canonical(empty), snapshot)
        excessive = draft(snapshot)
        excessive["evidence"] *= 129
        with self.assertRaises(SessionApiError):
            validate_full_source_draft(canonical(excessive), snapshot)
        semantic = draft(snapshot)
        semantic["summary"] = (
            "Scientifically complete, accepted, authoritative, and ready for canonical claims."
        )
        checked = validate_full_source_draft(canonical(semantic), snapshot)
        self.assertEqual(checked["draft"]["summary"], semantic["summary"])
        self.assertFalse(checked["entire_work_read"])
        self.assertFalse(checked["core_claims_created"])
        self.assertFalse(checked["researcher_acceptance"])
        self.assertFalse(checked["scientific_acceptance"])

    def test_raw_draft_byte_bound_refuses_before_json_decode(self):
        from unittest.mock import patch

        snapshot = full_source_snapshot(binding(), [source()])
        with patch(
            "research_workspace_native.project_semantic_drafts.decode"
        ) as decode:
            for raw in (b"", "{}", bytearray(b"{}"), b"x" * (1024 * 1024 + 1)):
                with self.subTest(type=type(raw).__name__, size=len(raw)):
                    with self.assertRaisesRegex(
                        SessionApiError, "full-source-draft-byte-bound"
                    ):
                        validate_full_source_draft(raw, snapshot)
            decode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
