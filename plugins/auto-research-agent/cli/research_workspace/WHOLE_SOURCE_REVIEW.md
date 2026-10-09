# Whole saved PDF source review

This carrier accepts a reviewed source reading. It keeps automatic parser
diagnostics and the separate engineering-only `body_review` scope unchanged.
It does not qualify formal admission, claims, need coverage or Stage2 import.

Attach a canonical `Stage1WholeSourceReview` manifest and canonical acceptance
with the CLI's `--expected-whole-source-review-acceptance-sha256` flag. The
caller supplies the acceptance root; artifact presence alone is insufficient.
Reviewer provenance is recorded; no authenticated human identity is asserted.

The source must already have full-text status, consistent/verified identity,
an untruncated saved acquisition, and complete nonblank PDF page extents.
Missing/omitted pages, incomplete extent proof and actual source truncation
cannot be cleared. Work/version/source, attempt, raw, text and the entire
original reading are exact bindings. All review, renderer and page artifacts
are preserved in the source inventory and rechecked at attachment.

Two representations are explicit. `extracted-text` requires confirmed text
fidelity and order for every page. `rendered-raw-with-extracted-text` requires
complete raw-page rendering reproduction and an accepted reading of every
source page. The latter can retain a failed/partial extracted-text status,
with page-specific limitations. It does not certify the extracted text as
faithful. Unresolved source-reading defects prevent acceptance. Damaged glyphs,
unreadable formula structure and graphic-only values remain disclosed Unknown
unless independently supported; this review creates no claim support.

Each page carries exact source-text extents and slice SHA, rendered-page path
and SHA, affirmative source body/order/fidelity verdicts, and evidence refs.
The render proof covers exactly the same ordered page set and raw SHA, binds
renderer program/runtime artifacts, and records actual reproduction results.
Acceptance requires a complete manifest, no unresolved material source defects,
and explicit admission/claim/import/execution/identity fences.

Selection exposes the original automatic assessment, accepted representation,
acceptance SHA, manifest and page limitations, per-page extracted fidelity/order
statuses and review reference separately. Original pending
flags are never rewritten. Old workspaces without this carrier retain rule
version1.1.0 and original behavior; a reviewed selection uses rule version1.2.0.

Excel lists page checks in `SourceReviewPages`. Bindings exceeding its cell
limit point to the complete, SHA-bound `literature/selection.json`; the JSON
and CSV retain every binding. Other oversized cells still fail validation.
