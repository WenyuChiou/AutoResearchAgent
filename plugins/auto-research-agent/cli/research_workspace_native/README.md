# Native workspace primitives

Persistent injected JSON-RPC requires a deadline-aware channel, durable event sink
and write-time binding checks. Typed IDs, exact answers and ambiguous failures stay
distinct; failed connections cannot resend. Protocol pin: `b5d805789d4033c911868f49118a264a7ab3d067`.
`BindingVerifier` reuses accepted pure-byte checks, rejects source caches and dirty
dependency HEAD. This does not attest the running process or its import closure.
Dependency pins retain verified raw Git blobs, not normalized worktree hashes.
Each write check compares physical regular tracked files with those bytes without
running clean filters. Unsupported modes/paths or CRLF/encoding transformations
that differ from retained blobs fail closed. Checks do not lock concurrent edits.
`ProjectStore` saves project/index/thread bindings and atomic state events in SQLite.
Process-held owners exclude other writers. Recovery preserves known-unsent
`intent-recorded` queues, `retired` answers and completed records; dispatched or
otherwise uncertain operations become unknown and cannot be resent.
`Journal` retains exact requests, idempotent intents, unknown outcomes and bound terminals.
Record a turn intent against the project's existing thread, then call `bind_rpc`
(`FrameJournal.correlate` for a frame-bound connection) before requesting `dispatching`.
Callers must inspect the value returned by `transition_intent`: only `dispatching`
permits the next I/O step; a resolved request returns an atomically persisted
`retired` answer with resolution evidence and must not be sent.
RPC claims bind the exact epoch, typed RPC ID, thread, intent hash and original owner.
Old owner/epoch claims cannot authorize a new dispatch. Receipts and reconciliation
must match the original claim; each native turn belongs to at most one start intent,
while an interrupt may reference that turn. Caller-supplied receipts establish
consistency with saved identities, not authenticity or execution permission.
`reconcile_thread` exhausts bounded turn/item cursors or fails without a partial result.
The caller supplies thread ownership and authenticated observations; reads are not an atomic
snapshot, exactly-once proof or permission to dispatch unknown work.
`FrameJournal` atomically saves complete validated frames and their state projection.
Durable typed correlations join out-of-order replies and terminals without guessing;
semantic conflicts retain raw evidence and quarantine. Ordinary notices stay passive.
Outgoing frames prove intention, not full writes. `RecordingChannel` separately wraps
injected read/write/close with append-only SQLite BLOBs and durable intent/result pairs.
Valid read bytes, including malformed UTF-8/JSON and partial frames, are saved before
return; oversized invalid reads retain a prefix with `capture_complete=false` and its
prefix SHA. Write results record one observed count, not full-frame/native delivery.
Read/write recording failure blocks further I/O; `close` still attempts cleanup once
even if recording fails. A read-to-commit crash can lose bytes; unmatched intents
remain unknown and old connection epochs cannot reopen. Authenticated lifecycle and
controller admission remain separate requirements; recorded bytes grant no authority.
Tests use synthetic channels and local storage; no Codex/model runs. Production launch,
HTTP/UI, scoring and live E2E remain separate slices.
No research/import/resume authority is granted; existing Engine guards stay unchanged.

Run these offline checks from the repository root with an installed Python interpreter
and a writable TEMP/TMP/TMPDIR outside Git:

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_transport.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_store.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_journal.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_history.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_frame_journal.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_binding_bytes.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_review.py -v
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_recording.py -v
```

Read-only frame/write observation bridge.
A read-only bridge joins a saved outgoing frame to contiguous intent/result suffix writes; complete observed writes grant no authentication or execution authority. Answer shape validation can run without I/O.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_write_observation.py -v
```

An independently testable existing-thread construction context.
BoundControllerContext requires explicit binding/admission callbacks and a durable
frame sink. Invalid construction changes no epoch; later failures preserve used
epochs and fault or unobserved-fault evidence. A recording channel closes once,
even when the separate failure event cannot persist. SQLite reopen preserves old
epochs and unknown requests; a new owner supplies a new explicit injected epoch.
The context has no answer, start, interrupt, pump, reconnect or launcher method.
Callbacks and recorded cleanup do not authenticate a native process or grant
execution authority. The corrected controller below reuses this context.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_construction.py -v
```

The injected controller preserves action intents before I/O, same-key replay without
writes, unknown outcomes and request-resolution/turn-terminal separation. It adds no launcher.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p 'test_research_workspace_native_controller*.py' -v
```

