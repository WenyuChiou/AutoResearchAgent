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
authenticated lifecycle, browser UI, scoring and live native E2E remain separate slices.
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

Existing-thread injected durable controller.
An existing-thread injected controller joins the journals and recording pump with mandatory caller admission and write-time checks. Local action intents precede native intents; same-key replay never writes, unknown work stays blocked and request resolution remains distinct from turn completion. This does not establish authenticated lifecycle, browser UI or native acceptance.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_controller.py -v
```

Injected controller fault and ownership regressions.
Synthetic safety fixtures cover stale answers, existing intent non-adoption, active epoch ownership, unknown recovery, malformed bytes, partial writes and binding rejection; these checks do not prove browser/service E2E or native execution.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_controller_safety.py -v
```

Preserve failed controller construction without poisoning a healthy retry.
Construction rejects invalid channels and epoch IDs before binding. A later failure retains the used epoch and fault evidence; an established recording channel closes once. Missing fault persistence remains blocked, with no native I/O.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_controller_construction.py -v
```

Keep project authority and native request targets inside a server-owned session facade.
SessionApi exposes opaque project/request/action references over an existing injected controller. Trusted callbacks check principal and source binding; they do not attest native authentication or lifecycle. API intents persist before controller calls, and replay/history never resends. This facade does not supply its own HTTP transport, browser UI or native execution.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_session_api.py -v
```

Expose the existing session facade through a bounded loopback HTTP adapter.
SessionHttpServer is an explicit 127.0.0.1 listener over a supplied SessionApi. GET may omit Origin; if supplied it must match exactly, and POST always requires exact Origin. Exact Host, bearer authentication and project authorization remain required. Port 80 uses canonical authority/origin, and a response timeout stops further replies. Malformed or oversized requests are rejected, and disconnected clients can read durable outcomes without resending. Tests use real temporary loopback HTTP with fake native channels; browser UI, public deployment, native authentication and model execution remain unverified.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_http.py -v
```

Serve the accepted original Wiki with a separate session interaction overlay.
WikiSessionServer requires the four exact accepted reference asset byte strings and their separately pinned public plugin README at trusted bootstrap. This composes the #88 synthetic reference with an injected session overlay; it does not load or relabel the #104 real-package projection. It publishes only a static allowlist and no private files. The panel uses a credential only in memory, stores non-secret intent keys before POST, and recovers with GET without resending. Native authentication and live research remain unverified; historical WorkspaceIndex status and research evidence are unchanged.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_wiki_http.py -v
```

ScopeApi wraps the existing facade. Trusted bootstrap binds an original ResearchBrief path and expected hash. Exact original bytes, parent hashes, new decision versions and reviews are persisted atomically in SQLite; replay is idempotent. Scope history does not change WorkspaceIndex/input binding, compile searches, approve runtime execution or start a turn. Source/operator provenance is an attestation, not independent proof of human identity.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_scope_api.py -v
```

ScopeWikiSessionServer adds same-origin scope history/version reads and explicit append/review routes over that facade. The separate three-language scope panel requires confirmation of the displayed exact version; a version switch disables old forms. Local non-secret intent keys hold uncertain writes and recover through GET only. A saved review is not core PR approval, a search permit or native input activation.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_scope_http.py -v
```

Bind synthetic fixture imports to one complete candidate checkout.
CandidateSources compiles captured Python source bytes from one absolute repository
root. It rejects missing, partial, preloaded, linked or mixed owned modules and
checks actual origins, package search paths and hashes again. Cached bytecode
cannot substitute for captured source. It is a test-only source boundary, not
native-process authentication or an external-dependency attestation. Failed
imports require a fresh process; no reusable Python-environment recovery is claimed.

```powershell
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_research_workspace_native_browser_source.py -v
```
