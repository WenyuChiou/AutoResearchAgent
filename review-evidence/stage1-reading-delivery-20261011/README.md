# Saved reading delivery evidence — 2026-10-11

This packet records saved Stage 1 reading-note and canonical-delivery engineering behavior. It is implementation-only. Stage 1 remains incomplete; scientific quality was not scored. No tests or browser/model/native/search calls were rerun while packaging.

## Preserved test results

- `stage1-claim-final-20261011-v1.log`: FAILED — 36 tests in 334.692s; 34 passed, one failure and one error. The origin-identity error and old once-only draft-guard assertion are retained.
- `stage1-claim-repairs-20261011-v2.log`: PASS — only those two exact selectors, 26.303s. This is not a full 36-test post-repair pass.
- Both matching JSON receipts are byte-exact originals with relative 866-path before/after inventories and unchanged-source assertions. Raw logs preserve their original command/runtime and traceback paths as diagnostic evidence; no research payload or credential files are included.
- Existing `ui-focused.log` and `ui-source-pins.json` remain byte-exact. Their Node/mock checks cover 6 classification plus 7 finding fields, raw Unknown, roles [], explicit checkbox, held/busy, Unicode, exact broker bodies, prepare guards and project-switch race handling.

## Browser v4

The actual local HTTP fixture exercised Core/SQLite with two authored saved sources and one synthetic provider unit. Actual native/model/search/acquisition calls were zero. It uses test-only Host service injection, so this is not production boot or own-account execution evidence. The fixture had a 180-second lease and the operator observed exit 0.

The raw saved history has 10 fixture-seeded rows followed by 7 newly saved rows: 6 manual UI POST submissions (reading review, checkpoint, export, prepare, deliver, second checkpoint), plus prepare's internal delivery-offer registration. The reviewed note preserved all 13 raw Unknown fields and roles []; the original 2 claims remained 2. Ordinary GET display/language changes created no additional submitted action.

The deliver action saved a canonical package as `saved-evidence-validated` with 2 papers, 2 claims and manifest SHA-256 `881365a7d77c5cc1325258d16214d9e67ead3abc544f26b5dc72aea96b9cdb6a`. The sixth manual submission intentionally created a second checkpoint (e000053 after e000052). The existing package then became `stale-input`, which the exact final JPG shows. The ledger content SHA is unchanged; checkpoint identity changed. The prior validated build remains recorded in the saved action excerpt. Neither status claims Stage 1 completeness.

`browser.json` includes allowlisted metadata, hashes, safe action excerpts, and original repo-relative browser source pins. The original full browser history remains private, identified by whole-log and final-record-line hashes; dynamic URL, materials-root bindings and source/note payloads are omitted. Two locator diagnostics (nonexistent #delivery-status and a guessed Chinese button label) caused no POST. English, Simplified and Traditional Chinese GET displays and fixture exit are operator observations, separately labeled from the raw fixture records.

The screenshot is copied byte-exact as JPG: encoded 1265×712 pixels; operator IAB viewport 1265×713. It is the final Traditional Chinese stale state, not a recapture of the earlier validated package.

## Source attribution and limits

`current-sources.json` separately captures current checkout sources at HEAD `5420dac8a08548d4decd25a444c729f265c4917f`. Original unit/browser pins are retained independently; changed bytes do not inherit earlier results. `prior-claim-review-inventory.json` hashes all existing older claim-review files, including ignored logs; older v3 claim-review evidence is not attributed to this v4 run.

New canonical-format Stage 2 consumption remains unconnected (eligible_for_stage2=false). Browser v4 does not exercise response-loss/unknown reconciliation or unread/missing reading recovery. Unknown notes, incomplete clusters, screening/identity reviews and open-round/coverage blockers remain visible in `current-scope.json`; saved evidence validation does not override them. Production native acceptance and a complete Stage 1 research result remain unproven.

`manifest.json` binds every payload file; `artifacts.sha256` additionally binds the manifest, excluding only itself. Files were created exclusively without replacing existing evidence.
