# Stage 1 execute and extract: public CLI adapter

This experimental adapter consumes the documented research-hub CLI and audit
schema. It imports no research-hub Python internals. It requires Python 3.11 and
the plugin's locked test/runtime dependencies. Install research-hub in a separate
environment; the adapter does not install, upgrade or merge that dependency.

The bundled `research-hub-audit.v1.schema.json` is copied with LF line endings (JSON content unchanged) from the public
schema in research-hub revision `35dde2a68d7296a5243c9b8d080df9bec705b352`, under
that project's MIT license. Its upstream PR is
[research-hub #137](https://github.com/WenyuChiou/research-hub/pull/137).
This is a provisional development surface until the owner merges it. Delivery
requires the merged revision and a new run; old manifests are immutable.

## Runtime and commands

Supply a JSON runtime conforming to `stage1-execution.v1.schema.json#/$defs/Pin`.
It records the full source revision, `development-unmerged` or `merged` status,
package version, wheel SHA-256, bundled audit schema SHA-256, executable SHA-256,
absolute `argv_prefix`, isolated working directory, dedicated config path/hash
and timeout (at most 600 seconds). The operator must retain package installation
and wheel provenance evidence. These recorded hashes do not authenticate a
package or prove that a remote PR was merged. The runner checks executable, config and captured code bytes before execution.
Runtime identity is the code-tree digest together with exact argv; revision and wheel
labels alone never identify executed code. The labels still require independent
build/install provenance; this code does not prove their source-to-wheel mapping. Never place credentials in argv or this runtime.

From the plugin `cli` directory:

```shell
python -m stage1_retrieval freeze-runtime --runtime DECLARATIONS.json --output RUNTIME.json
python -m stage1_retrieval init RUN --runtime RUNTIME.json --run-id RUN_ID --topic TOPIC
python -m stage1_retrieval execute RUN QUERY_EVENT_ID --backend openalex
python -m stage1_retrieval resume RUN BACKEND_ATTEMPT_ID
```

Bind the plan with `CoverageLedger.bind_plan(..., backends=[...], limit=...,
citation_backends=["semantic-scholar"])` before search. The existing coverage API
opens rounds and creates planned query events. Call `execute` once for each
declared search backend, then `complete_query` and `extract`. Search backends are
openalex, crossref, semantic-scholar, arxiv and pubmed. The public CLI receives the
exact query, year window, limit and ranking. A null plan ranking uses its public
`smart` default. Each authored adversarial query is a separate planned action.
The adapter does not use the hub's model-driven query expansion.

For citation expansion or identifier inspection, create a coverage expansion query from a naturally
discovered work/version, then execute it with semantic-scholar. The identifier
comes from that version's saved DOI or arXiv record. Missing identifiers fail
before a request. Search and citation backend obligations are separate.
`enrich` uses the declared search backends that support identifier lookup
(openalex, arxiv or semantic-scholar). `verify` selects doi.org or arxiv.org from
the saved identifier. A successful resolver response is `success_evidence`, with
zero candidate records. Use `compare_identity` for separate saved field
comparisons; neither command authenticates identity or verifies a scientific claim.

## Evidence and failures

An `ActionStarted` precedes process launch and includes exact argv, query binding,
runtime hash and capture location. `ActionFinished.execution_ref` points to a
versioned receipt containing process times, exit code, raw stdout/stderr hashes,
all saved audit file refs, observed provider/HTTP attempt counts and the original
audit attempt/index for each normalized candidate. Candidates retain discoveries
from different backend invocations. Identity and claims remain unverified.

The adapter retains pre-merge results even when the final CLI list is shorter.
Therefore recorded discovery counts can exceed the requested display limit.
These are candidate observations requiring screening, not included papers.

Only a complete valid audit with successful parsed results and an observed HTTP
success can establish `success_empty` or `success_nonempty`. HTTP 429, 404/410,
timeout, parse failure, unknown outcomes and nonzero exits remain failures.
Partial results survive as `partial_failure`; they are extracted but cannot
complete a coverage round. Missing/invalid audits produce explicit unknown
failures with unavailable provider counts. A missing registered evidence file
fails run validation. Exit zero and stdout `[]` alone cannot prove an empty result.

Process captures use exclusive files; a completed `process.json` seals hashes.
`resume` only imports matching bytes. It never starts a process. A second execute
for the same query/backend is rejected even after interruption. Inspect an
unfinished capture and document its cause before creating an explicit new query.
Original attempts remain in history. No automatic retry is performed.

Receipts replay offline, including command, process bounds, raw hashes, outcome,
normalized rows and original discovery mapping. The exporter copies their raw
evidence and reports CLI, provider and HTTP counts separately. Missing capture
coverage makes totals unavailable; none of these counts estimates model calls.

The gate still requires reviewed cluster evidence, recent completion, verified
closest works and two complete zero-yield rounds. Unknown truncation stays null.
`development-unmerged` adds an explicit blocker. Neither a valid receipt nor a
passing validator establishes scientific correctness or an A/B improvement.

## Immutable code identity

Use absolute `argv_prefix` entries: `[PYTHON, "-I", "-B", SCRIPT]` or
`[PYTHON, "-I", "-B", "-m", PACKAGE]`. The package must be a top-level module.
`freeze-runtime` records the interpreter import roots, installed package files,
bytecode, extension libraries, venv configuration, missing import paths, and the
script code tree. File names and SHA-256 values both contribute to the digest.
File symlinks bind the alias, link text, resolved target and target content hash;
retargeting or changed bytes invalidate the pin. Directory symlinks are rejected.
The interpreter probe uses public Python import machinery without importing the
research CLI. The adapter never imports research-hub implementation modules.

Initialization and launch recheck code and import resolution; saved replay checks
the recorded trees without starting a process. A changed/deleted/added code file,
changed venv or missing runtime is an explicit validation failure. Restoring exact
bytes permits replay; changing labels does not silently bless an existing run.
Old pins without code identity are rejected and need a new run. Do not mutate an
environment used by an active run. The installed runtime must be retained for live
export validation; a copied ledger alone does not authenticate missing executable
bytes. This is not a container sandbox or proof of OS/dynamic-library isolation.
Externally loaded code and source-to-build provenance still require operator audit.
