"""Run owned Core/SQLite observation cases in the fresh raw-source loader."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class OwnedSourceObservationTests(unittest.TestCase):
    def test_sealed_owned_source_observations(self):
        run_cases("owned_source_observation_cases", self)


if __name__ == "__main__":
    unittest.main()
