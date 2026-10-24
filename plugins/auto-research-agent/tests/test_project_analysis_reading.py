"""Pure saved-reading record preparation; no ledger or source I/O."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_analysis_reading import prepare_reading_record
from research_workspace_native.session_api import SessionApiError
from test_project_analysis_events import inputs, prepare, prepare_from_sources


def reading_inputs():
    snapshot, _, raw, facts, ref = inputs()
    plan = prepare(snapshot, raw, facts, ref)
    metadata = deepcopy(snapshot["reading_input"]["saved_reading"])
    metadata["schema_version"] = "1.0.0"
    metadata["candidate_event_id"] = "e000101"
    return plan, metadata


def reading(plan, metadata, **changes):
    kwargs = {
        "decision_event_id": "e000102",
        "claim_event_ids": {
            row["claim_key"]: f"e{200 + index:06d}"
            for index, row in enumerate(plan["claims"])
        },
        "previous_claim_spans": [],
        "review_event_id": None,
    }
    kwargs.update(changes)
    return prepare_reading_record(plan, metadata, **kwargs)


class AnalysisReadingTests(unittest.TestCase):
    def test_reading_record_accepts_only_strict_source_evidence_plan(self):
        snapshot, _, raw, facts, _ = inputs()
        plan = prepare_from_sources(snapshot, raw, facts)
        metadata = deepcopy(snapshot["reading_input"]["saved_reading"])
        metadata["schema_version"] = "1.0.0"
        metadata["candidate_event_id"] = "e000101"
        result = reading(plan, metadata)
        self.assertEqual(result["schema_version"], "1.1.0")
        self.assertEqual(result["roles"], [])
        for field, value in (
            ("proposal_sha256", "A" * 64),
            ("proposal_storage", "artifact-store"),
            ("proposal_ref", facts[0]["text_ref"]),
        ):
            bad = deepcopy(plan)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(SessionApiError):
                reading(bad, metadata)

    def test_reading_record_is_core_1_1_with_exact_unicode_spans(self):
        plan, metadata = reading_inputs()
        result = reading(plan, metadata, review_event_id="e000103")
        expected = [
            {"claim_id": f"e{200 + index:06d}", **row["span"]}
            for index, row in enumerate(plan["claims"])
        ]
        self.assertEqual(
            result,
            {
                "schema_version": "1.1.0",
                "work_id": "work-1",
                "version_id": "version-1",
                "candidate_event_id": "e000101",
                "decision_event_id": "e000102",
                "review_event_id": "e000103",
                "source_ids": ["source-1", "source-failed"],
                "classification": plan["proposal"]["reading"]["classification"],
                "findings": plan["proposal"]["reading"]["findings"],
                "roles": [],
                "claims": expected,
            },
        )
        self.assertEqual(result["claims"][0]["quote"], "尾端證據 Ω")

    def test_reading_record_keeps_all_previous_spans_and_copies_inputs(self):
        plan, metadata = reading_inputs()
        previous = [
            {
                "claim_id": "e000099",
                "source_id": None,
                "text_sha256": "a" * 64,
                "start": None,
                "end": None,
                "quote": None,
            }
        ]
        before = deepcopy((plan, metadata, previous))
        result = reading(plan, metadata, previous_claim_spans=previous)
        self.assertEqual((plan, metadata, previous), before)
        self.assertEqual(result["claims"][-1], previous[0])
        result["claims"][-1]["text_sha256"] = "b" * 64
        result["classification"][next(iter(result["classification"]))] = "changed"
        self.assertEqual((plan, metadata, previous), before)

    def test_reading_record_rejects_event_and_claim_map_errors(self):
        plan, metadata = reading_inputs()
        key = plan["claims"][0]["claim_key"]
        cases = (
            {"decision_event_id": "claim-1"},
            {"claim_event_ids": {}},
            {"claim_event_ids": {key: "e000200", "extra": "e000201"}},
            {"claim_event_ids": {key: "e1"}},
            {
                "previous_claim_spans": [
                    {
                        "claim_id": "e000200",
                        "source_id": "source-1",
                        "text_sha256": "a" * 64,
                        "start": 0,
                        "end": 1,
                        "quote": "x",
                    }
                ]
            },
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(SessionApiError):
                reading(plan, metadata, **changes)

    def test_reading_record_rejects_cross_version_and_bad_previous_spans(self):
        plan, metadata = reading_inputs()
        changed = deepcopy(metadata)
        changed["version_id"] = "version-other"
        with self.assertRaises(SessionApiError):
            reading(plan, changed)
        base = {
            "claim_id": "e000099",
            "source_id": "source-1",
            "text_sha256": "a" * 64,
            "start": 0,
            "end": 1,
            "quote": "x",
        }
        for bad in (
            {**base, "extra": True},
            {**base, "text_sha256": "A" * 64},
            {**base, "start": True},
            {**base, "end": 2},
            {**base, "source_id": "source-other"},
        ):
            with self.subTest(bad=bad), self.assertRaises(SessionApiError):
                reading(plan, metadata, previous_claim_spans=[bad])

    def test_direct_api_rejects_unhashable_prior_source_ids(self):
        plan, metadata = reading_inputs()
        base = {
            "claim_id": "e000099",
            "source_id": None,
            "text_sha256": "a" * 64,
            "start": None,
            "end": None,
            "quote": None,
        }
        for source in ([], {}):
            with self.subTest(source=source), self.assertRaises(SessionApiError):
                reading(
                    plan, metadata, previous_claim_spans=[{**base, "source_id": source}]
                )

    def test_direct_api_rejects_damaged_claim_keys_before_building_sets(self):
        plan, metadata = reading_inputs()
        for key in ([], {}, None, 1):
            bad = deepcopy(plan)
            bad["claims"][0]["claim_key"] = key
            with self.subTest(key=key), self.assertRaises(SessionApiError):
                prepare_reading_record(
                    bad,
                    metadata,
                    decision_event_id="e000102",
                    claim_event_ids={},
                    previous_claim_spans=[],
                    review_event_id=None,
                )

    def test_reading_record_keeps_failed_source_ids_and_old_raw_claims(self):
        plan, metadata = reading_inputs()
        old = {
            "claim_id": "e000099",
            "source_id": "source-failed",
            "text_sha256": "b" * 64,
            "start": None,
            "end": None,
            "quote": None,
        }
        result = reading(plan, metadata, previous_claim_spans=[old])
        self.assertEqual(result["source_ids"], ["source-1", "source-failed"])
        self.assertEqual(result["claims"][-1], old)


if __name__ == "__main__":
    unittest.main()
