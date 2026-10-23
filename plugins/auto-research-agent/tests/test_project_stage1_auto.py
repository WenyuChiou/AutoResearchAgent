"""Run only automatic Stage1 service cases in a fresh pinned source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectStage1AutoTests(unittest.TestCase):
    def test_existing_services_continue_until_missing_producer(self):
        run_cases("project_stage1_auto_cases", self, timeout_seconds=300)


if __name__ == "__main__":
    unittest.main()
