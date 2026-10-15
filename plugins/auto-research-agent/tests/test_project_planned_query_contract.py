"""Discoverable v1.1 project contract regression wrapper; saved fixture only."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class ProjectPlannedQueryContractDiscoveryTests(unittest.TestCase):
    def test_all_scenarios_in_fresh_raw_loader(self):
        run_cases("project_planned_query_contract_cases", self)
