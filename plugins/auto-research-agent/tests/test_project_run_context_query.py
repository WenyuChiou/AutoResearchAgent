"""Fresh raw-source query-owned companion regression; zero external execution."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class QueryRunContextTests(unittest.TestCase):
    def test_actual_query_owned_deliverable_run_context(self):
        run_cases(
            "project_run_context_query_cases.QueryRunContextCase.test_actual_query_owned_delivery_keeps_original_core_identity_and_resources",
            self,
        )


if __name__ == "__main__":
    unittest.main()
