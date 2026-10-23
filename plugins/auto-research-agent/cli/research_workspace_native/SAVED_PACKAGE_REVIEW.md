# Saved Stage 1 package review

`SavedReviewService` lets a researcher read an exact saved source, save an
include/exclude/pending opinion, request a correction, and request a Stage 2
handoff. It extends `MaintenanceInbox`: all actions use its existing
`maintenance_feedback` journal, immutable requests, private SQLite file and
transactional idempotency. Only the immutable registration metadata has a new
table, `maintenance_review_bindings`. Existing maintenance feedback is unchanged.

The service creates a **new saved review context**, identified by
`saved_review_ref`. This is not an active project or a restored historical run.
Known original project/run/input values remain original; absent input versions,
run IDs, briefs or ledgers stay null with a specific reason. It does not construct
a CoverageLedger or convert batch numbers to retrieval rounds.

## Trusted registration

An operator first validates the complete delivered package using its existing
producer/consumer contract. Then the operator prepares a private registration
JSON and independently pins its **raw file SHA-256**. This service checks those
registered bytes and exact work/version/source bindings; it does not replace
whole-package validation or infer the semantic identity of a paper from a hash.

Registration fields are exact; extra fields refuse:

| Field | Content |
| --- | --- |
| `schema_version` | `SavedStage1ReviewRegistration.v1` |
| `case_ref`, `project_id` | Trusted case reference and original project identity; must match the existing inbox binding. |
| `input_version` | Original nonnegative integer (not a boolean), or nonblank string of at most 256 UTF-8 bytes, e.g. `"20261009-A03"`; null requires an unknown reason. Value and JSON type are preserved without coercion or trimming. This does not change active-project input validation. Never substitute the new review revision. |
| `run_id` | Original run ID, or null with an unknown reason. Never substitute a guessed historical run. |
| `artifacts` | Map from opaque artifact ref to `{path, sha256, bytes, kind}`. Paths are safe relative paths under the fixed private root; kind is `utf8-text` or `opaque`. |
| `pins` | Exact keys `index`, `manifest`, `view`, `brief`, `ledger`, `run_manifest`; values reference registered artifacts. The first three are required; the latter three may be null. |
| `works` | Entries `{work_ref, version_id, source_refs}` with exact trusted work/version-to-source mappings. A metadata-only source stays metadata-only; registration does not confer full-text status. |
| `unknowns` | One nonempty reason for every null input/run/pin, and no extra keys. |

There are at most 500 work/version entries, 1,024 artifacts, 32 sources per work,
32 MiB per artifact and 256 MiB total. The registration is at most 1 MiB. An
oversized input refuses explicitly. Register the reviewed source/metadata files,
not a large ZIP as a substitute for accessible exact sources. Roots and the
SQLite file must be physical private paths outside Git. Symlink/reparse and
hard-linked source files refuse; each new operation checks regular file identity,
size and SHA-256. A changed package requires a new registration/case context and
fresh review. No old opinion is silently transplanted to it.

The operator constructs `MaintenanceInbox` using the registered case's original
`project_id`, index SHA and manifest SHA, then:

```python
service = SavedReviewService(
    inbox,
    package_root=private_package_root,
    registration_path=private_registration_file,
    registration_sha256=independently_checked_raw_file_sha256,
)
```

This is a trusted local bootstrap API, **not an HTTP registration endpoint**.
The browser may not choose paths, independent pins, principal identities or
server registrations. The inbox is borrowed: the embedding owner closes it.
On reopen, exactly the same registration is required. History remains readable
when original source bytes later drift; new offers and new writes refuse.

## Embedding API

The host authenticates its own principal and authorizes access to this case
before calling any method. A `principal_ref` is that host's trusted identity;
the service does not attest that a human performed a scientific review.
HTTP wiring, bearer tokens, exact Host/Origin checks, request limits and safe
public error mapping remain the embedding UI/Core owner's responsibility.
This change does not start or change an HTTP server.

