# Receive a direct-request Stage 2 delivery in ProjectHost

This trusted local import receives an existing sealed Stage 2 package whose
`Stage2DirectRequestOrigin` explicitly has `stage1_lineage=false`. It preserves
the request, sources, candidate versions, review comments and unknowns. It does
not create Stage 1 lineage, rerun research, evaluate it, or authorize experiments.

Use `ProjectStage2Service.import_direct_request_project(credential, **entry)`
or the official ProjectHost CLI flags `--stage2-direct-import-config PATH` and
`--stage2-direct-import-sha256 SHA256` together. The private configuration is
`ProjectStage2DirectImportConfiguration` version `1.0.0`, with a nonempty
`entries` list. Each entry contains exactly:

- `delivery_dir`: the sealed ordinary delivery outside Git.
- `expected_manifest_sha256`: its independently retained canonical manifest hash.
- `expected_request_sha256`: the externally retained original UTF-8 request hash.
- `project_id` and `input_version`: the trusted receiving catalog identity/version.

Catalog identity describes this receiving project; it does not rewrite the
original research packet. Keep all configuration, source text and credentials
outside Git. Browser input cannot supply these paths, import a package, change
model settings, or create a research grant. Use one current version per project
in the configuration; duplicate project IDs and overlapping selection bindings
are rejected before allocating the listener.

The importer validates the complete package and its registered workflow, retains
private byte-identical workflow files, then commits a distinct receiving event.
Repeating the same import reuses that project/event. Prefix-verified private
staging resumes after a write interruption and publishes final files only after
verification. A completed private copy is reused after an interrupted catalog
commit. Changed staging prefixes or final bytes are retained and refused.
Original research and failures remain unchanged.

The existing six-stage project page links Stage 2 to
`/project-stage2-selection.html#<project_ref>`. Read directions and materials
there. Zero recommendations remain readable and have no selectable direction.
An actual current eligible UI choice uses the existing human-submission,
workflow-frontier and Stage 3 intake validators. Selection does not authorize
experiments; `execution_authorized=false` remains mandatory.

The original Stage 1 import remains a separate verified path. The direct receiving
context cannot compile a Stage 1 plan or resume a research controller. Stage 3
planning uses its separately pinned trusted host configuration and original
planning intent; the import does not create either authority.
