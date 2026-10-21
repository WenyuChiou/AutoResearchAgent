# Retrieval trace producer and UI handoff

Scope: Issue #355, request S1-UI-TRACE-20261021.1. This is an implementation-only
export increment on prerequisite PR #365. A source-tested producer release and
actual UI acceptance are separate records. Core owns review and merge.

## Exact interface

Read `workspace/literature/academic_screening.json.rows[].retrieval_trace` and
join by project/input/package pin and the current work/version pair. The trace
identity scope is explicitly work-all-recorded-versions; its first discovery
may refer to another recorded version and must not be relabelled current-only.
The rest of the 1.1.3 rationale, claims, counts and source paths keep their
meaning. 30 saved works and 180 observations retain different denominators.
The new package version is 1.1.4; readmodel and delivery-review versions are 1.4.

Canonical bound-run mode reports the actual first discovery and its round,
plus four separately named counts. A work's query history includes only queries
that returned it, including those queries' failed attempts. Do not label a
query/backend/discovery count as searches until found.

Legacy mode reports saved appearances, distinct saved batches and first batch
by inventory order only. Missing records use null/not-recorded and specific
unknown reasons. Batch identifiers are not research-round identifiers. Include
mappings are bound to saved work/version; duplicate mappings follow identical
URL references to the include anchor. Historical edition authentication stays
unknown. All pointers resolve inside the independently pinned index.

## User-requested consumer behavior and acceptance

- Hide old D62 history from the default detail, retain immutable originals and
  complete audit exports. Never remove an unresolved current-review limitation.
- Make screening rationale a keyboard-operable collapsible section. The compact
  summary retains the disposition and meaningful first sentence; expansion
  reveals full needs, roles, limitations and source evidence without clipping.
- Show real first-round information only in bound-run mode. In legacy mode say
  saved appearances/batches, with exact missing-history reasons.
- Determine whether the animated graph keyboard timeout came from the locator
  or actual focus/activation. Record real Chrome focus plus Enter/Space operation
  and selected work/detail agreement. Mouse or stable-list success cannot stand
  in for graph keyboard success. Fix the actual defect and return evidence.
- Return the exact frozen consumer identity, manifest, source hashes, actual
  page/API/export results and failures. New producer and consumer revisions
  require their own completed checks; do not consume an in-progress candidate.

No private research content belongs in this GitHub record. No material ID,
receipt, browser pass, Core approval, formal Stage1 completion or Stage2 authority
is created by this document. UI service/source operations remain UI-owned.
