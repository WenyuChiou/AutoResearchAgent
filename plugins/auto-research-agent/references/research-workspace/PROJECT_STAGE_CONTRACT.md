# Universal Harness UI project and stage contract

## Goal and delivered boundary

The workbench is a reusable interface to the repository Harness. A researcher
starts an independent project with any topic, or explicitly asks their own Codex
for topic proposals, confirms a versioned scope and resources, and reviews each
saved operation and result. A demonstration topic is not a production default.

Current adapters cover project intake, offline Stage1 ledger operations, explicitly
sealed planned-query bootstrap/execution, canonical
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
| Stage1 search execution | query-authorize; query-bootstrap; query-execute; query-restore-owner | sealed limits, runtime job, reserved budgets, real runner receipts and retained failure/unknown history |
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

## Explicit Stage1 search bridge

The optional `ProjectStage1QueryService` wraps the existing `PlannedQueryService`
and unchanged retrieval runner. Entering a topic, enabling a consent checkbox,
registering a runtime, startup and GET never authorize or initialize that runtime.
The browser selects server offers and submits only key/revision/input version,
brief SHA, offer ref/SHA and explicit confirmation. Authorization also retains the
researcher's original consent text. Caller roots, executables, RPCs, query text,
runtime pins and permit paths are refused.

`query-authorize` exclusively writes a project/source/plan/runtime/cap-bound seal
and a separate input snapshot. That snapshot is not a canonical WorkspaceIndex.
The integer project input version and original raw brief SHA are distinct from
the legacy query adapter's brief-hash version domain; strict registration/permit
1.1 adds these bindings without widening legacy 1.0.

`query-bootstrap` durably reserves one 30-second probe budget and intent before
Core.create, then saves a new immutable seed and exact writable clone. Old offline
runs remain in history. The probe receipt says only that Core.create returned:
it is not authenticated process/import attestation or retained raw probe output.
Failures after entering Core.create and interrupted dispatch remain unknown and
cannot automatically retry. A completed job binds the actual manifest, seed tree,
current state, control database, project registration and permit.
The bootstrap deadline and unchanged authority are checked inside the final
SQLite transaction, including immediately before commit. A late callback or
database write rolls back completion/activation and retains execution-unknown.

### Closest-work citation tracing

The Stage1 project panel reads Core's current included, verified closest-work
reviews. References and cited-by have distinct explicit single-attempt grants,
bound to the exact work/version, round, saved frontier, registration and raw
source/runtime pins. `expansion-authorize` saves that immutable permission;
`expansion-execute` charges the existing query and project allowances before
using the same owner, worker and retrieval runner. Search permission alone does
not authorize these operations. Refresh, same-key replay and restored history
never dispatch; uncertain attempts remain held and reservations are not refunded.

New query bootstrap declares the supported Semantic Scholar citation backend in
the Core plan without authorizing a query. Existing immutable plans are retained;
unsupported legacy citation bindings and seeds without a discovered DOI/arXiv ID
remain unavailable. A failed seed does not hide other supported offers. Completed
seed/version/operation evidence is reused across rounds according to Core policy.
An observed backend return still needs its coverage receipt/truncation review,
source reading and researcher review; it cannot establish Stage1 completion.
No new model, source-read, research or scoring permission is granted by this panel.

`query-execute` reserves the next offered backend attempt and timeout+30 seconds
before dispatch. Cumulative reservations are checked against immutable intake
intent history, including failed and unknown actions. Admission binds the precise
outer request/inner client key and current seal/config/raw execution source before
the existing runner's I/O. Backend attempts are separate from provider HTTP calls,
bytes and monetary cost; those resource limits are not yet demonstrated.

Live ledger writes, local plan recording, checkpoint and export share the query
owner/frontier. The bootstrap run identity cannot be replaced by a sibling copy.
Checkpoint metadata must reference a real ledger event. Restoring an owner is an
explicit local history operation, with no probe, source or search dispatch. It
remains available after permit expiry; all new queries still refuse. GET and
same-key response-loss recovery only read history. A lost bootstrap worker is
shown as execution-unknown rather than running after a true store reopen.

