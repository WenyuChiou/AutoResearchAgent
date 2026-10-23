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

Focused tests use the real saved Core ledger, source registry, shared model broker,
resource reservations, records producer and exporter, with authored source/model
responses. They cover segmented text, exact spans, parent drift and budget limits,
invalid evidence, package generation and no-resend recovery. Related query/source
and existing model tests remain required. These tests establish implementation
behavior only. Actual Topic execution, model semantics, hosted CI, Core review,
native UI acceptance and formal Stage2 import require their own real receipts.
