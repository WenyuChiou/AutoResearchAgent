# Explicit saved-draft claim review: bounded UI evidence

This package retains the observed failures, focused implementation checks and one local HTTP browser save. It belongs to the existing integration worktree; no new model, native, search, source-acquisition call or scientific scoring was performed while packaging. Stage1 completion and scientific improvement are not claimed. The canonical format is being repaired independently.

| Original run | Observed outcome | Public evidence |
| --- | --- | --- |
| Existing saved-reading unit v1 | 4 tests, 24.712s; 1 failure and 4 errors. The saved context returned six items while the reading snapshot expected at least seven. | Unchanged raw existing-v1 log |
| Existing saved-reading unit v2 | 4 tests, 47.785s, OK after the context adapter fix | Unchanged raw existing-v2 log |
| UI Node v1 | PASS for explicit defaults, exact quotes, Unicode/UTF-8 limits, held/busy, stale version/language and response bounds; actual submitter mock also checks A pending / B loading / A saved | Unchanged raw ui-v1 log |
| Browser v1 | Failed before Host startup: fixture credential rejected by the original token syntax check | Original raw hash and exact failure message in browser-v1.json |
| Browser v2 | Fixture stopped on stdin EOF before a claim save; baseline 2, final 2; no saved stage1-claim action | Original raw hash, observed source pins and bounded excerpt in browser-v2.json |
| Browser v3 | One actual local POST saved a stage1-claim; baseline 2, final 3; reading GET inspected in English, Simplified Chinese and Traditional Chinese | Original raw hash/pins and exact saved action in browser-v3.json; screenshots |

The v3 original history records status saved for claim event e000047 and its source-bound quote, locator and text hash. It explicitly records stage1_complete=false, scientific_acceptance=false and reading_registration_complete=false. Saving that claim is distinct from accepting coverage, registering complete reading or delivering Stage1.

The fixture uses the real local ProjectHost, HTTP, SQLite and Core claim writer with authored saved-source text and a synthetic draft. Its already composed claim service is injected only by the test fixture. This does not attest production boot composition or full native execution. One synthetic provider unit is reported; actual model/native/search/source-acquisition calls are all zero. Fixture TTL is 180 seconds and the root operator observed exit0.

The root operator observed IAB viewport 1265×713. Original screenshot bytes are 1265×712 JPEGs under their original .png filenames; they are copied unchanged. The screenshots show the Traditional Chinese quote review panel, exact source/text hash/UTF-8 range and the explicit Unknown / not-delivered boundary.

Supplied fixture JSON logs do not independently record HTTP request counts, language switching, EOF cause or process exit status. Those observations are labeled root_operator_observed in browser-observations.json; the claim count, saved action and zero actual calls are directly excerpted from the original logs. Both v2 and v3 preserve start and stop source inventories. V3 has 167 start pins and 168 stop pins: project_stage1_coverage.py was lazily added, and all common pins retain their original hashes. These are observed source bytes, not hashes recomputed after later backend edits.

The three public unit/Node logs are byte-for-byte copies, including their execution paths. Browser raw logs remain private because they contain local absolute paths; public extracts retain their SHA-256, convert executed_sources to repository-relative paths and omit unrelated history. No token is published. manifest.json hashes the payload artifacts and README; artifacts.sha256 also hashes the manifest and excludes only itself. Packaging verifies originals were unchanged and does not rerun tests or browsers.