This first bridge retains one immutable query authorization/bootstrap per project.
An expired seal or revised input cannot be replaced, reset or reused for another
version. Versioned renewal/rerun generations, with separate retained budgets and
attempts, remain a required extension; the UI reports stale/unavailable rather
than silently granting new execution. Independent projects already have separate
seals, roots and history.

The common stage projection exposes search observations and separate reserved
attempts/probes/seconds. Actual backend-attempt counts require saved runner
receipts; token usage, cost, source reads and scientific scores remain Unknown
when absent. `stage1_complete` and `accepted` remain false. Source acquisition,
model reading, ledger-to-reading-record production and the full coverage loop
still require their own adapters/permits; this search segment does not complete
the full Stage1 goal. Stage2 execution and Stage3–6 remain unconnected.

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

Remaining production work is authenticated source acquisition,
ledger-to-reading-record production and authenticated retrieval/read/coverage,
the full Stage2 generation/extraction and
independent review/selection chain, stage execution permits and resource limits,
and actual own-account/native acceptance. Existing saved v6/2D/3D result views
remain separate from newly generated stage results until those source bindings
exist. Offline fixtures, browser tests and actual research acceptance must be
reported separately.

## Saved-source and manual-reading registry seam

`ProjectStage1RecordsService` is an injected server-side producer. Its three
explicit operations register an original saved source receipt, register typed
manual reading annotations, and produce current canonical records. It has no
public path-taking route, downloader, model reader or automatic stage start.
The trusted host must supply a three-argument context manager owning the current
run's saved mutation frontier. It yields a zero-argument owner/frontier check
callback which raises on refusal; `None` retains the existing offline fixture
seam. Any other yielded type is rejected before admission. Source and reading
registration compose this check with current Core state checks; records also
check the current coverage checkpoint and propagate the same callback into the
separate delivery-offer registration. The intake transaction checks before
admission and work, after work, and again after saved SQL writes immediately
before commit. Owner/deadline failure during saved SQL rolls back registry/offer
publication, retains the durable intent as unknown and never adopts the orphan
file or automatically retries. Context-exit checks alone are insufficient.
An absent or refused guard cannot write a registry or file. Production query-
owner wiring remains a trusted-host responsibility, not authority from this seam.

Sources require existing real Core `SourceReadStarted`/`SourceReadFinished`
pairs. The SDK receipt stays in its original declared `output_dir`, beneath
the fixed outside-Git materials root. Its raw receipt, every declared physical
artifact, observation time, request/resolved URL, status and Core raw/text refs
must agree. Registering saved bytes creates no fictitious read/import event,
does not rewrite an original receipt and grants no protected-import authority.
Candidates without a genuine completed source attempt block production;
failed attempts remain distinct originals rather than invented full text.

Manual annotations bind the current project/input/run/manifest, candidate,
screening decision and effective review. Six classification and seven findings
fields retain literal Unknowns. Every existing selected-version claim requires
its actual Core claim ID, source ID, text hash and explicit UTF-8 character
start/end/quote; repeated quotes are never resolved by first-match search.
Incompatible historical claim enums are explicit blockers, never mapped
silently. Roles require same-work claim references. Registration does not
authenticate a model-produced reading or establish scientific truth.

SQLite action and event receipts retain every annotation revision. Latest
explicit saved event order selects a reading; JSON key order cannot select it.
Self-rehashed mutable state, extra same-ref events, missing history and action
receipt disagreement reject production. The output includes all candidates,
every screening decision and every selected-version source attempt. Coverage
and `stop`/`continue` come exclusively from the current Core checkpoint.

Each run is bounded to 256 paper/source records, 256 claims per reading,
256 KiB per registry entry, 1,024 retained entries and 16 MiB records/artifacts.
The producer saves its intent before writing, verifies a fully written and
synced temporary file, and publishes an exclusive final name without overwrite.
The existing delivery service registers that immutable file with a separate
idempotent action. This is not a filesystem/SQLite distributed transaction:
crashes may retain a partial or complete orphan file and unknown intent. Such
an outcome never becomes an offer automatically and is never rewritten or
adopted on reopen. Same-key saved recovery performs no file producer again.

