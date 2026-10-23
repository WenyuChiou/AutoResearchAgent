# Completed Stage2 frontier registration recovery

The existing trusted ProjectStage2Service adapter exposes recover_frontier for
one saved action key. It repairs metadata after the frontier work completed but
the SQLite commit failed. The default advance_frontier replay is unchanged.

The caller retains the same project, activation hash, previous workflow head and
new workflow head. Recovery reopens current project/source bindings, reconstructs
the existing frontier journal and verifies the actual workflow event chain.
The fresh frontier must exactly match the saved post-work observation. Unknown
work outcomes, validation failures, changed requests and tampering remain held.

Recovery appends a saved frontier event and updates the original action receipt.
It preserves the failed event, original observation, recovery timestamp and hash
of the preceding failure receipt. Repeated recovery reads that same saved record;
it does not run a workflow action, model, review, search or package builder.

This is a trusted adapter API, with no new browser route or physical-path input.
It does not create a human choice, source permission, research acceptance or
execution authority. A selection service must separately retain the actual UI
request and verify its delivery/interaction/planning package. Browser and real
Stage3 receiver acceptance are separate; execution_authorized remains false.
