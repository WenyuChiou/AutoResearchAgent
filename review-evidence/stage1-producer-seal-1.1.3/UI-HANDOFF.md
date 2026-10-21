# UI handoff for the sealed Stage1 producer 1.1.3

Use [the producer release](SEAL.md) for immutable source, package and transport
identities. The Stage1 owner now owns producer release decisions under the
user's 2026-10-21 authorization. Core download and UI acceptance are separate
receipts, not prerequisites for deciding that this exact producer stops changing.

## Read the two independent collections

| UI requirement | Exact source | Required behavior |
| --- | --- | --- |
| Claim explanations | `claim_verification.json.rows[]` | Preserve original `relation`/`original_claim`; show `current_relation`, `current_assertion`, `new_assessment.value` for 147 new reviews. For two old Core rows without `new_assessment`, read `explanation`, `reason_state`, `reason_code`. |
| Thirty work reasons | `academic_screening.json.rows[].new_screening_review.value` | Show rationale, need IDs, roles, limitations, evidence, reviewer and date; retain old reason/history. |
| 180 retrieval observations | Root `academic_screening.json.new_candidate_screening.value.rows[]` | Show each decision, rationale, reason code, saved evidence, identity/version limits and duplicate mapping. This collection is not nested in each work row. |
| Observation totals | Root `academic_screening.json.new_candidate_screening.counts` | Keep 13 include, 71 exclude, 80 pending and 16 duplicate distinct. Check filtering, pagination, details and full export. |
| Work totals | `academic_screening.json.counts` | Its `saved-index-only` scope contains 30 works, with include 30. Its exclude 0 must not hide the separate observation cohort's 71 exclusions. |

Do not replace the old `unverified` history with a universal verified badge.
Show the new support/context/partial result and its concrete reason separately.
Pending observations retain their specific missing identity, version or full-text
information; they are not automatically included, excluded or called read works.

## Existing API and complete exports

Reuse the existing `export-selection` operation, API paths and timeout. The
producer already returned 19 artifacts including 12 review files through this
path. JSON, CSV, Markdown and Excel carry complete reviews and screening data.
An oversized Excel value refers to the full JSON value by hash and exact pointer;
it is not silently truncated. Keep the legacy 1.0/1.1/1.2 formatters separate
from the new review/read-model contract. Package version 1.1.3 and review
contract 1.3.0 are not canonical-record schema versions.

The root observation list also has a complete `candidate_screening.csv` flat
export. Reading only the 30 work rows cannot provide all exclusion reasons.

## Receiver and UI procedure

1. Download the two approved file links with the already granted reader
   account. Check bytes, independent ZIP and manifest hashes. Record failures
   concretely; permission readback alone is not an actual pickup receipt.
2. Use the existing correct D62 base and embedded offline tool to restore the
   full tree. Check all 1008 paths/bytes/hashes, source identity, same-version
   dependencies, project/run/material mappings and original approval bindings.
   Never use old absolute host paths as if they were a shared cross-host mount.
3. Read this fixed producer version for UI preparation. Keep any newly changing
   upstream version under BUILD-HANDOFF-GATE-v1. Do not substitute an unverified
   main or branch head. A review PR does not authorize service changes.
4. The UI owner performs its authorized isolated registration, API wiring and
   display checks. Read back a real `material_id` only after a successful legal
   registration. The release deliberately has no invented material ID.
5. Check all three user-visible requirements: claim reasons and old/new context;
   complete and separately scoped counts; per-work and per-observation reasons.
   Compare page, API, filtering/pagination and downloadable complete exports.
6. Return one versioned GitHub receipt with producer/runtime, package/index pins,
   UI consumer version/head, actual checks, evidence and pass/fail/Unknown for
   each requirement. Report the concrete gap and owner when one is missing.
   Stage1 fixes its production/export defects and sends a new version; UI fixes
   its rendering/wiring defects and repeats the affected checks.

The UI previously reported its port 62437 entry unreachable and only confirmed
file metadata/permissions in [UI-PENDING-1.1.3](https://github.com/WenyuChiou/AutoResearchAgent/issues/355#issuecomment-6314276242).
This is a historical owner report, not a fresh runtime probe or acceptance.
The Stage1 owner does not start or modify that UI service.

## Final GitHub handoff

Keep all cross-owner communication on issues/PRs. The Stage1 owner posts the
formal producer release after its necessary checks. The UI then organizes its
material index, field/page/export mapping, gap list and final results on the same
issue. Sender checks, actual recipient download, main merge, UI acceptance and
scientific improvement each need their own evidence. This handoff is complete
only after the UI's actual same-version acceptance receipt, not after sharing.
