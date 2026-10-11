# Native-candidate screening integration evidence

This is the normally merged existing #295 candidate, not a new PR or main merge.
Both the query-execution descriptor and read-only screening descriptor are kept;
all original native/runtime/source guards, v6 assets and frozen rules remain.

The trusted saved-frontier entry now refuses an outer closing or replaced bridge
before reading its inner owner. Two new tests compose actual Core/SQLite/library
services and cover outer/inner shutdown, a real replacement, the released SQLite
owner transaction and no automatic owner restore. `owner2.log` is their exact
actual PASS output: 2 tests/15.067s/zero skips, unchanged captured inventory.

The broader actual run `related40-failed.log` remains **FAILED**: 40 tests/144.682s,
zero skips, 39 individual cases passed and the one registry uniqueness assertion
failed (33 combined capability entries versus 32 unique IDs). Initial conflict
resolution incorrectly concatenated differently extended versions of one
capability. The correction joins them by capability_id, preserves both mechanism
increments and all test references and changes no production Python/web bytes.
`map5-fixed.log` is the separate actual correction verification:5/0.020s/zero skips
PASS. This does not relabel the original whole run as PASS or claim a final full
plugin suite. An intermediate conservative merge-script assertion refused to
write before the successful map correction; it is not a production test failure.

`browser17.json` is the unchanged installed Chrome155 receipt over this resolved
native candidate:17/17 PASS, zero page errors, empty fixture stderr/cleanup and
fixture exit0. Expected response-loss/refusal diagnostics remain present. Its
captured Python/JS/CSS/HTML and script hashes match the final production bytes.
It verifies the authored25-paper portal fixture and project/history/three-language
interaction. It does not exercise an authenticated Codex process, native research
or actual external query/source/model/score. Parent screening32/browser17 receipts
stay bound to their original parent bytes.

Each companion JSON retains the original command, actual exit/counts/time/log
hashes and selected captured sources; the complete original raw receipts remain
immutable privately. `manifest.json` binds these raw evidence files and records
final selected source pins separately. This README is explanatory and excluded
from that immutable manifest. Final exact-head hosted CI and Core acceptance are
pending. Source acquisition, typed model reading and full Stage1 coverage/quality
acceptance are incomplete; Stage2 deferred, Stage3–6 planned/unconnected.
