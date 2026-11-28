"""The coverage gate's lower bound is plain arithmetic; the numbers come from two real topics."""

from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_coverage.requirements import compare_with_scope, minimum_requirement


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
            self.need(24, 2), approved_rounds=3, approved_search_attempts=14
        )
        self.assertTrue(result["rounds_enough"])
        self.assertFalse(result["search_attempts_enough"])
        self.assertFalse(result["can_reach_coverage_gate"])
        self.assertEqual(result["min_search_attempts"], 150)

    def test_two_rounds_never_reach_the_gate_whatever_the_attempts(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1), approved_rounds=2, approved_search_attempts=128
        )
        self.assertFalse(result["rounds_enough"])
        self.assertTrue(result["search_attempts_enough"])
        self.assertFalse(result["can_reach_coverage_gate"])

    def test_plan_max_rounds_below_the_minimum_also_blocks(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1, rounds=2),
            approved_rounds=5,
            approved_search_attempts=128,
        )
        self.assertFalse(result["rounds_enough"])

    def test_enough_scope_is_marked_reachable(self):
        result = compare_with_scope(
            self.need(3, 1, closest=1), approved_rounds=3, approved_search_attempts=11
        )
        self.assertTrue(result["can_reach_coverage_gate"])


if __name__ == "__main__":
    unittest.main()
