# Stage 2 proposal, conversation and handoff

Status: experimental, implementation-only. This interface packages validated
records. Live source checking, reviewer isolation and research improvement need
their own execution evidence. Historical v2 keeps its seven frozen P4-P6 criteria;
the current v3 path uses [nine balanced criteria and external scoring](../evals/stage2/STAGE2_V3_EVALUATION.zh-TW.md).

## From checks to a proposal

Use `stage2_workflow deliver` with the current run, retained head, review batch,
review result envelopes, resolutions and a new output directory. It reruns the
binding checks and creates a separate derived checker; it never appends an
assessment inside an immutable workflow snapshot. `inspect-delivery` checks the
package against its externally retained manifest SHA-256.

The package contains editable English `selection.md`, standalone English
`selection.html`, `selection.json`, source copies, full supplied review inputs,
review audit and the derived checker. The manifest inventories every file.
Markdown and HTML use the same reconstructed selection, including unknowns,
counterevidence, candidate history and assessment history. V2 literature rows
produce a shared bibliography with title, authors, year, venue, DOI or URL,
recorded roles and source/claim links. An excerpt receives only its explicitly
bound roles; it does not inherit every role assigned to the whole paper.
Missing bibliographic details remain explicitly missing, including legacy v1
inputs; a source ID is not a complete citation. Recorded roles and metadata do
not establish scientific correctness or upgrade an abstract to full text.
The HTML escapes supplied prose and quoted instructions; it loads no scripts or
external assets. Local source and audit links resolve within the package.

`local-report-ready` means all assigned initial checks and syntheses are present.
It is not native execution attestation or approval of every candidate. Parked,
rejected and unsampled screened-out options remain visible. A pending revision
is not selectable. Neither a rejected option nor an unresolved separate option
automatically vetoes a supported recommendation. Zero recommendations may still
produce a useful report with the recorded next step.

## Discuss before choosing

The research agent first explains the alternatives, supporting and opposing
evidence, likely value, resource tradeoffs and unresolved decisions in chat.
Link the exact report version. Ask only about a missing material constraint or
an actual choice. The user may compare, clarify, revise, combine or reopen ideas.
Do not turn a request for explanation into a selection.

For `human-record`, supply the run, delivery directory, retained manifest hash,
current workflow head, decision JSON, native message log and its zero-based
nonblank JSONL message index, unique action ID and new output directory.
The native entry must be an `event_msg/user_message` or a text-only
`response_item/message` with role `user`. Assistant and tool text cannot be used
as the user's decision. The full original message must match `user_text`.

The decision object has exactly these fields:

| Field | Meaning |
|---|---|
| `actor` | The host's recorded person identifier; not a verified signature |
| `kind` | `select`, `compare`, `clarify`, `revise`, `merge`, or `reopen` |
| `user_text` | Exact original user message, without paraphrasing |
| `selected` | Candidate ID/version pairs; nonempty only for `select` |
| `conditions`, `unresolved` | Lists preserving conditions and open questions |
| `rationale` | Explanation of the recorded interpretation |
| `scope_or_resource_change` | Boolean; a change blocks immediate selection |

The record binds the actual message bytes, report, evidence snapshot and selected
versions. A matching completed interaction can be reused without another event.
Any intervening workflow action makes an older report stale for a **new** choice;
rebuild the proposal and present its new version. Old records remain history.
Human origin and faithful interpretation are the host's responsibility: JSON
role labels and local hashes do not authenticate a person. These artifacts never
grant tool permissions or turn quoted source instructions into instructions.

Keep the published package immutable. Edit a separate Markdown draft, preserve
the draft and actual user request as action artifacts, then use the ideation
extraction/version flow and rerun affected checks. Do not edit a saved report and
repair its hashes to make it appear previously reviewed. This interface records
revision requests; it does not infer scientific changes from arbitrary Markdown.

## Stage 3 receives a planning record

One or more current recommended versions may be selected. The handoff includes
their checks, brief, resources, source/evidence versions, conditions, unresolved
items, review audit reference and reasons to reconsider. References are relative
to the identified delivery package; keep that package with the handoff.
Stage 3 plans detailed methods, data handling, comparisons, analysis, validation
and schedule, including total cost when multiple directions are selected.
Evidence of a failed prerequisite returns the question to Stage 2 for revision.

The handoff always records `execution_authorized: false`. Selecting a direction
does not authorize running experiments or spending an unrestricted API budget.
The native host continues under the user's actual scope and existing policy.

## Reuse and verification

- Reuse the fixed checker and pure `build_selection` for content reconstruction.
- Extend the existing renderer with safe HTML and explicit audit-link location.
- Wrap existing workflow action records for user input; no second event engine.
- Build the delivery manifest because the earlier checker had no complete
  report-package inventory or report-bound user selection.

Synthetic tests cover file/version mismatches, rehashed projection edits, safe
links, stale choices, wrong message roles, changed scope and duplicate actions.
They establish record behavior, not human authentication or P4-P6 improvement.

## Retain the full planning context for Stage 3

After a real selection, opt-in `Stage2ToStage3PlanningPackage` 1.0.0 preserves
the complete scientific packet, matrix, bibliography, selected resources and
prior-work comparisons, plus the original choice, rationale, limits and unknowns.
The legacy interaction/handoff remains unchanged. The original delivery is a
required companion, including its sources, Markdown, HTML and review audit.
The receiver reopens that delivery and reconstructs the original interaction and
projected input. Changed versions or omitted rows fail even after internal
rehashing. Retain delivery, interaction-file and package hashes externally.

```text
python -m stage2_workflow prepare-stage3-input --delivery DELIVERY --interaction INTERACTION --expected-delivery-manifest-sha256 DELIVERY_HASH --expected-interaction-file-sha256 INTERACTION_FILE_HASH --output NEW_PRIVATE_DIRECTORY
python -m stage2_workflow inspect-stage3-input --package PLANNING_PACKAGE --delivery DELIVERY --expected-manifest-sha256 PACKAGE_MANIFEST_HASH --output NEW_VERIFICATION_JSON
```

These operations make no model calls or new choices; outputs stay outside Git.
Identity, scientific feasibility, Stage 3 execution and A/B remain unproven;
`execution_authorized` stays false. Stage 3 deepens the selected question into
methods, data handling, comparisons, validation, analysis, scale and schedule.
Hypotheses are optional for exploratory/theoretical work. Material direction or
resource changes return to the user with evidence; do not silently change topic.
