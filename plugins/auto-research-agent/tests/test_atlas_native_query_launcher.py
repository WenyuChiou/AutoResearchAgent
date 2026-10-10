"""Fresh raw-loader synthetic native/query launcher scenarios."""

import unittest
from planned_query_raw_runner import run_cases


class NativeQueryLauncherContractTests(unittest.TestCase):
    def test_fresh_raw_launcher_scenarios(self):
        run_cases("atlas_native_query_launcher_cases", self)
