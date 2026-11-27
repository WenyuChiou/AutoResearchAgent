"""Harness record: timeouts stay timeouts, failures name their reason, counts are saved ones."""

# ruff: noqa: E402 -- exercise repository CLI.
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from research_workspace_native import project_harness_record as record
from research_workspace_native.session_api import SessionApiError


def server(**overrides):
    projects = SimpleNamespace(
        read=lambda credential, ref: {
            "input_version": 1,
            "revision": 3,
            "input_origin": "own",
        },
        history=lambda credential, ref: {"actions": []},
    )
    values = dict(
        projects=projects,
        project_stage1=object(),
        project_stage2=object(),
        project_stage2_selection=SimpleNamespace(read=lambda *a, **k: None),
        project_stage3_http=SimpleNamespace(view=lambda *a, **k: None),
        stage1_view=lambda *a, **k: None,
        stage2_view=lambda *a, **k: None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def raising(error):
    def call(*args, **kwargs):
        raise error

    return call


class HarnessRecordErrorTests(unittest.TestCase):
    def test_a_deadline_timeout_is_raised_never_reported_as_an_empty_stage(self):
        for name in ("stage1_view", "stage2_view"):
            with self.subTest(read=name):
                with self.assertRaises(TimeoutError):
                    record.harness_record(
                        server(
                            **{
                                name: raising(
                                    TimeoutError("absolute request deadline expired")
                                )
                            }
                        ),
                        "own",
                        "ref",
                    )
        for owner, attribute in (
            ("project_stage2_selection", "read"),
            ("project_stage3_http", "view"),
        ):
            with self.subTest(read=owner):
                with self.assertRaises(TimeoutError):
                    record.harness_record(
                        server(
                            **{
                                owner: SimpleNamespace(
                                    **{attribute: raising(TimeoutError("late"))}
                                )
                            }
                        ),
                        "own",
                        "ref",
                    )

    def test_other_read_failures_name_their_stage_and_reason(self):
        result = record.harness_record(
            server(
                stage1_view=raising(sqlite3.OperationalError("locked")),
                stage3_http=None,
                project_stage3_http=SimpleNamespace(
                    view=raising(
                        SessionApiError("stage3-planning-resource-unavailable")
                    )
                ),
            ),
            "own",
            "ref",
        )
        self.assertEqual(result["stages"]["1"]["status"], "unavailable")
        self.assertEqual(result["stages"]["1"]["reason"], "OperationalError")
        self.assertEqual(
            result["stages"]["3"]["reason"], "stage3-planning-resource-unavailable"
        )
        self.assertIn(result["stages"]["2"]["status"], {"not-run", "recorded"})

    def test_selection_failure_is_stated_in_stage_two_not_swallowed(self):
        result = record.harness_record(
            server(
                stage2_view=lambda *a, **k: {"activation": {"x": 1}},
                project_stage2_selection=SimpleNamespace(
                    read=raising(SessionApiError("stage2-selection-source-invalid"))
                ),
            ),
            "own",
            "ref",
        )
        rows = {row["key"]: row for row in result["stages"]["2"]["rows"]}
        self.assertIn("stage2-selection-source-invalid", rows["candidates"]["missing"])

    def test_one_stage_can_be_read_alone_and_unknown_stage_is_refused(self):
        calls = []
        result = record.harness_record(
            server(
                stage1_view=lambda *a, **k: calls.append("1"),
                stage2_view=lambda *a, **k: calls.append("2"),
                project_stage3_http=SimpleNamespace(
                    view=lambda *a, **k: calls.append("3")
                ),
            ),
            "own",
            "ref",
            stage="3",
        )
        self.assertEqual(calls, ["3"])
        self.assertEqual(set(result["stages"]), {"3"})
        with self.assertRaises(SessionApiError):
            record.harness_record(server(), "own", "ref", stage="9")

    def test_counts_are_saved_values_and_renamed(self):
        result = record.harness_record(server(), "own", "ref")
        for stage in result["stages"].values():
            self.assertIn("rows_with_data", stage["summary"])
            self.assertNotIn("checks", stage["summary"])
        self.assertTrue(result["temporary_files"])
        stage2 = record.harness_record(
            server(
                stage2_view=lambda *a, **k: {"activation": {"x": 1}},
                project_stage2_selection=SimpleNamespace(
                    read=lambda *a, **k: {
                        "cards": [{}, {}, {}],
                        "selection_receipt": None,
                        "selection_status": "pending",
                    }
                ),
            ),
            "own",
            "ref",
        )["stages"]["2"]
        self.assertEqual(
            stage2["summary"]["records"], 0
        )  # derived cards are not records

    def test_classification_uses_whole_words_and_confusable_codes(self):
        for code, expected in (
            ("project-unavailable", "wrong-project"),
            ("stage3-planning-configuration-project-differs", "wrong-project"),
            ("stage2-selection-view-stale", "stale-version"),
            ("intake-source-version-differs", "stale-version"),
            ("idempotency-payload-differs", "duplicate-click"),
            ("stage2-selection-already-recorded", "duplicate-click"),
            ("intake-action-bound-exceeded", "over-limit"),
            ("stage2-selection-unconnected", "failed-check"),
            ("absolute request deadline expired", "failed-check"),
            ("unstaleable-thing", "failed-check"),
            ("delimiter-unlimited", "failed-check"),
            ("", "failed-check"),
            (None, "failed-check"),
        ):
            with self.subTest(code=code):
                self.assertEqual(record._classify(code), expected)


if __name__ == "__main__":
    unittest.main()
