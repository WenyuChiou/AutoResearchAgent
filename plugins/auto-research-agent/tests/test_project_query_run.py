"""Run authority scenarios in the existing exact raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectQueryRunTests(unittest.TestCase):
    def test_original_query_run_authority(self):
        run_cases("project_query_run_cases", self)


if __name__ == "__main__":
    unittest.main()
