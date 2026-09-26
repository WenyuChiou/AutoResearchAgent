"""Negative evidence-binding tests for evaluator execution v3.1."""

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_eval.common import sha
from stage1_eval.spans import (
    extraction_chunks,
    index_evidence,
    restore_passages,
    select,
    validate_index,
)


def evidence(text="A **verbatim** finding."):
    return {
        "answer": {
            "text": text,
            "sha256": sha(text.encode()),
            "origin": "subject-answer",
            "source_version": "version-1",
        }
    }


class EvidenceSpanTests(unittest.TestCase):
    def test_markdown_quotes_restored_without_model_retyping(self):
        rows = evidence()
        index = index_evidence(rows)
        result = restore_passages(
            {"criteria": [{"passages": [{"span_id": next(iter(index))}]}]}, index
        )
        self.assertEqual(
            result["criteria"][0]["passages"][0],
            {"evidence_id": "answer", "exact_quote": rows["answer"]["text"]},
        )

    def test_duplicate_text_does_not_authorize_wrong_file(self):
        rows = evidence()
        rows["foreign"] = {**rows["answer"], "source_version": "other-paper"}
        index = index_evidence(rows)
        own = next(k for k, v in index.items() if v["evidence_id"] == "answer")
        with self.assertRaisesRegex(ValueError, "wrong evidence file"):
            select(index, [own], evidence_id="foreign")
        self.assertEqual(len(index), 2)

    def test_version_and_rehashed_tamper_fail(self):
        rows = evidence()
        index = index_evidence(rows)
        for mutation in ("source_version", "text"):
            altered = deepcopy(rows)
            altered["answer"][mutation] = "tampered"
            altered["answer"]["sha256"] = sha(altered["answer"]["text"].encode())
            with (
                self.subTest(mutation=mutation),
                self.assertRaisesRegex(ValueError, "binding changed"),
            ):
                validate_index(index, altered)

    def test_raw_native_event_and_decoded_view_bound(self):
        raw = json.dumps({"item": {"aggregated_output": "line1\nline2"}})
        rows = {
            "trace-1": {
                "text": raw,
                "sha256": sha(raw.encode()),
                "origin": "subject-native-trace",
            }
        }
        index = index_evidence(rows)
        self.assertEqual(
            {r["view"] for r in index.values()}, {"text", "item.aggregated_output"}
        )
        self.assertIn("line1\nline2", [r["text"] for r in index.values()])

    def test_chunks_cover_complete_tail_and_keep_limit(self):
        text = "x" * 37_001 + " final cited paper"
        rows = evidence(text)
        _, chunks = extraction_chunks({"evidence": rows})
        self.assertTrue(
            all(sum(len(r["text"]) for r in c.values()) <= 12000 for c in chunks)
        )
        self.assertEqual("".join(r["text"] for c in chunks for r in c.values()), text)

    def test_model_authored_quote_rejected(self):
        index = index_evidence(evidence())
        with self.assertRaisesRegex(ValueError, "not author quotations"):
            restore_passages(
                {
                    "criteria": [
                        {
                            "passages": [
                                {
                                    "span_id": next(iter(index)),
                                    "exact_quote": "invented",
                                }
                            ]
                        }
                    ]
                },
                index,
            )
