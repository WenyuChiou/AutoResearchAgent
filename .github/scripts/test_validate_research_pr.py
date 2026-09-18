"""Regression tests for the research pull-request contract."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from validate_research_pr import changed_files, load_rubrics, validate_pr_body


VALID = """## Why
- Plain-language summary: Keep a searchable record so another person can see why each paper was kept or removed.
- Target primary metric(s): P2
Target metric P2 has a measured coverage failure.

## What
- Affected capability ID(s): skill:stage1-literature
- Capability decision: wrap
- Related external PR(s): None
Wrap the existing search command.

## How
Emit an append-only candidate ledger and explicit stop gate.

## Example
Before: count reached.
After: incomplete cluster continues.

## Evaluation
- Rubric version: aging-bidirectional-rubric-v1
- Rubric criterion ID(s): P2.CLUSTERS, P2.CLOSEST_WORK
- Evaluation mode: hybrid
- Hard measures: cluster and trace counts
- AI-judge evidence: deferred: waiting for the Stage 1 executable milestone; synthetic schema artifact passed
- Major-error guardrail: no fabricated source
- Per-PR metric evidence: synthetic coverage-gate regression passed
- Improvement statement: not yet demonstrated — deterministic behavior is implemented but live quality remains unknown; evidence: 18 validator tests passed and live A/B is deferred to the Stage 1 milestone
- Live paired A/B: deferred to Stage 1 executable milestone
Compare paired P2 counts and blinded judgments.

