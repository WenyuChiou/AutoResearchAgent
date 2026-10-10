# Optional planned queries on the local Codex Atlas host

The ordinary per-user setup remains unchanged: use your own Codex login,
selected executable/model, pinned configuration and bounded text permit.
Without query flags, no planned-query service, writer or search route is registered.
This addition does not widen that text permit, sandbox, network access or budgets.

An operator may separately register an already confirmed Stage 1 intake and plan.
Save a private JSON object with exactly `kind: LocalAtlasQueryRegistration`,
`schema_version: 1.0.0`, `project_ref`, and `registration`. The registration uses
the exact fields of `planned_query_contract.FIELDS`; no browser supplies these
paths, a permit, executable, runtime, principal list or admission callback.

The query brief has its own `brief_sha256`; its semantic `input_version` must
match the UI/native scope input version. It need not equal its own byte hash.
The original UI index, scope input and immutable Stage 1 parent remain pinned.
Register a separate, disjoint working ledger copied from that parent, a durable
control database, and a separately authorized `Stage1PlannedQueryPermit` binding
the confirmed brief, plan, runtime/source identities, allowed targets, expiry
and attempt/time/result budgets. Hashing a file does not grant permission.

After obtaining that applicable permission, append these flags to the existing
explicit `atlas_local_launcher.py --enable-native` invocation:

```text
--query-registration ABSOLUTE_PRIVATE_JSON_PATH --query-registration-sha256 SHA256_OF_EXACT_JSON_BYTES
```

Both flags are required. Preflight rejects altered bindings, expired permission,
foreign/preloaded source loaders, and mutable query storage overlapping any
native input, project view or future native attempt, before creating a writer.
The same local credential must satisfy the independent query principal allowlist.
The UI receives an opaque, version-bound offer; execution still needs explicit
confirmation and fresh admission before the runner and each subprocess spawn.

Refreshing or losing a response reads durable action history; it does not resend.
New ledger evidence does not silently replace the UI's saved projection or mark
Stage 1 complete. Reopening a database retains consumed budgets and old failures.
Synthetic tests use real HTTP/SQLite with injected channels and fake Hub execution;
they do not prove an actual Codex approval, live search, research or Stage 2 result.
