# AutoResearchAgent contributor contract

These instructions apply to this plugin and to the shared PR validation files
listed in the repository-root `AGENTS.md`. They apply to human- and AI-authored
changes. The core team organizes, reviews, and merges; contributors execute the
assigned slice, test it, open a PR, and respond to review.

## Read before planning or editing

Read these files in order. Do not rely on a summary from an earlier task.

1. [CONTRIBUTING.md](CONTRIBUTING.md)
2. [Evaluation contract](evals/README.md)
3. [Evaluation workflow](evals/EVALUATION_WORKFLOW.zh-TW.md)
4. [P1-P9 plain-language metrics](evals/METRICS_EXPLAINED.zh-TW.md)
5. [Operational definitions](evals/OPERATIONAL_DEFINITIONS.zh-TW.md)
6. [Aging bidirectional rubric](evals/rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md)
7. [PR guide](evals/PR_GUIDE.md)
8. [Capability-to-metric registry](evals/capability-metric-map.v1.json)
9. [Readiness and team workflow](evals/READINESS_AND_TEAM_WORKFLOW.zh-TW.md)

For Stage 1 work, also read the current
[stage1-literature skill](skills/stage1-literature/SKILL.md) and
[plugin status](README.md). The skill remains a foundation until its README and
tests demonstrate an executable retrieval, ledger, evidence-validation, and
coverage-gate path. Do not describe a planned or declarative capability as
implemented.

## Required development sequence

1. Identify the observed failure and its evidence artifact.
2. Select the affected capability and exact P1-P9 criterion IDs.
3. Search existing skills, MCP tools, CLIs, and research-hub capabilities.
4. Record one decision: `reuse`, `wrap`, `extend`, or `build-new`.
5. Implement one coherent capability with deterministic tests and explicit
   failure states.
6. Update `evals/capability-metric-map.v1.json` when a production capability or
   its measurable effects change.
7. Run the capability's registered tests and the full plugin contract suite.
8. Open a PR using every section of the repository template. Report the actual
   result as `improved`, `not improved`, or `not yet demonstrated`.

Passing a unit, schema, loading, or synthetic test proves implementation
behavior only. Scientific-quality improvement requires the frozen paired live
A/B at the capability's declared stage milestone.

## Evaluation and isolation rules

- Keep P1-P9 separate. Do not invent a composite quality score.
- Hard facts override an AI judge. Missing evidence remains `unverifiable`.
- Keep the private holdout, benchmark titles, answer keys, and condition map out
  of production prompts, queries, fixtures, tools, and stopping logic.
- Freeze the case, rubric, criterion catalog, holdout, prompt, runtime, builds,
  judges, pair order, and decision rule before a formal run.
- Preserve failures, retries, human interventions, runtime, tool calls, model
  calls, and cost as separate evidence.
- Auto-R1 and Auto-R2 remain blinded and independent. Disagreement requires
  Auto-ADJ. Declared audit triggers require a named human audit.
- Missing artifacts, mismatched hashes, changed run conditions, rejected audits,
  or added treatment major errors must fail closed or return `inconclusive`.

## Review and delivery

- Use a `codex/` branch. Never push directly to `main` for harness work.
- Commit only explicit paths. Each commit body includes `Why`, `What`, `Tests`,
  `AI contribution`, and `Human verification`.
- Report every related external PR, including research-hub and
  ai-research-skills changes. Do not merge it before core-team review.
- Contributors and their AI do not approve or merge their own harness PRs. The
  core team reviews and merges into `WenyuChiou/AutoResearchAgent` only; do not
  send this harness to OpenAI upstream.
- Governance changes require independent code review and harness-drift review.
