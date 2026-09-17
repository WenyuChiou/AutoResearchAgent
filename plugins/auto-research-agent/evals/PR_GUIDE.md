# Research harness pull-request contract

Every research-harness PR must explain why the change is needed, what options
were considered, how the selected mechanism works, and what observable behavior
changes. The default repository template is checked in CI.

## Required sections

### Why

Name the target primary metric, cite the baseline or failure artifact, and
explain why the failure matters to a later research decision. A statement such
as “improve literature search” is insufficient without a measured failure.

### What

Name every affected capability ID from the capability metric map. Describe the
methods considered and classify every capability as `reuse`,
`wrap`, `extend`, or `build-new`. Explain why the chosen option is the smallest
adequate intervention and identify out-of-scope work.

### How

Describe the concrete interfaces, artifacts, events, validation, error states,
human gate and stopping behavior. State how production logic stays isolated
from benchmark answers.

### Example

Show a representative before/after input and output or artifact. Use synthetic
identifiers unless the example is already public production evidence. Do not
paste frozen core-source titles or adjudication keys into production prompts.

### Evaluation

State the baseline, treatment, hard measures, human judgments, major-error
guardrail and cost measures. Include the actual per-PR metric evidence and the
live A/B decision. Routine PRs need deterministic checks; a stage milestone
needs the frozen paired live A/B protocol.

### Validation

List commands and actual results, review evidence, limitations, and whether a
live A/B run is required now or deferred to the milestone.

When any affected capability ID starts with `skill:`, add the five-line skill
test mini-report from the PR template. The report names the scenario, exact
command, expected result, actual result and limitations. The test must cover
loading/discovery, one representative behavior, and one relevant guardrail or
explicit failure state. Contract/schema tests with a synthetic fixture are
acceptable for a declarative workflow skill. Executable skills must exercise
their executable path. This report does not replace milestone A/B evidence or
blinded scientific scoring.

## Filled example

### Why

- Target metrics: P2 Relevant Coverage and P3 Auditability.
- Evidence: the exploratory baseline covered 4/4 broad clusters but reached
  only 7/10 frozen anchors and recorded no candidate decision ledger.
- Importance: a plausible literature table can still miss the closest work,
  which makes the downstream novelty claim unreliable.

### What

- Affected capability IDs: `skill:stage1-literature`.
- Options considered: hard-code missed titles; add another search provider;
  wrap existing search with coverage planning and an append-only ledger.
- Capability decision: `wrap` existing search and verification commands.
- Chosen change: add query-family planning, candidate decisions and a coverage
  stop gate. Benchmark titles remain outside production logic.

### How

- Emit `query_events.jsonl`, `candidates.jsonl` and
  `decision_events.jsonl` with source references and reason codes.
- Treat backend failure separately from a valid empty result.
- Return `continue` when the closest-work cluster lacks verified evidence.
- Allow a human to continue, revise the query, or accept the stop decision.

### Example

Before: `15 papers collected -> stop`.

After: `15 papers collected -> closest-work cluster incomplete -> continue`,
with the triggering query and candidate decisions linked from the gate result.

### Evaluation

- Hard measures: cluster coverage, frozen-anchor recall, decision-reason
  completeness, trace completeness, failures, time and tool calls.
- Human judgments: blinded P2 and P3 scores from R1, R2 and ADJ.
- Per-PR evidence: synthetic missing-cluster, backend-failure and reversal tests
  pass and produce schema-valid artifacts.
- Success: paired P2 and P3 improve, P1 does not regress, and no major error is
  added.

### Validation

- Synthetic backend failure and decision-reversal tests pass.
- Stage 1 evaluation artifact validates against the public schema.
- Three paired live A/B repeats are deferred to the Stage 1 milestone.
- Skill test scenario: synthetic incomplete closest-work cluster with one
  backend failure and one include-to-exclude reversal.
- Skill test command: `python -m unittest discover -s plugins/auto-research-agent/tests -p "test_*.py"`.
- Skill test expected: the skill loads, preserves both decisions, records the
  backend failure, and returns `continue`.
- Skill test actual: all targeted tests pass and the synthetic artifacts
  validate; attach the test count and artifact path from the current run.
- Skill test limitations: deterministic fixtures do not establish a P2 or P3
  improvement on live literature retrieval.

## Commit and merge record

Commits remain single-purpose and record `Why`, `What`, `Tests`,
`AI contribution`, and `Human verification`. Use a merge commit so the commit
history remains inspectable. Delete the merged branch after the `main` Stage 1
checks pass.
