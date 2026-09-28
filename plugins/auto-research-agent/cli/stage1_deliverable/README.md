# Experimental Stage 1 researcher deliverable

`cli:stage1-deliverable` builds the private package defined in
[the contract](../../references/stage1-research-deliverable.md) from canonical
records and public-source receipts. It does not search, nominate papers,
assess scientific claims or replace `stage1_export`. Readiness remains
**implementation-only**; improvement is **not yet demonstrated**.

## Runtime and commands

Use Python 3.11 and the committed `requirements-test.txt` lock, including
openpyxl 3.1.5, python-docx 1.2.0 and research-hub-pipeline from merge
`929bdd6d963acf4be5bc9d80ce3c5c0a0f77a834`. DOCX is available in this declared
runtime. A missing dependency fails rather than silently omitting a view.
Install into a dedicated environment from the plugin directory:

```text
uv venv --python 3.11 PRIVATE_RUNTIME
uv pip install --python PRIVATE_RUNTIME/Scripts/python.exe -r requirements-test.txt
```

On Unix use `PRIVATE_RUNTIME/bin/python`. Set `PYTHONPATH` to the absolute
`plugins/auto-research-agent/cli` directory. Use the environment's interpreter:

```text
python -m research_hub source fetch --url PUBLIC_URL --title EXACT_TITLE --output-dir PRIVATE_INPUT/source-001 --json
python -m research_hub source validate PRIVATE_INPUT/source-001/source-fetch-result.json --json
python -m stage1_deliverable build PRIVATE_INPUT/records.json PRIVATE_OUTPUT --records-sha256 RECORDS_SHA256
python -m stage1_deliverable validate PRIVATE_OUTPUT --expected-sha256 MANIFEST_SHA256
```

`--doi` is optional on source fetch. Use ordinary publicly accessible URLs,
never credentials or signed links. Each fetch/export requires a new directory.
Preserve partial exports and failures. `build` prints a JSON validation receipt
containing `manifest_sha256`; retain it separately as the trusted validation
hash. A hash copied from the package itself cannot establish authenticity.

## Canonical records

`records.json` has exactly these fields. Collections contain objects, not
keyed dictionaries; `records.py` implements the strict field validation.

| Collection | Required fields |
| --- | --- |
| Root | `kind: Stage1ResearchRecords`, `schema_version: 1.0.0`, `topic`, timezone-aware `as_of`, `papers`, `sources`, `claims`, `screening`, `coverage` |
| Paper | `work_id`, `version_id`, `title`, `authors` list, `year` integer or null, `venue`, normalized `doi` or null, public `url`, `evidence_level`, `source_ids`, `classification`, `roles`, `findings`, `claim_ids` |
| Classification | `topic_cluster`, `method`, `geography`, `population`, `data_type`, `domain` |
| Findings | `question`, `data`, `method`, `main_findings`, `limitations`, `relevance`, `transferability` |
| Role | `role` (classic/topic-core/closest-work/comparator), `reason`, same-work `claim_ids` |
| Source | `source_id`, `work_id`, `version_id`, relative `result_path`, receipt-file `result_sha256`, `access_note` |
| Claim | `claim_id`, `work_id`, `version_id`, `text`, `source_id`, `relation` (supports/partial/contradicts/unverified), `evidence_level`, `locator`, `start`, `end`, `quote` |
| Screening | `decision_id`, `work_id`, `version_id`, `status` (include/exclude/pending), `reason`, `query`, `discovery_path`, timezone-aware `observed_at` |
| Coverage | `need_id`, `description`, `work_ids`, `recent_sweep`, `closest_work_check`, `unresolved`, `stop_decision` (stop/continue), `reason` |

IDs start with an ASCII letter/digit and contain only letters, digits, dots,
underscores and hyphens. Every paper needs a source attempt and screening
history. References must belong to the same work/version. Claims and roles
may be empty when evidence is unavailable. Use explicit unknowns in unassessed
text fields, never invented findings.

`version_id` is an authored publication/version label, distinct from the
dependency's `source_version: sha256:...` binding downloaded bytes. Receipt
expected title/DOI must match the canonical paper. Authored authors, venue,
year, findings, roles and stopping judgments are not independently fact-checked.
Identity retains the parser's verified/consistent/unverified/mismatch status.

Evidence levels are `metadata`, `abstract`, `full-text`; paper/claim levels
cannot exceed actual accessible evidence. Claims use zero-based Unicode
character offsets in exact UTF-8 extracted text, with exclusive `end`.
`locator` must be exactly `characters START:END`; `quote` must equal that
bounded substring. For example, start 0/end 20 requires `characters 0:20` and
the first 20 source characters. Original PDF/HTML locators remain in receipts.
A matching quote establishes binding, not the truth of the authored claim.

## Package and replay

Outputs include README, six-sheet Excel, Markdown/DOCX reviews, BibTeX,
canonical papers JSONL, claim/screening CSVs, coverage Markdown, paper/provenance
manifests and `papers/` selected lawful full sources. `records.original.json`
preserves exact input. `sources/<source_id>/` preserves original receipts,
every declared raw attempt, extracted text and public-validator observations.

The provenance manifest binds canonical records, input, inventory, exporter,
interpreter, installed dependencies and counts. Replay uses the public offline
validator on a disposable relocated copy, checks historical validator evidence
and rebuilds every view. Rehashing edited views or extracted text does not
bypass semantic replay. Package directories can move within the same declared
runtime; different runtime bytes are rejected. Build/replay never acquire new
sources.

Each attempt records URI, time, MIME, byte count/hash, access note and parser.
No parser invocation is represented by null parser/version and
`parser_attempted: false`. Ten access states remain distinct: available,
abstract-only, metadata-only, paywalled, not-found, rate-limited, network-error,
parse-error, login-page, identity-mismatch. Bare HTTP 403 is an access/network
failure, not evidence of a subscription. Labels use recorded outcomes and
conservative markers; they do not independently audit licenses. The pinned
fetcher supports PDF/HTML; unsupported plain-text MIME remains a parse error.

Packages must stay outside Git. Unsafe paths, reparse points, duplicate IDs,
unknown receipt fields and recognizable credentials are rejected. Credential
screening is conservative and cannot prove arbitrary content has no secret;
use credential-free public acquisition. Excel formulas remain literal; CSV
formula prefixes are escaped. Excel oversized cells fail rather than truncate.
Editable views never become canonical: update records and export a new package.

## Tests and evidence limits

From the repository root with the declared interpreter:

```text
python -m unittest discover -s plugins/auto-research-agent/tests -p test_stage1_deliverable.py -v
```

Fixtures are authored synthetic PDF/HTML and synthetic failures, using the real
pinned extractor and public offline validator. They exercise source/view
tampering, false full-text labels, identity/version errors, credentials,
runtime drift, unsafe paths, historical validation evidence and no overwrite.
They are not live Japan observations.

The real unscored Japan pilot must retain a complete treatment package, native
A/B captures and complete evaluator/replay evidence. Report actual access
counts and every zero-count state in `not_exercised`; never synthesize pilot
failures. Package conformance does not establish P1-P3 improvement or authorize
formal subjects.
