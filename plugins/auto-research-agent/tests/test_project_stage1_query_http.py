"""Project query HTTP scenarios in the existing fresh raw-loader test worker."""

import unittest

from planned_query_raw_runner import run_cases


class ProjectStage1QueryHttpDiscoveryTests(unittest.TestCase):
    def test_fresh_raw_http_sqlite_scenarios(self):
        run_cases("project_stage1_query_http_cases", self)
