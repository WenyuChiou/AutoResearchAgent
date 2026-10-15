"""Fresh raw-source child for query revision boundaries; no real execution."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectQueryVersionTests(unittest.TestCase):
    def test_versioned_permission_and_history_boundaries(self):
        run_cases("project_query_version_cases", self)


if __name__ == "__main__":
    unittest.main()
