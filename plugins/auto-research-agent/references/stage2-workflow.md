# Stage 2 workflow: versioned research, not a second agent runtime

Status: experimental, implementation-only. The workflow adds record keeping to
native Codex. A passing contract test does not prove better scientific judgment.
The fixed seven-criterion `stage2-general-v2` rubric is unchanged.

## Why

The fixed-candidate checker correctly binds each assessment to a packet. It
cannot add a newly found source to that packet without breaking the binding.
The workflow keeps a sequence of immutable packets instead. A new source creates
a new snapshot; the old sources, candidate versions and assessments remain
available. A recommendation about an older snapshot is not a recommendation
about the current evidence.

## Research flow and ownership

1. Read the confirmed ResearchBrief, resources, Stage 1 sources and unresolved
   issues. Ask only about material missing conditions or a proposed scope change.
2. Compare questions, populations or objects, measurements, methods, conditions,
   results and limitations. Mark noncomparable results explicitly. Record shared
   studies, datasets and secondary citations; multiple reports are not necessarily
   independent evidence.
3. Explore in prose. Improvements and new mechanisms have equal standing. Keep
   source facts, interpretations and proposed benefits separate. No candidate
   quota, mandatory hypothesis, or reward for complexity applies.
4. Preserve the original proposal before a separate, tool-free extraction. Failed
   extraction leaves the original intact and the structured task incomplete.
5. Save independent initial challenge and feasibility reviews before revealing
   other judgments. Direct factual questions go to source verification. Only
   consequential, evidence-relevant disagreements need debate; votes do not
   resolve them. A challenger may support the original proposal.
6. Check opportunity, value, answerability, materials and execution. Unknown
   effectiveness can be a valid research question. Unknown enabling materials or
   a missing validation path cannot be declared feasible.
7. Supplement evidence only to answer a named uncertainty that may change the
   selection. Save the new snapshot and its impact list. Reassess candidates;
   do not carry forward an old PASS.
8. Produce a prehuman proposal and discuss the choices. A usable choice package
   and a user-confirmed direction are different states.
9. Bind the actual user response to the viewed report and selected candidate
   versions. Stage 3 receives resources, sources, unresolved issues and conditions
   for reconsideration. This handoff is not permission to run experiments.

At screening, keep rejected ideas and reasons. Audit the excluded candidate
nearest the shortlist and one other excluded candidate sampled using a saved
seed. Inspect all when fewer exist. Record why a reopened idea changes the
decision. Do not force a recommendation when none is supported.

## Snapshot and action contract

The snapshot wraps an unchanged `stage2_check` run. Its manifest binds the
original packet, source hashes, parent snapshot, settings and policy reference.
The first implementation conservatively marks **all** candidates pending after
an evidence change, including those reported unaffected. This can cost more
review work, but avoids an unsupported reuse decision. More selective reuse
requires a separately tested dependency analysis.

An action is started before external work and completed only after its artifacts
have been saved. Inputs, snapshot, settings, timestamps, result state and raw
artifact hashes are recorded. Completed matching units may be reused after byte
verification. An interrupted or failed action is not automatically restarted;
a later attempt must have its own identity and explain the correction.

Artifact input validation happens before publication. A crash during publication
preserves partial records; inspection rejects an unfinished result or artifact
directory. No automatic cleanup, retry or successful completion is inferred.

`complete`, `empty`, `unavailable`, `failed` and `interrupted` mean different
things. Missing costs are null. An empty tool result is not a failed tool call,
and neither says that no relevant literature exists.

Hashes and a separately retained head receipt detect changed local records.
They are not authentication against an actor who can rewrite all records and
their receipts. An action record alone does not attest that a model ran, that
review sessions were isolated, or that an excerpt supports a scientific claim.
Live execution must also supply the native call evidence.

## Local command interface

From the plugin's `cli` directory, `python -m stage2_workflow --help` lists the
record operations. JSON input files are read strictly; errors return exit code 2.

| Command | Required input files | Result |
|---|---|---|
| `init` | `--packet`, `--settings`, `--policy-ref`; also `--source-root`, `--output` | First immutable snapshot and workflow manifest |
| `inspect` | `--run`; optional retained `--expected-head` | Revalidated head, snapshot count and pending candidate IDs |
| `snapshot` | `--packet`, `--impact`; also `--run`, `--source-root`, `--reason`, `--expected-head` | New snapshot and impact history |
| `start` | `--inputs`, `--settings`; also `--run`, `--action-id`, `--kind`, `--expected-head` | New intent, or verified completed-unit reuse |
| `finish` | `--artifacts`, optional `--cost`; also `--run`, `--action-id`, `--status`, `--expected-head`, optional `--error` | Immutable terminal result and copied artifact hashes |
| `review-plan` | `--screening`; also `--run`, `--expected-head`, `--seed`, `--output` | Current-version isolated views for included and audited excluded candidates |
| `reconcile` | `--batch`, `--reviews`, `--resolutions`; also `--run`, `--expected-head`, `--output` | Local reconciliation with explicit pending, missing and failed states |

An impact file maps every candidate ID to `status` (`affected`, `unaffected` or
`unknown`) and a nonempty `reason`. The artifact file maps names to objects with
an existing local `path` and the expected `sha256`. Save the returned event head outside the mutable run when checking
for rehashed edits. `inspect` does not certify that a scientific stage finished.

Policy references are recorded metadata. The caller still loads and enforces
its canonical policy before native execution. This offline interface never
calls a model, searches, spends an API budget or chooses a research direction.

