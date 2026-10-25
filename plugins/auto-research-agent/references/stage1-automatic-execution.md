# Automatic Stage1 production on the existing project services

The opt-in `ProjectStage1ExecutionService` extends the original
`ProjectStage1AutoDriver`. It connects source acquisition, complete extracted-text
reading, automatic screening, full notes, coverage actions, record production and
the existing package exporter. A model result is an AI judgment; exact quotations
and successful export do not establish scientific correctness or human acceptance.

Default hosting stays passive. Trusted bootstrap must already own a confirmed
ResearchBrief, compiled plan, original query/source registrations and the existing
deny-only `ProjectModelService`. The browser cannot supply a provider, permit,
private root, model or source path. The ordinary model-authorization endpoint
rejects automatic-review requests; it cannot mint a batch delegation.

## Trusted entry

```python
host.register_stage1_execution(
    project_ref,
    permit_path=fixed_private_permit,
    permit_sha256=externally_trusted_sha256,
    output_root=existing_private_output,
)
result = host.continue_stage1(
    credential, project_ref,
    run_id=original_run_id,
    deadline=trusted_absolute_monotonic_deadline,
    max_actions=trusted_finite_action_limit,
)
```

Registration performs no model, search or download. The existing query owner still
needs its independently sealed search permission. The existing source owner uses
its lawful-public-source configuration, explicit grant, cumulative resource
reservations, parser and saved-source pipeline. An unfinished or uncertain job
blocks redispatch, including after reconnect or a changed caller key.

The pinned JSON delegation has these exact fields:

- `kind=Stage1AutomaticProductionPermit`, `schema_version=1.0.0`;
- `permission_id`, actual `principal`, `project_id`, exact `input_version`;
- `brief_sha256`, `plan_manifest_sha256`, `budget_sha256`;
- explicitly selected `model`, `max_calls`, `max_seconds`, timezone-bearing
  `expires_at`;
- `allow_model_calls=true`, explicit boolean `allow_source_acquisition`,
  explicit boolean `allow_query_expansions`, `automatic_screening=true`;
- `execution_scope=stage1-saved-text-automatic-review`, `external_search=false`,
  `frozen_subjects=false`, `stage2_execution=false`;
- exact raw `executor_sha256` and `review_units_sha256`.

Model child permits are derived only from that delegation. Each child binds one
task and its exact source snapshot, reserves one call through the original model
broker, and inherits the parent expiry. Both the parent's total calls/reserved
seconds and the original project's shared resource budget apply. Failed and
uncertain attempts remain charged. No new global model settings or account budget
is created. Public source/search budgets remain with their existing owners.

## What reading and screening establish

Each saved same-work/version source is replayed through the original source
registry. UTF-8 segments cover all extracted bytes with adjacent, non-overlapping
ranges. The initial limit is 1600 bytes per segment and 2 MiB of saved text per work;
oversized context remains explicit automatic work rather than silently dropping
records. A deterministic binary synthesis tree consumes validated child summaries
and exact child claims. Every segment, full child note, limitation and quotation
remains in the separately saved full note, including content omitted from the
short synthesis input.

The model broker still uses its authenticated provider and per-I/O admission.
Source instructions cannot enable tools or grant permissions. Model assertions
and classifications are retained as AI output. Quotes must match the shown source
bytes, while synthesis may only reuse exact validated child claims. Metadata-only
or contrary evidence cannot fill a supporting coverage slot. Identity remains
unverifiable without all required field evidence. Reading extracted text does not
attest PDF figures, equations, extraction completeness or scientific sufficiency.

Automatic decisions and Core claims append to the original ledger with an AI
verifier and no human authorization. Existing explicit include/exclude decisions
are retained; pending candidates can receive a newly reasoned AI decision. The
existing records service validates exact spans and registers notes without using
the human-reading endpoint. Coverage still uses the original replayed gate.
Unknown truncation stays null; source failures, budget stops and marginal-yield
sufficiency remain separate. No `human-action` stop or fabricated PASS is added.

