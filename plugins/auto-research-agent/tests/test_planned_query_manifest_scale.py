"""Run real-scale manifest cases in the existing fresh raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class PlannedQueryManifestScaleTests(unittest.TestCase):
    def test_real_scale_manifest_cases(self):
        run_cases("planned_query_manifest_scale_cases", self)


if __name__ == "__main__":
    unittest.main()