### Independent review batch

A screening row has `candidate_id`, `candidate_version`, `included` (boolean),
`distance` (nonnegative integer) and `reason`. Supply every current candidate
exactly once. Distance is the researcher's recorded proximity to the shortlist,
not an automatically measured scientific quality. The batch binds that whole
population, seed, packet, snapshot and two separate role views per selected item.

The host gives each reviewer only its own view and source access, saves the
initial native result, and then performs synthesis. A result envelope has
`candidate_id`, `candidate_version`, `role`, `status`, `review` and `error`.
Only `complete` has a review object and null error. `empty`, `unavailable`,
`failed` and `interrupted` have null review and an explanation. An absent
envelope remains missing. None of these incomplete states permits synthesis.

Resolutions contain `candidate_resolutions` (rows with `candidate_id` and the
existing evidence-bound `resolution`) and `next_step`. Even matching scores
need an explicit synthesis; no majority rule is introduced. An audited excluded
idea can become a recommended option when the new evidence supports reopening
it. Zero recommendations require an explained next step. Local readiness is not
native execution attestation or proof that a scientific judgment is correct.

Both commands write new UTF-8 JSON files and refuse overwrites. Use `start` and
`finish` to preserve their inputs and outputs as workflow action artifacts.
Never apply assessments inside the immutable snapshot's embedded checker: its
history must stay empty, and inspection rejects this out-of-band mutation.

`make_followup` in `stage2_workflow.orchestration` binds the question, material
decision at risk, evidence needed, previous attempts, next action and canonical
policy reference. It records whether unchanged unproductive work should stop
and whether scope/resource changes need a human decision. It does not execute
the action, verify a proposed action is useful, or grant another retry budget.
The host must enforce the policy and save actual call results separately.

## Context, tools and limits

Load the brief, current candidate, important counterexamples and source index
first; retrieve full passages when needed. Summaries never replace source
evidence. Preserve native Codex search, reading and agents. Research-hub is an
optional source adapter, not a mandatory detour through another search.

The host enforces its canonical policy for retries, concurrency and bounded
lookup. The workflow stores the policy reference and hash; it creates no
background agent, new global budget or automatic approval. Unknown costs remain
unknown. Stop an unproductive lookup with an explicit next-step record.

## Reuse decisions

| Capability | Decision | Reason |
|---|---|---|
| `ResearchBrief` and `stage2_common` | reuse | Confirmed scope and source/version checks already exist. |
| `stage2_check` | wrap | Each source-bound checker run remains immutable. |
| `literature-triage-matrix` | wrap | Use comparison and evidence roles; keep the local rubric. |
| `gap-to-topic` | wrap | Reuse precedent and feasibility inquiry; do not inherit its one-topic, no-invention or 1–5 scoring restrictions. |
| `agent-debate` | wrap | Independent initial views and evidence-led resolution, not routine argument or voting. |
| `research-workflow-orchestrator` | wrap | Reuse checkpoint and handoff principles without starting another runtime. |
| Snapshot lineage and action identity | build-new | The checker has fixed sources and no cross-snapshot action record. |

## Evaluation boundary

Program tests establish lineage, failure handling and reuse behavior. AI
diagnostics separately test whether an agent discovers and fixes scientific
problems. Live pilots must exercise the full path, including independent
reviews, supplemental evidence, Q&A and recovery. Only then may a frozen A/B
compare stock Codex with the same Codex plus this Stage 2 harness.

P4 must not regress. P5 and P6 each need improvements in at least two of three
pairs and no regressions, with no additional major errors. Missing necessary
criteria or audits produce `inconclusive`, not a smaller scoring denominator.
The current foundation does not provide those live or formal results.

## Registered content history

`deliver --record-registered-history` opts into delivery manifest v1.3 and
registered-history provenance v2. It retains the actual workflow manifest,
event chain, consecutive snapshots, candidate changes and table-only bridges.
Portable inspection rebuilds the same history from the retained files. This
supports an honestly labelled parent-authored or imported revision without
inventing a native model call, source acquisition or human approval.

This mode cannot be combined with `--source-update-receipt` or guard bundles.
The existing source-update and authenticated content-extraction receipt modes
remain separate. Recorded history is evidence that content changed and was
registered; it does not establish the author, execution success, scientific
correctness, formal isolation or a user's choice. Current independent reviews
and external assessment still need their own authentic evidence.

Table-only snapshots do not manufacture candidate revisions. Unknown source or
resource conditions remain unknown. Missing or altered history, claims,
sources, event links or retained manifest receipts fail inspection.

### Importing pre-existing local history

Delivery1.4/provenance2.1 adds an explicit `--imported-history-delivery PATH
EXPECTED_MANIFEST_SHA256` option to `deliver --record-registered-history`.
Use a retained legacy delivery1.1 manifest receipt, not a newly invented reason.
The adapter verifies every copied inventory byte and binds each old transition's
exact candidate, evidence and source identity to the initial workflow packet.
Relocated source paths are allowed; changed source bytes or versions are not.
Missing, unrelated, conflicting or duplicate transitions fail closed. Partial
genuine history stays partial. Legacy delivery1.3 replay remains unchanged.

The copied records attest **local content history only**. Prior review, user
selection, execution and authorship do not become current approval. Current
independent reviews and assessment are still required. No external score,
scientific truth, Stage3 authorization or formal A/B admission follows from
successfully importing these records.
