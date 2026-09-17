## Why

<!-- Cite the observed failure or baseline artifact and explain why it matters. -->

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

## How

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
- Time, tools, failures, and human-intervention guardrails:
- Live paired A/B: <!-- required now / deferred to stage milestone, with reason -->

## Validation

- [ ] Targeted regression tests pass.
- [ ] Evaluation schema and synthetic fixture tests pass.
- [ ] No frozen benchmark title or answer key enters production logic.
- [ ] Independent review is complete when required.
- [ ] Limitations and deferred work are recorded.

Commands and actual results:

## Commit and AI record

- Commits are single-purpose and include Why, What, Tests, AI contribution,
  and Human verification.
- AI contribution:
- Human verification:
