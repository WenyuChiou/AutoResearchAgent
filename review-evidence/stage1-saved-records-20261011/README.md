# Stage1 saved-source and manual-reading engineering evidence

This increment belongs to the existing #271 integration candidate. It adds a
trusted saved-source registry, a manual reading registry, and a bounded canonical
records producer. The original SDK source receipt stays in its declared output
directory; the producer reconciles actual Core source events, physical artifact
hashes, work/version, current screening/review, and exact UTF-8 claim spans. It
then uses the existing delivery registration/package builder. Old screening
decisions, failed sources, Unknowns, partial evidence and continue blockers remain.

## Captured runs

| Run | Result | Test time | Source inventory |
| --- | --- | --- | --- |
| Historical initial | 26 tests, 4 errors | 127.441s | Changed during execution; historical mixed-source evidence |
| Historical review | 9 tests, 1 error | 65.066s | Unchanged |
| Final | 15 tests, 0 failures/errors/skips | 67.825s | Unchanged |

The final run contains ten new regressions and five capability-map tests. It
covers two authored nonempty sources through reading/records/registration/real
canonical delivery validation; true SQLite reopen never rewrites an old action.
Additional cases cover wrong spans/hashes, source tamper, stale checkpoint,
mutation-guard refusal, preserved HTTP503 failure and screening revision, mutable
registry tamper, extra saved events, and post-publication/save failure recovery.
The final receipt driver elapsed time is 69.985s, separate from unittest time.

The initial run's authored second-source title mismatch yielded no extracted
claims. Its imported TestCase also loaded 22 existing delivery tests. Its source
inventory changed while execution was in progress, so its failures are not
attributed to the final candidate. The review run's one error was a test trying
to DELETE an immutable event while resetting an adversarial fixture. The final
regressions use separate append-only cases, preserving Core immutability. Both
original failures are retained without rewriting their raw receipts or logs.

## Independent review and fixes

A read-only independent review reproduced a registry boundary failure using
real in-memory SQLite: an extra saved event with the same reference and altered
payload could previously become the last reading despite an unchanged registry.
The final `_entries` requires a complete one-to-one state/event mapping, unique
references, the actual saved intake action receipt, and its request/digest/ref.
The reviewer independently confirmed the original single event is accepted and
both altered and identical duplicates are refused. The final append-only tests
also reject consistently rehashed state/event rows without a matching action.

The review identified a second boundary: a context failure after the final file
had been published could record a failed action without observing the output.
The final writer returns its output observation before the shared post-work
binding check. A failure now preserves execution-unknown plus intended file/hash
evidence; SQLite reopen of the same key neither republishes nor adopts the file.
That regression passed in the final run. The final static review reported no
additional blocking issue in this bounded seam. Review is not Core approval.

## Evidence boundaries and remaining work

- These are public authored engineering fixtures with mocked external HTTP/DNS,
  actual Core/SQLite/SDK parsing and offline canonical package validation. No
  actual source acquisition, external search, Codex/model/native call, scoring,
  frozen A/B or scientific acceptance occurred. No full plugin suite/CI is claimed.
- Saved reading annotations have trusted manual-saved provenance; they are not
  authenticated model-generated reading. The mutation guard is a required trusted
  context-manager injection, not a connected production query/source/model worker.
- Reusable `saved_stage1_case()` is a test context manager. The source registries
  and producer are server-only seams, not browser arbitrary-path endpoints.
- Metadata-only unattempted candidates, imported historic sources and incompatible
  ledger enums are explicit blockers. Unknown is never silently inferred away.
- Atomic publication uses an exclusive same-filesystem hard link. Unsupported
  filesystems fail closed; filesystem and SQLite are not one distributed atomic
  transaction. Partial or orphan files remain as evidence; unknown actions are not
  automatically rewritten or adopted. In a failure observation `records_sha256`
  denotes the intended complete output digest, not a captured partial-byte digest.
- Current package output preserves Stage1 incomplete/continue eligibility. New
  live reading/query/source workers, coverage/stop and researcher acceptance remain
  outstanding. This increment does not complete Stage2 or change Stage3-6 status.

`manifest.json` binds the five increment source paths and all nine raw files.
Raw receipt JSON/log bytes retain their original CRLF and absolute local paths;
README and manifest are authored LF. No papers, full research text, SQLite,
credentials or actual model replies are included. After the parent integrates
current main, it must bind final candidate hashes and necessary CI separately;
the captured pre-merge map/contract hash must not be relabeled as post-merge PASS.
