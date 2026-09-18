# Research harness pull-request contract

Every research-harness PR must explain why the change is needed, what options
were considered, how the selected mechanism works, and what observable behavior
changes. The default repository template is checked in CI.

Write every section in plain language that a new teammate can understand on the
first read. Use short sentences and concrete examples, and define necessary
technical terms. The `Plain-language summary` gives the problem, change and
benefit in one sentence. CI checks its presence; the core team reviews actual
clarity.

## Required sections

### Why

Name the target primary metric, cite the baseline or failure artifact, and
explain why the failure matters to a later research decision. A statement such
as “improve literature search” is insufficient without a measured failure.
Start with the one-sentence plain-language summary.

### What

Name every affected capability ID from the capability metric map. Describe the
methods considered and classify every capability as `reuse`,
`wrap`, `extend`, or `build-new`. Explain why the chosen option is the smallest
adequate intervention and identify out-of-scope work.

List every related cross-repository PR as a GitHub PR URL, separated by
semicolons, including `research-hub` or `ai-research-skills` changes. Do not put
the current AutoResearchAgent PR in this field. Write `None` when no external
PR exists. The core team must be notified when any related PR is opened so it
can review the whole change rather than only the local adapter.

### How

Describe the concrete interfaces, artifacts, events, validation, error states,
human gate and stopping behavior. State how production logic stays isolated
from benchmark answers.

### Example

Show a representative before/after input and output or artifact. Use synthetic
identifiers unless the example is already public production evidence. Do not
paste frozen core-source titles or adjudication keys into production prompts.

### Evaluation

State the baseline, treatment, registered rubric version, exact criterion IDs,
evaluation mode, hard measures, AI-judge evidence, major-error guardrail and
cost measures. Include the actual per-PR metric evidence and the live A/B
decision. Routine PRs need deterministic checks; a stage milestone needs the
frozen paired live A/B protocol.

Add one `Improvement statement` beginning with `improved`, `not improved`, or
`not yet demonstrated`. State the behavior, then add `; evidence:` followed by
a measurement, passed/failed test, artifact, or explicit milestone deferral in
the same sentence. This prevents a completed coding task from being mistaken
for a useful harness improvement.

### Validation

List commands and actual results, review evidence, limitations, and whether a
live A/B run is required now or deferred to the milestone.

Treat the completed PR description as the executor's short progress report to
the organizing core team. Record `Execution status` as `complete`, `partial`,
or `blocked`, and state the remaining work or blocker. A partial or blocked PR
must name what prevents completion. The core team uses this report, test
results, improvement statement and external PR links to supervise progress and
choose the next task.

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

- Plain-language summary: Keep the search trail so another person can see what
  was tried, why papers were kept, and why the search stopped.
- Target primary metric(s): P2 Relevant Coverage and P3 Auditability.
- Observed problem and evidence: the exploratory baseline covered 4/4 broad clusters but reached
  only 7/10 frozen anchors and recorded no candidate decision ledger.
- Why this matters to the research workflow: a plausible literature table can still miss the closest work,
  which makes the downstream novelty claim unreliable.

### What

- Affected capability ID(s): skill:stage1-literature
- Options considered: hard-code missed titles; add another search provider;
  wrap existing search with coverage planning and an append-only ledger.
- Capability decision: wrap
- Decision reason: reuse existing search and verification commands.
- Chosen change: add query-family planning, candidate decisions and a coverage
  stop gate. Benchmark titles remain outside production logic.
- Out of scope: live scientific-quality claims before the Stage 1 milestone.
- Related external PR(s): None

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

- Baseline and treatment: stock search versus the same search wrapped with the
  candidate ledger and coverage gate.
- Rubric version: aging-bidirectional-rubric-v1.
- Rubric criterion ID(s): P2.CLUSTERS, P2.CLOSEST_WORK,
  P3.DECISION_TRACE, P3.FAILURE_STATE, P3.STOP_EVIDENCE.
- Evaluation mode: hybrid.
- Hard measures: cluster coverage, frozen-anchor recall, decision-reason
  completeness, trace completeness, failures, time and tool calls.
- AI-judge evidence: deferred: waiting for the Stage 1 executable milestone; this PR
  provides deterministic synthetic artifacts only.
- Major-error guardrail: no benchmark title enters production logic and no
  backend failure is reported as an empty result.
- Per-PR metric evidence: synthetic missing-cluster, backend-failure and reversal tests
  pass and produce schema-valid artifacts.
- Improvement statement: not yet demonstrated — deterministic behavior is implemented but live quality remains unknown; evidence: synthetic tests passed and live A/B is deferred to the Stage 1 milestone
- Time, tools, failures, and human-intervention guardrails: report all calls,
  failures and interventions separately from P2 and P3.
- Live paired A/B: deferred to the Stage 1 executable milestone.
- Success: paired P2 and P3 improve, P1 does not regress, and no major error is
  added.

### Validation

- Synthetic backend failure and decision-reversal tests pass.
- Stage 1 evaluation artifact validates against the public schema.
- Three paired live A/B repeats are deferred to the Stage 1 milestone.
- Execution status: complete
- Remaining work or blocker: None
- Review and merge owner: core team
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
`AI contribution`, and `Human verification`. Contributors open PRs and address
feedback; the core team reviews and merges them. Use a merge commit so the
commit history remains inspectable. Delete the merged branch after the `main`
Stage 1 checks pass.
