# Contributing to the research harness

This plugin treats evaluation as part of implementation. The rules apply to
every contributor, including AI-authored changes.

## Before implementation

1. Identify the observed failure and evidence artifact.
2. Select the primary metric or metrics P1-P9 that the change can affect.
3. Search existing skills, MCP tools, CLIs and research-hub capabilities.
4. Classify the chosen approach as `reuse`, `wrap`, `extend`, or `build-new`.
5. Keep benchmark answers, paper-title hints and adjudication keys outside
   production prompts, code, fixtures and stopping rules.

Infrastructure may be an evaluation enabler rather than a direct quality
improvement. Mark that honestly; do not claim a P1-P9 gain until paired evidence
exists.

## Capability-to-metric registration

Every production skill, MCP tool, CLI, validator or gate must have one entry in
`evals/capability-metric-map.v1.json`. The entry records:

- owner path and capability status;
- target primary metrics and expected direction;
- hard measures produced by the implementation;
- the question that requires blinded rubric-based AI judgment;
- guardrails, regression tests and the live A/B milestone.

CI checks that plugin skills, the repository PR validator, and capabilities in
standardized `tools/`, `mcp/`, `cli/`, `validators/`, and `gates/` locations are
registered. Put a multi-file capability in one immediate child directory; put a
single-file entry point directly in the standardized location. One registry
entry owns each discovered file or directory entry point.

Every capability PR must run the deterministic checks named by its `test_refs`
and provide the resulting artifact or command output in the PR. These checks
verify the metric interface and prevent regressions. They do not prove that the
scientific score improved. Only the frozen paired live A/B at the declared
milestone can support that claim.

### Minimum skill test and mini-report

Every PR that adds or changes a `skill:*` capability must include a small,
repeatable test and a five-line mini-report in the PR `Validation` section:

- `Skill test scenario`: one representative input or synthetic fixture;
- `Skill test command`: the exact command or CI job that ran;
- `Skill test expected`: the observable behavior or artifact expected;
- `Skill test actual`: the observed result, including pass/fail and useful counts;
- `Skill test limitations`: what this test does not establish.

The minimum test must prove that the skill is discoverable or loadable and that
one representative path produces its declared artifact or behavior. It must
also exercise one relevant guardrail or explicit failure state. A declarative
workflow skill may satisfy this with contract/schema tests and a synthetic
scenario; it does not need a live literature run in every PR. A skill with
executable orchestration must test the executable path rather than only inspect
its prompt text.

This mini-report is deliberately short so contributors can iterate quickly. It
is evidence that the capability behaves as specified, not evidence that P1-P9
improved. Scientific improvement still requires the paired live A/B and
rubric-based AI judging at the declared stage milestone.

## Pull requests

Use the repository template and complete all six sections: Why, What, How,
Example, Evaluation and Validation. Name every affected capability ID. CI
rejects unknown IDs, metric targets that disagree with the registry, missing
P1-P9 targets, a capability decision other than the exact values `reuse`,
`wrap`, `extend`, or `build-new`, changed capability paths omitted from the PR,
or blank metric evidence fields.

Write all six sections in plain language that a new teammate can understand on
the first read. Prefer short sentences, concrete inputs and outputs, and one
specific example. Define a necessary technical term where it first appears.
The required `Plain-language summary` says in one sentence what is wrong, what
will change, and why that change helps. CI checks that this summary exists; the
core team checks whether the whole PR is actually clear.

Each PR should implement one coherent capability. Include deterministic tests
and update the capability metric map in the same PR. State whether the frozen
paired A/B is required immediately or deferred to the stage milestone.

Each PR must also name the registered rubric version, exact criterion IDs and
evaluation mode (`deterministic`, `ai-judge`, or `hybrid`). Criterion IDs must
belong to the declared P1-P9 targets. Record the AI-judge result artifact, or a
concrete milestone deferral when the PR only establishes an interface. A test
pass proves implementation behavior; only the paired milestone result can
prove a scientific-quality gain.

Every PR must include one `Improvement statement` beginning with `improved`,
`not improved`, or `not yet demonstrated`. In the same sentence, name the
behavior that changed, then add `; evidence:` followed by a measurement,
passed/failed test, artifact, or explicit milestone deferral. Use `not yet
demonstrated` when only deterministic tests exist; do not turn a passing test
into an unsupported scientific-quality claim.

## Review ownership and cross-repository work

The core team is the organizer. It defines task boundaries, priorities,
dependencies and milestones; monitors progress; reviews the research direction
and evidence; and performs the merge. Contributors are executors. They
implement only the assigned scope, test it, open the PR, report progress and
respond to review comments. Contributors must not approve or merge their own
harness PRs.

The completed PR description is the contributor's execution report. It must
record `Execution status` as `complete`, `partial`, or `blocked`, and name any
remaining work or blocker. Together with the test results, improvement
statement and related PR links, this gives the core team enough information to
supervise progress and decide the next assignment. A partial or blocked report
cannot use `None` for the remaining work or blocker.

List every related PR outside this repository in `Related external PR(s)` as
GitHub PR URLs separated by semicolons, including changes proposed to
`research-hub`, `ai-research-skills`, or another dependency. Do not list the
current AutoResearchAgent PR in this field. Use `None` only when no external PR
exists. Send the core team each link as soon as the external PR is opened and
keep it unmerged until the core team reviews it. If repository permissions
prevent the core team from merging, the contributor merges only after explicit
core-team approval and records the resulting merge commit in the
AutoResearchAgent PR.

## Commits and merge

Each commit is single-purpose and includes these body fields:

```text
Why:
What:
Tests:
AI contribution:
Human verification:
```

After required checks and core-team review pass, the core team merges with a
merge commit and deletes the branch. The core team then verifies the Stage 1
workflow on `main` after merge.
