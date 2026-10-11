# Source status / reading prompt boundary

Existing candidate #295 only; no new PR or merge. Parent 2f63fbfcfdbcd86c9c1207ece8e04d83b66579ce. Actual base c71974e43c02de453cff9ebf9f03cb53aa629845 is retained.

The source API already emits followup; renderSources incorrectly read processing and hid parser/Core registration failures. The corrected UI separates historical transport and followup status, preserves error code or error type, and does not treat the source job's old reading_complete=false as current reading status. Missing followup stays Unknown. Rendering cannot dispatch or grant execution.

Saved reading allows a 48,000-byte snapshot but the complete prompt must fit 32,768 bytes. Preview previously advertised availability before checking that prompt. Authorization wrote immutable permit bytes before building the prompt/offer. The corrected preview validates the same prompt; authorization performs deterministic prompt/offer validation and offer-count checks before creating the permit. Existing source verification, exact quotes, size limits and budgets are unchanged. No truncation or segmentation is fabricated.

## Checks and evidence scope

- Initial targeted run: 9 tests / 19.829 seconds, 8 passed and 1 error; the raw result remains FAILED. The new regression initially used an unfunded fixture and hit model-zero-budget. The test was given an authored offline budget, and its first failed authorization is inspected through SessionApiError.receipt.
- Final repaired selectors: 2 tests / 5.386 seconds, 0 skips, PASS. Oversize input is authored at the saved-snapshot seam with three individually legal 11,400-byte excerpts; pure prompt validation and real SQLite/history are exercised. This is not an actual source-registry assembly or native/model run. No permit/offer/model dispatch/Core write occurs; failed history and same-key replay are retained.
- The normal saved-source synthetic reader path and original deadline guard passed in the initial run; their source is unchanged. This does not turn that initial full run into PASS.
- Separate map check: 5 tests / 0.019 seconds, PASS. Applicable unchanged binding/transport/content invariant evidence from the predecessor is reused, not rerun.
- Final installed Chrome 155.0.8059.39: 36 source-status renders, three languages and repeated history rendering, zero page/console errors. Actual public serializer and actual renderSources/text functions run over authored observations on a temporary HTTP page. This is not the complete project page, authentication, current API/SQLite/browser E2E, live acquisition or own-account Codex execution.
- Narrow Ruff format/check, Node syntax and Git whitespace checks pass.

Publication logs normalize LF/trailing ASCII whitespace only; publication-manifest.json preserves original private hashes and exact transformation. Original failed logs/receipts remain immutable. Source inventories bind the tested implementation and browser receipt to exact bytes. No new full suite, live model, search, acquisition, scoring or research execution occurred.

Remaining: complete real own-account Stage1 coverage/repair/stop/acceptance, current source/reading integration, canonical 1.1/1.2 Stage2 consumer/execution, held cleanup, Core ordered integration/admission and unreceived package050. Stage3–6 remain planned/unconnected. Registration/drafts/tests/CI do not establish scientific acceptance.
