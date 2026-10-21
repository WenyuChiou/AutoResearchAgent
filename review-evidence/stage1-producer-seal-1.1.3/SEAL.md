# Stage1 producer engineering release 1.1.3

Release ID: `S1-PRODUCER-SEAL-1.1.3`.

The Stage1 owner fixes the existing saved-source review, screening reasons and
complete export package at the identities below. The user explicitly authorized
this owner to decide the producer release and submit a reviewable PR on
2026-10-21. Core no longer needs to approve the producer's release decision.
Core still owns review and merge. Receiving the package, operating the UI and
accepting its actual display remain separate recorded outcomes.

This is a producer engineering release, with `implementation-only` evaluation
readiness. It does not finish the scientific Stage1 workflow, establish research
improvement or authorize Stage2 research. No private paper text enters this PR.

## Immutable identities

| Identity | Fixed value |
| --- | --- |
| Original data producer | `1e8d3c16cc784a49c00ede80c88a6eef5cc204ac` |
| Engineering runtime | `7cbb6396d5a730ee364c7aa84278085120fd35f1` |
| Runtime tree | `8b2278e08c0b0fadab88e448c6cb6e7c9e1cff36` |
| Data version | `1.1.3` |
| Read-model contract | `S1-SCREENING-READMODEL-1.3.0` |
| Review export contract | `S1-DELIVERY-REVIEW-1.3.0` |
| Prior-review projection | `1.1.0` |
| Full package | 160808960 bytes, 1008 files |
| Full ZIP SHA-256 | `83cb5c8c682660ff1e0b52eae4400dd5e2a3309746ab6e8b6d793e2c6e89f4fa` |
| `delivery.json` SHA-256 | `1fb4dccef1f8d965c4db2338b69e76740b314e74fe68340c1ab388404056eaeb` |
| Workspace index SHA-256 | `817bf0161464ac1b417a0d4d4cfb88313811393728901d49126ca83315cba50e` |
| Original-records manifest SHA-256 | `c5a6fed15f2816f0df26891774aa53849392c61189d259f9e9f8d23a1740a4ac` |
| Workspace view manifest SHA-256 | `a825e5084199363a6019bc6c0513ae3bb810449e37d8c8d6314e867c2d6a115a` |
| Original D62 raw index SHA-256 | `ab8ce0f71f8cfc74cc8938c7d383fc7ac19403c12cc771373b8b5106a7821bf8` |

The runtime differs from the data producer only in two synthetic test modules:
`test_original_record_recovery.py` and `test_saved_source_reassessment.py`.
They resolve the temporary directory's physical parent before entering the
existing private-output guard. Production code and its guard are unchanged.
Git content identity is distinct from checkout LF/CRLF representation.

This PR records the release; its own commit is not the runtime execution commit.
It reuses the existing package's machine-readable manifests and validators,
without adding a release parser, runtime gate or capability registry entry.

## Private transport

The user authorized `wec324@lehigh.edu` as a reader of exactly these two existing
files. `hod325@lehigh.edu` remains owner. File permission readback confirmed no
new public, domain-wide or other user grants. Use file links; the parent's
private organization does not grant permission to its other historical files.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| [Private delta](https://drive.google.com/file/d/1LeyPZ91RYIDHuLVtsefSR94yOx8s3HOj/view) | 24825865 | `aa5f8bf1693c813b62e867bdf66a2b25ce07bd4918f4fade632ff321dc83c722` |
| [Engineering evidence](https://drive.google.com/file/d/1qE9g2Znd2Yh-_3MB4tZN6yqpe96WKlD0/view) | 413055 | `3b41ae685215f46224c8f243f1536b106bfc8b3af77808966f19219ba03e2024` |

Independent transport manifest SHA-256:
`cd75a9fc2374f8b8b5919c47a9122a5f82d0e7f64b5262dab910d0a46f989b78`.

Independent engineering manifest SHA-256:
`b779b83bc73fc819869f8d07a08e86823d47a44870638e62a60e7338394c7bd6`.

The delta uses the already delivered D62 base, 202890605 bytes with SHA-256
`1a9725f260357b68c7cd3b39e0d643450aa52285aa175d10b5496bf2c19b776b`.
Its embedded README and offline tool restore the exact 1008-file tree. It does
not promise the same ZIP bytes after recompression. Do not request the base
again when the recipient already has its correct copy.

## Recorded engineering evidence

- Fresh release verification checks all three ZIP identities, every package
  inventory entry and all 1008 delta/base target members against the full tree.
- Fresh registered standard regression ran 435 tests with zero failures/errors,
  three skips and zero incomplete partitions. PR body/dependency contracts ran
  68 tests; invariant/plugin/stage smoke and CI quality contracts each ran nine
  tests, all passing. Manual-only integration remains deferred. The final issue
  receipt links the actual logs and exit-code records; skips are not passes.
- Existing exact-runtime CI is [run 39541057126, attempt 1](https://github.com/WenyuChiou/AutoResearchAgent/actions/runs/39541057126).
  The scope job and macOS, Ubuntu and Windows steps 12/13 succeeded. Windows
  covers the configured smoke scope, not full integration. Governance step 14
  was skipped; the repository's required-check set remains Unknown.
- The original real-data API export returned 19 artifacts. Twelve review files
  were read back byte-for-byte in 5.266 seconds within the existing 10-second
  operation deadline. Original API paths and actions remain compatible.
- Previous macOS failures, Windows symlink skips and manual-only test deferrals
  are retained. A skip is not a pass. Merged stdout/stderr from old runs is not
  rewritten as independently captured stderr.

## Content scope and limits

All 149 original claim records remain. Of those, 147 have new, explicitly dated
AI source reviews: 112 supports, 28 context and 7 partial. Seven partial claims
also carry narrowed assertions. Two other records retain recovered old Core
reasons. Every row has a readable explanation; a new AI review is not an
independent scientific or human approval.

Thirty saved works have new per-work need, role, reason, evidence and limitation
records. The separate 180 saved retrieval observations have 13 include, 71
exclude, 80 pending and 16 duplicate decisions with individual reasons.
These observations are not a historical deduplicated-paper total. Pending
identity/version/full-text questions and missing old A03 history remain explicit.

## Separate acceptance states

At this release decision, sender package/transport checks are recorded; a Core
download receipt and UI content acceptance have not been observed. Their later
receipts are appended on [issue 355](https://github.com/WenyuChiou/AutoResearchAgent/issues/355).
Do not mutate the frozen ZIPs to rewrite their earlier pending-state snapshots.

The UI can now receive this sealed producer version, verify its independent
pins and legal mappings, and prepare its own same-version display acceptance.
The UI owner retains service, layout, renderer, registration and activation
ownership. Existing merge rules, native approval bindings and formal Stage2
consumer limitations remain in force. Main merge and new documentation-PR CI
are not claimed by this release record.

Any change to the sealed data, its runtime or the interface contract requires a
new version and an explicit old-to-new handoff. A new source or package cannot
silently replace this release.
