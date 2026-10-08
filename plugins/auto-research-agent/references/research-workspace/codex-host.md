# Local atlas host and Codex connection

The atlas remains an immutable, read-only research view. A separate loopback host
serves registered, hash-pinned view manifests and adds a three-language connection
panel and whole-workspace case links. The original exported HTML and evidence stay
unchanged. A served-overlay receipt distinguishes original and presented bytes.

Run from the plugin CLI path with an installed Python interpreter:

```powershell
python -B -m research_workspace_native.atlas_host --config C:/private/views.json --config-sha256 <SHA256> --open
```

Configuration has only `views`, an array of entries with `ref`, `label`, absolute
`manifest` path, manifest `sha256` and boolean `fixture`. Each registered manifest
must describe a complete atlas export. Files are verified and snapshotted before
listening; unknown paths and API writes are rejected. Same-title cases remain
separate views. This is a single-user localhost host, not public deployment or
multi-tenant access control. Browser bootstrap credentials remain only in memory.

An explicit startup `--check-codex --codex <absolute executable> --codex-sha256
<SHA256> --probe-root <new private directory>` performs one bounded
`initialize → initialized → account/read(false)` check. It closes that process and
retains an exclusive receipt. Account reads may contact authentication services.
GET only retrieves the saved observation. Passing does not mean a persistent
research session, model entitlement, process containment or completed model turn.

## Requested UI maintenance assistant

The user requested a small global feedback box on 2026-10-08. Its intended flow is
feedback → separate UI worktree/Codex thread → tests → Draft PR → branch preview.
Research-stage conversation and maintenance use separate permissions and histories.
Refresh or a lost response must read a saved intent rather than resend. Source
roots, allowed UI paths, base/head, task identity and execution limits belong to the
server. Changes never silently overwrite the accepted UI or merge themselves.

This host does not dispatch that maintenance task. Persistent native lifecycle,
project admission, turn delivery, review callbacks and preview publication remain
required before enabling automatic modification. A static HTML file cannot own the
local Codex process; the local host or a deployed backend must run alongside it.

## Stage 1 adapter maintenance

Consume the Stage 1 producer's canonical package, ledger, selection and source
identities through `research_workspace`, not copied demonstration records. For
each accepted producer revision, compare schemas/fields with the adapter, run
the registered projection/atlas tests and add regressions for new states or
fields. Unsupported schema versions reject rather than silently omit evidence.
New output uses a new directory, manifest and source hash; old output stays intact.
The host binds each complete view separately and never hot-swaps project data.
Adapter source changes require a reviewed PR. This policy does not itself watch
GitHub, restart paused automations, rerun research or automatically fetch packages.
