
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
