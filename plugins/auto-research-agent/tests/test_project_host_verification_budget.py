"""Project routes answer a verification budget overrun with its own 503."""

# ruff: noqa: E402 -- exercise repository CLI.
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from research_workspace_native.project_host import ProjectHandler
from stage1_retrieval import verification_clock


class ProjectRouteBudgetTests(unittest.TestCase):
    def test_overview_budget_overrun_is_503_with_its_own_reason(self):
        replies = []

        def overview(token, ref, **_):
            raise verification_clock.LocalVerificationBudgetExceeded(
                verification_clock.BUDGET_CODE
            )

        handler = SimpleNamespace(
            path="/api/projects/project-a/overview",
            headers={},
            _headers=lambda method: ("token", 0),
            _remaining=lambda: 1.0,
            _reply=lambda status, value: replies.append((status, value)),
            server=SimpleNamespace(
                authenticate=lambda token: "local-viewer",
                overview=overview,
                projects=SimpleNamespace(),
            ),
        )
        ProjectHandler._project(handler, "GET")
        self.assertEqual(
            replies, [(503, {"error": "local-verification-budget-exceeded"})]
        )


if __name__ == "__main__":
    unittest.main()
