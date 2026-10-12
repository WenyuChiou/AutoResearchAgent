# Two current adapter review repairs

This fixes PR271 comments4242990258 and4242990261 on source195feb09/current
parentd155e288. It updates the same consolidated candidate; no new PR, main
merge, approval or conversation resolution.

Valid canonical1.2 cold-start libraries with no screening decisions now export
the empty legacy Screening CSV/XLSX sheet using its existing eight columns.
The full package/validator/Atlas regression retains both unread works, raw
artifacts, Unknown fields, zero decisions and no completion/execution grant.
Actual focused run:7 tests/39.549s/0skip PASS. The original KeyError and initial
authored-fixture input failure remain separately published.

The receipt-fed Stage2 pipeline now refuses the complete assembled prompt above
10,000 UTF8 bytes before saving a task/intent or dispatching. This conservative
model-independent bound includes sources, retained replies, schema and repair
text. It preserves original artifacts and refuses cached oversized intents on
reopen; it never silently truncates. Actual production-policy checks cover the
8MiB input,262144-byte reply/repair, Unicode exact/over boundary, aggregate
sources and later phases, with unchanged files/history and no dispatch.

Final focused run:19 tests/10.027s/0skip PASS:10 actual production-policy cases
and9 historical phase/isolation/reopen semantics under an explicit test-only
16KiB override. Those9 are not production-context readiness. The original
normal extraction/final-extraction fixture exceeds the actual conservative
bound and remains refused/pending; Stage2 is not declared complete. Its first
test-seeding KeyErrors remain published as failures. No new tokenizer,
compression protocol, model, search, native research or full local suite.

Manifest source/log hashes bind these checks. Published logs only normalize
CRLF to LF, retaining the original hash. Existing Core source/identity rules,
frozen schemas/rubrics and score denominators stay unchanged. The user's
three-candidate consolidation direction is retained; later repairs remain in
the existing PR. Final hosted CI and Core acceptance are separate gates.
