"""Discover passive intake prerequisites in a fresh raw-source loader."""

import atlas_test_paths  # noqa: F401
import unittest
from planned_query_raw_runner import run_cases


class ProjectStage1IntakePrerequisiteTests(unittest.TestCase):
    def test_fresh_scope_and_history_guards_in_raw_loader(self):
        run_cases("project_stage1_intake_cases", self)
