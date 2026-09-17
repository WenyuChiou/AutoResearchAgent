# AutoResearchAgent evaluation contract

This directory makes harness improvement measurable while keeping evaluation
answers outside the production agent.

## What is versioned here

- `primary-scorecard.v1.json` freezes the nine primary judgments, P1-P9.
- `stage1/metric-spec.v1.json` defines the required Stage 1 counts, 0-2
  anchors, major-error gate and paired comparison rule.
- `schemas/stage1-evaluation-result.v1.schema.json` defines one scored run.
- `../validators/stage1_evaluation_result.py` rejects cross-field count and
  adjudication states that JSON Schema cannot express.
- `stage1/baseline-run01.summary.json` preserves aggregate diagnostic evidence
  from the exploratory stock-Codex run. It is not a formal paired baseline.
- `examples/stage1-evaluation-result.synthetic.json` is public test data.
- `METRICS_EXPLAINED.zh-TW.md` explains P1-P9 with plain-language examples for
  presentations, contributor onboarding and rubric calibration.
- `OPERATIONAL_DEFINITIONS.zh-TW.md` defines units, numerators, denominators,
  adjudication rules and the limits of the frozen core-source anchors.

The benchmark paper list, answer keys, raw responses, full text and human
adjudication stay in a separately controlled bundle. Production skills and
runtime code must not read this directory. The committed files contain metric
definitions and aggregate evidence only.

## Evaluation cadence

1. **Every PR:** register every affected production capability, run its declared
   deterministic schema, invariant and synthetic-fixture tests, and report the
   resulting metric evidence. CI checks that the PR metric and capability map
   agree.
2. **Stage milestone:** run three paired repeats of baseline and treatment with
   the same frozen prompt, model, reasoning mode and stock tools. Alternate the
   condition order and compare within each pair.
3. **Before a generalization claim:** evaluate one blind case disclosed only
   after the harness and rubric are frozen.

For each primary metric, preserve R1, R2 and adjudicated scores separately.
Report factual items as counts and proportions. Do not sum P1-P9 into one total.
Major errors and efficiency measures remain separate from quality scores.

## Hard measures and human judgments

The scorecard is hybrid. Reconstructable counts, ratios, schema validity,
artifact presence, timestamps, failures and costs are hard measures. Whether a
claim is substantively supported, an alternative source is equally direct, or
an audit trail is sufficient remains a blinded human judgment. Automated CI
must not present a passing schema as a passing P1-P3 scientific score.

Therefore, “check the metric for every tool” has two levels. Every PR must prove
that its metric-producing behavior and guardrails work on deterministic data.
The stage-level paired A/B is run when an executable vertical slice is ready,
because running a live literature benchmark for every small commit would mix
in model and search variability and would expose the holdout too often.

## Stage 1 decision rule

A Stage 1 treatment is an improvement only when paired P2 and P3 results
improve, P1 does not regress, and the treatment adds no major error. Runtime,
tool calls and human interventions are reported as costs, not mixed into the
quality score.

The external development benchmark is bound by SHA-256 in
`stage1/metric-spec.v1.json`. Changing a prompt, fixture, rubric or scoring
definition requires a new version; never overwrite v1.

Research-harness pull requests follow [PR_GUIDE.md](PR_GUIDE.md) and the
repository pull-request template. The PR contract connects every change to an
observed failure, an intended metric movement and acceptance evidence.
