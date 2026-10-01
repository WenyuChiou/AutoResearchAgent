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

## Stage 1 to Stage 2 handoff

Stage 2 must not copy claims from an editable spreadsheet or a chat summary.
Run `python -m stage2_workflow import-stage1` with the trusted external hashes
for the accepted Stage 1 handoff and private deliverable. The command also
requires a confirmed `ResearchBrief` and an explicit resource-envelope text
file. It creates a Stage 2 packet v2 whose structured literature records,
sources, evidence and unresolved coverage items remain bound to the Stage 1
work/version records. The structured projection retains title, authors, year,
venue, DOI, URL, classification, literature roles, findings and claim IDs.
Unverified, partially supported and contradicted claims are also listed in the
Stage 2 unresolved items with their work/version, assertion and source locator.
Their evidence relations remain unchanged; an exact quote binding does not
make an unresolved assertion a confirmed premise. Claims without accessible
source text must remain explicit coverage obligations in the canonical records,
rather than acquiring an invented quote merely to enter the evidence table.

The bridge verifies the complete private package before reading it. It carries
exact extracted UTF-8 source text when available, preserves the true evidence
level, and emits a metadata snapshot when source text is unavailable. It never
promotes metadata or an abstract to full text. Each Stage 1 claim becomes a
Stage 2 evidence row only when its exact quote is present in the bound source
snapshot. Separate hashes freeze the imported Stage 1 literature, source and
evidence projections. Stage 2 may append records marked `origin=stage2`, but it
cannot rewrite the `origin=stage1` projection.

The resulting packet has an empty candidate list. Its comparison field records
which works and dimensions Stage 2 still needs to compare; it does not invent a
comparison or research direction. Import status is
`ready-for-explicit-stage2-start`, while the preserved Stage 2 state remains
`not-started` and `execution_authorized: false`. A researcher must explicitly
start the Stage 2 workflow. The Stage 2 `StageRun.input_refs` then binds the
externally approved source-packet bytes and the relocated stored-packet bytes,
so a later review can reconstruct exactly which Stage 1 evidence entered
direction generation. Because the seed can contain publicly
accessible full text, its output must pass the same private, outside-Git storage
guard as the Stage 1 deliverable. Stage 2 v2 checker and workflow runs inherit
the same guard because they copy the bound source snapshots. Retain the
importer's external `packet_sha256` receipt and pass it as
`--expected-packet-sha256` when initializing either v2 run. A packet that merely
recomputes its own internal hashes is not accepted without that external value.