`read()` separates recorded work, automatic pending/retry work, technical blockers
and researcher questions. Only final reviewed questions are surfaced; equivalent
questions retain their different work contexts. `note()` returns a current
hash-bound full note without its private path. `export_notes()` creates an
exclusive private companion manifest alongside the unchanged canonical exporter.
The exporter receives the current ledger digest, and the driver ends at the saved
delivery barrier. `stage1_complete`, scientific acceptance and Stage2 execution
remain false.

## Read-only UI integration

After trusted registration, authenticated `GET /api/projects/<ref>/overview`
and `GET /api/projects/<ref>/stage1` expose `stage1.automatic_production` and
`automatic_production`, respectively. This additive value is null when no
producer is registered, the project/input/brief/plan differs or no saved run
exists. It never adopts another project's delegation. Existing default hosting
and execution admission remain unchanged.

The projection retains separate `automatically_recorded`, `automatic_pending`,
`technical_blocked` and `researcher_questions` groups, plus actual model-job
counts. Progress schema `1.0.1` additionally exposes `automatic_resolved` and
each recorded row's actual decision/event, AI proposal, identity status,
rationale and source/version reference. A completed write is not a completed
assessment: a pending AI judgment, unverified identity or a retained decision
that differs from the model remains automatic follow-up. Unread sources remain
technical work. Only a fully read, identity-verified terminal decision without
open questions enters `automatic_resolved`; this is an AI screening outcome,
not scientific or human acceptance. `automatically_recorded` is the recording
inventory, overlaps the outcome groups and must not be counted as resolved.
Reading an unfinished outcome never resends its existing model job. Its binding,
run reference and ledger digest identify the exact saved state. The `notes`
inventory supplies work/version, SHA-256 and an opaque same-origin URL. Fetch
that URL with the existing bearer authentication to read the complete saved
UTF-8 note. The handler reopens the current work/source and verifies note bytes;
it returns the same binding/run/ledger identity without a private filesystem path.

`GET /api/projects/<ref>/stage1/automatic-notes/<sha256>` accepts no client path,
permit or provider. Missing registration or a different producer project returns
409; an unavailable current note digest returns 404; altered note bytes fail
with the existing error envelope. Writes and GET bodies are rejected, and the
existing Host/Origin/fetch-site/authentication/deadline guards apply. These reads
create no tasks, permits, model calls, source requests or Stage2 actions.

## Existing pending observations

`research_workspace.pending_backlog.prepare_execution_queue` consumes an externally
pinned `S1-AUTOMATIC-BACKLOG-1.0.0` companion. It preserves every observation,
original decision hash and exact typed input. Each observation receives stable
identity, lawful acquisition, full-text review, rescreening, full-note and coverage
tasks. Duplicate observations remain distinct; a URL match never certifies a work
or version. Queue preparation performs zero research/model/acquisition calls and
does not resolve an academic decision.

The real legacy input `20261009-A03` is a string. The current native producer's
positive integer project schema cannot silently adopt it. The original legacy run
owner must supply a legitimate same-identity execution binding and valid unspent
permits. Exhausted historical resources, another UI's allowance and a new caller
key cannot grant that authority. The queue remains automatic pending meanwhile;
it is not a list of researcher-only decisions or a claimed 80-paper reading run.

## Verification boundary

### Review input/result 1.1 and saved recovery

New automatic tasks bind the complete confirmed needs and current scope choices,
the plan's inclusion/exclusion criteria, decomposition and cluster questions in
`semantic_context`, with canonical brief/plan content hashes. The actual model
turn contains that context. Rehashed snapshots cannot substitute another scope.
If the unchanged 10000-byte complete prompt bound cannot fit the confirmed
meaning, registration refuses before a model reservation; it never clips scope.

Each new claim requires `assessment: {reason_code, rationale}`. The lowercase
hyphenated code is at most 80 characters and the assertion-specific rationale is
at most 1024 UTF-8 bytes. Status-only reasons refuse. Synthesis must copy the
entire displayed validated claim, including that assessment, and Core receives
the same assessment in the append-only claim event. A quote match alone is not
support. Historical 1.0 results remain readable without invented reasons.

