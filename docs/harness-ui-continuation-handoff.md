# V9 manual continuation and review handoff

Tracking: #346. Status: proposed integration follow-up, not an execution-ready interface.

## Observed versions and scope

- UI: local V9; its deployed Harness remains pinned to `5ac3804c8d1632da0655dde9d45cdb0b44f73631`.
- Remote main inspected on 2026-10-17 UTC: `d6357d477cf156a11d3bd43f4d4953a439999f10`.
- The current main project contract and Stage2 CLI were read separately. This does not claim that V9 ran the new main.
- Stage1 A03 v3 and Stage2 natural-request v5 are separate deliveries. The latter has no Stage1 lineage. Their presence in one UI project is an operator reference, not a scientific upstream relationship.
- This walkthrough made zero model, search, source-acquisition or scoring calls. No research completion, route acceptance or Stage3 permission is asserted.
- Original failed/unknown operations, budgets and package bytes remain unchanged.

## What was actually exercised locally

Using the received v5 packet (raw SHA256 `a6f146d41526d84ca477ddbb921f7fffbef8d827e8610a889c5e606ad5cef2a2`):

1. A browser operator entered the existing packet path, source root and expected hash.
2. The local adapter called the original `stage2_common.validate_packet`; the packet has 11 sources, 12 evidence entries and four candidates.
3. The operator compared S05/S08 and candidates A/C at version 1. A local shortlist was saved with packet identity and compare-and-swap revision.
4. The adapter called `initialize_workflow` and `inspect_workflow`, with zero model/source budgets. It retained the new operation, manifest and event head.
5. The service was restarted. The browser restored the same shortlist, revalidated the original head/source records and exported a continuation request.
6. The original report remains explicitly labelled as saved delivery output. No new research output or formal human interaction was created.

The UI-only shortlist persistence defect was fixed locally. Unknown source IDs, changed candidate versions, changed packet hashes and conflicting stale edits reject. A note edit retains the saved shortlist. That UI patch is not included in this documentation PR.

## Existing entry points to reuse

| Existing capability | Actual boundary |
| --- | --- |
| Project overview/contract; Stage1 checkpoint and saved delivery | Saved state and bound operations; a saved package is not an active native run. |
| `stage2_workflow import-stage1` / `import-stage1-exploratory` | Require the exact input/acceptance/resource bindings. A generic uploaded file is not automatic admission. |
| `stage2_workflow init` / `inspect` / `snapshot` | Persist/revalidate evidence and event history; initialization does not execute research. |
| `stage2_workflow human-record` | Requires actual user text, viewed delivery, manifest, decision, message index, action ID and current head. A comparison checkbox is not this record. |
| `prepare-stage3-input` / `prepare-stage3-advice` | Separate selected context from unselected advice; neither is Stage3 execution permission. |
| Stage2 trusted activation/frontier | Source-bound registration and descendant event validation; not arbitrary browser paths or native execution. |

Reference: [project contract](../plugins/auto-research-agent/references/research-workspace/PROJECT_STAGE_CONTRACT.md) and [Stage2 CLI](../plugins/auto-research-agent/cli/stage2_workflow/__main__.py).

## Requested integration work and acceptance criteria

These are consumer-visible gaps, not a claim that the Harness lacks its scientific implementation. Maintainers should first identify an existing supported entry point; add core functionality only if absent.

| Area | UI responsibility | Maintainer clarification or missing bridge |
| --- | --- | --- |
| Stage1 review during a loop | Show latest committed round, new discoveries, inclusions/exclusions with original reasons, readings, coverage and pending questions. Retain the previous snapshot while work continues. | Identify the supported immutable round/checkpoint projection and its run/input/frontier identity. A saved historical feedback JSON cannot serve as a live session. |
| Stage1 continue/revise/stop | Preserve researcher text and display requested versus observed state separately. Do not mutate the executor's in-flight plan. | Specify how a review request is accepted at a safe boundary, how changed scope/plan versions are admitted, and how stop/continue receipts bind to the original operation. Original Unknown never becomes retry permission. |
| Stage1 ledger completeness | Display all supplied decisions, reversals and discovery counts; show missing reasons as missing. | Preserve future actual reason events and source/query IDs. Supply any retained original events; do not reconstruct old rejected candidates or invent reasons from the final include list. |
| Imported Stage1 continuation | Offer compatible next actions only after admission. | Clarify canonical-version support, exact handoff/brief/resources/acceptance requirements and retained output receipt. Failed or exploratory input must not become an accepted Stage2 seed. |
| Stage2 comparison to human decision | Keep a comparison shortlist separate from a route decision; show the exact viewed candidate versions and original evidence. | Supply the supported conversion/registration from this manual-v1 delivery to a current workflow delivery accepted by `human-record`, or explicitly state it cannot be converted. Register actual independent roles/receipts where required. Do not copy author assessments into independent review slots. |
| Updated output to UI | Load artifacts only from the returned operation/current head; label previous output as previous. | Provide the source-bound output registration/frontier receipt, polling/recovery semantics and stale-result rejection. No result is inferred from a completed button action. |
| Papers, metrics and gaps | Compact side-by-side comparisons with optional detail and original-source links. | Map recorded paper fields and candidate/evidence relations. Keep proposed metrics, actual measurements and report-quality scores distinct. Unrecorded methods, units or protocols stay Unknown; incompatible conditions are not directly comparable. |

### Proposed Stage1 researcher interaction

Read the latest committed checkpoint at any time; record a review against that exact version. At the next supported boundary, choose continue, revise the next plan, or request stop. Only a new Harness receipt permits the UI to show the change as applied. The next round follows the retained gap/plan and available authority; it is not a blind repeat. These are requested UI semantics, not new scientific stopping rules.

### Required consumer tests

- Import/register a valid delivery, then reject changed bytes, unsupported schema and forged lineage.
- Restart/lose a response and recover the same operation without dispatching it again.
- Reject stale head, changed candidate version and mismatched project/input.
- Save an actual user's review with the exact viewed version; keep compare-only actions non-authoritative.
- Expose requested-stop separately from observed terminal state; Unknown remains held.
- Produce one supported next-step output and render it from its own receipt, without reusing the demo package.
- Show unavailable capabilities and original missing fields without fabricated completion.

## Validation and remaining work

Local evidence for this follow-up: three targeted HTTP tests passed (authentication/origin; real-packet shortlist persistence, version/hash/CAS rejection and fresh-store restore; research route refusal), generated JS syntax passed, and the browser import/prepare/restart/restore/export sequence succeeded. The browser retained two Three.js duplicate-import warnings and zero captured console errors. A transient browser automation selector race during reload was retained separately.

This PR adds documentation only. It does not ship the local V9 code, change scientific rules, implement the requested bridge, run a model evaluation or demonstrate end-to-end research. Both the local V9 integration and this proposed contract need owner review before any production claim. No private package, machine configuration, credentials or paper text is included.
