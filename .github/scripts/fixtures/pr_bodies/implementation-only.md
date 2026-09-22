## Why
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