Two individually valid child results can exceed the 10000-byte input bound. The
1.1 synthesis projection first tries the complete child context, then packs only
whole questions, claims with reasons, and limitations deterministically. Its
hash-bound count manifest and `projection.complete=false` expose omissions; all
full results and all segment, intermediate and root notes remain saved. A partial
projection requires `decision=pending`, empty coverage assignments and
`closest=false`. That flag propagates to later synthesis and progress as
`semantic_projection_complete=false`, with
`synthesis-evidence-projection-incomplete`. It cannot enter `automatic_resolved`.
This is bounded pending work, not a completed semantic synthesis or permission to
reduce the source evidence. Complete confirmed meaning is retained in every turn.

Passive work/progress reads do not render a future prompt or reserve a call.
Saved charged results are revalidated and their full notes can be read/exported
without redispatch. New service instances reopen those same durable bindings;
old permit/runtime hashes cannot silently authorize changed producer bytes.

The actual `OwnAccountProjectModelFactory` accepts automatic-review input 1.1.0
and historical 1.0.0. This adapter keeps exact kind, project, typed input, work,
task, brief, snapshot, prompt and source hashes, and deny-only authority checks.
Unsupported versions and rehashed identity or authority changes still refuse
before a native model is constructed. Boundary regressions feed the snapshot
emitted by the real automatic producer into this factory; only `StageModel` is
replaced with a no-process test seam. They do not attest a native or research run.

The authored charged-recovery regression retains its original 300-second
continuation deadline and source/result data. A test-only dispatch wrapper now
includes the original exception chain and remaining deadline in a failed
assertion, then rethrows the same exception without retry. A pass on another
host does not close an independently observed failure or establish its cause.

### Offline resource feasibility

The existing 1600-byte leaf/binary-synthesis path costs two model calls even for
one leaf (leaf plus root). With multiple leaves it costs the leaf count plus each
successive rounded-up binary level. Thirty one-leaf works therefore consume all
60 allowed calls before planning or any other model work; longer texts can exceed
that cap. A saved-delivery barrier or fully covered text is not proof that a new
30-work task is executable within 60 calls, 40 queries, 80 source attempts, three
rounds and three hours. Reservations, failures and uncertain attempts retain their
original cost. No limit or expiry is raised here.

The already existing `read-full-paper` / `analyze-full-paper` path has its own
`stage1-full-source-context-1.0` profile and a 256 KiB full-frame admission bound.
Reusing that path is conditional on complete source/context bytes fitting the
actual serialized native turn, its inspected runtime and trusted host/permit
bindings. It is a separate operation and the automatic delegation does not grant
it. Source sizes, runtime binding, other model tasks and available resources must
be known before a feasible new-topic execution can be claimed. This repair adds
no alternate executor and performs no live new-topic work.

Focused tests use the real saved Core ledger, source registry, shared model broker,
resource reservations, records producer and exporter, with authored source/model
responses. They cover segmented text, exact spans, parent drift and budget limits,
invalid evidence, package generation and no-resend recovery. Related query/source
and existing model tests remain required. These tests establish implementation
behavior only. Actual Topic execution, model semantics, hosted CI, Core review,
native UI acceptance and formal Stage2 import require their own real receipts.

## Composed native host

The compatibility candidate combines the fixed de92358 producer with Core's
74ea551 native host. It preserves full-source reading and analysis, explicit
run-grant continuation, saved Wiki views, and configured Stage2 controllers.
Automatic-review snapshots bind their work directly; Core reading and analysis
offers retain the work reference already validated in their permits. Their
different snapshot shapes are not interchangeable.

The original operator registers the optional producer with
`ProjectHost.register_stage1_execution` using an externally pinned private permit
and the original source/model/records owners. Registration starts no model,
source, query, or Stage2 operation. Authenticated overview and Stage1 reads expose
`automatic_production`; complete notes use the returned opaque `notes[].url`.
Core run-grant arguments still select the original bounded continuation. An
invalid grant cannot fall through to automatic production, and an unconfigured
Stage2 controller remains unconnected.

Deploy one complete, checked source closure and bind its real host, project,
typed input, brief, plan, run, and ledger. The old de92358 package and this composed
candidate have different runtime identities; do not overlay selected files or
reuse a host attestation from another source closure. Original UI receiving and
actual page acceptance follow the completed build and the operator's binding.
No stored run means null with its reason; do not start research to populate a
read-only acceptance fixture. Original30 receiving-only import retains its
separate accepted a778 source and admission inputs.
