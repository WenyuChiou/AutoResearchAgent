"""Run authority scenarios in the existing exact raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectStage1RunQueryDispatchTests(unittest.TestCase):
    def test_original_host_query_continuation(self):
        run_cases("project_stage1_run_query_cases", self)


if __name__ == "__main__":
    unittest.main()
