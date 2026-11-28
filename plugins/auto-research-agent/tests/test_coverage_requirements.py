"""The coverage gate's lower bound is plain arithmetic; the numbers come from two real topics."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from research_workspace_native.project_coverage_hint import coverage_requirement_hint
from research_workspace_native.coverage_requirements import (
    compare_with_scope,
    minimum_requirement,
)


SECONDS = dict(approved_seconds=10**6, seconds_per_attempt=90)


def policy(*, zero=2, closest=3, rounds=3):
    return dict(
        max_rounds=rounds,
        consecutive_zero_yield_rounds=zero,
        closest_min_verified=closest,
    )


class MinimumRequirementTests(unittest.TestCase):
    def need(self, planned, backends, **kwargs):
        return minimum_requirement(
            planned_query_count=planned,
            backend_count=backends,
            stop_policy=policy(**kwargs),
        )

    def test_real_topics_two_backends_24_queries(self):
        need = self.need(24, 2)
        self.assertEqual(need["min_closed_rounds"], 3)
        self.assertEqual(need["searches_per_round"], 48)
        self.assertEqual(need["expansions_min"], 6)
        self.assertEqual(need["min_search_attempts"], 150)

    def test_real_topics_one_backend_24_queries(self):
        self.assertEqual(self.need(24, 1)["min_search_attempts"], 78)

    def test_smallest_plan_one_backend(self):
        self.assertEqual(self.need(3, 1, closest=1)["min_search_attempts"], 11)

    def test_more_zero_yield_rounds_need_more_rounds(self):
        need = self.need(3, 1, zero=3, closest=1)
        self.assertEqual(need["min_closed_rounds"], 4)
        self.assertEqual(need["min_search_attempts"], 4 * 3 + 2)

    def test_bad_counts_are_refused_by_the_function_not_guessed(self):
        for planned, backends in ((0, 1), (1, 0), (True, 1), (1, "2")):
            with self.subTest(planned=planned, backends=backends):
                with self.assertRaises(ValueError):
                    self.need(planned, backends)


class CompareWithScopeTests(unittest.TestCase):
    def need(self, planned=24, backends=1, **kwargs):
        return minimum_requirement(
            planned_query_count=planned,
            backend_count=backends,
            stop_policy=policy(**kwargs),
        )

    def test_the_scope_that_was_approved_in_the_real_run_cannot_reach_the_gate(self):
        result = compare_with_scope(
            self.need(24, 2),
            approved_rounds=3,
            approved_search_attempts=14,
            **SECONDS,
        )
        self.assertTrue(result["rounds_enough"])
        self.assertFalse(result["search_attempts_enough"])
        self.assertFalse(result["can_reach_coverage_gate"])
        self.assertEqual(result["min_search_attempts"], 150)

    def test_two_rounds_never_reach_the_gate_whatever_the_attempts(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1),
            approved_rounds=2,
            approved_search_attempts=128,
            **SECONDS,
        )
        self.assertFalse(result["rounds_enough"])
        self.assertTrue(result["search_attempts_enough"])
        self.assertFalse(result["can_reach_coverage_gate"])

    def test_plan_max_rounds_below_the_minimum_also_blocks(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1, rounds=2),
            approved_rounds=5,
            approved_search_attempts=128,
            **SECONDS,
        )
        self.assertFalse(result["rounds_enough"])

    def test_enough_scope_is_marked_reachable(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1),
            approved_rounds=3,
            approved_search_attempts=11,
            **SECONDS,
        )
        self.assertTrue(result["can_reach_coverage_gate"])

    def test_attempts_enough_but_reserved_seconds_run_out_first(self):
        # real server: 600 reserved seconds, 60 s timeout + 30 s margin = 90 s per attempt.
        # 78 attempts need 30 + 78 * 90 = 7050 s, so 128 attempts alone would not be enough.
        result = compare_with_scope(
            self.need(24, 1),
            approved_rounds=3,
            approved_search_attempts=128,
            approved_seconds=600,
            seconds_per_attempt=90,
        )
        self.assertEqual(result["min_reserved_seconds"], 7050)
        self.assertTrue(result["search_attempts_enough"])
        self.assertFalse(result["seconds_enough"])
        self.assertFalse(result["can_reach_coverage_gate"])

    def test_enough_seconds_are_marked_reachable(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1),
            approved_rounds=3,
            approved_search_attempts=11,
            approved_seconds=30 + 11 * 90,
            seconds_per_attempt=90,
        )
        self.assertTrue(result["seconds_enough"])
        self.assertTrue(result["can_reach_coverage_gate"])

    def test_plan_round_limit_is_reported_apart_from_the_approved_scope(self):
        small_plan = compare_with_scope(
            self.need(3, 1, closest=1, rounds=2),
            approved_rounds=5,
            approved_search_attempts=128,
            **SECONDS,
        )
        self.assertTrue(small_plan["plan_rounds_too_small"])
        small_scope = compare_with_scope(
            self.need(3, 1, closest=1, rounds=5),
            approved_rounds=2,
            approved_search_attempts=128,
            **SECONDS,
        )
        self.assertFalse(small_scope["plan_rounds_too_small"])
        self.assertFalse(small_scope["rounds_enough"])


class HintFromSavedPlanTests(unittest.TestCase):
    """The read-view helper turns saved plan files into numbers, or says why it cannot."""

    LIMITS = dict(
        backends=["openalex", "arxiv"],
        max_attempts=128,
        max_reserved_seconds=600,
        timeout_seconds=60,
    )

    def binding(self, root, *, rounds=3):
        return dict(plan_root=root, settings=dict(budgets=dict(rounds=rounds)))

    def write_plan(self, root, *, queries=24, stop_policy=None):
        (root / "coverage_plan.json").write_text(
            json.dumps(
                dict(proposal=dict(stop_policy=stop_policy or policy())),
            ),
            encoding="utf-8",
            newline="",
        )
        (root / "query_plan.jsonl").write_text(
            "".join(
                json.dumps(dict(query_id=f"q{i}")) + chr(10) for i in range(queries)
            ),
            encoding="utf-8",
            newline="",
        )

    def test_saved_plan_gives_the_numbers_including_reserved_seconds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_plan(root)
            hint = coverage_requirement_hint(self.binding(root), self.LIMITS)
        self.assertEqual(hint["min_search_attempts"], 150)
        self.assertEqual(hint["min_reserved_seconds"], 30 + 150 * 90)
        self.assertFalse(hint["seconds_enough"])
        self.assertFalse(hint["can_reach_coverage_gate"])

    def test_missing_or_broken_plan_files_say_why_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(
                coverage_requirement_hint(self.binding(root), self.LIMITS),
                {"unavailable": "coverage-plan-unreadable"},
            )
            self.write_plan(root)
            (root / "query_plan.jsonl").unlink()
            self.assertEqual(
                coverage_requirement_hint(self.binding(root), self.LIMITS),
                {"unavailable": "query-plan-unreadable"},
            )
            self.write_plan(root, stop_policy=dict(max_rounds=3))
            self.assertEqual(
                coverage_requirement_hint(self.binding(root), self.LIMITS),
                {"unavailable": "plan-values-invalid"},
            )
            self.write_plan(root)
            self.assertEqual(
                coverage_requirement_hint(
                    self.binding(root), dict(self.LIMITS, timeout_seconds=None)
                ),
                {"unavailable": "approved-scope-values-missing"},
            )


if __name__ == "__main__":
    unittest.main()
