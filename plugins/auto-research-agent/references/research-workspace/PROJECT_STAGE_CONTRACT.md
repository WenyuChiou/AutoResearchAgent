# Universal Harness UI project and stage contract

## Goal and delivered boundary

The workbench is a reusable interface to the repository Harness. A researcher
starts an independent project with any topic, or explicitly asks their own Codex
for topic proposals, confirms a versioned scope and resources, and reviews each
saved operation and result. A demonstration topic is not a production default.

Current adapters cover project intake, offline Stage1 ledger operations, canonical
delivery of trusted registered saved reading records, and source-bound Stage2
import and workflow initialization. The separate native
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
Stage2 import is not comparison generation or final route selection. A canonical
package validated mechanically is also not Stage1 scientific acceptance.

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
| Stage1 | initialize; plan-query; checkpoint; export; deliver a registered saved-record offer | bound ledger, real core gate, planned queries, delivery offers/package hashes and action history |
| Stage1 execution | execute-query currently refuses as unconnected | no search or source-read completion is inferred |
| Stage2 | actions: activate a registered source-bound package | offers, saved activation and history |
| Content planning | models/authorize; models/actions | models, offers, paginated actions and hashed UTF-8 output chunks |
| Native content session | models/native/answer; models/native/interrupt | cached native requests, actions and terminal observations |

Stage2 trusted registration revalidates repository package and source hashes at
activation. It uses `stage2-general-v3/daily_v3`; historical v2 is separate.
Browser file paths and caller-supplied seeds cannot replace that registration.

## Saved-record Stage1 delivery

Trusted server code calls `ProjectStage1DeliveryService.register_records` with
the exact raw records SHA and current ledger state SHA. It grants no acquisition,
import, model or search authority. Registration checks actual work/version IDs,
all screening revisions, source attempt/result IDs, request/final URI, observation
time, HTTP/outcome, raw/text hashes and claim quotation spans against the replayed
CoverageLedger. Unknown classification, findings and scientific states remain
Unknown. An authored records file cannot override the real checkpoint/handoff
eligibility or stop gate.

For a failed fetch, raw response bytes may exist only in its final attempt rather
than its top-level available-source fields. Bind those actual preserved bytes.
When the SDK observed no response bytes at all, a ledger failure may retain the
exact original SDK failure receipt as its raw-output observation; it is not a
paper or a synthetic empty response. The original null response/text hashes and
failed access state remain unchanged.

The browser selects an opaque offer and sends `key`, `revision`, `input_version`,
`brief_sha256`, `ledger_state_sha256`, `confirmed`, `offer_ref` and `offer_sha256`
to `POST /api/projects/<project-ref>/stage1/deliver`. The server persists intent
before calling the unchanged canonical package build and semantic validator.
Natural full-hash IDs and portable package filenames remain unchanged; Windows
uses extended filesystem handles inside the already guarded private directory.

Saved artifacts bind the current offer, append-only successful event and action
receipt, deterministic private output path, original records hash, package hash,
counts and real handoff. Changed mutable display state or file bytes fail closed.
GET checks saved hashes/inventory only; it does not launch source replay, build
another package or resend a failed action. Trusted `binding` explicitly performs
semantic replay and returns the bound package/handoff; it does not start Stage2.

ProjectHost uses the existing bounded 30-second request maximum for local saved
compiler/package work, including pre-admission and pre-commit deadline checks.
This is not model or research time authorization. A slow/partial output remains
failed or execution-unknown; its key cannot rebuild it automatically. Long-running
delivery jobs and authenticated acquisition are separate remaining work.

`stage1_complete` and scientific scoring remain false here. This is the saved
records-to-package segment, not an automatic ledger-to-reading-record producer,
a new-topic research run, or a completed Stage1 milestone.

## Stage2 frontier interface

Trusted `ProjectStage2Service.advance_frontier` accepts only an existing project,
idempotency key, activation hash, expected old workflow head and exact new head.
It revalidates the current source package, handoff, activation journal and actual
descendant event chain. The original activation receipt is retained; stale CAS,
forged receipts or changed workflow bytes reject. Same-key history and true SQLite
reopen do not execute workflow producers. There is no browser execution route,
native/model/search dispatch, score, completion or next-stage permission. Stage2
full execution is deferred while Stage1 integration is prioritized.

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
ledger-to-reading-record production and authenticated retrieval/read/coverage,
the full Stage2 generation/extraction and
independent review/selection chain, stage execution permits and resource limits,
and actual own-account/native acceptance. Existing saved v6/2D/3D result views
remain separate from newly generated stage results until those source bindings
exist. Offline fixtures, browser tests and actual research acceptance must be
reported separately.
