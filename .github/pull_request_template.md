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
- Internal prerequisite PR(s): <!-- None, or stacked AutoResearchAgent PR URLs separated by semicolons. -->
- External dependency pin(s): <!-- None, or PR_URL @ 40-character SHA @ open|merged. Use the open head SHA or immutable merge SHA. -->

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

- Evaluation readiness: <!-- exactly one: implementation-only / stage-executable / improvement-demonstrated -->
- Baseline and treatment:
- Rubric version: <!-- aging-bidirectional-rubric-v1 -->
- Rubric criterion ID(s): <!-- Exact IDs such as P3.DECISION_TRACE, separated by commas. -->
- Operational-definition mapping: <!-- One per criterion: P3.STOP_EVIDENCE -> S1_STOP_EVIDENCE -> derive.stop_inputs_recorded; separate entries with semicolons. -->
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
