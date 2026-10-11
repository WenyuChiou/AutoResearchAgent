# Saved-source evidence review

Same candidate #295; parent `3e4b4c08cba180a749429dc6d3e086d413552dfe`, retained B dependency `c71974e43c02de453cff9ebf9f03cb53aa629845`. No new PR or merge. This fixes the prior model-draft-only claim entry gap; Core identity and coverage rules are unchanged.

## Behavior and repair

Open a paper in the project literature library, choose **Review evidence in saved source text**, select an exact passage and explicitly review one claim, location, relation and evidence level. The source remains verbatim. English, Simplified Chinese and Traditional Chinese controls are present. The panel starts hidden and opens only on request.

`project_saved_claims.py` reuses saved source verification and Core `ClaimEvidence`. The server resolves the source registry/text reference and binds work/version/input/brief/frontier/hash; browser input contains opaque offers and exact UTF8 spans, never paths or owner/permit. Bounded pages reach text beyond a model excerpt. Five distinct primary-text claim IDs remain necessary for identity review; saving evidence does not semantically verify identity, accept coverage, complete Stage1 or unlock Stage2.

Manual and model-draft claims share the existing durable `stage1-claim` action kind. Exact-key replay reads saved history; changed payload, stale binding and invalid spans are refused. A real append followed by failure remains execution-unknown after SQLite reopen, blocks new writes and never re-appends on replay. The old draft receipt scan now tolerates manual receipts without losing its original duplicate guards. Strict HTTP refusal envelopes cover both variants.

## Checks actually run

- Initial new-source tests: **FAILED 7 / 70.330s**, six passed and one HTTP fixture error (`http` helper shadowed the module). The six passing cases include unchanged-Core identity review with five distinct claims, unchanged old event prefix, replay/new-key duplicate refusal, pre-intent source/span rejection, actual SQLite reopen after an uncertain append, late multibyte pages and compatibility with draft claims.
- HTTP repair v1/v2: retained **FAILED** runs for incorrect test assertions (foreign credential is 401; durable refusal is known-unsent). Final repaired selector: **PASS 1 / 8.837s**, actual temporary HTTP GET/auth/refusal/write/replay. No combined seven-test PASS claim.
- Existing model-reading regression: **PASS 5 / 52.892s**.
- Related claims/host/map run: **FAILED 22 / 84.165s**, 21 passed and one negative host assertion expected only the older diagnostic. The already-existing expansion guard rejected the untrusted owner before the saved-record guard; production rejection was not weakened. Corrected exact guard/asset selectors: **PASS 2 / 1.145s**; factory is still never called for an invalid owner.
- Final capability map: **PASS 5 / 0.018s**. PR validator regression: **PASS 58 / 2.817s**. Scoped Ruff check/format, Node syntax and Git diff check passed separately.
- Installed Chrome with actual temporary HTTP/SQLite/Harness Core: **PASS 5 checks**, one submitted claim POST, Core claims 2 to 3, zero page errors, empty fixture stderr and exit0. See [receipt](receipt.json), [English](en.png), [简体](zh-Hans.png), [繁體](zh-Hant.png), [after recovery](after-recovery.png). This includes actual trilingual passive GETs; an explicitly authored production-widget CRLF/Chinese/emoji seam; close during delayed GET; failed-page history retention; double-click and response-loss recovery through the real UI. The correct session-storage key is asserted nonempty before refresh and empty after history recovery.

Original browser observations remain in [history](historical-browser-observations.json). The first four-check PASS used a wrong-storage-key assertion and cannot prove local intent clearance. The second fixes that assertion; the third adds close/paging checks but predates the final host binding flag/format. Only the final receipt above binds the published production bytes. Expected model/Stage2-unconnected HTTP409 and deliberate response-loss diagnostics are preserved; no empty-console claim.

[Source inventory](source-inventory.json) binds 15 code/test/map/document paths; physical and staged Git bytes match. The final browser receipt verifies its loaded source/web hashes against these actual working files. [Publication manifest](publication-manifest.json) identifies raw copies and the sole receipt transformation: checkout-absolute source keys to repository-relative keys, with hash values preserved. Private raw hashes are declarations, not proof Core inspected private data.

## Reproduce and limits

Use existing Python/Node/Playwright and installed Chrome; no installation is performed. Run `python -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_project_saved_claims.py -v`. For the browser, set `PLAYWRIGHT_MODULE` to the existing Playwright module and `CHROME_PATH` to the installed executable, then `node plugins/auto-research-agent/tests/browser/project-saved-claim-live.cjs <python> <fresh-absolute-private-output>`. The fixture uses stdin DEVNULL, file-stop and a 180-second lease; old output directories fail rather than overwrite receipts.

Sources are authored fixtures and the preloaded draft uses one synthetic provider unit. No new actual source acquisition, search, native/model research or scoring runs here. This demonstrates a saved-source human-review handoff and failure recovery, not full own-account Stage1 execution or semantic/scientific acceptance. Core ordered/current-main admission, complete Stage1 coverage/repair/stop/acceptance, held native cleanup and private package050 receipt remain pending. Canonical Stage2 execution is deferred; Stage3–6 planned/unconnected. No full suite is claimed for this increment; hosted CI must be observed for its new exact head.
