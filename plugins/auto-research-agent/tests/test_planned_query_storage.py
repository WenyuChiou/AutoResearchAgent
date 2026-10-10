"""Discoverable pure source/storage contract wrapper."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class PlannedQueryStorageDiscoveryTests(unittest.TestCase):
    def test_all_scenarios_in_fresh_raw_loader(self):
        run_cases("planned_query_storage_cases", self)
