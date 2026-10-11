# Saved canonical Stage 1 projection

This implementation reads an already saved bare `Stage1ResearchDeliverable`
1.0/1.1 package using its externally supplied `provenance_manifest.json` hash.
It checks the complete inventory and consumed artifact bytes and reuses the
existing WorkspaceIndex, v6 Atlas, Wiki and bibliography. Every virtual
`deliverable/...` inventory path records its physical relative path in the bare
package. Missing readiness stays missing; Core 1.1 history and nullable evidence
stay unchanged and its Stage 2 consumer stays unconnected.

The bare reader is the Python API
`research_workspace.canonical_delivery.project_canonical_delivery`. It is not
supported by the existing `python -m research_workspace` CLI, which continues to
read an outer private delivery envelope. Bare view receipts name the actual
Python reader/renderer APIs, canonical manifest filename/hash and reader source
hash. An exact assertion preserves the old outer-package CLI rebuild dictionary.

This slice creates no server mount, API, native session, search, model call,
source-runtime replay, new scientific assessment or Stage 2 permission. The
private input package is not copied, rebuilt or changed. Tests use authored
private fixtures, never research papers or frozen answers. The renderer test
writes a new test-owned presentation directory; the reader only returns data.

## Observed validation

- Seven focused reader tests passed in 14.605 seconds before the later view
  receipt correction. They are retained as historical checks, not a fresh
  seven-test result on this final source.
- Nine existing projection tests passed in 2.847 seconds before that correction.
- After the receipt correction, the affected reader/view selector and the
  existing graph-view selector passed: two tests, 0.921 seconds.
- The final map, Ruff and diff checks are recorded in `checks/` and `receipt.json`.
- No full plugin suite, browser interaction or live/native/research lane ran.

The first captured combined run failed while preparing its Core fixture:
`package.build` rejected the test environment's research-hub merge pin. The
production runtime guard was preserved. The test was corrected to author a bare
saved byte inventory directly, avoiding a package rebuild for a reader test.
Its imported TestCase alias was also fixed to avoid discovering unrelated tests.
An earlier call returned partial output and its completion was not captured; it
is explicitly unobserved. Initial Ruff diagnostics were corrected.

`captured/` preserves text from the actual tool responses, including the failure.
These are transcriptions of captured terminal text, not recovered original
process-stream files. The initial tool output was partial/truncated where noted;
uncaptured bytes, original stream hashes and original source pins remain unknown.
Final `checks/` logs were captured directly from subprocess stdout/stderr, then
normalized to LF for the public evidence. Their original stream bytes are kept
outside Git; the receipt lists raw and public hashes and the normalization.

Use `receipt.json` for exact commands, outcomes, source hashes and evidence limits.
Scientific improvement remains **not yet demonstrated**. Core review and GitHub
delivery are separate; this receipt grants no execution or merge authority.
