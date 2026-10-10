"""Discoverable source/intake contract wrapper; no backend or model."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class PlannedQueryContractDiscoveryTests(unittest.TestCase):
    def test_all_scenarios_in_fresh_raw_loader(self):
        run_cases("planned_query_contract_cases", self)
