# Workspace interface v1

This is an offline candidate, not an accepted-main or live-readiness claim.
The sibling JSON fixes the meaning of data, identities, metrics and actions.
It deliberately does not freeze graph positions, colors, line styles, panel
order, font size, node navigation or whether process detail is collapsed.
Keep the reviewed v6 content-first interface while changing those presentation
choices independently of the runtime.

## One server configuration

`WorkspaceUiConfig.v1.schema.json` centralizes pinned case manifests, language,
density and requests to use existing server objects. `compile_config` takes the
exact config/contract/schema bytes with external expected SHA256 values. It
returns the unchanged AtlasHost `{views}` format and detached presentation and
server-object requests. It creates no file, process, thread, channel or permit.

The host does not yet consume this new config directly. Integration is one
trusted entry-point change: compile, validate the resulting legacy view config
with `load_views`, resolve opaque object references from an existing server
registry, and pass explicitly supplied objects to the existing AtlasHost.
Never import a module or execute a command named by an object reference.

Example settings (the placeholders require real external pinned hashes):

```json
{
  "kind": "WorkspaceUiConfig", "schema_version": "1.0.0",
  "interface_sha256": "<contract raw SHA256>",
  "views": [{"ref":"case-a","label":"Case A","manifest":"<absolute private path>","sha256":"<manifest raw SHA256>","fixture":true}],
  "presentation": {"language":"en","density":"comfortable"},
  "native": {"mode":"disabled"},
  "maintenance": {"mode":"disabled"}
}
```

An enabled-mode declaration remains `declared-not-activated`. `runtime_ref`
names an already created SessionOwners object, not a launcher specification.
`inbox_ref` names a trusted server mapping to a private record-only inbox.
No credential, permission, source root, model, epoch or executable is accepted
through these modes. Actual Host/API source and principal checks still apply.
Presentation values are preferences; the existing renderer must explicitly
consume them before claiming they affected a page.

## The renderer reads a stable projection

Existing `window.WORKSPACE_VIEW` remains the wire data; existing AtlasModel
provides Stage 1 papers and Stage 2 comparison papers. Preserve every source
field, original quotation, work/version identity, hash and access limitation.
Do not rewrite the canonical source data to suit a graph. Relation rendering
can use focus/aggregate views, but never fabricate a scientific relation.

Index SHA hashes exact index bytes. Records SHA hashes canonical records.
Neither creates a ResearchBrief input version. Static pages lacking the latter
show Unknown. ResearchBrief 1.1 accepts a nonblank string or a positive integer;
preserve its exact type. Native SessionApi requires a 64-hex input_version from
the actual server binding. If those namespaces differ, an explicit source-bound
mapping is required; this compiler never coerces, hashes or supplies that mapping.
A visual asset version is independent of these identities.

Stage 1 formal-eligibility rows retain excluded and pending papers, reasons,
source links, notes and bibliography. Row counts are work/version counts;
the confirmed formal target is distinct works, and current main proposes at
least 30 for new briefs. A proposal is not the user's submitted answer or a
new budget. Frozen old targets remain unchanged. The 30–40 paper UI focus is
a viewing preference and never replaces the full retained screening history.

The current AtlasModel discovery fields are null. The typed ledger extension
lists the real source fields for a future adapter, not an already integrated
feature. Count discovery IDs, queries and backend attempts separately. The
backend result position is not a relevance score or a global discovery rank.
Decision history must preserve event IDs, prior decisions and reversals.

Shared-method similarity is recorded tag Jaccard, not evidence strength. Show
its unit alongside the graph; missing tags stay Unknown. Topic bars count
papers with each label and can overlap. Candidate comparison cells retain the
source field path. Stage 2 identities come from its own source packet; an
operator-selected reading bridge is not original-producer lineage evidence.

## Scores, actions and compatibility

Show Stage 2 daily_v3 P4/P5/P6 as separate percentages, each max six points
and three required rows. A required null keeps the whole dimension null; do
not shrink its denominator. `audit-required` is provisional even if numbers
exist. Retain R1/R2/ADJ, disagreement and source/rubric/bundle hashes. Source
changes make the old assessment stale; they do not request a new judge run.
Stage 1 general v3 has 3/4/3 criteria and frozen applicability rules; do not
borrow Stage 2's fixed-six or a historical recall denominator.

Native reads never start or pump a session. An explicit offer GET can publish
local durable offer state but sends no native frame. Browser writes use exact
opaque references, revision and a saved idempotency key. A lost response is
recovered through history, never a fresh key/retry. A physical write is not a
resolved request, terminal turn, model success or research completion.
The optional feedback inbox only records; it does not dispatch UI repairs.

Keep new read-only fields additive, preserve unknown source fields, and reject
unknown modes/action authority. Current wire schema stays strict; update the
compatible response schema/version before accepting a new optional field.
A required identity/schema semantic change
needs a new contract and adapter, then a reviewable PR. UI-only edits may use
the same contract if source identities, metrics and action meanings stay intact.
This candidate does not change rubric/baseline, enable protected import/resume,
grant new model/search/judge authority, or prove actual Windows native or
scientific acceptance. Pending stack and accepted main are reported separately.
