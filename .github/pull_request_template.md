## Why

<!-- Cite the observed failure or baseline artifact and explain why it matters.
Use short, plain sentences that a new teammate can understand. Define necessary
technical terms where they first appear. -->

- Plain-language summary: <!-- One sentence: what is wrong, what changes, and why it helps. -->
- Target primary metric(s): <!-- P1-P9; not-applicable or contextual "None — reason" is allowed only for a Git-diff-verified governance-only PR. -->
- Observed problem and evidence:
- Why this matters to the research workflow:

## What

<!-- Compare plausible methods. Use reuse, wrap, extend, or build-new. -->

- Affected capability ID(s): <!-- IDs from the capability maps; not-applicable or contextual "None — reason" is allowed only for a Git-diff-verified governance-only PR. -->
- Options considered:
- Capability decision: <!-- exactly one: reuse / wrap / extend / build-new -->
- Chosen change:
- Out of scope:
- Related external PR(s): <!-- None — reason, or external GitHub PR URLs separated by semicolons. Do not list this AutoResearchAgent PR. -->
- Internal prerequisite PR(s): <!-- None — reason, or stacked AutoResearchAgent PR URLs separated by semicolons. -->
- External dependency pin(s): <!-- Only runtime dependencies: None — reason, or PR_URL @ 40-character SHA @ open|merged. Every pin must also appear in Related external PR(s); related governance/docs PRs need no pin. -->

## How

<!-- Use concrete inputs, outputs, steps, and failure examples. -->

- Interfaces, artifacts, or events:
- Validation and explicit error states:
- Human-in-the-loop gate and stopping behavior:
- Production/evaluation isolation:

## Example

<!-- Give a concrete before/after example without leaking benchmark answers. -->

Before:

After:

## Evaluation

<!-- For a governance-only PR accepted by the Git-diff classifier, use either
the exact value not-applicable or a contextual value such as "None — no metric
is measured by this documentation change" for research metrics, capabilities,
rubric criteria, operational mappings, invariant IDs/evidence, evaluation mode,
hard measures, AI-judge evidence, guardrails, per-PR metrics, and readiness
artifacts. The contextual reason must be concrete. PR text cannot select this
path: only a complete, verified AGENTS-only Git diff can waive research metric
IDs. Runtime, validator, evaluation, test, or CI changes still require their
mapped metric, capability, criteria, and invariant evidence. Keep readiness
implementation-only; state that no research-quality improvement is claimed;
include commands, actual results, limitations, and traceable source references
for both independent reviews, the reviewed revision, and patch hash. This
validator checks body format only: it cannot authenticate review sources or
accept their results. Do not claim PASS here; the core team verifies external
records against the exact revision and patch before merge. -->

- Evaluation readiness: <!-- exactly one: implementation-only / stage-executable / improvement-demonstrated -->
- Baseline and treatment:
- Rubric version: <!-- aging-bidirectional-rubric-v1 (legacy), stage1-general-v3, or stage2-general-v2 (implementation-only) -->
- Rubric criterion ID(s): <!-- Exact IDs such as P3.DECISION_TRACE, separated by commas. -->
- Operational-definition mapping: <!-- One per criterion: P3.STOP_EVIDENCE -> S1_STOP_EVIDENCE -> policy.evaluate; separate entries with semicolons. -->
- Required invariant IDs: <!-- Comma-separated IDs derived by the PR validator. -->
- Invariant test evidence: <!-- INVARIANT -> path.py::Class.test_method -> passed; separate entries with semicolons. -->
- Evaluation mode: <!-- exactly one: deterministic / ai-judge / hybrid -->
- Hard measures:
- AI-judge evidence: <!-- improvement-demonstrated uses artifact: manifest=PATH; sha256=64HEX; lower readiness may defer. -->
- Major-error guardrail:
- Per-PR metric evidence:
- Improvement statement: <!-- Format: STATUS — what changed; evidence: measurement, passed/failed test, artifact, or explicit milestone deferral. STATUS is improved / not improved / not yet demonstrated. -->
- Live smoke evidence: <!-- stage/improvement uses artifact: manifest=PATH; sha256=64HEX; implementation-only may defer. -->
- Paired evaluation evidence: <!-- improvement uses the same bound manifest; lower readiness may defer. -->
- Runtime integrity evidence: <!-- stage/improvement uses the same bound manifest; implementation-only may defer. -->
- Time, tools, failures, and human-intervention guardrails:
- Live paired A/B: <!-- improvement uses the same bound manifest; otherwise give a concrete milestone deferral. -->

## Research Deliverable

<!-- Every PR must declare whether it changes the Stage 1 researcher-facing
deliverable. Use required for the Stage 1 report/source-package implementation.
Use not-applicable only with a concrete reason, and write exactly not-applicable
in every evidence field. -->

- Applicability: <!-- exactly one: required / not-applicable -->
- Applicability reason:
- Public source acquisition evidence: <!-- lawfully public PDF, HTML or text full sources, plus unavailable outcomes. -->
- Editable report evidence: <!-- Excel, Markdown, BibTeX, metadata, claims, screening and coverage outputs. -->
- Source binding evidence: <!-- work, version, URL/URI, access time and SHA-256. -->
- Access-state evidence: <!-- paywall, not found, parse error, login page and other explicit states. -->
- Access and repository guardrail evidence: <!-- lawfully public sources; no paywall bypass; abstract is not full text; paper files stay out of Git. -->
- Japan pilot evidence: <!-- required format: artifact: manifest=PATH; sha256=64HEX -->

## Validation

- [ ] Targeted regression tests pass.
- [ ] Evaluation schema and synthetic fixture tests pass.
- [ ] No frozen benchmark title or answer key enters production logic.
- [ ] External review source links and revision/hash references are included; core-team acceptance is separate.
- [ ] Limitations and deferred work are recorded.
- Governance validation evidence: <!-- Governance-only PRs: actual command(s), result(s), and explicit limits of what the checks establish. -->
- Governance review evidence: <!-- Governance-only PRs: code review source: HTTPS URL; harness-drift review source: HTTPS URL; reviewed revision: 40-hex SHA; patch SHA256: 64-hex SHA; external acceptance: not verified by this validator. Do not write PASS. -->

Commands and actual results:

- Execution status: <!-- exactly one: complete / partial / blocked -->
- Remaining work or blocker: <!-- None, or a concrete description. -->
- Review and merge owner: core team

<!-- Required when any affected capability ID starts with skill:. Keep this
mini-report concrete; a full live A/B remains deferred unless this is a stage
milestone. Remove these five lines when the PR does not change a skill. -->
- Skill test scenario:
- Skill test command:
- Skill test expected:
- Skill test actual:
- Skill test limitations:

## Commit and AI record

- Commits are single-purpose and include Why, What, Tests, AI contribution,
  and Human verification.
- AI contribution:
- Human verification:
