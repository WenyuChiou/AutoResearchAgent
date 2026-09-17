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
- the question that still requires blinded human judgment;
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
improved. Scientific improvement still requires the paired live A/B and human
judgment at the declared stage milestone.

## Pull requests

Use the repository template and complete all six sections: Why, What, How,
Example, Evaluation and Validation. Name every affected capability ID. CI
rejects unknown IDs, metric targets that disagree with the registry, missing
P1-P9 targets, a capability decision other than the exact values `reuse`,
`wrap`, `extend`, or `build-new`, changed capability paths omitted from the PR,
or blank metric evidence fields.

Each PR should implement one coherent capability. Include deterministic tests
and update the capability metric map in the same PR. State whether the frozen
paired A/B is required immediately or deferred to the stage milestone.

## Commits and merge

Each commit is single-purpose and includes these body fields:

```text
Why:
What:
Tests:
AI contribution:
Human verification:
```

After required checks and review pass, merge with a merge commit and delete the
branch. Verify the Stage 1 workflow on `main` after merge.
