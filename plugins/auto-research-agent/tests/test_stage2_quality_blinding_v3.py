# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Blinding and restoration tests for native Stage 2 v3 quality batches."""

import copy
import json
import sys
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage2_common import Stage2Error
from stage2_live.rubric_quality_v3 import (
    prepare_quality_batch,
    quality_batch_schema,
    quality_prompt,
    restore_quality_batch,
)


RUBRIC = json.loads(
    (PLUGIN / "evals" / "rubrics" / "stage2-general.v3.json").read_text(
        encoding="utf-8"
    )
)


def cases():
    criterion = RUBRIC["criteria"][0]["id"]
    return [
        {
            "case_id": "private-answer-score-0-anchor",
            "criterion_id": criterion,
            "base_case_id": None,
            "variant": "anchor-score-0",
            "facts": [
                {
                    "evidence_id": "private-fact-target-score-0",
                    "text": "The record makes an unsupported central claim.",
                }
            ],
            "observation": "The subject record is available.",
            "presentation": "Subject assessment A.",
        },
        {
            "case_id": "private-answer-score-2-anchor",
            "criterion_id": criterion,
            "base_case_id": None,
            "variant": "anchor-score-2",
            "facts": [
                {
                    "evidence_id": "private-fact-target-score-2",
                    "text": "The record is faithful and bounded.",
                }
            ],
            "observation": "The subject record is available.",
            "presentation": "Subject assessment B.",
        },
    ]


def raw_batch(prepared):
    return {
        "kind": "Stage2RubricQualityBatchV3",
        "role": "R1",
        "judgments": [
            {
                "case_id": case_alias,
                "status": "scored",
                "score": score,
                "evidence_ids": [
                    next(iter(prepared["aliases"]["evidence_ids"][case_alias]))
                ],
                "reason": "Judged from the supplied fact.",
                "major_error": score == 0,
            }
            for case_alias, score in zip(("case-01", "case-02"), (0, 2))
        ],
    }


class QualityBlindingV3Tests(unittest.TestCase):
    def test_private_answer_identifiers_are_absent_from_prompt_schema_and_raw(self):
        source = cases()
        prepared = prepare_quality_batch("R1", source, RUBRIC)
        raw = raw_batch(prepared)
        visible = "\n".join(
            (
                prepared["prompt"],
                json.dumps(prepared["schema"], sort_keys=True),
                json.dumps(raw, sort_keys=True),
            )
        )
        for row in source:
            self.assertNotIn(row["case_id"], visible)
            self.assertNotIn(row["base_case_id"] or "anchor-score-0", visible)
            self.assertNotIn(row["variant"], visible)
            for fact in row["facts"]:
                self.assertNotIn(fact["evidence_id"], visible)
        self.assertEqual(
            [row["case_id"] for row in raw["judgments"]], ["case-01", "case-02"]
        )

        renamed = copy.deepcopy(source)
        for index, row in enumerate(renamed, 1):
            row["case_id"] = f"different-secret-{index}"
            row["facts"][0]["evidence_id"] = f"different-fact-{index}"
        renamed_prepared = prepare_quality_batch("R1", renamed, RUBRIC)
        self.assertEqual(prepared["prompt"], renamed_prepared["prompt"])
        self.assertEqual(prepared["schema"], renamed_prepared["schema"])
        self.assertEqual(quality_prompt("R1", source, RUBRIC), prepared["prompt"])
        self.assertEqual(quality_batch_schema("R1", source), prepared["schema"])

    def test_restore_returns_original_ids_and_rejects_cross_case_facts(self):
        source = cases()
        prepared = prepare_quality_batch("R1", source, RUBRIC)
        raw = raw_batch(prepared)
        restored = restore_quality_batch(raw, "R1", source, prepared["aliases"])
        self.assertEqual(
            [row["case_id"] for row in restored["judgments"]],
            [row["case_id"] for row in source],
        )
        self.assertEqual(
            [row["evidence_ids"] for row in restored["judgments"]],
            [[row["facts"][0]["evidence_id"]] for row in source],
        )

        crossed = copy.deepcopy(raw)
        crossed["judgments"][0]["evidence_ids"] = ["evidence-02-01"]
        with self.assertRaisesRegex(Stage2Error, "foreign-or-duplicate"):
            restore_quality_batch(crossed, "R1", source, prepared["aliases"])

        duplicate = copy.deepcopy(raw)
        duplicate["judgments"][1]["case_id"] = "case-01"
        with self.assertRaisesRegex(Stage2Error, "unknown-or-duplicate"):
            restore_quality_batch(duplicate, "R1", source, prepared["aliases"])

        unknown = copy.deepcopy(raw)
        unknown["judgments"][0]["case_id"] = "case-99"
        with self.assertRaisesRegex(Stage2Error, "unknown-or-duplicate"):
            restore_quality_batch(unknown, "R1", source, prepared["aliases"])


if __name__ == "__main__":
    unittest.main()
