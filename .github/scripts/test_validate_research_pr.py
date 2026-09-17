"""Regression tests for the research pull-request contract."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from validate_research_pr import changed_files, validate_pr_body


VALID = """## Why
- Target primary metric(s): P2
Target metric P2 has a measured coverage failure.

## What
- Affected capability ID(s): skill:stage1-literature
- Capability decision: wrap
Wrap the existing search command.

## How
Emit an append-only candidate ledger and explicit stop gate.

## Example
Before: count reached.
After: incomplete cluster continues.

## Evaluation
- Hard measures: cluster and trace counts
- Human judgment rubric: blinded P2 score
- Major-error guardrail: no fabricated source
- Per-PR metric evidence: synthetic coverage-gate regression passed
- Live paired A/B: deferred to Stage 1 executable milestone
Compare paired P2 counts and blinded judgments.

## Validation
Synthetic regression tests passed.
"""

CAPABILITIES = {
    "skill:stage1-literature": {
        "metrics": {"P1", "P2", "P3"},
        "owner_path": "plugins/auto-research-agent/skills/stage1-literature",
    }
}


class ResearchPullRequestContractTests(unittest.TestCase):
    def test_complete_body_passes(self):
        self.assertEqual(validate_pr_body(VALID, CAPABILITIES), [])

    def test_missing_and_empty_sections_fail(self):
        body = VALID.replace(
            "## Example\nBefore: count reached.\nAfter: incomplete cluster continues.\n\n",
            "",
        )
        body = body.replace(
            "## Validation\nSynthetic regression tests passed.",
            "## Validation\n<!-- fill this -->",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn("missing section: ## Example", errors)
        self.assertIn("empty section: ## Validation", errors)

    def test_metric_and_capability_decision_are_required(self):
        body = VALID.replace("P2", "coverage").replace(
            "- Capability decision: wrap\nWrap the existing search command.",
            "- Capability decision:\nAdd another search step.",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn(
            "Why or Evaluation must name at least one primary metric P1-P9", errors
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

    def test_decision_keyword_elsewhere_does_not_fill_decision_label(self):
        body = VALID.replace(
            "- Capability decision: wrap\nWrap the existing search command.",
            "- Capability decision: TBD\nDo not reuse the existing search command.",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertIn(
            "Capability decision must be exactly reuse, wrap, extend, or build-new",
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
