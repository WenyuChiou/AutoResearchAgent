"""Run real project query scenarios in the existing fresh raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectStage1QueryTests(unittest.TestCase):
    def test_sealed_project_query_lifecycle(self):
        run_cases("project_stage1_query_cases", self)


if __name__ == "__main__":
    unittest.main()
