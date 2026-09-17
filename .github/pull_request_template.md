## Why

<!-- Cite the observed failure or baseline artifact and explain why it matters.
Use short, plain sentences that a new teammate can understand. Define necessary
technical terms where they first appear. -->

- Plain-language summary: <!-- One sentence: what is wrong, what changes, and why it helps. -->
- Target primary metric(s): <!-- P1-P9 -->
- Observed problem and evidence:
- Why this matters to the research workflow:

## What

<!-- Compare plausible methods. Use reuse, wrap, extend, or build-new. -->

- Affected capability ID(s): <!-- IDs from capability-metric-map.v1.json -->
- Options considered:
- Capability decision: <!-- exactly one: reuse / wrap / extend / build-new -->
- Chosen change:
- Out of scope:
- Related external PR(s): <!-- None, or external GitHub PR URLs separated by semicolons. Do not list this AutoResearchAgent PR. -->

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

- Baseline and treatment:
- Hard measures:
- Human judgment rubric:
- Major-error guardrail:
- Per-PR metric evidence:
- Improvement statement: <!-- Format: STATUS — what changed; evidence: measurement, passed/failed test, artifact, or explicit milestone deferral. STATUS is improved / not improved / not yet demonstrated. -->
- Time, tools, failures, and human-intervention guardrails:
- Live paired A/B: <!-- required now / deferred to stage milestone, with reason -->

## Validation

- [ ] Targeted regression tests pass.
- [ ] Evaluation schema and synthetic fixture tests pass.
- [ ] No frozen benchmark title or answer key enters production logic.
- [ ] Independent review is complete when required.
- [ ] Limitations and deferred work are recorded.

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
