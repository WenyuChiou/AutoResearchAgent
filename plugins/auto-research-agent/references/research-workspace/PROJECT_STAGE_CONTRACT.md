# Universal Harness UI project and stage contract

## Goal and delivered boundary

The workbench is a reusable interface to the repository Harness. A researcher
starts an independent project with any topic, or explicitly asks their own Codex
for topic proposals, confirms a versioned scope and resources, and reviews each
saved operation and result. A demonstration topic is not a production default.

Current adapters cover project intake, offline Stage1 ledger operations, and
source-bound Stage2 import and workflow initialization. The separate native
candidate supplies bounded Codex **content planning**. They do not yet form a
complete search/read/deliver/compare/review research execution chain. Stage3–6
are planned and unconnected. This document is an engineering interface contract;
it does not change a research rubric, baseline, denominator or assessment rule.

## Version and identity

`GET /api/projects/<project-ref>/contract` returns
`HarnessUiProjectView`, `schema_version: "1.0.0"`. Stage keys are strings `1`–`6`.
Every stage has `input`, `status`, `connected`, `execution_authorized`, `accepted`,
`expected_outputs`, `artifacts`, `attempts`, `pending_questions`, `approvals`,
`metrics`, and `assessment`. Empty arrays are unconnected projection slots, not
proof that a running executor has no questions or artifacts.

The binding contains opaque `project_ref`, durable `project_id`, monotonically
changing `revision`, `input_version`, raw `brief_sha256`, and compiled
`plan_manifest_sha256`. Independent topics remain separate even when their
titles match. Revising a topic creates a new input version. Old briefs, plans,
intents and attempts remain recoverable; they cannot authorize the new version.

`GET /api/projects/<project-ref>/overview` joins intake, content-provider offers
and observations, Stage1 and Stage2 under the same store lock. It is the UI's
source-loading barrier. While a new snapshot is being read, old forms cannot
submit. A failed observation does not infer that an earlier operation was unsent.

## State and measurement

An intent saved, a native write observed, a call completed, an artifact validated,
and a research stage accepted are different facts. `accepted` requires explicit
source-bound stage acceptance; neither a green CI result nor a model's success
message changes it. Stage1 ledger export is not its canonical research package.
Stage2 import is not comparison generation or final route selection.

Each measurement uses `{value, unit, status, evidence}`. Legal measurement states
are `unknown`, `recorded`, `stale`, `partial`, and `failed`. Unknown values are
`null`, never implicit zero. Numeric values must be finite and nonnegative.
Common measures are actual model calls, search attempts, source reads, elapsed
seconds, input/output tokens, and monetary cost. Reserved calls use a separate
`model_calls_reserved` measure. Platform usage/cost absent from a receipt stays
unknown. Scientific assessment separately retains status, score and original
rubric hash; this adapter never invents a score or normalizes the core rubric.

## Actions, recovery and authority

The browser submits opaque offers or question/action references, their hashes,
the displayed input identity and revision, and a client idempotency key. It never
supplies a root, thread, RPC ID, process owner, epoch, or execution permit.
The server persists intent before work and rejects changed-payload reuse.

Nonsecret browser intent identity is saved before POST. After refresh, response
loss or reconnect, the browser reads history only. A key is released only by a
matching server record: key, project reference, operation kind and original
request hash. Queued, running, execution-unknown and failed-or-unknown outcomes
remain blocked. Model terminal observations must retain that original binding;
an operation name alone is not reconciliation evidence. Native questions retain
separate answer intents; content-mode tool approvals may only decline/cancel.

Scope/resource confirmation is not execution permission. A content operation
requires an explicit, server-bound one-call authorization and a separate send.
Search/source/browser tools require their applicable permits and consent. A
callback or ledger intent is not authenticated tool execution. No unknown
attempt is automatically retried, no frozen run is resumed, and no Stage3 is
started by Stage2 import.

## Current routes

| Adapter | Explicit POST operations | Read-only observations |
| --- | --- | --- |
| Project | create; confirm; configure; revise; compile | project list/detail; history; overview; contract; exact action recovery |
| Stage1 | initialize; plan-query; checkpoint; export | bound ledger, real core gate, planned queries and action history |
| Stage1 execution | execute-query currently refuses as unconnected | no search or source-read completion is inferred |
| Stage2 | actions: activate a registered source-bound package | offers, saved activation and history |
| Content planning | models/authorize; models/actions | models, offers, paginated actions and hashed UTF-8 output chunks |
| Native content session | models/native/answer; models/native/interrupt | cached native requests, actions and terminal observations |

Stage2 trusted registration revalidates repository package and source hashes at
activation. It uses `stage2-general-v3/daily_v3`; historical v2 is separate.
Browser file paths and caller-supplied seeds cannot replace that registration.

## Adding a stage without rebuilding the UI

A future adapter must use this same project store and binding, expose read-only
observations, and supply server-owned offers for its explicit mutations. Its
producer must retain raw source/artifact hashes, failed and older attempts,
question/approval intents, applicable permits, bounded resources and independent
assessment. Revision races, response loss, true store reopen/new owner, changed
payloads and cross-project requests must fail closed without duplicate execution.

Stage-specific executors still need implementation and validation. Adding Stage3
will reuse intake, identity, intent/history, metrics and native/API boundaries;
it is **not** a promise that an unimplemented stage can be connected by changing
HTML alone. Only the stage-specific views and output presentation should change.

Remaining production work is authenticated retrieval/source acquisition,
ledger-to-canonical Stage1 delivery, the full Stage2 generation/extraction and
independent review/selection chain, stage execution permits and resource limits,
and actual own-account/native acceptance. Existing saved v6/2D/3D result views
remain separate from newly generated stage results until those source bindings
exist. Offline fixtures, browser tests and actual research acceptance must be
reported separately.
