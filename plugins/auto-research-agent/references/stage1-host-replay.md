# Saved source replay after host relocation

A private Stage 1 package may preserve a successful validator command from a
different machine. Editing that command would erase historical evidence. The
opt-in `HostReplayReceipt` v1 instead binds the unchanged package, its original
observations and a separately executed offline replay on the receiving host.
Ordinary package validation remains strict and still rejects the old path.

This extends `cli:research-workspace` and `cli:stage1-deliverable` for
`P3V3.DECISION_TRACE` / `S1V3_DECISION`. It reuses the existing source receipt,
relocation, observation and complete package/view validators. It records technical
evidence only; scientific improvement is not yet demonstrated.

## Inputs and trust

The independently supplied receipt SHA-256 is a separate trust input. An operator
must review the actual replay process evidence before supplying it. A self-hashed
JSON file cannot prove that a command ran or authenticate a reviewer.
Each pinned JSON is hashed and strictly parsed from one UTF-8 byte snapshot;
duplicate keys, non-finite values and replacement between hash and parsing reject.

The schema is `schemas/stage1-host-replay.v1.schema.json`. The receipt contains:

- Exact project/input identity, external snapshot reference and original canonical
  manifest SHA-256. The referenced snapshot and manifest are read again.
- Separate historical producer and actual replayer runtimes, interpreter locations
  and complete exporter Python-file inventories. The caller supplies their source
  roots separately. Files are read and hashed; attachment code is never executed.
- The current validator's complete CLI/schema/requirements inventory and runtime.
  All installed distribution bytes, dependency Python bytes, SDK merge identity,
  Python version and executable bytes must agree across the three runtimes. Only
  the separately pinned exporter implementation may differ.
- Exactly one record for every canonical source, with work/version identity, exact
  raw archive inventory, old validation hash, actual new observation and process
  start/end times. Missing, duplicate and extra records fail closed.

Each observation must retain the nine command arguments, zero exit, unchanged
stderr, no acquisition, original source hash, reconstructable relocated receipt,
successful SDK report and matching source version. Only the interpreter location
and the existing report fields `checked_at`, `result_path`, `output_dir` and
`receipt_sha256` may differ between old and new observations. The new report time
must fall within its process interval. Full package inventory, canonical identity,
claims, access states and regenerated editable views retain all existing checks.

Inspection reuses the externally accepted offline replay; it does not run another
search or claim that a new SDK process ran during inspection. Changed source bytes,
runtime dependencies, validator code or snapshot require new bound evidence and a
newly reviewed external hash.

## CLI and Python API

```shell
python -m research_workspace.saved_admission PRIVATE_ROOT \
  --snapshot-ref snapshot-ref.json \
  --host-replay-receipt host-replay.json \
  --trusted-host-replay-sha256 REVIEWED_RECEIPT_SHA256 \
  --historical-exporter-root ORIGINAL_SOURCE/cli/stage1_deliverable \
  --replayer-exporter-root REPLAYER_SOURCE/cli/stage1_deliverable
```

All four host-replay options are required together. Without them the original
strict runtime/path checks apply. The Python API has the same keyword arguments.
Direct package callers load a context using
`research_workspace.host_replay.load_host_replay(...)`, then pass it explicitly
to `stage1_deliverable.package.validate(..., host_replay=context)`. The context
rechecks current runtime/code and archive bytes. The outer-package Python API
`project_package(..., host_replay=context)` reuses the same verified evidence for
observed-title/DOI projection; normal projection stays unchanged.

## Acceptance and importer boundary

Successful technical inspection still returns blocked admission until the existing
independently trusted Core aggregate and actual HTML operation receipts pass. It
creates neither receipt. Historical claims and missing discovery history remain
unchanged. No candidate is selected, material ID invented or Stage 2 started.

The existing formal CLI importer now accepts the same four explicit options on
`stage2_workflow import-stage1`: `--host-replay-receipt`,
`--trusted-host-replay-sha256`, `--historical-exporter-root`, and
`--replayer-exporter-root`. They require a saved-source v2 handoff,
`--saved-source-root`, and the independent Core acceptance digest. Its bound
snapshot reference comes from that hash-verified handoff. One resolved context
reaches initial package validation, saved admission, source projection, and final
package validation. A Python-only verified context must retain the same snapshot,
project/input, canonical manifest, and receiving package root; it cannot be mixed
with explicit trust arguments or supplied as browser JSON.

Context-enabled imports return ImportReceipt 2.1.0 with host receipt evidence and
`source_canonical_records_version`. The saved-source path without a host context
retains its 2.0.0 receipt. Neither path grants research execution or creates Core
or HTML acceptance. All existing brief, resource, selection, and output checks
remain active.

Canonical records 1.1/1.2 and the native ProjectStage2Service trusted-offer/HTTP
adapter remain unconnected. The saved snapshot/handoff uses a string input
version; the current native intake uses an integer. This increment does not
coerce identities or change either contract. Formal native receiving requires an
explicit versioned compatibility design and its own actual regressions.

## Verification

```shell
python -m unittest discover -s plugins/auto-research-agent/tests -p test_stage1_host_replay.py -v
```

The synthetic fixture exercises actual offline source parsing and complete view
reconstruction. It tests rehashed receipt tampering, source/identity/coverage,
commands, reports, runtime/code changes and the strict legacy path. These checks
do not establish scientific improvement, Core acceptance or browser operation.
