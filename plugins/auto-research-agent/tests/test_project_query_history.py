"""Discover project-query history regressions in a fresh raw-source loader."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class ProjectQueryHistoryDiscoveryTests(unittest.TestCase):
    def test_history_binding_scenarios_in_fresh_raw_loader(self):
        run_cases("project_query_history_cases", self)
