"""Discoverable wrapper; all named scenarios run in a fresh raw-loader child."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class PlannedQueryHttpDiscoveryTests(unittest.TestCase):
    def test_all_scenarios_in_fresh_raw_loader(self):
        run_cases("planned_query_http_cases", self)
