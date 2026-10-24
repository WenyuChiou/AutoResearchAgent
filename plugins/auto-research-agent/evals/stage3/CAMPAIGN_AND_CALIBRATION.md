# Stage3 offline campaign and calibration preparation v1

Handoff: stage3-eval-campaign-20261023-v1, issue #381.
This is implementation-only. No subject, model, judge, expert annotation,
calibration, held-out validation, research experiment or formal A/B is dispatched.
All four authority flags remain false. A saved score is not research permission.

## Reuse and ownership

Reuse stage3_plan.evaluation prepare/record, its source-aware validators and raw
judgment contract; storage private/write-once/2 MB/flush/fsync rules; plan1.1
conditions and the existing semantic review. Historical preparation.py v1 keeps
its original three AB/BA/AB slots. Campaign is a separate explicit version.
Stage2 selection/interaction/handoff, HTML, ProjectHost/service and receiver stay
with their owner. Native session/process/evaluator engines are not reimplemented.
Build/runtime and role configurations are declarations, not authenticated
execution attestations. Unverified identity, isolation and content blinding stay
unverified. This interface does not change plan readiness or unknown resources.

## Input and public commands

Put the plugin cli directory on PYTHONPATH. Start from the committed synthetic
definition example; replace the declared selection with the exact four bindings
from a source-verified evaluation request. Each case lists base_case_id, variant,
research_type, split and optional subject bindings {repeat, arm, request, failure}.
Requests and failure logs use absolute paths and independent raw-file SHA256.
A request wraps a verified saved plan with candidate/version, all SQ references,
source, schema, rubric and guidance. Original synthetic/manual origin survives.
Absent subjects remain not-run; a pinned failure stays a subject failure. No
request is generated from report-ready, ZIP contents or a model recommendation.
A fully unrun example has declared-unverified inputs and cannot receive grades.

- campaign-prepare --definition FILE --expected-sha256 RAW_SHA --output NEW_DIR
- campaign-inspect --campaign DIR --expected-sha256 CAMPAIGN_SHA
- campaign-record --campaign DIR --expected-sha256 CAMPAIGN_SHA --unit-id ID
  --judgment RAW_FILE --expected-judgment-sha256 RAW_SHA --output NEW_UNIT_DIR
- campaign-summary --campaign DIR --expected-sha256 CAMPAIGN_SHA --index FILE
  --expected-index-sha256 RAW_SHA

Definition schema_version 1.0.0 requires campaign_id, integer seed, repetitions,
cases, A/B build/protocols, shared runtime, R1/R2/ADJ configurations,
subject_order, display_order, limits and analysis. Orders may be AB, BA or seeded;
the two seeded domains are separate and actual schedules are saved.
Limits.max_units is configurable up to 4096; limits.max_view_bytes bounds the
aggregate views up to 32 MB. Each artifact still has the existing 2 MB cap.
Deadline is frozen metadata; no command waits for an external service or retries.
Inputs/schema/producer/view changes require new versions/paths.

Inspect revalidates source bytes and deterministically reconstructs the manifest,
including schedule, private mapping, provenance and displayed views. It does not
trust rehashed status fields. Preserve the returned campaign_sha256 externally.
Preparation can resume same-key/same-bytes; an incomplete directory is retained
and rejected, never overwritten or treated as a finished campaign.

Give assessors only the subject-*.json views in saved display_order. Private
manifest, A/B protocols, arm mapping and storage paths are withheld. Views use
neutral aliases; they retain all question/evidence/design context. Masking names
does not establish absence of textual clues. The returned judgment keeps the
request_sha256 and view question_ref aliases; the recorder retains exact original
bytes, creates a separately hashed question-ref translation, then uses the
existing evaluation-record validator. It does not repair judgments or generate
rationales. Malformed/invalid Unicode/deep JSON and IO failures remain explicit.
Accepted same-key input replays without rewriting; changed bytes reject.
An incomplete receipt is partial evidence, not an invitation to retry a judge.

## Index, roles and descriptive output

The external-hash-bound Stage3CampaignIndex has schema_version 1.0.0,
campaign_sha256, receipts (absolute path/raw SHA256 bindings) and
human_interventions (nonnegative count or null). Keep successive indexes at new
paths. Every receipt retains unit identity, raw/mapped judgment, original record,
error and false authority flags. A source-aware read rebuilds the record; changing
its vector and rehashing it does not turn it into valid evidence.

R1/R2 vectors remain separate. Differences require an ADJ record; an unexpected
ADJ is not used to complete a pair. Supplied actor/model names do not authenticate
people or independence. Audit triggers are explicit: disagreement, unverifiable,
grader_error or score-zero. Pending audit is retained even after ADJ. Summary is
descriptive and usable_for_formal_pairing is always false.

P7, P8 and P9 stay separate. A pair is observed-scored only when both selected
vectors have scored values for that dimension; recorded/null is not scored.
Report pair win/loss/tie/incomplete separately from independent base-case counts.
The explicit v1 rule pareto-over-planned-pairs makes a base incomplete if any
planned variant/repeat is incomplete; otherwise wins with no losses are a win,
losses with no wins a loss, both are mixed, and all ties are a tie.
This is a declared engineering summary rule, not a universal scientific decision.
Multiple variants, SQs and raters do not increase independent n. Ordinal 0/1/2
are compared by order; no composite, interval-scale average or performance
estimate is emitted. Tokens/cost remain null when not observed.

## Expert calibration and held-out preparation (not run)

Use stage3-calibration-annotation.synthetic.json as a fillable format, not a
reference label. Retain every SQ, applicability/necessary condition, lawful
alternative, source/version/plan pointer, original comment, 0/1/2/null,
critical defects, disagreements and adjudication/audit status.
Diagnostic non-applicability does not exempt a whole P7/P8/P9 dimension.
An unknown is not zero; a grader technical failure is separate.

Split by base_case_id before annotation or model tuning. All variants and repeats
of one base stay in the same calibration/development/held-out split.
Research type is open text: empirical, observational, simulation, qualitative,
theoretical and engineering designs can use lawful alternatives. No fixed
case count/type quota/dataset/LLM/RCT/p-value/GPU/16-week requirement is imposed.

Before any future real estimate, freeze case sampling, the case-level rule,
missing-data/failure coverage, role/audit handling and uncertainty assumptions.
Preserve raw agreement and distributions. Ordinal alpha or weighted kappa needs
an appropriate scale, rater design, weights and missingness policy; agreement is
not accuracy. Precision/recall/F1 requires genuine expert reference labels and
an explicit defect unit; no AI fixture is an expert label. Any bootstrap must
resample independent base cases, not variants/SQs/raters, under a frozen protocol.
If prerequisites are missing, estimates stay not-run/null. No universal cutoff
or additional readiness/permission gate is introduced.

Reuse guidance D01-D09 and its S01-S10 source/version/method-location/limitation
table in references/stage3-evaluation-guidance.v1.md. These support construct and
procedure choices; this slice does not reread every paper or validate the local
rubric. Expert calibration, reliability and scientific improvement remain unknown.
