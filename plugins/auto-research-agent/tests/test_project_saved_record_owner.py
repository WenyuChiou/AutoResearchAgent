"""Run production saved-owner scenarios in the fresh raw-source test process."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectSavedRecordOwnerTests(unittest.TestCase):
    def test_production_saved_owner_guard(self):
        run_cases("project_saved_record_owner_cases", self)


if __name__ == "__main__":
    unittest.main()
