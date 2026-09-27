# Fixed-candidate Stage 2 checker

This offline slice records a researcher's or agent's assessments. It validates
source and version bindings and disposition eligibility, not scientific truth.
Keep a separate independent evaluator for judging research quality.

## Inputs and commands

Use a confirmed `ResearchBrief`, resource limits, source snapshots, exact evidence,
comparison text, candidate histories and unresolved issues. The input schema is
[`stage2-packet.v1.schema.json`](../schemas/stage2-packet.v1.schema.json).
The assessment schema is [`stage2-check.v1.schema.json`](../schemas/stage2-check.v1.schema.json).
Install `requirements-test.txt` in the selected Python environment and put this
plugin's `cli/` directory on `PYTHONPATH` before these commands:

```text
python -m stage2_check init --packet packet.json --source-root source-root --output new-run
python -m stage2_check apply --run new-run --assessment assessment.json
python -m stage2_check export --run new-run
```

`init` requires a new directory. It copies immutable UTF-8 source snapshots under
`sources/`, preserves original paths and hashes, and creates a Stage 2 run.
It does not modify Stage 1's handoff or start Stage 3. Save the returned manifest
outside the mutable run as a receipt of the admitted input.

`apply` appends a validated event. The assessment must reference the original
input packet hash and current candidate version. Reusing the same event ID with
the same content is idempotent; different content with that ID fails. Keep the
returned `event_sha256` externally. A revised candidate must use the same ID,
next version and previous version as parent; it needs a fresh assessment.

`export` rebuilds the selection views and shared StageResult. For replay against
a previously retained receipt, add `--expected-event-head` followed by that
64-character hash. The local hash chain detects inconsistent edits; only an
external receipt detects a fully rewritten or truncated valid tail. Do not
claim that self-hashing makes an editable local directory tamper-proof.

## Scientific checks and dispositions

| Axis | Question |
|---|---|
| opportunity | What remains after the closest prior work, and what supports that claim? |
| value | What useful knowledge, measurement, validation or decision can this add? |
| answerability | Which observation, derivation or comparison could answer it? |
| materials | Are the needed materials, variables, granularity and access appropriate? |
| execution | Is a minimum study plausible within time, compute, API and skill limits? |

An assessed score is 0 (evidence against), 1 (partially supported) or 2 (sufficient
for design). `unknown` and `not-applicable` have null scores and explanations.
Unknown needs a next check. Recommendation requires all applicable axes at 2,
at least one applicable axis, no unknown or hard blocker, and no requested scope
change. This is a conservative first-slice gate, not a prediction of success.

Use `revise` with a next step and optionally a revised candidate. Use `park` when
evidence or resources are unresolved. Use `reject` only with a supported negative
assessment. The packet's general unresolved list is informational; record a
material candidate blocker in its checks. A rejected option must not erase a
different eligible recommendation. Scope changes remain pending human decisions.

The prehuman selection contains options, assessments, retained revisions,
recommendations, reasons and next steps. Its effective `evaluation_packet`
includes revisions, with original source paths; the neutral `action_record`
binds that effective packet. The original input hash remains separately recorded.
Incomplete rechecks leave the action record unavailable instead of fabricating a
completed judgment. Use the run's `sources/` as the effective packet's source root.
Imported revisions without their original reasons, or actions without source
evidence, remain visible in the selection. They produce `action_record=null`,
`action_record_status=unavailable` and explicit `action_record_blocking_items`.
Do not invent missing history to make an evaluator handoff pass. This is missing
handoff evidence, not a scientific zero score or loss of the original records.
`decision_events.jsonl` projects recorded actions into the shared `DecisionEvent`
contract with links to original assessment events. It records system observations,
not human approvals. `stage_result.json` reuses the shared `StageResult` and
`GateResult`, always requiring human review before Stage 3.

## Transparent proposal report

`selection.md` presents the supplied research brief, comparison, current
directions and five-axis assessments, followed by retained versions, actions
and exact source excerpts. Candidate and axis evidence IDs link to the excerpt
appendix; source links open the run's copied snapshots, with work, version,
locator, evidence level and SHA-256 shown. Keep the report alongside its JSON,
events and `sources/` directory when sharing it.

Read the candidate descriptions as proposals and the assessments as supplied
judgments. The exporter checks bindings before rendering; it does not establish
novelty, importance or effectiveness. A quoted precedent can motivate a method
without proving the proposed method works. State each source's particular role
in the comparison or rationale, including contrary evidence and what remains
untested. No hidden reasoning transcript is needed; give a concise explanation
that another researcher can check.

The v1 packet does not have structured title, author, DOI or evidence-role
fields. Supply verified citation details with source IDs in the comparison when
available; the report labels the missing structured metadata and never invents
a bibliography or guesses a source's role. Automated bibliography enrichment
and live proposal generation remain future work. Re-exporting old runs enriches
the readable view without rewriting their input, events or evaluation contract.

## Open proposal development

Use two equally valid entry routes: improve an existing method or design, or
propose a new concept, mechanism or design. An improvement explains the original
limitation, proposed change and value against the original and closest work.
A new concept explains its motivation, premises, difference from prior work and
testable implications. Both routes check precedents and counterevidence, then
use the same five axes and disposition rules before researcher selection.
They may overlap or change during revision; neither route is a scoring bonus,
a fixed schema enum, or a quota that every run must fill.

Allow evidence-motivated new methods and assumptions to enter discussion even
when the sources do not explicitly name a gap. Keep proposed benefits separate
from established findings. Describe the proposed mechanism, supporting premises,
closest alternatives, a minimum informative comparison and failure conditions.
Compare added complexity and cost against a simpler alternative; adding another
module is not evidence of novelty or value.

Use the existing candidate `opportunity`, `approach`, `requirements` and
`limitations` fields after open reasoning. Preserve the original prose and
attribute sources to the premises they actually support. Do not manufacture an
evidence quote for a new proposal or silently promote an analogy to a finding.

An unmeasured research outcome does not by itself make an axis `unknown`:
score the adequacy of the motivation, answerability and preliminary feasibility.
Put the untested outcome in the question and limitations. Mark an axis `unknown`
when evidence needed to judge that axis is missing, such as uncertain access to
indispensable data; those unknowns still block recommendation. A sufficient
assessment permits detailed design, not a claim that the new method works.

Keep both exploratory and conventional options when justified, without a quota
for either. The first slice accepts supplied candidates and assessments; the
open reasoning guidance does not implement a generator or establish creativity.

## Reproducible offline check

```text
python -m unittest discover -s plugins/auto-research-agent/tests -p test_stage2_checker.py -v
```

The synthetic suite tests revisions, evidence tampering, missing variables,
resource limits, unknowns, simple adequate methods, mixed portfolios and zero
recommendations. Its supplied assessments are controlled inputs. It does not
prove that an autonomous agent will discover these problems or improve P5/P6.