Keep project authority and native request targets inside a server-owned session facade.
SessionApi exposes opaque project/request/action references over an existing injected controller. Trusted callbacks check principal and source binding; they do not attest native authentication or lifecycle. API intents persist before controller calls, and replay/history never resends. HTTP, browser UI and native execution are not supplied by this slice.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_session_api.py -v
```

API recovery fixtures reopen SQLite using a new writer, owner and connection epoch.
Synthetic crash gaps before dispatch and after observed writes retain history without retry.
Post-recording status/fault persistence failure keeps its missing fault event distinct
from independently recorded channel close evidence. These are injected failure tests,
not actual native process crash or Windows research acceptance.

An explicit authenticated loopback HTTP listener wraps the injected SessionApi.
It checks exact Host/Origin and bearer credentials, bounds JSON bodies/responses,
and returns saved action history without retrying a lost response. Excess sockets
close before handler creation. The connection cap defaults to 16 (allowed 1-128);
each admitted socket has at most one handler and one deadline timer. The absolute
socket deadline defaults to 5 seconds (allowed greater than 0 through 30), including
trickled request lines, headers and bodies. A deadline closes the HTTP socket; it
does not cancel an already admitted controller action or prove native completion.
Its slot stays occupied until that handler finishes. The caller explicitly owns
listener start/stop and supplies trusted authentication and project bindings.
This slice provides no process launcher, browser UI or native research authority.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_http.py -v
```

