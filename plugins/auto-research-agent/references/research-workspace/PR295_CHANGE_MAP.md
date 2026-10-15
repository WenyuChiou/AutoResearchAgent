# PR #295 change map and historical evidence

This map separates executable features from historical review artifacts. It does
not establish a complete live Stage 1/2 research run or scientific improvement.

## Frozen inventory

Original head: `304420f022cb80bcbd4e4039f3f80a1e5800098d`.
Inventory base: `356cc24df148f9e238f2e42f96607991ed836dc4`.
Accepted main integrated normally: `9377ae5127e261614e834b903f9a8fbc128832f9`.

The exact Git base/head diff contained 819 paths, 158080 added lines and 245
deleted lines. GitHub displayed 159460 additions; the table below uses
`git diff --numstat --no-renames BASE...HEAD`, with the frozen SHAs above.

| Content | Paths | Added lines | Disposition |
|---|---:|---:|---|
| Historical review evidence | 553 | 98464 | Archive original bytes; retain seven compact Wiki evidence files |
| Runtime and UI | 93 | 24160 | Preserve |
| Tests and fixtures | 151 | 31736 | Preserve; repair observed synchronization/lifecycle defects |
| Documents and examples | 16 | 2933 | Preserve; repair complete-ready receipt publication |
| CI | 4 | 468 | Preserve all platforms, tests and explicit failures |
| Versioned capability registry | 1 | 264 | Preserve; frozen v1 remains unchanged |
| Git attributes | 1 | 55 | Preserve asset byte/line-ending rules |

Fourteen nonempty duplicate blob groups account for about 434 KB. Most excess
text comes from different historical receipts repeating complete source
inventories. Those receipts cannot be rewritten as one current PASS.

## Review complete features in this order

These are review batches inside this existing PR, not additional PRs.

1. **Runtime and portable connection.** Runtime specifications, bootstrap and
   context, process lifecycle, local configuration and connection.
   Start with `cli/research_workspace_native/runtime_spec.py`,
   `bootstrap.py`, `bootstrap_context.py` and their identity/recovery tests.
2. **Projects and queries.** Topic/scope versions, resource budgets, planned
   query binding, permission, storage, history and bounded retrieval.
   Start with `project_intake.py`, `planned_queries.py` and the query tests.
3. **Sources and provenance.** Public acquisition/resolution, contained workers,
   saved parser input, source observations and exact work/version identity.
   Start with `bounded_public_source.py`, `owned_source_observations.py` and
   `saved_source_parser_factory.py`.
4. **Stage 1 reading and delivery.** Saved reading, manual notes, claim review,
   coverage, canonical records and current-project delivery.
   Start with `project_model_reading.py`, `project_saved_claims.py` and
   `cli/research_workspace/canonical_delivery.py`.
5. **The v6 Wiki and stage boundaries.** Same-page topic/operations/progress,
   current-project results below, paper selection, graphs and Stage 2 views.
   Start with `cli/research_workspace_native/web/projects-*.js` and the
   registered browser/HTTP tests.
   Stage 3-6 UI execution remains planned/unconnected.

Paths above are relative to `plugins/auto-research-agent/` unless starting with
`cli/`; runtime filenames in batches 1-4 share
`cli/research_workspace_native/`. Existing merged main functionality is
retained, including its separately owned Stage 2 admission and advisory code.

## Historical evidence preservation and recovery

Only 546 evidence files newly added by this PR were removed from its current
tree: 98069 text lines and 16249022 bytes. No production or test file was removed.
Runtime/tests/registries do not read those historical receipt paths.
The seven files in
[the Wiki evidence folder](../../review-evidence/team-wiki-20261014/README.md)
remain unchanged and retain their original scope and source bindings.

All 553 original evidence files were archived before cleanup. Every ZIP entry
was read back and verified against its original Git blob, byte count and SHA-256.
The private archive contains 17231513 uncompressed bytes; its SHA-256 is
`741e4fa02df84dca8d5b1dfcb80577cc415039ccc2e6c6d33553c0a1b4ee688d`.
The original head remains an ancestor of this PR and has a local recovery
branch, `codex/pr295-before-cleanup-20261014`. History was not rewritten.

Retrieve an old receipt without replacing current source:

```powershell
git show 304420f022cb80bcbd4e4039f3f80a1e5800098d:review-evidence/PATH
```

Or export both historical evidence trees outside the checkout:

```powershell
git archive --format=zip --output=../pr295-original-evidence.zip 304420f022cb80bcbd4e4039f3f80a1e5800098d -- review-evidence plugins/auto-research-agent/review-evidence
```

That export also includes any evidence already present at the original head;
its container hash differs from the private 553-file archive. Original receipts,
failures and hashes remain historical, not evidence that a later head passed.
Normal cleanup reduces the review diff; it does not erase old Git objects or
make the remaining implementation a 500-line PR.
