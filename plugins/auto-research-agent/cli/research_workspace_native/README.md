# Native workspace primitives

An explicit `codex_probe.run_probe` adds a one-shot connection readiness check.
It requires an absolute executable and SHA-256, an empty private working root,
an exclusive receipt and a bounded protocol deadline. Only initialize,
initialized and account/read(false) are sent. No thread, resume, turn, login,
model, search or research operation is exposed. Account reads can contact the
authentication backend. Sanitized receipts retain response hashes, failures and
cleanup without account email, tokens or stderr. A check pass is an observation,
not persistent session readiness, process containment or model entitlement.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_codex_probe.py -v
```

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

# Injected bootstrap context: implementation-only

`BootstrapContext` requires a pre-existing, unsent `thread/start` intent bound
to the project, index hash, source input version and exclusive process-held owner.
Literal source and lifecycle callbacks are necessary before adopting a channel;
these callbacks are not authenticated authority or Windows process attestation.

The helper durably records typed RPC/frame identities and exact outgoing claims
before I/O, uses one recording channel and transport, and rejects caller-created
dispatches. It only permits a submitted read-only sandbox. Constructor failure
after ownership transfer closes the underlying channel even if wrapper creation
fails; failed cleanup remains explicit. It never creates a thread by itself.

Focused verification uses fake channels and real SQLite only:

`python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_bootstrap_context.py -v`

No process launch, account proof, research, model turn, import, resume, reconnect,
or budget is provided. Ordinary controller constructors retain their guards.

# Injected lifecycle and same-transport handoff: implementation-only

`BootstrapSession.open_thread` follows initialize, initialized, account/read and
one explicitly admitted thread/start over the same transport. It verifies the
typed RPC responses, account enum shape, submitted cwd/model/approval policy and
effective readOnly sandbox with literal networkAccess false. This observation
does not authenticate a process, create execution authority or test a model.

`InjectedSessionController.adopt_ready` consumes a ready session once. It retains
the initialized transport, byte recording, used IDs, raw frames and unparsed
buffer. Late admission/source/owner failures close the channel and preserve
uncertainty. No failed attempt automatically sends again or opens a new channel.

`recover_thread` completes only a retained completed reply's local thread binding
after a crash window; it cannot resume, import or send. Actual authenticated
launcher, production API start offer, continuous event pump and webpage transcript
integration remain separate work. No actual Codex or paid model call was made.

Focused verification uses fake channels and real SQLite:

`python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_bootstrap.py -v`

### Ordinary message offers (implementation-only)

`SessionApi.register(..., start_offer=trusted_callback)` optionally binds a
server-owned offer. `offer()` saves its exact identities without native I/O;
`message()` accepts only key, revision, opaque offer ref/hash and text. Server
binding/admission and the controller guard remain independent. API-only unknown
or uncertain native dispatch blocks new keys after reopen; no automatic retry or
API retirement is provided. Conservative byte/start limits are not token/cost
authorization. HTTP/UI, actual native authentication and research remain separate.

### Process deadline helper (implementation-only)

`process_deadline.Deadline` bounds store/SQLite lock waits and readonly guards.
Verifier workers cannot be forcibly cancelled and must never mutate caller state.
Neutral fake-child fixtures do not grant native process or model authority.

### Owned stdio channel (implementation-only)

`process_channel.OwnedProcessChannel` requires server-owned bindings and explicit
trusted admission before fixed stdio startup. Inspect cleanup leader/errors;
caller gates and file hashes do not attest native authority or Windows containment.
Tests run fake OS children, never actual Codex/model/research.
