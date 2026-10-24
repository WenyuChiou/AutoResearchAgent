"""Original saved source broker, authored receipts only."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planned_query_raw_runner import run_cases


class ProjectSourceRunTests(unittest.TestCase):
    def test_original_source_run_authority(self):
        run_cases("project_source_run_cases", self)


class MalformedRunProofTests(unittest.TestCase):
    def test_untyped_saved_action_key_is_a_typed_refusal(self):
        from research_workspace_native.project_source_run import saved
        from research_workspace_native.session_api import SessionApiError

        for value in (None, [], {}):
            with self.subTest(value=value), self.assertRaises(SessionApiError):
                body = {
                    "confirmed": False,
                    "key": "not-authorized-work",
                    "run_authority": {"action_key": value},
                }
                saved(None, "alice", "project", body, "source-authorize")


if __name__ == "__main__":
    unittest.main()
