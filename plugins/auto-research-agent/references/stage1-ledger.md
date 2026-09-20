# Stage 1 saved-observation ledger

This is the independent part of implementation PR 2: `extract → validate →
gate → checkpoint`, with action receipts for later `execute` integration.
It imports observations supplied by the caller. It does not run searches,
verify bibliographic identity, or establish scientific coverage. Every manifest
states `mode: offline-import` and `research_hub_pin: null`. The search adapter
must wait for the documented audit surface in research-hub PR 137 to merge and
be pinned. Do not substitute private Python imports or an unmerged dependency.

## Run the CLI

Use Python 3.11 with the existing hash-locked dependencies:

```shell
uv run --no-project --python 3.11 --with-requirements plugins/auto-research-agent/requirements-test.txt python plugins/auto-research-agent/cli/stage1_ledger --help
```

The examples below assume those dependencies are installed in the active
Python environment. Paths are relative to the repository root. Use a new run
directory outside the checkout to keep research data out of Git.

```shell
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run init --run-id synthetic-run --objective "Synthetic household question"
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run start --request query.json
```

`query.json` contains:

```json
{"operation":"search","arguments":{"query":"synthetic household question","year":"2024-2026","rank_by":"year","adversarial":false}}
```

Each write prints an event ID or artifact reference as JSON. Save the returned
IDs; do not guess them. To register an actual observed backend, use `start`
with this request, substituting the query event ID returned above:

```json
{"operation":"backend","arguments":{"variant":"base","argv":["synthetic-tool","search","synthetic household question"]},"backend":"synthetic","parent_id":"QUERY_EVENT_ID"}
```

Save the actual stdout, stderr and normalized record array using `save`:

```shell
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run save --producer ATTEMPT_EVENT_ID --source records.json
```

A normalized record has `title`, `authors` (strings), `year` (integer or null),
and optional nullable `doi`, `arxiv`, `pmid`, `version`. These are observed
metadata, not verified facts. Unknown fields are rejected during extraction;
keep the complete upstream output in a separate raw artifact. A version label
is source-specific evidence, not permission to equate different identifiers.

`finish --request completion.json` accepts `attempt_id`, `outcome`,
`http_status`, `exit_code`, `stdout`, `stderr`, `records`; the last three use the
complete ArtifactRef objects returned by `save`. `records` must be null on
failure. Only HTTP 2xx plus exit code zero and a parsed array can yield
`success_empty` or `success_nonempty`. HTTP 429 is `rate_limited`; HTTP 404 is
`not_found`. Other outcomes include `timeout`, `network_error`, `http_error`,
`parse_error`, `interrupted`, `unknown_error`. No command retries a backend.

```shell
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run complete-query --query-id QUERY_EVENT_ID
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run extract
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run validate
python plugins/auto-research-agent/cli/stage1_ledger --run ../synthetic-run checkpoint
```

`validate` exits 1 with an explicit error on a missing file, hash mismatch,
invalid schema, broken reference, changed projection or inconsistent derived
record. Unavailable counts are null. A valid report checks record consistency,
not scientific truth. Unbound runs return `continue` or `human-review`.
Runs with a frozen [coverage plan](stage1-coverage.md) use the reviewed coverage
and marginal-yield policy, which can report an operational `stop-sufficient`.
A failed validation preserves its report but
does not create a successful checkpoint.

The equivalent public entrypoints are `python
plugins/auto-research-agent/validators/stage1_run.py RUN_DIRECTORY` and `python
plugins/auto-research-agent/gates/stage1_readiness.py RUN_DIRECTORY`.

## Decisions and claims

`decide --request decision.json` accepts `work_id`, `decision` (`pending`,
`include`, `exclude`), `reason`, `rationale`, and nonempty `evidence_refs`.
Use a specific lowercase reason code such as `scope-match`,
`population-mismatch`, or `insufficient-evidence`. A second decision points to
the first; it never replaces it. Cold-start screening starts pending until an
explicit, reasoned decision is recorded.

A human override also supplies `actor` and `authorization`, containing the
actual `input` and reviewed `state_sha256`. The latter is emitted by `recover`
or a checkpoint. A decision or new observation changes that hash; another
checkpoint alone does not. Preserve the user's actual words. A recorded human
input is an audit assertion, not authenticated proof of who typed it.

`claim --request claim.json` accepts `work_id`, `version_id`, `claim_text`,
`relation` (`supports`, `partial`, `contradicts`, `unclear`, `unverifiable`),
`evidence_level` (`metadata`, `abstract`, `full_text`, `primary_data_or_table`,
`unavailable`), `locator`, `source_ref`, and `verifier`. The early offline labels
`pending`, `context` and `full-text` remain readable for existing observations;
prefer the packet's canonical terms for new records.
The verifier has `actor`, `actor_type` (`agent` or `human`), and `method`.
A locator has `section` and an exact `quote` present in the saved UTF-8 text.
Uncertain relations (`pending`, `unclear`, `unverifiable`) permit metadata-only
evidence or no locator. An `unavailable` level requires a null locator; its
source reference identifies the saved material inspected, not proof of a claim.
`partial` means the supplied evidence supports only part of the stated claim;
it requires a locator just as `supports` and `contradicts` do. Reading an
abstract permits an abstract-level annotation; it does not upgrade the work's
identity or the evidence level of the source metadata. The validator cannot
prove that the supplied text belongs to the named version or supports the
scientific claim; identity verification and independent claim audit remain
required before using it as verified evidence.

