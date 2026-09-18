# AutoResearchAgent evaluation contract

This directory makes harness improvement measurable while keeping evaluation
answers outside the production agent.

## What is versioned here

- `primary-scorecard.v1.json` freezes the nine primary judgments, P1-P9.
- `rubrics/aging-bidirectional-rubric.v1.json` freezes machine-addressable
  criteria, 0-2 anchors, major errors, research modes and bidirectional case
  boundaries for all three stages.
- `schemas/rubric-judge-result.v1.schema.json` defines a blinded Auto-R1,
  Auto-R2, Auto-ADJ or targeted human-audit result.
- `schemas/judge-bundle.v1.schema.json` and `../validators/judge_bundle.py`
  bind judge outputs to one frozen plan and subject. They compare every unit's
  score and major-error IDs, require Auto-ADJ on disagreement, require the
  declared human audit, and block paired evaluation until the bundle is usable.
- `schemas/paired-evaluation-request.v1.schema.json`,
  `schemas/paired-evaluation-decision.v1.schema.json`, and
  `../validators/paired_evaluation.py` consume exactly six usable bundles,
  verify each run's condition/build/runtime/process attestation, apply the
  three-pair rule per metric, require close-pair audits, bind output to the
  request hash, block added errors, and report quality separately from costs.
- `EVALUATION_WORKFLOW.zh-TW.md` explains the complete frozen-case, paired-run,
  judge, adjudication, audit and reporting flow in plain language.
- `schemas/holdout-manifest.v1.schema.json` and
  `../validators/holdout_manifest.py` define private holdout curation,
  private-artifact declarations and canonical hashing. The validator does not
  prove runtime isolation or artifact bytes; the later evaluation runner must
  attest both. The committed one-anchor example is only a synthetic contract
  fixture, not an acceptable scientific holdout.
- `schemas/evaluation-plan.v1.schema.json` and
  `../validators/evaluation_plan.py` freeze the prompt, runtime, builds,
  holdout, blinded judges, three alternating pairs, audit triggers and decision
  rule before execution. The committed plan is synthetic and cannot support a
  scientific improvement claim. Human approval records still require the core
  team or trusted roster system to verify identity and artifact bytes; the
  runner must also attest the reviewed treatment diff and opaque judge packets.
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

For each primary metric, preserve Auto-R1, Auto-R2 and Auto-ADJ scores
separately. A targeted human audit is required for the triggers named in the
rubric and before an external generalization claim.
Report factual items as counts and proportions. Do not sum P1-P9 into one total.
Major errors and efficiency measures remain separate from quality scores.
The paired runner sets `external_claim_ready` to false until the core team completes the separately governed external-claim audit.

## Hard measures and rubric-based AI judgments

The scorecard is hybrid. Reconstructable counts, ratios, schema validity,
artifact presence, timestamps, failures and costs are hard measures. A blinded
AI judge applies the human-defined rubric to substantive support, substitute
sources and scientific sufficiency. Hard facts take precedence over the judge.
Missing evidence remains unverifiable. Automated CI must not present a passing
schema as a passing P1-P9 scientific score.

Therefore, “check the metric for every tool” has two levels. Every PR must name
the exact rubric criterion IDs it changes and prove that its metric-producing
behavior and guardrails work on deterministic data.
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