Serve the accepted original Wiki with a separate session interaction overlay.
WikiSessionServer requires the four exact accepted reference asset byte strings and their separately pinned public plugin README at trusted bootstrap. This composes the #88 synthetic reference with an injected session overlay; it does not load or relabel the #104 real-package projection. It publishes only a static allowlist and no private files. The panel uses a credential only in memory, stores non-secret intent keys before POST, and recovers with GET without resending. Native authentication and live research remain unverified; historical WorkspaceIndex status and research evidence are unchanged.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_wiki_http.py -v
```

Opt-in real browser/local-service check, with two synthetic projects and injected
channels: run `tests/research_workspace_native_browser/core_panel_fixture.py` from
the declared checkout. Supply absolute `--repo`, exact `--head`, installed `--node`,
Playwright skill `--executor` (`run.js`), installed `--node-modules`, and a new
Git-external `--output` directory. It performs no installs, native research or model
calls. Chromium opens visibly, only the owned loopback origin is allowed, and the
driver has one 120-second deadline. The caller's credentials are never requested.
The default requires a clean checkout without bytecode caches. Precommit checks may
explicitly supply `--staged-sha256` for the full-index staged binary diff; unstaged,
untracked, stale-head, partial-checkout or mixed-origin candidates are rejected.
Actual imported origins, source/asset/runtime hashes, project/input bindings,
browser checks and service results are saved. Double click, lost response, refresh,
project switch, reload and reconnect must produce one injected write for project-a
and zero for project-b. `dispatched` / `answer-sent` remain distinct from native
resolution or turn completion. Ordinary CI runs source guards without a browser.
This bounded panel check does not attest real Stage1, native authentication,
research-topic isolation, full workspace acceptance or the real-package projection.

The core panel fixture loads its four accepted reference assets from the exact retained public Git commit, verifies their fixed hashes and reports commit/path/hash separately.
Mutable main presentation assets remain unchanged; missing or mismatched retained blobs reject without lazy fetch, object replacement or another checkout.

Append source-bound ResearchBrief versions and explicit reviews with ScopeApi.
Original brief bytes, parent/version hashes and old reviews remain saved.
A trusted HTTP deadline check inside the mutation transaction rejects an expired queued save.
Saved scope is not active input, a permit, or execution authority.

python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_scope_api.py -v

ScopeWikiSessionServer adds scope history, selected-version review and explicit confirmation to the original Wiki.
The panel translates interface labels only; source and user text remain original.
Its trusted deadline check runs after store lock waits and before transactional commit.
Expired append/review requests leave SQLite state unchanged. Viewing or saving never starts research.
Credentials remain in memory; response loss reads saved history without automatic POST retries.

python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_scope_http.py -v

The expanded browser fixture requires one complete absolute --repo; overlays and fallback checkouts are rejected.
Captured owned Python source is compiled directly, with construction and shared native fixtures included.
Loaded paths, raw source hashes and package paths are checked again before each control operation.
An import rejection requires a fresh process; no third-party or native-process attestation is claimed.

python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_browser_source.py -v

Retain the core panel recipe guards and scenarios; separately identify its pinned presentation inputs.
The separate browser/native-session/browser_driver.cjs exercises the full original sixteen synthetic session and scope scenarios.
Run it explicitly with installed Node, Playwright and Chromium; it performs no downloads or native/model/research calls.
Driver, fixture and loader must be at their standard paths under the sole --repo checkout.
Use a new exclusive output receipt; previous R9/R10 results retain their original source attribution.
The fixture uses the current 16-connection cap and five-second HTTP deadline.
Its running phase has an absolute 120-second deadline; bounded cleanup is additional.
Cleanup failures, surviving workers or receipt persistence failures cannot report success.
This synthetic host remains separate from the true Stage1 package and actual native acceptance.

Opt-in browser driver requires explicit --repo/--python/--playwright/--browser/--reference/--temp/--scope/--output; ordinary Python discovery does not launch it.

HTML integration adds explicit bootstrap/context, owned process deadlines and passive session ownership.
OwnedProcessChannel requires a trusted unsent spawn intent and separate source/admission gates; viewing never creates it.
The shared host_config entry resolves already registered runtimes and requires their explicit credential.
Missing references remain unavailable. Successful AtlasHost construction transfers runtime shutdown ownership; failed construction does not.
Feedback inbox references remain borrowed, and closing a host preserves their embedding ownership.

Message offers publish max_text_bytes and advance the saved revision when first recorded.
Prepare rereads the same source binding and enables Send only after the offer and view revisions agree.
NativeKnownUnsent.v1 receipts are issued only for verified message offers/identities/sources, never-admitted keys and explicit pre-admission validation refusals.
The receipt binds project_ref, index_sha256, input_version, client_key, offer_ref and offer_sha256.
The UI removes only the matching local intent; timeout, missing response and uncertain outcomes retain the original key and recover by GET.
Transcript projections retain literal text, partial windows, failures and unknown state; dispatch is not completion.
Synthetic fake-child and injected-channel tests do not establish native authentication or research quality.

AtlasHost optionally takes the same runtime's ScopeApi, reusing the existing source-bound
scope history, append and review HTTP handlers and three-language panel. Approval Accept
is disabled by default. Trusted SessionApi registration may supply an approval_policy
for one exact saved request; literal True is required again before dispatch and the
controller's independent admission still applies. The browser cannot supply this policy,
paths or permits. Saving scope or requesting the next stage is not execution authority.

python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_atlas_scope_approval.py -v

AtlasHost(stage_actions=...) exposes trusted saved-input StageActions over the same
loopback host. The stage panel checks Stage1 checkpoint / Stage2 completion and
records review, hold or request-next decisions without starting research. Every
action binds project/index/input/source hashes, with intent-before-execution and
GET-only recovery. Missing stage input stays missing; a WorkspaceStageReviewRecord
is neither native-user attestation nor permission to execute the next stage.
Run test_workspace_stage_http, test_workspace_stage_storage and test_workspace_stage_panel
for repository-case HTTP/SQLite and synthetic DOM checks.

Trusted embeddings can call runtime_factory.compose_runtime with exact pinned
runtime specs, authenticate and five server gates: verify_source, admit_spawn,
admit_lifecycle, admit_attach and admit_action. enabled defaults to False. Optional
approval_policy independently admits one exact saved approval. The runtime owns
the existing process/bootstrap/controller/registry sequence; call start once,
then pass it to AtlasHost(native_runtime=runtime, credential=credential).
Successful host composition owns shutdown. Spec loading rejects previous journals,
sidecars and cross-project source/store overlap; this is a bounded NEW session,
not resume, multi-tenant authentication or proven process-tree containment.
Runtime tests use actual Python fake children and HTTP/SQLite, never Codex/models.
Run test_atlas_runtime_spec and test_atlas_runtime_factory for those offline cases.

## Public-source proposal and owned local observation seam

`project_source_permit.proposal` prepares a source-specific offer from the
authenticated project's current brief, settings, plan, run, manifest, semantic
state, candidate, screening decision and selected saved version. Core metadata
currently has no saved URL field: the offer explicitly proposes the resolver for
that exact DOI; missing DOI or disabled resolver policy remains unavailable.
Credential-bearing, structurally private or nonstandard URLs refuse without
DNS. Counts remain integral; finite fractional reserved seconds stay exact.
The raw search/source reservation state has its own SHA, so an old offer becomes
stale even when both remaining amounts saturate the same displayed server cap.
Search and source seconds share the configured total. A future orchestration
service must also reconcile all other lane reservations before admission.

This proposal is read-only, not a saved approval or executable permit. Its URL
and limits do not attest DNS, redirects, an actual connection or enforcement by
the SDK. The retained SDK only exposes per-request timeout; a separate bounded
transport, durable approval/job/reservations and project API/UI are still needed.
Never reuse a query-only permit to acquire a source or invoke a model.

`OwnedSourceObservations` is a trusted local adapter over an already registered
`PlannedQueryService`. It stores intent before local Core changes, recognizes
only its exact recorded `SourceReadStarted`, and preserves the original owner,
principal, request hash, frontier and append-only observations. The ordinary
search offer and generic saved writer continue to refuse pending sources.
GET does not restore ownership or dispatch I/O. Same-key history, including an
unknown outcome, never calls the producer again; changed payload refuses.
Only explicit existing service registration may read history after real SQLite
reopen. It is not source-job adoption, permission recovery or an automatic retry.

The separate store checker runs before mutation and after SQL immediately before
commit. Losing the real owner after intent SQL prevents any Core write; losing
it after Core effects or final SQL rolls back successful publication and retains
unknown. Core journal effects cannot be rolled back, so this seam does not
pretend multi-store atomicity. The trusted completion producer must check the
current project/decision/version and saved original receipt; neither adapter
authenticates an actual reader, launcher, model or research result. This seam is
not currently an external source execution endpoint. Stage2 execution remains
deferred and Stage3–6 planned/unconnected.

Topic revision preserves settled searches as separate input-version history.
Before revising an initialized query ledger, restore its saved ownership with
the existing explicit action after a restart; GET does not restore it. Running
or unknown operations and an unfinished source parser hold revision. The old
permit, ledger, failed actions and cumulative reservations remain saved. Confirm
the new scope/settings and compile its plan, then explicitly authorize a new
search seal; old keys only replay history. The panel shows both current-version
and cumulative reservations. This does not refund budgets or grant model/source
permission. Legacy projects already revised with a used stale seal remain held;
this increment does not migrate their historical execution. Stage2 execution is
still deferred and Stage3–6 remain planned/unconnected.

The newly delivered `/project-atlas.html` child is a read-only view of the exact
project/input version, reached through the owner workspace's bound memory
channel. It keeps the original v6 renderer and verified note/BibTeX file reads.
Project setup and Harness operations remain in the owning workspace; use
**Return to project** rather than creating another project inside this viewer.
The browser fixture `tests/browser/project-delivery-flow-test.cjs` walks two
authored saved sources through reading registration, checkpoint, preparation,
delivery, exact BibTeX click/download and a non-executing Stage2 input hold.
This exercises actual HTTP/SQLite/Core services, without real model, search,
native research, scientific evaluation or acceptance of the incomplete stage.

## Complete saved Stage1 screening library

The universal project portal has a read-only screening library next to the real
ledger controls. Every saved candidate remains visible, including excluded,
pending and unscreened works, unread versions and actual source failures. Select
a paper for its exact work/version, metadata, discovery and query/attempt counts,
source/import/claim history, decision reasons and reversals. Only current-version
source URLs appear in its main access area; older versions remain in history.
Relevance stays Unknown when no assessment exists. Discovery order, query count,
backend attempts and recorded rounds are separate observations, not a relevance
ranking or full-text reading proof. Source availability does not prove reading.

`ProjectStage1LibraryService.read` derives a `Stage1ScreeningLibraryEnvelope` from
Core Candidate/Claim/Decision snapshots, one validated run, its current manifest,
semantic state, complete journal and confirmed project/input/brief/plan/settings
binding. The complete projection has an external SHA-256; it is not persisted
by GET, is not `Stage1ResearchRecords`, and grants no stage acceptance. A current
checkpoint's saved snapshot bytes are checked; historical checkpoint refs stay
historical. The complete projection has a 16 MiB bound with explicit refusal,
never a silently shortened bibliography.

HTTP GET `/api/projects/<ref>/stage1/screening/<inputVersion>/<stateSHA>/<offset>`
reads 20 summaries. Later pages require the complete projection SHA as an extra
path component. GET `/api/projects/<ref>/stage1/screening-detail/<inputVersion>/<stateSHA>/<projectionSHA>/<index>`
reads one complete original row. Principal/project/version/state/projection/index
must match. The existing 1 MiB response cap remains; oversized single-row history
is refused explicitly. No browser root, owner, runtime or permit is accepted.
Refresh and language changes do not dispatch or implicitly restore a missing
query owner. Project switching clears old rows and rejects delayed responses.

The canonical producer still requires genuine current screening decisions,
version-bound reading and source records for every candidate. An unscreened
candidate now refuses as `saved-current-decision-required` before reading lookup;
it never receives an invented pending decision or fake access failure. This
companion makes partial search history usable while keeping that stricter gate.
The complete neutral projection retains even failed queries with zero candidates;
the current browser card exposes each paper's query history and global failure
counts, but does not yet expose the full orphan-query outcome history in a
separate panel. The existing Core journal keeps those observations intact.
Source acquisition, model reading, coverage completion and new-topic end-to-end
Stage1 acceptance remain separate pending interfaces; Stage2 execution is deferred
and Stage3–6 stay planned/unconnected. Local/CI fixtures are engineering evidence.

## Saved SDK source observation completion

`complete_saved_source` in `project_stage1_source_observation` is a local bridge
from an original SDK receipt to one already saved `SourceReadStarted` event.
It does not download, start a model, authorize acquisition or retry a reader.
The owner supplies the exact captured start payload, fixed private materials
root, original receipt path/hash and externally verified runtime hash. The
start request must contain the SDK's six normalized fields: `operation`, `doi`,
`url`, `title`, `output_dir` and `public_only`. Any timeout or execution budget
stays in the owner's separate intent. The original SDK directory cannot be
relocated or rewritten to fit this interface.

Before any Core artifact save, the helper checks the entire receipt and SDK
digest, all declared raw/text artifacts, and start/attempt/observation time
ordering. It uses the existing explicit SDK-to-Core outcome mapping and keeps
the full SDK attempt history in the original receipt. Only an `available`
outcome supplies nonempty UTF-8 text; HTTP, network, parse and other unavailable
outcomes remain failures. A network failure without response bytes binds the
actual SDK receipt as its failure artifact. The declared runtime hash is marked
`saved-sdk-observation; not execution attestation`: it does not authenticate a
process, verify reading fidelity, identify a paper or support a scientific claim.

One exclusive Core writer lock covers the local completion. The optional
`check_current` callback runs before each mutation and after completion. The
owning wrapper remains responsible for current project, candidate, decision,
version, permit, budget and frontier checks, durable intent before external
I/O, and the final action commit. Core journal effects cannot roll back:
partial artifact saves remain pending, and a completed local event followed by
owner failure must retain an unknown action rather than a usable success.
The wrapper must refuse automatic replay or adoption after reopen. Repeating a
completed source intent refuses. After a valid completion, a fresh checkpoint
and the existing `ProjectStage1RecordsService.register_source` bind the source
description into the saved registry; they do not create a reading record or
change coverage, stop or Stage 2 eligibility.

`test_project_stage1_source_observation.SourceObservationTests` exercises real
Core/SQLite and the SDK parser against authored HTTP mocks. Its eight checks
cover available completion/registration/reopen, HTTP 503, timeout, changed
start/request/version, receipt/time/artifact tampering, partial receipts,
owner refusal before or after a raw save, and the fixed materials root. The
captured run passed 8 tests in 13.960s with unchanged source inventories. This
is an offline helper result; the production owner wrapper, source worker, real
acquisition, model reading and full Stage 1 acceptance need separate evidence.

## Distinct controlled acquisition and saved-public parsing

`acquired_source_parser.parse_acquired_source` verifies an externally saved
`PublicSourceAcquisitionReceipt`, its exact server request/job/runtime binding,
every bounded raw response, selected successful hop and original hashes. It
requires literal parse admission and an explicitly supplied trusted runner;
the default refuses before parsing. Original acquisition bytes are retained.
An exclusive intent and saved-public manifest precede the runner, and repeated
or ambiguous work cannot adopt an old output or automatically retry.

The SDK's public `import_saved_public_source` parser writes a separate receipt.
Its `source import-saved` operation, two saved-input attempts and
`original_http_acquisition_verified=False` remain unchanged. The returned
bundle binds both original receipts and all declared artifacts. It cannot be
passed off as `source fetch` or silently completed through the legacy Core
source-observation helper. A successful body is not an identity, reading,
claim or stage-acceptance verdict; parser failures keep their real status.

An injected synchronous parser is an offline test seam. Before/after deadline
checks cannot interrupt a hung parser; production needs a separately owned,
bounded parser process and current job/permission/budget checks. This helper
does not dispatch from GET, mutate Core, register a paper, grant protected
import authority or connect the full Stage 1 UI execution path. Stage 2 keeps
its existing source-bound interfaces; Stage 3–6 remain planned/unconnected.

## Shared resource reservations and controlled public-source transport

`project_resource_budget` validates search, model and source reservations against
the same project/input/brief/settings declaration. A reservation event and its
next causal action intent are saved in the first SQLite transaction. Changing
the mutable reservation map or counters cannot reduce that saved reservation;
failed and unknown operations do not refund it. Historical query permits bind
their original authorization bytes. Model offers bind the original action
request, and recoverable legacy model windows conservatively reserve the original
allowance. Missing historical evidence refuses execution; reads never migrate it.
Declared/reserved seconds and calls remain separate from observed usage or cost.
The final query checker runs outside the service lock, then rechecks local owner,
closing, deadline and permit expiry before allowing a worker to proceed.

`bounded_public_source.acquire_public_source` accepts a separately admitted exact
request, numeric public-peer binding and an explicitly configured typed resolver.
Its default resolver is unavailable. Redirects, aggregate HTTP attempts/body bytes
and network/cleanup/file finalization share one deadline. Raw/error/partial bytes
and original attempts remain private. A successful raw body is compared with the
streamed write count/hash; drift or late completion cannot become a usable success.
A receipt published before a later timeout remains immutable, with a separate
exclusive failure observation that the acquisition parser must reject.

`ProcessBoundedResolver` uses a fresh spawned child and waits for its sole writer
to exit before reading bounded IPC. Private/mixed/malformed/late answers refuse,
and failed cleanup poisons the resolver. Cleanup has an additional bounded
allowance; synchronous process startup, filesystem operations and parser execution
still need an outer owned hard-deadline worker. Resolver/transport hashes are
bindings, not execution authentication or a source permit.
Final physical-body verification also uses a bounded regular-file reader and
stable identity checks; a filesystem without stable file identities refuses
execution. An oversized probe never becomes a complete-file hash.

The low-level transport alone grants no source permission or model execution.
The project host composes it with separate bound authorization, durable jobs and
source/reading controls. GET remains passive. Offline fixtures make no actual
external search/source/native/model/research/scoring call.

Saved reading draft review is a separate local UI action. Open the saved
`read-paper` result in project history, select its exact source quotation, and
enter a claim, source location, relation and evidence level. The default relation
is pending; summary/classification/findings retain their original Unknown values.
`ProjectStage1ClaimService` resolves source/work/version and UTF-8 positions from
the saved model artifacts, rechecks the current project and source bytes, then
calls the unchanged Core `Ledger.claim`. A real saved claim returns its event ID
and character locator; it does not register the whole reading, approve coverage,
complete Stage1 or unlock Stage2. Refresh/response loss reads the same durable
action history. A failed or unobserved append holds new writes across reconnect.

Saved-source reading now retains the last checkpoint as historical evidence
without requiring that checkpoint to be current. The current owned frontier,
source SDK receipts and exact text hashes are still checked. Delivery retains
its separate current checkpoint and canonical records gates. Canonical records
1.1 retain every legal Core relation/evidence level, nullable locator, original
claim event and historical source bytes; existing 1.0 records remain supported.
These UI/adapter checks do not demonstrate a live Codex research run.

Saved-source evidence review also works without a model draft. In the project
literature library, open a paper and choose **Review evidence in saved source
text**. Select a verbatim passage, enter one claim and its location, then explicitly
review its relation and evidence level. Bounded pages cover the saved text beyond
the model excerpt; this action makes no model or source-acquisition call. The
server binds the current work/version, source registry, original text hash and
owned ledger frontier before appending Core `ClaimEvidence`. Core identity
review still requires five distinct primary-text claim IDs; these are human
judgments, not automatic identity approval. Unknown values remain Unknown.
The same durable `stage1-claim` history handles replay and uncertain writes;
refresh after a lost response reads history without submitting again.

After reviewing source quotations, choose **Review and register reading notes**
in the Codex/Harness operation panel. The saved-source route reviews existing
sources and claims without inventing a model draft. Edit the classification and
findings, optionally select literature roles with an explicit reason and
same-work claim evidence, check the confirmation, and save the reading note.
The model-draft review route remains available separately. Unknown
and all Core claims remain; this single SQLite action grants no source/model
permission and appends no Core claim. Once all current readings are registered,
check the evidence gate, export the saved ledger, prepare the records, then build
the canonical delivery. A review-only/partial package does not complete Stage1.
Stage2 refuses a 1.1 package until its consumer is implemented; Stage3-6 remain
planned/unconnected. A failed or uncertain prepare is retained for reconciliation;
refresh and same-key replay cannot repeat the file producer.

Saved-source reading offers bind the current project revision, input/brief,
work/version, source-registry snapshot, raw source bytes, Core claim set and
owned ledger frontier. A manual quotation's original durable intent and receipt
bind its exact UTF-8 byte range, including repeated passages; registration does
not choose the first occurrence. A changed source, claim, revision or owner
requires a fresh review. Unknown and uncertain writes stay recorded, and true
SQLite reopen reads the same-key action instead of registering again. This
offline human-review path makes no search, model or native research call and
does not grant Stage1 acceptance.

### Preserve the reviewed v6 interface

The operation drawer includes a version-bound **Stage1 current progress** guide.
It reads the same overview used by the existing controls, identifies held or
uncertain work first, and navigates to scope, search, screening, reading,
coverage, delivery or retained history. Navigation issues no POST and never
creates a key, permit, session or retry. A saved step or validated package is
labelled separately from accepted research. Missing evidence remains Unknown;
old input versions cannot supply the current guide. English and both Chinese
variants use the same source-bound states, with no changes to the original graph.

Saved Stage1/Stage2 pages retain their dark sidebar, 2D/3D graph, paper detail,
compact direction summary and folded process history. A compact **Project &
research topic** section precedes Stage1. Select an existing project, or enter
a new topic and open the existing scope form; entering a topic alone submits
nothing. Selection reads the current server-owned project and input version.
The same **Codex & Harness** button opens that one operation document in a
drawer with separate styles. Closing it retains both the graph and operation
document. Opening, closing, translation and refresh never dispatch research.
Select the operation project explicitly; a historical saved case is not the
current project's result or permission. Original package/renderer files stay
unchanged and derived host assets have separate hashes.

The selector and drawer share one broker and one iframe. Initialisation reads
the project list; it creates no project, permit, session or turn. Topic prefill,
project selection and translation do not start Harness research. Confirm the
scope and budgets explicitly in the operation form, then use its current
server-bound offers for each stage action, question or approval. Only opaque
project references and nonsecret display context cross this presentation seam;
credentials, permits and durable action keys remain in the existing broker.
The saved Atlas shown below is labelled separately from the selected operation
project; selecting a new project never relabels a historical package as its
result. Stage2 uses the same project identity when admitted, with execution
still deferred here; Stage3-6 remain planned/unconnected.

When starting `run-project-workspace.py`, pass the existing private, pinned
`--views-config <views.json> --views-sha256 <SHA256>` alongside the existing
project/runtime flags. `/` redirects to the first registered view, preserving
its relative asset/note paths; the config order chooses this landing view.
Omitting the config registers no saved cases: the initial topic-intake page is
then available, but an old `/views/.../atlas.html` URL cannot exist. A new topic
does not receive an invented graph. Its validated saved delivery opens through
the existing private v6 viewer. `/projects.html` remains a separate operation
entry, not a replacement saved-results UI.

Only the derived `/projects-panel.html` allows same-origin framing. Atlas parent
pages allow that frame but still forbid being embedded themselves. External
framing, unsafe Host/Origin and API admission checks remain rejected; an iframe
separates styles, not same-origin script privileges. Stage2 execution remains
deferred and Stage3–6 planned/unconnected.
