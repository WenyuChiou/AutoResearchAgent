# Current admission of saved Stage 1 sources

This opt-in implementation uses `SavedSourceCandidateSnapshot`1.0 and
`Stage1Handoff`2.0. Legacy CandidateRevision, discovery events, handoff1.0,
coverage stopping, and Stage2Packet2.0 retain their original contracts.

The snapshot records a new admission time and the actual saved-source mode.
Each row binds the saved acquisition provenance and its original acquisition time;
an unknown original time remains null, separately from the current admission time.
Its historical discovery events are null and its historical trace is missing.
It cannot claim a completed search, a zero-yield round, HTTP200, saturation or
`stop-sufficient`. Original request, brief, cumulative resource record, package,
view and notes retain separately bound artifact bytes outside Git.

`python -m research_workspace.saved_admission EVIDENCE_ROOT --snapshot-ref REF`
replays the existing source/view qualification and need coverage, the complete
deliverable validator, source identities and full notes. A ref is exactly
`{path, sha256, bytes}`, with a contained portable relative path.
Without external acceptance, it emits a blocked handoff candidate and five
outstanding checks. It never marks Stage1 completed.

`--acceptance-ref REF --trusted-acceptance-sha256 HASH` explicitly supplies the
independently accepted Core artifact. Core must bind this snapshot and contract,
the delivered producer bytes and successful required CI, plus separate brief
lineage, deliverable semantics, coverage/claim review and handoff-contract evidence.
Each category binds project/input, validator/rubric bytes and located check results
within the saved-source admission scope. Required CI names follow the existing
four PR jobs at the reviewed head and three post-main OS jobs at the delivered
two-parent merge. Merge parents/tree and phase-specific heads remain bound;
the PR-only job is not required on a push event. Unrelated successes do not count.
The receipt must also bind all seven actual HTML actions, their native action
references, timestamps and retained evidence, the exact HTML version and the
downloaded selected bibliography. Static HTML inspection cannot replace this.
These are externally accepted observations, not authentication supplied by hashes;
never create these receipts merely to make the validator pass.

The dependent Stage2 importer slice adds the opt-in handoff2.0 receiver.
It must pass its separate Stage2 v2 contract before official positive import.

Synthetic tests exercise rejection and binding mechanics. They establish neither
real Core acceptance, browser operation, scientific sufficiency nor improvement.
Complete rehearsal still requires actual HTML, positive import and the continuous
saved-source workflow to pass. Unknown claims and previous failures stay visible.
