"""Run source cases in the existing fresh raw loader; no live calls."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class RawSourceTests(unittest.TestCase):
    def test_sealed_source_cases(self):
        run_cases("project_source_dispatch_cases", self)


if __name__ == "__main__":
    unittest.main()
