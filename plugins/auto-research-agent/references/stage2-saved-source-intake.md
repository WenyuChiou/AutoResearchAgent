# Import an accepted saved-source handoff into the existing Stage 2 workflow

The host operator can register an accepted `Stage1Handoff` 2.0.0, import its
canonical 1.0.0 records, read back the saved packet and initialize the existing
workflow. Initialization creates no research direction or human selection and
does not run a model, search, acquisition or later stage. A material registration
ID is not a CLI import prerequisite. Canonical records 1.1/1.2 still need their
separate consumer implementation; this adapter does not silently downgrade them.
Saved snapshot, replay and handoff input versions accept the existing nonempty
string IDs or the native project's positive integers. They retain their exact
type: integer `1` and string `"1"` are different versions, with no coercion.

## Complete the same-version evidence first

The producer must finish its review, required CI and sealed delivery. Consumers
retain `WAIT_UPSTREAM` while that version is building or its state is unknown.
Source-only delivery and engineering approval do not establish content or HTML
acceptance. Preserve frozen deliveries and earlier failed observations.

For saved-v2, provide the original snapshot, unchanged source/view/brief/resource
bytes, four independent Core review categories and an actual seven-action HTML
receipt. The existing `inspect_saved_admission` validator must recompute an
eligible handoff from the external Core aggregate hash. A manually edited
eligible flag, author report or old receipt with substituted hashes is rejected.
The seven HTML actions are first load, paper detail, graph selection, full note,
BibTeX download, refresh and keyboard operation. Use their real tool references,
start/end times with time zones and private evidence. The expected HTML is the
snapshot's producer HTML. Acceptance of another consumer page requires a
separately reviewed derived-page contract; replacing the expected hash does not
provide one.

Host relocation additionally requires all four host-owned replay inputs:

- The `HostReplayReceipt` file and its independently trusted external SHA-256.
- The historical exporter's source directory.
- The actual replayer's source directory.

These four values are all-or-none. The receipt binds the exact snapshot and
canonical manifest, every source archive, historical and actual replay results,
interpreter/dependency bytes and the complete current CLI/schema inventory. A
changed validator requires a current binding; an earlier technical replay never
becomes Core acceptance. Existing replay observations may be retained only when
the operator independently verifies their unchanged exporter, runtime and input
scope. Rebinding current validator bytes is not another source execution.
Evidence directories are data, never imported as Python code. Browsers cannot
choose physical paths, trust roots or bootstrap inputs.

## CLI: import, initialize, then inspect

The names below refer to real externally fixed host inputs. Keep these private;
do not derive trusted hashes from browser requests or an untrusted sidecar.

```powershell
python -B -X utf8 -m stage2_workflow import-stage1 `
  --deliverable $deliverable `
  --deliverable-manifest-sha256 $manifestSha `
  --handoff $handoff --handoff-sha256 $handoffSha `
  --brief $brief --resources $resourceEnvelope --output $newSeed `
  --saved-source-root $evidenceRoot `
  --saved-source-acceptance-sha256 $trustedCoreAggregateSha `
  --host-replay-receipt $hostReplay `
  --trusted-host-replay-sha256 $trustedHostReplaySha `
  --historical-exporter-root $historicalExporter `
  --replayer-exporter-root $actualReplayer
```

Retain the actual JSON stdout as the import receipt. Read the emitted
`packet.json`, verify its hash against the receipt, inspect every projected
source and full-note hash, and retain the cumulative resources and Unknown claim
relations. Use a new output directory; existing or partial output is not replaced.
The importer uses one verified replay context for admission, initial package
validation, source projection and final package revalidation. Changes during
projection reject the operation. Failure cleans only the seed directory owned by
that import; it does not alter source evidence or release resource reservations.

```powershell
python -B -X utf8 -m stage2_workflow init `
  --packet $packet --source-root $newSeed --output $newWorkflow `
  --settings $originalSettings --policy-ref $originalPolicyRef `
  --expected-packet-sha256 $actualImportedPacketSha
python -B -X utf8 -m stage2_workflow inspect `
  --run $newWorkflow --expected-head $actualInitializedHeadSha
```

Save actual outputs and verify the packet hash, workflow manifest and event head
on a new read. Keep the original confirmed brief, policy, resource limits,
cumulative usage and held reservations. The initialized packet has no candidates;
research execution remains unauthorized and not started. Import or initialization
does not finish Stage 1 scientific review or the whole user request.

## Existing project service: trusted registration, opaque activation, reopen

The trusted operator supplies the same six optional saved-source/replay arguments
to `ProjectStage2Service.register`. It uses the original `ProjectIntakeService`
project, confirmed input version, brief bytes, compiled plan, settings and resource
envelope. A saved snapshot from a different project/input is refused; do not
create substitute identities or approvals to make it fit.

The public offer includes only independent acceptance/replay hashes. Its offer
hash binds those pins along with the existing brief, plan, manifest, handoff,
settings and resource hashes. Private paths stay in host-owned inputs. An explicit
activation submits the existing opaque offer reference/hash, revision and original
idempotency key; browser-provided trust or physical-path fields are rejected.

Activation replays admission, calls the same importer and `initialize_workflow`,
and retains the actual v2 import receipt in the existing action/artifact journal.
`read`, `action` and `history` expose that saved result. Trusted `binding` reopens
the workflow frontier and checks admission, pinned offer, packet and every full
note again. A changed note or acceptance pin refuses reuse. Same-key recovery
returns the recorded action without another import or workflow. Preserve
interrupted output and unknown intents for reconciliation; never retry them under
a new key just to obtain a successful result.

Legacy handoff-v1 inputs retain their existing offer and result shape. Saved-v2
does not add a new engine, native launcher, credential source, human decision or
scientific evaluation.
