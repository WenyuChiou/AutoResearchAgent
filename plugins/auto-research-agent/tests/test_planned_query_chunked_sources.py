"""Fresh-loader source chunk guards; no native/model/search calls."""

import unittest
from planned_query_raw_runner import run_cases


class PlannedQueryChunkedSourceTests(unittest.TestCase):
    def test_fresh_raw_source_bounds_and_bytes(self):
        run_cases("planned_query_chunked_source_cases", self)
