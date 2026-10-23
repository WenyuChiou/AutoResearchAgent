# Recorded search prefix, contract S1-RETRIEVAL-TRACE-1.1.0

This opt-in companion answers a narrow question: within one externally pinned
recorded run and input, which query and backend attempts had started by the
first recorded CandidateSnapshot discovery completion for this work? It includes unsuccessful, empty,
unrelated and pending attempts. One query can have several backend attempts.
The inclusive cutoff is the earliest completion across all recorded versions.
A later selected version or known round never replaces an earlier unknown round.
Earlier raw results that were never extracted and mapped to this work are not
searched by this command; they cannot establish a universal first returned work.

Put the plugin `cli/` directory on `PYTHONPATH`, then read existing private files:

```shell
python -B -X utf8 -m research_workspace.retrieval_prefix index.json \
  --journal screening_events.jsonl --trusted-index-sha256 <external-index-pin> \
  --project-id <recorded-project> --input-version 1 --run-id <recorded-run>
```

The callable `derive_retrieval_prefix` accepts those same exact raw byte inputs
and identities. It checks the mandatory external raw-index hash before decoding,
existing index/screening contracts, the journal pin and genesis chain, event and
parent/completion order, and full library query-history equality. It reads each
input once; the CLI only prints a JSON companion and never edits the inputs.
Its `search_attempts_until_first_discovery` object keeps query-start and
backend-attempt-start denominators separate from completions. A started attempt
still open at the cutoff remains `pending-at-cutoff`, even if it failed later.
Original discovery, distinct-query, producing-backend and query-backend counts
remain in their original `counts` field. Index JSON pointers and pinned journal
JSONL line/payload pointers locate each observation.

The trusted index pin must come from the original accepted capture, outside the
package being checked. Recomputing a new hash after deleting and renumbering
events cannot substitute for that pin. The verified prefix covers these saved
bytes only; it does not establish that unrecorded real-world searches never
occurred. Referenced raw source-artifact bodies are not replayed by this command;
their saved refs remain explicit and `source_artifact_bytes_replayed=false`.

Omit `--journal` to report precise Unknown prefix counts. A legacy index without
a recorded-run library has `binding=null`; requested identities remain separately
labelled `requested_binding`, never presented as historical identities. Mixed
bindings, changed pins, missing/reordered chain events and inconsistent histories
reject. Existing trace1.0 and default JSON/CSV/XLSX/Markdown exports retain their
original bytes. This companion cannot authenticate human/Core acceptance, grant
Stage2 import/execution, launch research or establish scientific improvement.
