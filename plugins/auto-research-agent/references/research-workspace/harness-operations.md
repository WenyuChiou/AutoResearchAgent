# Server-owned Harness operations

`research_workspace_native.harness_ops.HarnessOps` calls existing
`validate_index`, `derive_literature_selection` and `selection_files` producers.
This service performs saved-input checks, conservative screening and exports;
it does not search, score, approve a stage, import protected inputs or call a model.

Trusted startup supplies immutable index bytes and their raw SHA-256, a private
output root and principal allowlist for each opaque project reference. The raw
index hash and canonical selection input hash remain separate. `view` and
`get_action` read only. `execute` accepts only an action, index hash, expected
revision and idempotency key; the host supplies its absolute request deadline.

SQLite intent precedes producer execution. Same-key replay reads the old attempt;
changed payload rejects. Lost-process running work becomes unknown and is never
redispatched. Failures and partially saved files remain retained. Exports use new
private directories and fixed names; downloads verify the saved size and hash.
Deadline checks are cooperative between Python/file steps, not forced cancellation.

An authenticated, source-valid stale revision is refused before producer admission.
Only a successfully committed `known-unsent` refusal binds the exact request digest,
project reference, raw and canonical input hashes, client key and offered/observed
revisions. HTTP remains 409; GET can recover that durable refusal after response loss
or journal reopen. Its key always replays the refusal. The UI verifies the complete
receipt against its retained intent and current source-bound view before releasing
that intent for a new explicit action. Missing/mismatched receipts, deadline/owner
or commit failures retain uncertainty; no automatic POST or replacement key follows.

The Atlas host mounts three buttons, authenticated routes, operation history and
hash-checked downloads when trusted startup supplies this service. Opt in with
`--harness-operations-root C:/private/new-operations` to the existing pinned
Atlas host command; the directory must be new and outside Git. No native/model
lifecycle is enabled by this option. Synthetic-input tests call real producers;
actual native and scientific acceptance remain separate.