## Validation
Synthetic regression tests passed.
- Execution status: complete
- Remaining work or blocker: None
- Review and merge owner: core team
- Skill test scenario: synthetic missing coverage cluster
- Skill test command: python -m unittest discover
- Skill test expected: the skill loads and returns continue
- Skill test actual: 4 tests passed and the fixture validated
- Skill test limitations: no live retrieval or human P2 score
"""

CAPABILITIES = {
    "skill:stage1-literature": {
        "metrics": {"P1", "P2", "P3"},
        "criteria": {
            "P1.CLAIM_SUPPORT",
            "P2.CLUSTERS",
            "P2.CLOSEST_WORK",
            "P3.DECISION_TRACE",
        },
        "owner_path": "plugins/auto-research-agent/skills/stage1-literature",
    }
}


class ResearchPullRequestContractTests(unittest.TestCase):
    def test_only_frozen_unique_rubrics_are_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "draft.json").write_text(
                '{"status":"draft","rubric_version":"draft-v1","metrics":[]}',
                encoding="utf-8",
            )
            (root / "frozen.json").write_text(
                '{"status":"frozen","rubric_version":"frozen-v1","metrics":[{"id":"P1","criterion_ids":["P1.ONE"]}]}',
                encoding="utf-8",
            )
            self.assertEqual(load_rubrics(root), {"frozen-v1": {"P1.ONE": "P1"}})
            (root / "duplicate.json").write_text(
                '{"status":"frozen","rubric_version":"duplicate-v1","metrics":[{"id":"P1","criterion_ids":["P1.DUP"]},{"id":"P2","criterion_ids":["P1.DUP"]}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate criterion ID"):
                load_rubrics(root)

    def test_complete_body_passes(self):
        self.assertEqual(validate_pr_body(VALID, CAPABILITIES), [])

    def test_missing_and_empty_sections_fail(self):
        body = VALID.replace(
            "## Example\nBefore: count reached.\nAfter: incomplete cluster continues.\n\n",
            "",
        )
        body = re.sub(
            r"## Validation.*\Z",
            "## Validation\n<!-- fill this -->",
            body,
            flags=re.DOTALL,
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn("missing section: ## Example", errors)
        self.assertIn("empty section: ## Validation", errors)

    def test_metric_and_capability_decision_are_required(self):
        body = VALID.replace("P2", "coverage").replace(
            "- Capability decision: wrap",
            "- Capability decision:",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn(
            "Target primary metric(s) must name at least one metric P1-P9", errors
        )
        self.assertIn(
            "Capability decision must be exactly reuse, wrap, extend, or build-new",
            errors,
        )

    def test_required_metric_values_and_before_after_are_not_placeholders(self):
        body = VALID.replace(
            "- Hard measures: cluster and trace counts", "- Hard measures:"
        ).replace(
            "Before: count reached.\nAfter: incomplete cluster continues.",
            "Before:\n\nAfter:",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn("Evaluation requires a non-empty 'Hard measures:' value", errors)
        self.assertIn("Example requires a non-empty 'Before:' value", errors)
        self.assertIn("Example requires a non-empty 'After:' value", errors)

    def test_registered_rubric_criteria_and_evaluation_mode_are_required(self):
        missing_version = VALID.replace(
            "- Rubric version: aging-bidirectional-rubric-v1\n", ""
        )
        errors = validate_pr_body(missing_version, CAPABILITIES)
        self.assertTrue(any("Rubric version" in error for error in errors))

        wrong_version = VALID.replace(
            "aging-bidirectional-rubric-v1", "aging-bidirectional-rubric-v9"
        )
        self.assertIn(
            "Rubric version must name a registered rubric version",
            validate_pr_body(wrong_version, CAPABILITIES),
        )

        unknown_criterion = VALID.replace("P2.CLUSTERS", "P2.NOT_REAL")
        self.assertIn(
            "unknown rubric criterion ID(s): P2.NOT_REAL",
            validate_pr_body(unknown_criterion, CAPABILITIES),
        )

        wrong_metric = VALID.replace("P2.CLUSTERS", "P3.SEARCH_TRACE")
        self.assertIn(
            "rubric criteria require undeclared target metric(s): P3",
            validate_pr_body(wrong_metric, CAPABILITIES),
        )

        invalid_mode = VALID.replace(
            "- Evaluation mode: hybrid", "- Evaluation mode: manual"
        )
        self.assertIn(
            "Evaluation mode must be exactly deterministic, ai-judge, or hybrid",
            validate_pr_body(invalid_mode, CAPABILITIES),
        )

        missing_metric_criterion = VALID.replace(
            "- Target primary metric(s): P2", "- Target primary metric(s): P1, P2"
        )
        self.assertIn(
            "target metrics missing a rubric criterion ID: P1",
            validate_pr_body(missing_metric_criterion, CAPABILITIES),
        )

        placeholder_judge = VALID.replace(
            "deferred: waiting for the Stage 1 executable milestone; synthetic schema artifact passed",
            "TBD",
        )
        self.assertIn(
            "AI-judge evidence must use 'artifact: PATH', 'deferred: REASON', "
            "or 'not-applicable: REASON' with concrete detail",
            validate_pr_body(placeholder_judge, CAPABILITIES),
        )
        arbitrary_judge = VALID.replace(
            "deferred: waiting for the Stage 1 executable milestone; synthetic schema artifact passed",
            "banana",
        )
        self.assertTrue(
            any(
                "AI-judge evidence must use" in error
                for error in validate_pr_body(arbitrary_judge, CAPABILITIES)
            )
        )

    def test_plain_language_summary_is_required(self):
        body = VALID.replace(
            "- Plain-language summary: Keep a searchable record so another person "
            "can see why each paper was kept or removed.",
            "- Plain-language summary:",
        )
        self.assertIn(
            "Why requires a non-empty 'Plain-language summary:' value",
            validate_pr_body(body, CAPABILITIES),
        )

        placeholder = VALID.replace(
            "Keep a searchable record so another person can see why each paper was "
            "kept or removed.",
            "TBD",
        )
        self.assertIn(
            "Plain-language summary must be one concrete sentence explaining the "
            "problem, change, and benefit",
            validate_pr_body(placeholder, CAPABILITIES),
        )

    def test_unknown_capability_and_metric_mismatch_fail(self):
        unknown = VALID.replace("skill:stage1-literature", "tool:unregistered-search")
        errors = validate_pr_body(unknown, CAPABILITIES)
        self.assertIn(
            "unknown capability ID 'tool:unregistered-search'; register it in "
            "capability-metric-map.v1.json",
            errors,
        )

        mismatch = VALID.replace("P2", "P8")
        errors = validate_pr_body(mismatch, CAPABILITIES)
        self.assertIn(
            "capability 'skill:stage1-literature' has no declared target metric in "
            "common with its registry entry (P1, P2, P3)",
            errors,
        )

        criterion_mismatch = VALID.replace(
            "P2.CLUSTERS, P2.CLOSEST_WORK", "P3.VERSION_DATE"
        ).replace("P2", "P3")
        errors = validate_pr_body(criterion_mismatch, CAPABILITIES)
        self.assertTrue(
            any(
                error.startswith(
                    "capability 'skill:stage1-literature' has no declared rubric "
                    "criterion in common"
                )
                for error in errors
            )
        )

    def test_decision_keyword_elsewhere_does_not_fill_decision_label(self):
        body = VALID.replace(
            "- Capability decision: wrap",
            "- Capability decision: TBD",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn(
            "Capability decision must be exactly reuse, wrap, extend, or build-new",
            errors,
        )

    def test_external_prs_must_be_none_or_linked(self):
        invalid = VALID.replace(
            "- Related external PR(s): None",
            "- Related external PR(s): research-hub PR pending",
        )
        self.assertIn(
            "Related external PR(s) must be 'None' or a semicolon-separated list "
            "of external GitHub pull-request URLs",
            validate_pr_body(invalid, CAPABILITIES),
        )

        linked = VALID.replace(
            "- Related external PR(s): None",
            "- Related external PR(s): https://github.com/WenyuChiou/research-hub/pull/123; "
            "https://github.com/WenyuChiou/ai-research-skills/pull/456",
        )
        self.assertEqual(validate_pr_body(linked, CAPABILITIES), [])

        mixed_with_unlinked = VALID.replace(
            "- Related external PR(s): None",
            "- Related external PR(s): https://github.com/WenyuChiou/research-hub/pull/123; "
            "ai-research-skills PR pending",
        )
        self.assertTrue(
            any(
                error.startswith("Related external PR(s) must")
                for error in validate_pr_body(mixed_with_unlinked, CAPABILITIES)
            )
        )

        current_repo = VALID.replace(
            "- Related external PR(s): None",
            "- Related external PR(s): "
            "https://github.com/WenyuChiou/AutoResearchAgent/pull/4",
        )
        self.assertTrue(
            any(
                error.startswith("Related external PR(s) must")
                for error in validate_pr_body(current_repo, CAPABILITIES)
            )
        )

    def test_improvement_statement_requires_status_and_concrete_evidence(self):
        for value in (
            "TBD",
            "improved",
            "improved — this change definitely works very well",
            "improved — trace completeness increased; evidence: works very well",
            "unknown — coverage changed; evidence: 3 tests passed",
        ):
            body = VALID.replace(
                "not yet demonstrated — deterministic behavior is implemented but live "
                "quality remains unknown; evidence: 18 validator tests passed and live "
                "A/B is deferred to the Stage 1 milestone",
                value,
            )
            self.assertTrue(
                any(
                    error.startswith("Improvement statement must")
                    for error in validate_pr_body(body, CAPABILITIES)
                ),
                value,
            )

        for value in (
            "improved — trace completeness increased from 60% to 100%; evidence: paired metric artifact run-03.json",
            "not improved — paired P2 remained unchanged across three runs; evidence: 3 paired runs scored 1",
            "not yet demonstrated — deterministic behavior exists but live quality is unknown; evidence: 18 tests passed and live A/B is deferred to the Stage 1 milestone",
        ):
            body = VALID.replace(
                "not yet demonstrated — deterministic behavior is implemented but live "
                "quality remains unknown; evidence: 18 validator tests passed and live "
                "A/B is deferred to the Stage 1 milestone",
                value,
            )
            self.assertEqual(validate_pr_body(body, CAPABILITIES), [], value)

    def test_core_team_is_the_review_and_merge_owner(self):
        body = VALID.replace(
            "- Review and merge owner: core team",
            "- Review and merge owner: contributor",
        )
        self.assertIn(
            "Review and merge owner must be exactly 'core team'",
            validate_pr_body(body, CAPABILITIES),
        )

    def test_execution_report_status_and_blocker_are_consistent(self):
        invalid_status = VALID.replace(
            "- Execution status: complete",
            "- Execution status: done",
        )
        self.assertIn(
            "Execution status must be exactly complete, partial, or blocked",
            validate_pr_body(invalid_status, CAPABILITIES),
        )

        missing_blocker = VALID.replace(
            "- Execution status: complete",
            "- Execution status: partial",
        )
        self.assertIn(
            "Partial or blocked execution must describe the remaining work or blocker",
            validate_pr_body(missing_blocker, CAPABILITIES),
        )

        reported_blocker = missing_blocker.replace(
            "- Remaining work or blocker: None",
            "- Remaining work or blocker: Waiting for the related research-hub PR review",
        )
        self.assertEqual(validate_pr_body(reported_blocker, CAPABILITIES), [])

    def test_skill_change_requires_concrete_test_mini_report(self):
        labels = (
            "Skill test scenario",
            "Skill test command",
            "Skill test expected",
            "Skill test actual",
            "Skill test limitations",
        )
        for label in labels:
            body = VALID.replace(
                next(
                    line
                    for line in VALID.splitlines()
                    if line.startswith(f"- {label}:")
                ),
                f"- {label}:",
            )
            errors = validate_pr_body(body, CAPABILITIES)
            self.assertIn(
                f"Validation requires a concrete '{label}:' value for skill changes",
                errors,
            )

    def test_skill_change_rejects_placeholder_test_report_values(self):
        replacements = {
            "Skill test scenario": "TBD",
            "Skill test command": "n/a",
            "Skill test expected": "TODO later",
            "Skill test actual": "pending",
            "Skill test limitations": "none",
        }
        body = VALID
        for label, placeholder in replacements.items():
            original = next(
                line for line in body.splitlines() if line.startswith(f"- {label}:")
            )
            body = body.replace(original, f"- {label}: {placeholder}")
        errors = validate_pr_body(body, CAPABILITIES)
        for label in replacements:
            self.assertIn(
                f"Validation requires a concrete '{label}:' value for skill changes",
                errors,
            )

    def test_skill_change_accepts_concrete_values_starting_with_placeholder_words(
        self,
    ):
        body = (
            VALID.replace(
                "- Skill test scenario: synthetic missing coverage cluster",
                "- Skill test scenario: Pending citations exercise the stop gate",
            )
            .replace(
                "- Skill test expected: the skill loads and returns continue",
                "- Skill test expected: Unknown sources remain explicitly unverified",
            )
            .replace(
                "- Skill test limitations: no live retrieval or human P2 score",
                "- Skill test limitations: Not tested on Windows; Linux CI passed",
            )
        )
        self.assertEqual(validate_pr_body(body, CAPABILITIES), [])

    def test_non_skill_change_does_not_require_skill_test_mini_report(self):
        body = "\n".join(
            line for line in VALID.splitlines() if not line.startswith("- Skill test ")
        ).replace("skill:stage1-literature", "validator:research-pr-contract")
        capabilities = {
            "validator:research-pr-contract": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": ".github/scripts/validate_research_pr.py",
            }
        }
        self.assertEqual(validate_pr_body(body, capabilities), [])

    def test_mixed_capability_change_requires_skill_test_mini_report(self):
        body = VALID.replace(
            "skill:stage1-literature",
            "validator:research-pr-contract, skill:stage1-literature",
        ).replace("- Skill test actual: 4 tests passed and the fixture validated", "")
        capabilities = {
            **CAPABILITIES,
            "validator:research-pr-contract": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": ".github/scripts/validate_research_pr.py",
            },
        }
        errors = validate_pr_body(body, capabilities)
        self.assertIn(
            "Validation requires a concrete 'Skill test actual:' value for skill changes",
            errors,
        )

    def test_changed_capability_must_be_declared_and_owned(self):
        changed = ["plugins/auto-research-agent/skills/stage1-literature/SKILL.md"]
        missing = VALID.replace(
            "skill:stage1-literature", "validator:research-pr-contract"
        )
        capabilities = {
            **CAPABILITIES,
            "validator:research-pr-contract": {
                "metrics": {"P3"},
                "criteria": {"P3.DECISION_TRACE"},
                "owner_path": ".github/scripts/validate_research_pr.py",
            },
        }
        errors = validate_pr_body(missing, capabilities, changed)
        self.assertIn(
            "changed capabilities missing from 'Affected capability ID(s):': "
            "skill:stage1-literature",
            errors,
        )

        unowned = ["plugins/auto-research-agent/tools/new_search.py"]
        errors = validate_pr_body(VALID, CAPABILITIES, unowned)
        self.assertIn(
            "changed capability path "
            "'plugins/auto-research-agent/tools/new_search.py' has no registry owner",
            errors,
        )

        nested_init = ["plugins/auto-research-agent/tools/new_search/__init__.py"]
        errors = validate_pr_body(VALID, CAPABILITIES, nested_init)
        self.assertIn(
            "changed capability path "
            "'plugins/auto-research-agent/tools/new_search/__init__.py' has no "
            "registry owner",
            errors,
        )

    def test_changed_files_uses_merge_base_for_diverged_histories(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init")
            git("config", "user.name", "Research Contract Test")
            git("config", "user.email", "research-contract@example.invalid")
            (repo / "shared.txt").write_text("base\n", encoding="utf-8")
            git("add", "shared.txt")
            git("commit", "-m", "base")
            base_branch = git("branch", "--show-current")

            git("switch", "-c", "feature")
            (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
            git("add", "feature.txt")
            git("commit", "-m", "feature")
            feature_sha = git("rev-parse", "HEAD")

            git("switch", base_branch)
            (repo / "base-only.txt").write_text("advanced\n", encoding="utf-8")
            git("add", "base-only.txt")
            git("commit", "-m", "advance base")
            advanced_base_sha = git("rev-parse", "HEAD")

            self.assertEqual(
                changed_files(advanced_base_sha, feature_sha, cwd=repo),
                ["feature.txt"],
            )


if __name__ == "__main__":
    unittest.main()
