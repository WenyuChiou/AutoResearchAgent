# Stage 1 researcher deliverable

Stage 1 finishes with a researcher-facing literature package, not only an
evaluation bundle or a chat response. The existing `stage1_export` remains the
replayable evaluator input. A research-deliverable exporter is a separate
production capability and must derive every view from the same validated,
version-bound records.

## Required private package

```text
stage1_research_deliverable/
├── README.md
├── literature_catalog.xlsx
├── literature_review.md
├── literature_review.docx          # when the declared runtime supports it
├── references.bib
├── papers.jsonl
├── claims_and_evidence.csv
├── search_and_screening.csv
├── coverage_and_stop.md
├── paper_manifest.jsonl
├── provenance_manifest.json
└── papers/
    ├── <work_id>__<version_id>.pdf
    ├── <work_id>__<version_id>.html
    └── <work_id>__<version_id>.txt
```

`papers.jsonl` and `provenance_manifest.json` are the canonical structured
records. Excel, Markdown, DOCX and BibTeX are editable views. Their work,
version, claim, decision and source counts must reconcile with the canonical
records. A missing optional DOCX must be reported as unavailable; it must not
silently remove the required Excel, Markdown or BibTeX outputs.

The Excel workbook contains these sheets:

1. `Papers`: identity, citation, venue, identifier, source version, access date
   and evidence level.
2. `Classification`: topic cluster, method, geography, population, data type,
   domain and evidence-backed classic, topic-core, closest-work or comparator
   roles.
3. `Findings`: question, data, method, main findings, limitations, relevance
   and transferability.
4. `Claims`: claim ID, work/version, relation, evidence level, locator and
   source artifact hash.
5. `Screening`: include, exclude or pending status; reason; decision history;
   query; and discovery path.
6. `Coverage`: research need, recent sweep, closest-work check, unresolved
   evidence, stop decision and reason.

Classic, topic-core and closest-work remain separate judgments under the
existing Stage 1 definitions. Age, popularity or a plausible title does not
establish any of these roles.

## Lawful source acquisition

Reuse Codex native public reading and a pinned research-hub source fetch when
they answer the need. Complete the normal reuse, wrap, extend or build-new
decision before adding another downloader.

- Save a publicly accessible PDF, public repository copy, author-posted
  version, arXiv version or public HTML/text full text when lawfully available.
- Bind every saved document to work ID, version ID, requested and resolved
  URL/URI, observed access time, content type, access or license note, parser
  and version, byte count and SHA-256.
- Validate PDF bytes, content type and readability. A login page, error page or
  HTML response named `.pdf` is not a paper PDF.
- Keep `available`, `abstract-only`, `metadata-only`, `paywalled`, `not-found`,
  `rate-limited`, `network-error`, `parse-error`, `login-page` and
  `identity-mismatch` distinct. Preserve attempts and reasons.
- Never bypass a paywall, login, CAPTCHA or access control. Never save a
  credential in the ledger or package. A later user-provided lawful copy enters
  as a new source import rather than rewriting the earlier failure.
- Never label metadata or an abstract as full text. Missing full text remains
  missing even when the citation identity is valid.
- Keep papers and potentially copyrighted source text in the private run
  package. Git may contain schemas, synthetic fixtures, de-identified counts
  and hash-bound manifests, but not downloaded paper files.

## Pull request and pilot evidence

Every research-harness PR completes the `Research Deliverable` section of the
repository template. An evaluator-only, Stage 2 or governance-only PR can use
`not-applicable` with a concrete reason. A Stage 1 deliverable implementation
uses the registered `cli:stage1-deliverable` capability, declares `required`
and provides evidence for all six fields. The PR validator automatically
rejects `not-applicable` for files owned by that capability.

The first executable acceptance run is the predeclared, unscored Japan pilot.
Its public-safe manifest binds the private package, validation report, exporter
runtime and counts without publishing paper bytes. The pilot must exercise:

1. Excel, Markdown, BibTeX, metadata, claims, screening and coverage output.
2. Work/version, URL/URI, access-time and SHA-256 bindings.
3. At least one lawful public full source and an actual unavailable/access-error
   observation. Preserve all ten access states as distinct counts. List every
   zero-count state in `not_exercised`; never manufacture a live failure to
   satisfy a checklist. Deterministic tests cover the unobserved branches. The
   core team decides whether another lawful live probe is needed.
4. No paywall bypass, no abstract-as-full-text label and no paper files in Git.
5. Full package validation, including cross-format ID/count reconciliation and
   tamper rejection.

Report acquired PDF/HTML/text counts, inaccessible reasons, full-text
acquisition fraction and exporter runtime separately from P1-P3. A valid
package proves delivery behavior. Scientific improvement still requires the
frozen paired A/B and its existing decision rule.
