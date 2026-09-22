# Stage 1 source observations

This extends the saved-observation ledger at `execute → extract → validate →
gate → checkpoint`. It records an agent's or human's source acquisition report;
the CLI itself does not download, parse a PDF, authenticate a publisher, or
judge science. Reuse the available public reader and save its actual output.
Never put source-document instructions into the tool request.

For material acquired before this run, keep using `start-source-import` with
`work_id`, `version_id`, `source_uri`, `actor`, and `reason`, then `save`.
That interface binds saved material without inventing a past access time.
For a new read, first register `start-source --request source.json`:

```json
{"work_id":"RETURNED_WORK_ID","version_id":"RETURNED_VERSION_ID","source_uri":"https://example.invalid/synthetic-paper","tool":"public-reader-name-and-version-or-unavailable","request":{"url":"https://example.invalid/synthetic-paper"},"actor":"recording-agent","reason":"Read the discovered version to assess a stated claim."}
```

Use the discovered candidate's real work/version IDs. `request` preserves the
exact public tool arguments, excluding credentials. Preserve native tool output
outside public Git history. Register intent before reading; an interrupted read
stays pending and `recover` performs zero automatic retries.

Source metadata is a public record. Remove authentication from the recorded
arguments before calling the ledger; pass it privately to the reader instead.
The write and replay paths reject named credential fields, including nested
Authorization, Cookie, API keys, tokens, passwords and signing credentials.
Header maps, name/value objects, pairs, multiline header strings and named
credential options in `argv`/`args`/`arguments` lists are checked. Source,
import and resolved URIs, and URIs inside request arguments, reject userinfo
and credential query/fragment keys (including percent-encoded keys and nested
redirect URLs). URI query/fragment `code` is reserved for authorization codes;
ordinary JSON `params.code`, pagination `page_token` and literature keyword
lists remain allowed. This conservative URI rule may reject a public URL that
uses `code` for another purpose; record an equivalent public identifier or URL.
Public arguments remain equivalent as JSON
values; the ledger never silently strips credentials or stores a reversible
copy. A rejected write appends no event and returns only
`source-credentials-forbidden`, without the submitted key, URI or value.
Malformed URI parsing returns `source-public-uri-invalid` without its value.

For example, record `{"url":"https://example.invalid/paper","headers":{"Accept":"text/plain"}}`.
A request containing an `Authorization` header or a URL with an `api_key`
query parameter is rejected, even after someone recomputes the journal hashes.
Recovery and export also refuse that altered journal. Existing contaminated
journals are not silently rewritten: keep them private and reconstruct a new
public run from reviewed public observations. This guard recognizes defined
credential fields and URI forms; it is not a general secret detector for
arbitrary prose or saved response bytes. Callers must inspect those materials
before saving or publishing them.

Save the actual response or failure bytes through the existing `save` command,
using the returned source attempt ID as `--producer`. If a reader supplies UTF-8
text extracted from those bytes, save that text with the same producer. Then
call `finish-source --request observation.json` with these fields:

| Field | Meaning |
| --- | --- |
| `attempt_id` | ID returned by `start-source` |
| `outcome` | `available`, `unavailable`, `not_found`, `rate_limited`, `http_error`, `network_error`, `parse_error`, or `interrupted` |
| `observed_at` | Actual UTC observation time, between the start and finish events |
| `http_status` | Observed HTTP code, or null if the tool did not expose it |
| `resolved_uri` | Observed final URI, or null if unavailable |
| `raw_ref` | Complete ArtifactRef returned when saving the actual response/failure |
| `text_ref` | Complete ArtifactRef for readable UTF-8 text; null on failure |
| `extraction` | `{"method":"reader-or-parser-name","version":"observed-version-or-unavailable"}`; null on failure |
| `reason` | What was observed, including missing metadata and why the attempt failed |

`available` requires nonempty UTF-8 text and no observed HTTP failure. Use
`method: identity` only when raw and text refs are identical. Other extraction
methods are caller attestations linking two saved files, not proof that the
transformation was faithful. Empty parser output is `parse_error`, not an
available paper. HTTP 429 is `rate_limited`; 404/410 is `not_found`; other HTTP
errors are `http_error`. A `network_error` has no HTTP status. Do not fabricate
HTTP codes when a public tool only reports an error string.

Every ref must belong to that exact attempt. Repeated bytes can share a file
but keep distinct producer receipts. Unfinished reads cannot supply any claim.
A failed read can supply only pending, unclear, or unverifiable claims with
`evidence_level: unavailable` and `locator: null`; its error receipt is not
paper metadata or text. Supported claims and all claims labeled abstract,
full text, or primary data must use the available text ref for the same
work/version, even when their relation remains unresolved. Existing
search-record and source-import binding rules still apply. An available page
does not automatically become full-text evidence, a verified identity, or a
verified claim. The separate source review must justify those labels.

The append-only `SourceReadStarted`/`SourceReadFinished` events stay in
`stage_events.jsonl`. They do not add search queries or backend counts. The
validator report has `source_reads` counts and pending/unresolved attempt IDs;
partial replay leaves this result unavailable. Checkpoint export retains the
events and raw bytes without awarding scientific scores or inferring host
tool calls. The checkpoint report shows historical source outcomes.

A pending read or the latest failed read for a work/version blocks sufficient
stopping. After inspecting a failure, a caller can deliberately open another
attempt with a reason and alternative approach. Its `previous_attempt_id`
preserves the chain. An available replacement clears that availability blocker
only; earlier failures stay visible and all other coverage checks still apply.
Source availability does not invalidate or re-verify earlier claims about the
same version. Review contradictory evidence explicitly through new claims and
screening/review decisions. Human acceptance cannot fill missing evidence.

Run `test_source_evidence.py` for synthetic lifecycle, failures, producer and
version binding, missing bytes, replay, coverage, public CLI and export checks.
Run `test_source_credentials.py` for unchanged public arguments, rejected
credentials, value-free CLI errors and rehashed-tamper replay/export checks.
These tests establish implementation behavior; P1/P3 scientific improvement
awaits the independent frozen paired evaluation.