## Files, identity and recovery

`run_manifest.json` fixes the local configuration. `stage_events.jsonl` is the
authoritative append-only journal, with a sequence and previous-event SHA-256.
The four projections `query_events.jsonl`, `candidates.jsonl`,
`decision_events.jsonl`, `claim_evidence.jsonl` are also append-only. Candidate
rows are cumulative revisions; use the latest revision per work for current
state. `coverage_and_stop.md` is a replaceable view of the last checkpoint;
immutable validator reports and all saved bytes remain under `raw/`.

New runs declare `checkpoint_output_contract: stage1-handoff-v1`. Every valid
checkpoint's `StageResult.outputs` contains immutable candidate, claim and
decision snapshots plus a `Stage1Handoff` artifact. The validator replays their
contents against the exact source state; simply rehashing invented contents
cannot pass. Repeating a checkpoint reuses identical bytes. A new observation
or decision produces new snapshots while retaining the older ones. These
derived artifacts do not change the reviewed research-state hash.

The handoff selects only currently included works, distinguishes listed from
reviewed versions and preserves all candidate and decision history in its input
snapshots. It reuses the documented `literature-triage-matrix` manual-paper-list
input and default comparison columns at the pinned stable skill revision. It
does not populate comparison cells from memory or execute Stage 2. Its
`eligible_for_stage2` is the Stage 1 operational gate result; `stage2.status`
remains `not-started` and `execution_authorized` remains false. Existing runs
without this manifest contract and their empty-output checkpoints remain
readable. Missing immutable output files require exact restoration; `recover`
rebuilds only projections and the derived coverage view.

Deduplication uses DOI, then arXiv/PMID, then normalized Unicode title, year
and first author. Different identifier namespaces stay separate. Conflicting
metadata is retained as `conflict`; agreement remains `unverified`. Every
backend and query discovery is retained. Unstated versions stay separate.
Malformed records produce an append-only ExtractionFailure and an unresolved
extraction obligation. Re-running `extract` neither repeats that failure nor
silently removes the obligation. Corrected observations need a new receipt;
an extraction failure currently remains unresolved and prevents sufficient stop.
Its evidence is retained for review; corrected data never erases the failure.

`recover` can append a missing, complete projection suffix from the journal.
It refuses conflicting projections and torn journal lines. It reports unfinished
attempts and performs zero automatic retries. An interrupted writer leaves
`.writer-lock`; verify that process has stopped before manually removing that
lock. Never delete a running writer's lock. Preserve corrupt files for review.
Raw files are size-bounded, hashed, and never silently overwritten. Paths must
stay inside the run; symlinks and parent traversal are rejected. This is a
single-writer local ledger, not a distributed transaction service. The journal
detects accidental changes; it is not an externally signed audit log.

## Compare saved bibliographic evidence

After extracting the saved observations, `compare-identity --request request.json`
appends an IdentityComparison to `stage_events.jsonl`. The request contains
`target_work_id`, `target_discovery_id`, `assessor`, and exactly one of
`reference_discovery_id` or `resolver_ref` (omit the unused field or set it to
null). Discovery IDs come from candidate provenance; resolver_ref is a stored
ArtifactRef. The CLI reads saved bytes only.

Each comparison reports title, ordered authors, year, DOI, arXiv, PMID, explicit
version and arXiv revision as match, mismatch, unavailable or invalid. Identifier
normalization preserves namespace and checks secondary identifiers even when
DOI matches. A missing year is unavailable. Different versions remain distinct.

Work agreement is consistent only when title, authors and year match, at least
one shared identifier matches, no shared identifier conflicts, neither candidate
has unresolved metadata conflicts, and the discoveries name different backends.
Different backend names do not establish independent underlying authorities.
Version agreement additionally requires a matching explicit version or arXiv
revision and no conflicting version observation. Unknown versions stay
unverified. Resolver-only evidence and repeated observations from the same
backend cannot establish independent agreement. A discovery cannot check itself.

This records bibliographic consistency, not authenticated identity or scientific
claim verification. Candidate identity and claim evidence levels are unchanged.
The live identity wrapper and source review must still establish source
authenticity and version relationships before sufficient stopping is possible.

`identity-status` first validates the run, then returns the latest comparison per
target work/version. Each has a `current` flag bound to both candidate revisions;
a new discovery makes affected older comparisons stale. Rechecking appends a new
event with `previous_comparison_id`. Validator replay recomputes comparisons and
rejects changed outcomes, altered source references and incorrect history even
when someone recomputes the journal hashes.

## Reproduce the acceptance example

```shell
python -m unittest discover -s plugins/auto-research-agent/tests -p test_stage1_ledger.py -v
```

The synthetic fixture has exactly three queries and four backend attempts,
including HTTP 429, two discoveries of one DOI, and include-to-exclude history.
It removes a raw file, checks a nonzero validator exit, restores the exact
bytes, then checks validation succeeds. Closest work remains unverified, so
the result cannot say research is finished. Additional tests execute the CLI,
recover interrupted writes and reject altered records. These checks establish
implementation behavior, not a P1/P2/P3 quality improvement.