Offline tests use two authored SDK HTTP sources with real Core/SQLite, typed
saved annotations, canonical delivery and the actual offline package validator.
They are engineering fixtures. Actual public acquisition, native model reading,
complete coverage/researcher acceptance and source/model execution permits
remain unconnected by this seam; Stage2 is unchanged.

### Open a saved Stage1 delivery in the v6 Atlas

The current `saved-evidence-validated` artifact appears automatically as an
inline saved literature network in the owning project workspace. It uses the
original v6 graph, details, compact direction summary and bibliography, bound
to the current project and input version. Project setup and Harness operations
stay in that workspace; **Refresh saved state** reloads saved history and
restores the inline view for the current delivery binding. Viewing the saved
package does not execute research.

Authenticated GET routes bind project, input version, revision, artifact and
manifest: `/api/projects/{ref}/stage1/atlas/{input}/{revision}/{artifact}/{sha}`.
Notes and BibTeX use its `/files/{opaque_ref}/{sha}` catalog. Paths, owners,
native IDs and permits cannot be supplied. Source/receipt/frontier checks,
complete byte inventory and before/after deadline checks reject stale or
changed evidence. Reading uses the pure canonical reader and existing local
ledger checks, without package rebuild, source-runtime replay or action writes.
Responses share the host's 1 MiB bound and refuse larger projections.
Package traversal rejects unlisted paths before reading their content. Regular
files are captured with explicit byte/count/aggregate limits; the pure reader
uses that immutable snapshot rather than reopening disk content. A second
bounded capture checks the physical package again before returning.

The public shell contains reviewed code only. The original project window
retains its in-memory credential, reads private JSON and transfers it through
an exact-origin/window MessageChannel. The graph never receives the credential
or private server paths; downloads are authenticated by the project window.
Refreshing the graph rechecks the same saved binding with GET, never POST.
Changing project/revision retires the view and ignores late responses.
Directly opening the shell without its project window supplies no private data.

Unknown, partial, pending audit and failed attempts retain their saved meaning.
The bare package has no new readiness evidence or Stage2 execution authority.
Source identities requiring unavailable semantic replay fail closed. Stage3–6
remain planned/unconnected. Graph access does not demonstrate native/model
execution or full Stage1/Stage2 acceptance.

### Preserve unread candidates in a saved delivery

Canonical records `1.2.0` add the already implemented read-only
`Stage1ScreeningLibrary` and its original raw artifacts to the delivery. Every
Core candidate remains in the paper catalog. Query/backend history, first
discovery order, result position, versions, actual decisions/reversals and
source attempts remain distinct; result position is not a relevance score.
An unscreened candidate has no invented `DecisionEvent`.

`discovery-only` papers preserve saved discovery metadata, an actual URL or
null, metadata evidence level and Unknown reading/classification fields.
They have no fabricated source receipt or claim. If a selected version already
has a source attempt, claim or current review, missing registered reading still
refuses delivery. Human-reviewed rows retain the original complete source and
claim guards. The server compares the full library to its current Core
projection during production, registration, delivery and explicit recovery.
Raw artifacts retain original refs and hashes, including historical versions.
The exact complete Core journal is also archived and hash/chain checked;
query, source and decision history cannot be shortened by rewriting counts.
Legacy fully annotated `1.0/1.1` contracts remain unchanged.

The graph, complete library, notes and bibliography consume the same saved
Index. The existing project screening-library panel exposes the real discovery
counts; the unchanged v6 graph's discovery-count presenter remains a separate
UI follow-up. None of these records establish complete reading, sufficient
coverage, stage acceptance or a relevance ranking. Stage2 explicitly refuses
the unconnected `1.2` consumer; Stage3–6 remain planned/unconnected.
