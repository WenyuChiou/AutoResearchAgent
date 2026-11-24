
## Source provenance

Completion stdout, stderr and records must come from that attempt. Equal bytes
share a content-addressed file, but each producer has its own ArtifactStored
receipt. Replay rejects borrowed receipts, including historical affected runs.

Search-record claims bind to a matching work/version discovery and the quote
must occur inside that record. A batch containing another paper is not its source.
For saved primary text, first call `start-source-import --request REQUEST.json`
with `work_id`, `version_id`, `source_uri`, `actor`, and `reason`, then `save` with
the returned event as `--producer`. This records a caller-attested offline import,
not an HTTP success or source authentication. A claim for another work or version
is rejected. Network acquisition/failure evidence belongs to a separate adapter.

## Externally provided saved candidates

When the operator already has a public material but no search candidate exists,
use `python -m stage1_ledger --run RUN admit-saved-candidate --request REQUEST.json
--source FILE`. The JSON supplies `record` (existing title/authors/year and an
explicit version), `material_sha256`, public `source_uri`, truthful
`original_type`, `actor`, `reason`, `expected_state_sha256`,
`expected_manifest_sha256` (SHA-256 of canonical manifest JSON), and the expected
`work_id`/`version_id` derived by the existing identity functions. A stale run,
wrong identity or changed file is refused before candidate registration.

This creates a `CandidateRevision` with explicit `provided` provenance and null
query/backend/completion IDs. It records the material's original type and bytes,
not a claimed HTTP acquisition or verified identity. The work remains
unverified and unscreened. Duplicate identical material reuses its original
admission; journal recovery repairs projections without inventing search events.
Existing `start-source` and saved-source readers can then use that work/version.
Older readers that do not recognize provided provenance must not consume the new
run; historical ordinary candidates keep their existing schema and replay.

For project applications, `ProjectStage1Service.admit_saved_candidate` adds the
existing authenticated project/input/revision/state and durable action-key
guards. The application owner supplies `materials_root`; the request supplies a
contained `source_relative` and matching `source_project_ref`, plus the same
record, hash, URL, type, work/version and reason. The actor comes from the
authenticated principal. This is a Core/application API, not a new Wiki HTTP
route or authorization to execute queries, screen a work or launch a model.
