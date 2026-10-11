# Stage1 source frontier refusal — engineering evidence

The current query owner now explicitly refuses unfinished source events instead of reading a missing `operation` field. This is a pending-write guard, not source acquisition or permission to resume a source. The ordinary unexecuted search and completed source history remain supported.

- saved-mutations15: 15/15 pass, 41.084s. Real Core/SQLite/fresh raw loader; external backend/probe mocked. Includes existing pending source, owner reopen, no additional dispatch and unchanged saved history.
- related38: 38/38 pass, 86.137s, separate invocation. Existing query core/safety/storage/strict contract scenarios. No combined53 or full-plugin claim.
- red-keyerror: one actual ERROR, missing `operation`; raw log and source inventory retained.
- red-fixture-no-extract and red-fixture-parent: initial test construction errors, not production failures; kept separately.
- Local evidence packaging also previously failed a Git diff check due to CRLF under `-text`; only authored text was normalized and one raw receipt received a path-specific CR-at-EOL attribute. Original raw receipt bytes were retained. This was not a test assertion or research failure.

No actual search/source/native/model/scoring was executed. Scientific improvement and full Stage1 acceptance remain pending. The search-bridge packet retains its own earlier source hashes and invocations; this follow-up does not reattribute its45-test batch to changed planned_queries bytes.
