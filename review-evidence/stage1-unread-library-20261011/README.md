# Complete saved screening library in canonical Stage1 delivery

Existing candidate B/#271 is extended with output-only canonical 1.2. The
existing fully-read 1.0/1.1 path remains unchanged. Discovery-only candidates
retain exact saved metadata, decisions or not-screened state, query positions,
first discovery order, repeats, source attempts, reversals and the complete
raw Core journal. They have Unknown findings and no invented source/claim.
Core candidate/schema/rubric/coverage rules and the v6 renderer are unchanged.

The independent package validator binds DOI/venue and every raw artifact,
checks journal hash/sequence/chain/typed events, and rejects linked omissions.
Typed DecisionEvent authorization null is masked only in a validated scan
copy; original input/journal/snapshots stay byte-identical. Arbitrary source
null, strings and actual credentials remain rejected.

The Index, generated reports and per-work Wiki notes expose the same saved
library. The v6 graph discovery-count presenter is still a separate follow-up.
The new-format Stage2 consumer remains explicitly unconnected. This does not
claim real research, own-account Codex, native execution or scientific gain.

## Actual narrow checks and retained failures

- run-1: FAILED4 /15.198s: three passed; the mixed package hit the existing
  credential scanner's false positive on typed Core authorization:null.
- run-2: FAILED2 /18.202s: typed-null/journal/history/DOI/venue regression passed;
  mixed package later hit Windows long-path output in the test fixture.
- run-3: PASS1 /22.472s /0skip: the mixed package, Atlas and Wiki selector after
  using the existing extended-path output helper. Production sources unchanged
  after run-2; only the test output handle changed. This is not one combined
  final suite. Map5 /0.015s, Ruff format/check and diff check passed separately.

No full rerun, native/model/search/source acquisition or Stage2 execution.
Source hashes and original commands/results are in source-and-results.json.
Failures are retained and are not relabeled as passing. The native producer
integration is verified and delivered separately in existing candidate C/#295.
