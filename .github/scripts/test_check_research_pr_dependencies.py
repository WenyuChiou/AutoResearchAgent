"""Regression tests for live pull-request dependency checks."""

import unittest

from check_research_pr_dependencies import validate_dependencies
from test_validate_research_pr import VALID


class FakeResolver:
    def __init__(self, states):
        self.states = states

    def resolve(self, url):
        return self.states[url]


class ResearchPullRequestDependencyTests(unittest.TestCase):
    def test_cross_repository_pr_cannot_be_an_internal_prerequisite(self):
        url = "https://github.com/WenyuChiou/research-hub/pull/137"
        body = VALID.replace(
            "- Internal prerequisite PR(s): None",
            f"- Internal prerequisite PR(s): {url}",
        )
        errors = validate_dependencies(body, True, FakeResolver({}))
        self.assertEqual(
            errors,
            [
                "internal prerequisite must belong to "
                f"WenyuChiou/AutoResearchAgent: {url}"
            ],
        )

    def test_draft_stacked_pr_can_depend_on_open_internal_pr(self):
        url = "https://github.com/WenyuChiou/AutoResearchAgent/pull/12"
        body = VALID.replace(
            "- Internal prerequisite PR(s): None",
            f"- Internal prerequisite PR(s): {url}",
        )
        resolver = FakeResolver(
            {
                url: {
                    "state": "OPEN",
                    "mergedAt": None,
                    "reviewDecision": "CHANGES_REQUESTED",
                }
            }
        )
        self.assertEqual(validate_dependencies(body, True, resolver), [])

    def test_ready_pr_rejects_unmerged_or_changes_requested_prerequisite(self):
        url = "https://github.com/WenyuChiou/AutoResearchAgent/pull/12"
        body = VALID.replace(
            "- Internal prerequisite PR(s): None",
            f"- Internal prerequisite PR(s): {url}",
        )
        resolver = FakeResolver(
            {
                url: {
                    "state": "OPEN",
                    "mergedAt": None,
                    "reviewDecision": "CHANGES_REQUESTED",
                }
            }
        )
        errors = validate_dependencies(body, False, resolver)
        self.assertIn(f"ready PR requires merged internal prerequisite: {url}", errors)
        self.assertIn(f"ready PR prerequisite has changes requested: {url}", errors)

    def test_external_open_pin_checks_head_sha_and_allows_draft(self):
        url = "https://github.com/WenyuChiou/research-hub/pull/137"
        sha = "a" * 40
        body = VALID.replace(
            "- External dependency pin(s): None",
            f"- External dependency pin(s): {url} @ {sha} @ open",
        )
        resolver = FakeResolver(
            {
                url: {
                    "state": "OPEN",
                    "mergedAt": None,
                    "reviewDecision": "",
                    "headRefOid": sha,
                    "mergeCommit": None,
                }
            }
        )
        self.assertEqual(validate_dependencies(body, True, resolver), [])

        executable = body.replace(
            "- Evaluation readiness: implementation-only",
            "- Evaluation readiness: stage-executable",
        )
        self.assertIn(
            f"ready or executable PR requires merged external dependency: {url}",
            validate_dependencies(executable, True, resolver),
        )

    def test_external_pin_rejects_sha_drift(self):
        url = "https://github.com/WenyuChiou/research-hub/pull/137"
        expected = "a" * 40
        actual = "b" * 40
        body = VALID.replace(
            "- External dependency pin(s): None",
            f"- External dependency pin(s): {url} @ {expected} @ open",
        )
        resolver = FakeResolver(
            {
                url: {
                    "state": "OPEN",
                    "mergedAt": None,
                    "reviewDecision": "",
                    "headRefOid": actual,
                    "mergeCommit": None,
                }
            }
        )
        self.assertIn(
            f"external dependency SHA mismatch for {url}: expected {expected}, got {actual}",
            validate_dependencies(body, True, resolver),
        )

    def test_ready_pr_requires_merged_external_merge_sha(self):
        url = "https://github.com/WenyuChiou/research-hub/pull/137"
        sha = "c" * 40
        body = VALID.replace(
            "- External dependency pin(s): None",
            f"- External dependency pin(s): {url} @ {sha} @ merged",
        )
        resolver = FakeResolver(
            {
                url: {
                    "state": "MERGED",
                    "mergedAt": "2026-09-20T12:00:00Z",
                    "reviewDecision": "APPROVED",
                    "headRefOid": "d" * 40,
                    "mergeCommit": {"oid": sha},
                }
            }
        )
        self.assertEqual(validate_dependencies(body, False, resolver), [])
        executable = body.replace(
            "- Evaluation readiness: implementation-only",
            "- Evaluation readiness: stage-executable",
        )
        self.assertEqual(validate_dependencies(executable, False, resolver), [])
        resolver.states[url]["reviewDecision"] = ""
        self.assertIn(
            f"executable readiness requires an approved external dependency: {url}",
            validate_dependencies(executable, False, resolver),
        )


if __name__ == "__main__":
    unittest.main()
