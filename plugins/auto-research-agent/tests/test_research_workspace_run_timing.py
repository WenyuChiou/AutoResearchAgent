"""Check bound timing reports, interval unions and explicit missing measurements."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.run_timing import summarize_timing
from stage1_deliverable.common import DeliverableError


PINS = {"project_id": "synthetic", "input_version": "3.0.0", "index_sha256": "a" * 64}


def interval(identity, phase, start, end):
    return {
        "id": identity,
        "phase": phase,
        "started_at": start,
        "ended_at": end,
        "evidence_refs": ["synthetic:attempt/" + identity],
    }


def fixture():
    return {
        "kind": "Stage1RunTiming",
        "schema_version": "1.0.0",
        **PINS,
        "started_at": "2026-10-08T09:00:00-04:00",
        "ended_at": None,
        "observed_at": "2026-10-08T14:00:00Z",
        "intervals": [],
    }


class RunTimingTests(unittest.TestCase):
    def test_integer_input_version_is_supported_but_bool_alias_is_rejected(self):
        record = {**fixture(), "input_version": 1}
        pins = {**PINS, "input_version": 1}
        self.assertEqual(summarize_timing(record, **pins)["input_version"], 1)
        record["input_version"] = True
        with self.assertRaises(DeliverableError):
            summarize_timing(record, **pins)

    def test_parallel_cross_phase_union_timezone_and_input_preservation(self):
        record = fixture()
        record["ended_at"] = "2026-10-08T13:40:00+00:00"
        record["intervals"] = [
            interval(
                "a", "search", "2026-10-08T09:00:00-04:00", "2026-10-08T13:20:00Z"
            ),
            interval("b", "search", "2026-10-08T13:10:00Z", "2026-10-08T13:30:00Z"),
            interval(
                "c", "acquisition", "2026-10-08T13:05:00Z", "2026-10-08T13:25:00Z"
            ),
            interval(
                "d", "engineering", "2026-10-08T13:25:00Z", "2026-10-08T13:35:00Z"
            ),
            interval("e", "ci-wait", "2026-10-08T13:30:00Z", "2026-10-08T13:40:00Z"),
        ]
        before = deepcopy(record)
        report = summarize_timing(record, **PINS)
        self.assertEqual(record, before)
        expected = dict(
            wall_seconds=2400,
            finished_run_seconds=2400,
            research_active_seconds=1800,
            engineering_seconds=600,
            ci_wait_seconds=600,
            known_active_seconds_lower_bound=2100,
            completed_interval_seconds=2400,
        )
        self.assertEqual({key: report[key] for key in expected}, expected)
        self.assertEqual(report["phases"]["search"]["duration_seconds"], 1800)
        report["intervals"][0]["evidence_refs"].append("output-change")
        self.assertEqual(record, before)

    def test_pending_and_missing_are_not_zero_complete(self):
        record = fixture()
        record["intervals"] = [interval("p", "search", "2026-10-08T13:10:00Z", None)]
        report = summarize_timing(record, **PINS)
        self.assertEqual(report["wall_seconds"], 3600)
        self.assertIsNone(report["finished_run_seconds"])
        self.assertIsNone(report["research_active_seconds"])
        self.assertEqual(report["phases"]["search"]["status"], "pending")
        self.assertIsNone(report["phases"]["search"]["duration_seconds"])
        self.assertEqual(report["phases"]["intake"]["status"], "unmeasured")
        self.assertIsNone(report["phases"]["intake"]["duration_seconds"])

    def test_stale_bindings_and_record_contract_reject(self):
        for key, value in (
            ("project_id", "other"),
            ("input_version", "2.0.0"),
            ("index_sha256", "b" * 64),
            ("kind", "other"),
            ("schema_version", "2.0.0"),
            ("intervals", {}),
        ):
            record = fixture()
            record[key] = value
            with self.subTest(key=key), self.assertRaises(DeliverableError):
                summarize_timing(record, **PINS)
        for record in (None, [], {}, {**fixture(), "extra": True}):
            with self.subTest(record=record), self.assertRaises(DeliverableError):
                summarize_timing(record, **PINS)

    def test_unknown_duplicate_bad_evidence_and_invalid_interval_times_reject(self):
        good = interval("a", "search", "2026-10-08T13:10:00Z", "2026-10-08T13:20:00Z")
        changes = [
            ("phase", "future-phase"),
            ("evidence_refs", []),
            ("started_at", "2026-10-08T13:10:00"),
            ("started_at", float("nan")),
            ("started_at", "2026-10-08T12:00:00Z"),
            ("started_at", "2026-10-08T15:00:00Z"),
            ("ended_at", "2026-10-08T13:00:00Z"),
            ("ended_at", "2026-10-08T15:00:00Z"),
            ("ended_at", float("inf")),
        ]
        for key, value in changes:
            record = fixture()
            record["intervals"] = [{**good, key: value}]
            with (
                self.subTest(key=key, value=value),
                self.assertRaises(DeliverableError),
            ):
                summarize_timing(record, **PINS)
        record = fixture()
        record["intervals"] = [good, deepcopy(good)]
        with self.assertRaisesRegex(DeliverableError, "duplicate"):
            summarize_timing(record, **PINS)

    def test_reversed_future_run_and_interval_after_recorded_end_reject(self):
        for ended in ("2026-10-08T12:00:00Z", "2026-10-08T15:00:00Z", "invalid"):
            with self.subTest(ended=ended), self.assertRaises(DeliverableError):
                summarize_timing({**fixture(), "ended_at": ended}, **PINS)
        record = fixture()
        record["ended_at"] = "2026-10-08T13:15:00Z"
        record["intervals"] = [
            interval("a", "search", "2026-10-08T13:10:00Z", "2026-10-08T13:20:00Z")
        ]
        with self.assertRaises(DeliverableError):
            summarize_timing(record, **PINS)


if __name__ == "__main__":
    unittest.main()