```python
target = {"work_ref": work_ref, "version_id": version_id, "source_ref": source_ref}
page = service.source(service.ref, target, offset=0, limit=4096)
offer = service.offer(principal_ref, service.ref, "submit-review", target)
body = {
    "key": client_generated_idempotency_key,
    "offer": offer,                 # Echo the complete server offer unchanged.
    "decision": "pending",         # include / exclude / pending
    "message": original_review_text,
    "confirmed": True,
}
receipt = service.submit_review(principal_ref, service.ref, body)
saved = service.action(service.ref, body["key"])
history = service.history(service.ref, after_revision=0, limit=100)
```

Source offsets and lengths count Unicode code points. The source response
contains the original text slice, its exact work/version/source hash, total
length, next offset and bound review context. It makes no model or network call.

For a correction use an offer for `request-fix` and call `request_fix`; its
target may be one source or null for the entire package. For handoff use a
`request-handoff` offer with null target and call `request_handoff`. Both use
`decision: null` and require original nonempty explanatory text. `submit` also
accepts these operation-specific offers. Messages retain whitespace and Unicode
verbatim up to 4,000 UTF-8 bytes; they are never clipped.

Every offer binds the principal, operation, current review revision, original
project/input/run, independent registration pin, source snapshot hash, package
pins and optional exact work/version/source. New writes compare the review
revision inside `BEGIN IMMEDIATE`; two tabs cannot both commit different keys
against the same revision. One committed action advances review revision once.
An unchanged key/body replays the same receipt even after source drift. Changed
payloads under the same key refuse. Lost responses recover with `action` or
`history`, without resubmitting under a new key. Reads never dispatch or retry.

An optional trusted `before_commit` callback checks the host deadline before and
after insertion. Source pins are freshly checked on both sides of insertion;
failure rolls back the row. The inherited SQLite busy timeout is five seconds,
and synchronous file reads are bounded in bytes but are not hard-timeout worker
containment. The embedding host still owns its deadline and process policy.

All receipts retain `status: recorded-not-dispatched`, original message and
decision, offer and context, request hash, saved sequence, timestamp, key,
principal and `review_revision`. They explicitly preserve:

```json
{
  "active_project_ref": null,
  "stage1_complete": false,
  "core_acceptance": false,
  "execution_authorized": false
}
```

An opinion does not rewrite the frozen package, scientific result, source status,
budget or original ledger. A correction request records work to be handled; it
does not produce a revised package. A handoff request is reviewable evidence for
Core; it does not import Stage 2, create Core acceptance, initialize a workflow,
start research, choose a candidate or grant execution.

## Local operator CLI

With the plugin `cli/` on `PYTHONPATH`, all commands use these same trusted local
options (absolute private paths and an independently checked registration hash):

```text
python -m research_workspace_native.saved_review \
  --database /private/review.sqlite3 --package-root /private/package \
  --registration /private/registration.json \
  --expected-registration-sha256 <RAW_REGISTRATION_SHA256> register
```

Replace the final `register` with one of:

```text
offer --principal researcher-1 --operation submit-review --target-json '<TARGET_JSON>'
submit --principal researcher-1 --request /private/confirmed-request.json
source --target-json '<TARGET_JSON>' --offset 0 --limit 4096
history --after-revision 0 --limit 100
action --key review-001
```

Only explicit registration can create a new review registration. The submit
request file has the exact `body` shape above, using the previously returned
offer. CLI principal labels are operator declarations, not authenticated web
identities. The CLI must not be exposed to arbitrary browser-supplied argv.

## Acceptance boundary

`test_saved_package_review.py` exercises real SQLite, original text readback,
review/correction/handoff receipts, two-handle deduplication and revision CAS,
wrong project/work/version/source/offer/principal rejection, post-insert source
drift rollback, deadline rollback, passive reopen and CLI receipt readback.
The previous inbox suite still exercises its unchanged public feedback API.
These are deterministic implementation checks with authored fixtures.

Actual UI registration, authentication, browser controls and same-version
acceptance still require the UI/Core adapter and its real readback. Core must
separately verify the accepted Stage 1 package, genuine brief/resource envelope,
handoff and original run context required by its existing importer. Missing
historical inputs remain explicit dependencies; this review service cannot
supply them or stand in for Core's independent acceptance.
