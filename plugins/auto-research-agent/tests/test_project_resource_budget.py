"""Run shared resource budget cases in the fresh raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectResourceBudgetTests(unittest.TestCase):
    def test_sealed_project_resource_budget(self):
        run_cases("project_resource_budget_cases", self)


if __name__ == "__main__":
    unittest.main()
