"""Regression tests for the research pull-request contract."""

from pathlib import Path
import hashlib
import json
import re
import subprocess
import tempfile
import unittest

from validate_research_pr import (
    CRITERION_INVARIANTS,
    EVALUATOR_INVARIANTS,
    RUNTIME_INVARIANTS,
    changed_files,
    load_bound_readiness_manifest,
    load_criterion_submetrics,
    load_invariant_registry,
    load_operational_submetrics,
    load_rubrics,
    validate_pr_body,
    validate_readiness_manifest,
)


VALID = """## Why
- Plain-language summary: Keep a searchable record so another person can see why each paper was kept or removed.
- Target primary metric(s): P2
Target metric P2 has a measured coverage failure.

## What
- Affected capability ID(s): skill:stage1-literature
- Capability decision: wrap
- Related external PR(s): None
- Internal prerequisite PR(s): None
- External dependency pin(s): None
Wrap the existing search command.

## How
Emit an append-only candidate ledger and explicit stop gate.

## Example
Before: count reached.
After: incomplete cluster continues.

## Evaluation
- Evaluation readiness: implementation-only
- Rubric version: aging-bidirectional-rubric-v1
- Rubric criterion ID(s): P2.CLUSTERS
- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations
- Required invariant IDs: pr-readiness-enforced
- Invariant test evidence: pr-readiness-enforced -> .github/scripts/test_validate_research_pr.py::ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence -> passed
- Evaluation mode: hybrid
- Hard measures: cluster and trace counts
- AI-judge evidence: deferred: waiting for the Stage 1 executable milestone; synthetic schema artifact passed
- Major-error guardrail: no fabricated source
- Per-PR metric evidence: synthetic coverage-gate test passed
- Improvement statement: not yet demonstrated — deterministic behavior is implemented but live quality remains unknown; evidence: 18 validator tests passed and live A/B is deferred to the Stage 1 milestone
- Live smoke evidence: deferred: the stage executable milestone will produce the first live run and validator report
- Paired evaluation evidence: deferred: the frozen three-pair evaluation runs only after the stage executable milestone
- Runtime integrity evidence: deferred: runtime hashes and resume checks belong to the stage executable milestone
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
            "P3.DECISION_TRACE",
        },
        "owner_path": "plugins/auto-research-agent/skills/stage1-literature",
    }
}
FIXTURE_ROOT = Path(__file__).parent / "fixtures/pr_bodies"


class ResearchPullRequestContractTests(unittest.TestCase):
    def test_frozen_criteria_and_derived_invariants_are_fully_registered(self):
        rubrics = load_rubrics()
        criterion_submetrics = load_criterion_submetrics()
        operational_submetrics = load_operational_submetrics()
        every_criterion = {
            criterion_id for criteria in rubrics.values() for criterion_id in criteria
        }
        self.assertEqual(set(criterion_submetrics), every_criterion)
        for criterion_id, submetric_ids in criterion_submetrics.items():
            self.assertTrue(submetric_ids, criterion_id)
            self.assertTrue(
                submetric_ids.issubset(operational_submetrics),
                (criterion_id, submetric_ids),
            )
            rubric_metric = next(
                criteria[criterion_id]
                for criteria in rubrics.values()
                if criterion_id in criteria
            )
            for submetric_id in submetric_ids:
                self.assertIn(
                    rubric_metric,
                    operational_submetrics[submetric_id],
                    (criterion_id, submetric_id),
                )
        invariants = load_invariant_registry()
        derived = set().union(
            *CRITERION_INVARIANTS.values(),
            RUNTIME_INVARIANTS,
            EVALUATOR_INVARIANTS,
        )
        self.assertTrue(derived.issubset(invariants))
        for invariant_id, registration in invariants.items():
            self.assertTrue(registration["path_patterns"], invariant_id)
            for pattern in registration["path_patterns"]:
                re.compile(pattern)
            re.compile(registration["selector_pattern"])

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

    def test_readiness_manifest_rejects_unbound_evidence(self):
        body = VALID.replace(
            "- Evaluation readiness: implementation-only",
            "- Evaluation readiness: stage-executable",
        ).replace(
            "- Live smoke evidence: deferred: the stage executable milestone will produce the first live run and validator report",
            "- Live smoke evidence: artifact: manifest=missing.json; sha256="
            + "a" * 64,
        )
        errors = validate_pr_body(
            body,
            CAPABILITIES,
            execute_invariant_tests=False,
        )
        self.assertTrue(
            any("readiness manifest does not exist" in error for error in errors)
        )

    def test_all_three_readiness_body_fixtures_pass(self):
        for readiness in (
            "implementation-only",
            "stage-executable",
            "improvement-demonstrated",
        ):
            with self.subTest(readiness=readiness):
                body = (FIXTURE_ROOT / f"{readiness}.md").read_text(encoding="utf-8")
                self.assertEqual(
                    validate_pr_body(
                        body,
                        CAPABILITIES,
                        allow_contract_fixtures=True,
                    ),
                    [],
                )
                if readiness != "implementation-only":
                    self.assertTrue(
                        any(
                            "contract-fixture evidence cannot support" in error
                            for error in validate_pr_body(body, CAPABILITIES)
                        )
                    )

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
        placeholder_result = VALID.replace(
            "- Per-PR metric evidence: synthetic coverage-gate test passed",
            "- Per-PR metric evidence: TBD",
        )
        self.assertIn(
            "Per-PR metric evidence must name an actual passed/failed result, count, "
            "measurement, or artifact",
            validate_pr_body(placeholder_result, CAPABILITIES),
        )

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

        criterion_mismatch = VALID.replace("P2.CLUSTERS", "P3.VERSION_DATE").replace(
            "P2", "P3"
        )
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
        ).replace(
            "- External dependency pin(s): None",
            "- External dependency pin(s): https://github.com/WenyuChiou/research-hub/pull/123 @ "
            + "a" * 40
            + " @ open; https://github.com/WenyuChiou/ai-research-skills/pull/456 @ "
            + "b" * 40
            + " @ open",
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

    def test_readiness_is_required_and_implementation_only_can_defer(self):
        missing = VALID.replace("- Evaluation readiness: implementation-only\n", "")
        self.assertIn(
            "Evaluation readiness must be exactly implementation-only, "
            "stage-executable, or improvement-demonstrated",
            validate_pr_body(missing, CAPABILITIES),
        )
        premature = VALID.replace(
            "not yet demonstrated — deterministic behavior is implemented but live "
            "quality remains unknown; evidence: 18 validator tests passed and live "
            "A/B is deferred to the Stage 1 milestone",
            "improved — trace completeness increased from 60% to 100%; evidence: "
            "paired metric artifact run-03.json",
        )
        self.assertIn(
            "implementation-only readiness cannot claim 'improved' before the frozen "
            "paired evaluation",
            validate_pr_body(premature, CAPABILITIES),
        )
        self.assertEqual(validate_pr_body(VALID, CAPABILITIES), [])

    def test_each_declared_criterion_needs_operational_mapping(self):
        body = VALID.replace(
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.missing_symbol",
        )
        self.assertIn(
            "operational mapping target does not exist under a declared production owner: SKILL.missing_symbol",
            validate_pr_body(body, CAPABILITIES),
        )
        wrong_submetric = VALID.replace(
            "P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "P2.CLUSTERS -> S1_DELIVERY -> SKILL.coverage_obligations",
        )
        self.assertIn(
            "criterion P2.CLUSTERS must map to frozen submetric(s): S1_COVER",
            validate_pr_body(wrong_submetric, CAPABILITIES),
        )
        closest_to_count = VALID.replace(
            "- Rubric criterion ID(s): P2.CLUSTERS",
            "- Rubric criterion ID(s): P2.CLUSTERS, P2.CLOSEST_WORK",
        ).replace(
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations; P2.CLOSEST_WORK -> S1_DELIVERY -> SKILL.closest_work",
        )
        self.assertIn(
            "criterion P2.CLOSEST_WORK must map to frozen submetric(s): S1_COVER",
            validate_pr_body(closest_to_count, CAPABILITIES),
        )

    def test_derived_invariant_and_real_test_selector_are_required(self):
        missing_id = VALID.replace(
            "- Rubric criterion ID(s): P2.CLUSTERS",
            "- Rubric criterion ID(s): P2.CLUSTERS, P2.CLOSEST_WORK",
        ).replace(
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations; P2.CLOSEST_WORK -> S1_COVER -> SKILL.closest_work",
        )
        self.assertIn(
            "Required invariant IDs missing derived invariant(s): "
            "unverified-closest-blocks-stop",
            validate_pr_body(missing_id, CAPABILITIES),
        )
        missing_selector = VALID.replace(
            "ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence",
            "ResearchPullRequestContractTests.test_method_does_not_exist",
        )
        self.assertTrue(
            any(
                "test selector does not exist" in error
                for error in validate_pr_body(missing_selector, CAPABILITIES)
            )
        )

    def test_stop_evidence_requires_all_stop_inputs_invariant(self):
        body = (
            VALID.replace("P2.CLUSTERS", "P2.CLUSTERS, P3.STOP_EVIDENCE")
            .replace(
                "P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
                "P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations; P3.STOP_EVIDENCE -> S1_STOP_EVIDENCE -> SKILL.coverage_stop",
            )
            .replace(
                "- Target primary metric(s): P2", "- Target primary metric(s): P2, P3"
            )
        )
        self.assertIn(
            "Required invariant IDs missing derived invariant(s): all-stop-inputs-required",
            validate_pr_body(body, CAPABILITIES),
        )

    def test_p1_identity_claim_and_locator_require_binding_invariants(self):
        body = (
            VALID.replace(
                "- Target primary metric(s): P2", "- Target primary metric(s): P1"
            )
            .replace(
                "P2.CLUSTERS",
                "P1.IDENTITY, P1.CLAIM_SUPPORT, P1.LOCATOR",
            )
            .replace(
                "P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
                "P1.IDENTITY -> S1_META -> SKILL.source_version; "
                "P1.CLAIM_SUPPORT -> S1_CLAIM -> SKILL.claim_verification; "
                "P1.LOCATOR -> S1_CLAIM_LOCATOR -> SKILL.source_documents",
            )
        )
        capabilities = {
            "skill:stage1-literature": {
                **CAPABILITIES["skill:stage1-literature"],
                "criteria": {"P1.IDENTITY", "P1.CLAIM_SUPPORT", "P1.LOCATOR"},
            }
        }
        errors = validate_pr_body(body, capabilities)
        self.assertNotIn(
            "operational submetric S1_CLAIM_LOCATOR does not measure P1 for P1.LOCATOR",
            errors,
        )
        self.assertTrue(
            any(
                all(
                    invariant in error
                    for invariant in (
                        "artifact-producer-bound",
                        "evidence-work-version-bound",
                        "missing-evidence-fails-closed",
                    )
                )
                for error in errors
            )
        )

    def test_stage_executable_requires_live_runtime_and_complete_status(self):
        body = VALID.replace(
            "- Evaluation readiness: implementation-only",
            "- Evaluation readiness: stage-executable",
        )
        errors = validate_pr_body(body, CAPABILITIES)
        self.assertTrue(any("Live smoke evidence" in error for error in errors))
        self.assertTrue(any("Runtime integrity evidence" in error for error in errors))

        complete = (FIXTURE_ROOT / "stage-executable.md").read_text(encoding="utf-8")
        self.assertEqual(
            validate_pr_body(
                complete,
                CAPABILITIES,
                allow_contract_fixtures=True,
            ),
            [],
        )
        weak_hash = re.sub(r"sha256=[0-9a-f]{64}", "sha256=" + "a" * 64, complete)
        self.assertTrue(
            any(
                "manifest sha256 does not match" in error
                for error in validate_pr_body(
                    weak_hash,
                    CAPABILITIES,
                    allow_contract_fixtures=True,
                )
            )
        )

        cross_repo_internal = VALID.replace(
            "- Internal prerequisite PR(s): None",
            "- Internal prerequisite PR(s): "
            "https://github.com/WenyuChiou/research-hub/pull/137",
        )
        self.assertIn(
            "Internal prerequisite PR(s) must be 'None' or a semicolon-separated "
            "list of WenyuChiou/AutoResearchAgent pull-request URLs",
            validate_pr_body(cross_repo_internal, CAPABILITIES),
        )
        manifest = {
            "readiness": "stage-executable",
            "evidence_scope": "live-smoke",
            "execution_status": "complete",
            "validator_status": "passed",
            "resume_status": "failed",
            "_verified_roles": {
                "live-run",
                "validator-report",
                "runtime-bytes",
                "dependency-bytes",
                "resume-report",
            },
        }
        self.assertIn(
            "readiness manifest resume_status must be 'passed'",
            validate_readiness_manifest(
                manifest, "stage-executable", "not yet demonstrated"
            ),
        )

    def test_improvement_demonstrated_requires_full_paired_bundle(self):
        body = (FIXTURE_ROOT / "improvement-demonstrated.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            validate_pr_body(body, CAPABILITIES, allow_contract_fixtures=True), []
        )
        missing = re.sub(
            r"- Paired evaluation evidence: artifact:.*",
            "- Paired evaluation evidence: deferred: paired evidence is intentionally missing for this negative test",
            body,
        )
        self.assertTrue(
            any(
                "requires hash-bound paired evidence" in error
                for error in validate_pr_body(
                    missing,
                    CAPABILITIES,
                    allow_contract_fixtures=True,
                )
            )
        )

    def test_improvement_claim_is_recomputed_by_formal_paired_evaluator(self):
        repo_root = Path(__file__).resolve().parents[2]
        detail = (
            "manifest=.github/scripts/fixtures/pr_evidence/"
            "improvement-demonstrated.manifest.json; sha256="
            "a4f7c8ad503b1f074312403fbafc84625945923f5320482a55693b67f2a9aa2f"
        )
        manifest, load_errors = load_bound_readiness_manifest(
            detail,
            repo_root,
            allow_contract_fixtures=True,
        )
        self.assertEqual(load_errors, [])
        manifest["evidence_scope"] = "formal-paired"
        errors = validate_readiness_manifest(
            manifest,
            "improvement-demonstrated",
            "improved",
            repo_root=repo_root,
        )
        self.assertTrue(
            any(error.startswith("formal paired evaluator:") for error in errors),
            errors,
        )

    def test_live_cli_and_evaluator_capabilities_derive_integrity_invariants(self):
        cli_capabilities = {
            "cli:stage1-live": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": "plugins/auto-research-agent/cli/stage1_live",
                "kind": "cli",
                "runtime_integrity_required": True,
            }
        }
        cli_body = VALID.replace("skill:stage1-literature", "cli:stage1-live")
        errors = validate_pr_body(cli_body, cli_capabilities)
        self.assertTrue(
            any(
                "dependency-sha-bound" in error
                and "resume-no-reexecution" in error
                and "runtime-bytes-bound" in error
                for error in errors
            )
        )

        offline_capabilities = {
            "cli:stage1-offline": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": "plugins/auto-research-agent/cli/stage1_offline",
                "kind": "cli",
                "runtime_integrity_required": False,
            }
        }
        offline_body = VALID.replace("skill:stage1-literature", "cli:stage1-offline")
        offline_errors = validate_pr_body(offline_body, offline_capabilities)
        self.assertFalse(
            any(
                invariant in error
                for invariant in RUNTIME_INVARIANTS
                for error in offline_errors
            ),
            offline_errors,
        )

        missing_flag_capabilities = {
            "cli:stage1-legacy": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": "plugins/auto-research-agent/cli/stage1_legacy",
                "kind": "cli",
            }
        }
        missing_flag_body = VALID.replace(
            "skill:stage1-literature", "cli:stage1-legacy"
        )
        missing_flag_errors = validate_pr_body(
            missing_flag_body, missing_flag_capabilities
        )
        self.assertTrue(
            any(
                all(invariant in error for invariant in RUNTIME_INVARIANTS)
                for error in missing_flag_errors
            ),
            missing_flag_errors,
        )

        validator_capabilities = {
            "validator:example": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": "plugins/auto-research-agent/validators/example.py",
                "kind": "validator",
            }
        }
        validator_body = VALID.replace("skill:stage1-literature", "validator:example")
        self.assertTrue(
            any(
                "rehash-tamper-rejected" in error
                for error in validate_pr_body(validator_body, validator_capabilities)
            )
        )

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
        body = body.replace(
            "P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "P2.CLUSTERS -> S1_COVER -> validate_research_pr.required_ids",
        )
        capabilities = {
            "validator:research-pr-contract": {
                "metrics": {"P2"},
                "criteria": {"P2.CLUSTERS"},
                "owner_path": ".github/scripts/validate_research_pr.py",
            }
        }
        self.assertEqual(validate_pr_body(body, capabilities), [])

    def test_rehash_tamper_rejected_for_every_readiness_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "run.json"
            artifact.write_text('{"status":"complete"}\n', encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "kind": "ReadinessEvidenceManifest",
                        "schema_version": "1.0.0",
                        "evidence_scope": "live-smoke",
                        "artifacts": [
                            {
                                "role": "live-run",
                                "path": "run.json",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            _, errors = load_bound_readiness_manifest(
                f"manifest=manifest.json; sha256={digest}", root
            )
            self.assertIn(
                "readiness artifact 'live-run' sha256 does not match file bytes",
                errors,
            )

        unrelated = VALID.replace(
            "ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence",
            "ResearchPullRequestContractTests.test_complete_body_passes",
        )
        self.assertTrue(
            any(
                "is not allowed by invariant-registry.v1.json" in error
                for error in validate_pr_body(unrelated, CAPABILITIES)
            )
        )

    def test_exact_invariant_selector_must_execute_successfully(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "plugins/auto-research-agent/skills/example/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("coverage obligations\n", encoding="utf-8")
            test_path = root / "tests/test_invariant.py"
            test_path.parent.mkdir()
            test_path.write_text(
                "import unittest\n\n"
                "class InvariantTests(unittest.TestCase):\n"
                "    def test_readiness_bound(self):\n"
                "        self.fail('controlled invariant failure')\n\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n",
                encoding="utf-8",
            )
            body = (
                VALID.replace("skill:stage1-literature", "skill:example")
                .replace("pr-readiness-enforced", "fixture-invariant")
                .replace(
                    ".github/scripts/test_validate_research_pr.py::ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence",
                    "tests/test_invariant.py::InvariantTests.test_readiness_bound",
                )
            )
            capabilities = {
                "skill:example": {
                    "metrics": {"P2"},
                    "criteria": {"P2.CLUSTERS"},
                    "owner_path": "plugins/auto-research-agent/skills/example",
                }
            }
            invariants = {
                "fixture-invariant": {
                    "path_patterns": [r"tests/test_invariant\.py"],
                    "selector_pattern": r"InvariantTests\.test_readiness_bound",
                }
            }
            errors = validate_pr_body(
                body,
                capabilities,
                known_rubrics={"aging-bidirectional-rubric-v1": {"P2.CLUSTERS": "P2"}},
                known_submetrics={"S1_COVER": {"P2"}},
                known_criterion_submetrics={"P2.CLUSTERS": {"S1_COVER"}},
                known_invariants=invariants,
                repo_root=root,
            )
            self.assertTrue(
                any("exact test selector failed" in error for error in errors), errors
            )

    def test_wrapped_mapping_and_invariant_lines_are_supported(self):
        body = VALID.replace(
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER -> SKILL.coverage_obligations",
            "- Operational-definition mapping: P2.CLUSTERS -> S1_COVER ->\n"
            "  SKILL.coverage_obligations",
        ).replace(
            "- Invariant test evidence: pr-readiness-enforced -> .github/scripts/test_validate_research_pr.py::ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence -> passed",
            "- Invariant test evidence: pr-readiness-enforced ->\n"
            "  .github/scripts/test_validate_research_pr.py::ResearchPullRequestContractTests.test_readiness_manifest_rejects_unbound_evidence -> passed",
        )
        self.assertEqual(validate_pr_body(body, CAPABILITIES), [])

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
