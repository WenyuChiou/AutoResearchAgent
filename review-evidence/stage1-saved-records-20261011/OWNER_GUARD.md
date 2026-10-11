# Saved Stage1 owner/frontier precommit correction

This increment updates the same #271 candidate; it creates no new PR and does
not merge main. The original evidence in this directory remains unchanged.

## Observed failure and correction

The two pre-fix real SQLite cases reproduce an unsafe boundary: after local
source-registration work or the delivery offer's saved SQL writes, the injected
owner/frontier became invalid. A context-exit check raised only after commit, so
the original action still claimed saved. Raw before receipts and logs preserve
both actual failures (`saved` instead of `execution-unknown`).

The three-argument mutation guard now yields None or a zero-argument check
callback. None preserves the original offline seam. Other yielded values reject
before intent admission. A callback raises on owner/frontier refusal and composes
with current Core state; records also recheck their checkpoint. Source/reading
registrations pass the composed check into the existing intake transaction.
Records pass it through the separate delivery-offer registration, whose optional
trusted callback is callable-or-None and preserves default old callers.

The shared work transaction checks before work, after work and finally after
saved state/event and action SQL writes, immediately before commit. Refusal at
that final check rolls back registry/offer publication while retaining the
durable intent as execution-unknown. File publication remains a separate effect:
an already-published records file remains observed, not silently adopted or
overwritten on true SQLite reopen. The earlier pre-admission check is retained.
This reuses `_perform`; no Core/frozen scoring or source semantics changed.

## Actual verification

| Run | Result | Test time | Inventory |
| --- | --- | --- | --- |
| Pre-fix proof | 2 tests, 2 failures | 8.954s | Unchanged |
| Final focused | 16 producer + 5 map, all 21 passed | 127.672s | Unchanged |
| Related shared/default path | 21 intake + 9 HTTP host + 1 delivery, all 31 passed | 19.389s | Unchanged |

The focused regressions cover invalid/closing guard before admission, owner loss
after source and reading local work, owner loss after source saved SQL, records
publication failure evidence, and offer rollback after saved SQL plus actual
SQLite reopen without another file write. Existing package/hash/Unknown/failure
history cases remain in the same run. The related batch validates default
callbacks, shared intake deadlines/idempotence, local HTTP host behavior and
default delivery same-key replay. These are two separate passing batches; no
single combined suite or complete plugin/CI pass is claimed. Ruff check/format
and Git diff checks passed before the frozen captures.

The read-only reviewer identified the need for a true post-SQL precommit check;
its final independent review result is reported separately. These checks do not
grant execution, authenticate model reading or demonstrate scientific quality.
No actual external acquisition/search, Codex/model/native call, scoring or live
research occurred. The production host must supply a trusted serialized owner
guard and enforce the permitted frontier; nullcontext is only an offline seam.
Filesystem and SQLite are not one distributed transaction; observed partial or
orphan files and unknown attempts remain retained. Source/model workers and
Stage1 research acceptance still require their separate authorized integration.

`owner-guard-manifest.json` binds all six changed source/contract paths and raw
before/after/shared receipts. JSON/logs are untouched captured bytes, including
original local absolute paths and CRLF. This document and manifest are LF. No
papers, full research content, SQLite, account credentials or real model replies
are published. Final integrated candidate heads and CI must be bound separately.
