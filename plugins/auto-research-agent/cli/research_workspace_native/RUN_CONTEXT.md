# Saved Stage1 run context

New `ProjectStage1DeliveryService.deliver` results bind a separate
`Stage1RunContext` 1.0.0 companion after the existing canonical producer succeeds,
before its result is committed. Browser callers still select an existing opaque
offer: they cannot choose source paths, output paths or a runtime. The canonical
manifest and its strict inventory are unchanged.

The trusted producer chooses the canonical sibling `<canonical-name>-context`.
It contains an exact canonical package copy, the confirmed brief, compiled plan,
complete current Core ledger/artifacts and the current project's original intake
events/actions/state plus the actually validated resource view. Each item has a
contained relative path, byte count and SHA-256 in `run-context.json`. The
descriptor's external manifest hash is persisted in the real successful delivery
action and event, then checked against the stored artifact during readback.

Brief needs, original user input, query concepts/families and original compiled
query parameters are retained in their original representations. A separate
keyword field is not invented when the original input has none. Query failures,
decisions, source failures, coverage and resource counters remain original data.
Missing cost or observed duration stays null. Capture time is explicitly separate
from historical discovery/access times; batches never become discovery rounds.

## Precise journal boundary

`capture_boundary` names the exact project revision, last event sequence and state
hash at the durable delivery intent. This prefix ends **before** the new delivery
saved event is published. It cannot include that event: the saved event binds the
companion hash, so including it would create a circular hash. Earlier finalize,
failure, held and resource events remain in the prefix. The complete Core ledger
is a separate source, including its current checkpoint and artifact bytes.
Its actual Core run ID and manifest hash are saved explicitly. Query-owned
`stage1-live-*` and offline `stage1-run-*` registrations keep their original
distinct Core identities; the exporter never guesses IDs by replacing prefixes.

All captured source directories are disjoint from the chosen sibling output.
Private-root, contained path, symlink/reparse, hardlink, file-count and byte limits
apply. Capture validates the original resource accounting under the existing
intake lock, uses the same bytes for hashing and writing, then rereads every source
and the intake frontier before publishing success. Failure leaves partial files
for reconciliation and the existing durable failed/Unknown action. It never
removes reservations, refunds resources or starts a second attempt.

An identical idempotency key replays its original action receipt without capturing
today's source state. A changed payload with the same key refuses. New artifacts
require a context; historical artifacts without one are explicitly reported as
`legacy-no-run-context`, and are not silently migrated or reclassified as complete.

## Receiving saved bytes

Use a checked Python environment with the plugin's existing dependencies:

```powershell
python -B -X utf8 -m research_workspace_native.project_run_context `
  'D:\Receiving Root\saved-run-context' --expected-manifest-sha256 '<external SHA256>'
```

This command validates exact inventory, project/input/brief/plan/run/checkpoint/
handoff/canonical bindings, replays saved Core artifacts without runtime checks,
and checks the captured resource event/action prefix. Every current file read is
relative to the received root. Original absolute paths inside archived records
remain unchanged historical data and are not opened or executed.

The portable check does not attest an interpreter, SDK, another computer, live
research, source semantics, reviewer identity, Core approval or formal Stage2
admission. The original canonical producer has its existing strict runtime/source
replay; receiving-host strict replay remains the separately sealed provider's
responsibility. The companion does not relax either guard or replace an
ImportReceipt. All execution, Core/scientific and Stage2 flags remain false.

Author-created offline fixtures exercise real intake, Core ledger operations,
checkpoint, offer, package, context capture and readback for distinct inputs.
The two-topic fixture authors query/source observations directly into Core and
parses different local source bodies. A separate query-owned fixture exercises
the existing authorization, reservation, bootstrap, query/import/extraction and
saved delivery controller with a local authored child, without network calls.
These are implementation evidence; they are not new-topic research success or a
second physical computer. Main Wiki browser behavior and actual consumer import
retain their respective owners and acceptance records.
