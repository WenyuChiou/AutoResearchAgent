# ResearchBrief v1: confirm the direction before narrowing the search

The flow is: natural-language direction → needs and open questions → necessary
clarification or bounded exploration → user scope decision → concepts and queries
→ retrieval, reading and comparison. This contract has no default country.

A proposal is a suggestion. A user decision is permission to use that scope.
Keep those records separate. Existing explicit constraints count as decisions;
do not ask again just to fill a new form. Record the original turn verbatim.

## Versioned records

`ResearchBrief`, schema version `1.0.0`, contains:

| Field | Meaning |
|---|---|
| `original_description` | Original user direction, unchanged in every revision. |
| `needs` | Objects with `need_id` and a concrete knowledge `question`. |
| `scope_fields` | Each field has `field`, boolean `material`, and `reason`. Geography is always considered, even when immaterial. |
| `suggestions` | Suggested value and its literature, data, validation bases and source refs; not a decision. |
| `decisions` | Append-only events containing event ID, field, status, value, actor, authority=user, verbatim user_input, source_ref and recorded_at. |
| `previous_sha256` | Previous brief file hash; null for the first record. |

Decision status is `specified`, `unrestricted`, `not-applicable`, `pending`, or
`recommendations-requested`. Only `specified` carries a value. `not-applicable`
needs an explanation. All material fields must be resolved before compilation.
The user may leave geography unrestricted while other fields are decided.
Suggested choices must have `literature_basis`, `data_basis`, `validation_basis`
and nonempty `source_refs`. A selection may name `selected_suggestion`.

Use the plugin `cli/` directory on `PYTHONPATH`:

```shell
python -m stage1_brief record request.json brief-v1.json
python -m stage1_brief validate brief-v1.json --confirmed
python -m stage1_brief compile brief-v1.json search-request.json plan-v1 --as-of 2026-09-26 --actor researcher
python -m stage1_brief validate-plan plan-v1 brief-v1.json
python -m stage1_brief record revised-request.json brief-v2.json --previous brief-v1.json
```

`search-request.json` contains the existing coverage `proposal` and
`query_bindings`. Every family has a `family_id`, nonempty known `need_ids`,
`purpose` (`study-evidence` or `transferable-method`) and `scope_filters`.
Study filters must agree with specified decisions. Broad decisions cannot carry
a hidden filter. A method comparator may declare another geography only with a
`transfer_rationale`. It does not replace the study scope. Inspect concept terms
and authored adversarial queries too: a structural validator cannot prove a
natural-language term was correctly classified.
Declared filters are inserted into topical, recent and adversarial queries;
recording a filter without applying it is not a valid bound plan.

The output keeps existing coverage artifacts and adds `research_brief.json` and
`research_brief_binding.json`. The latter binds the exact brief, proposal,
family-to-need mapping and coverage manifest. A new brief revision requires a new
plan directory; validation against the new brief rejects the old plan. No file
is overwritten. Decision records are operator attestations, not cryptographic
proof that a named person approved them.

## Intake metrics are not literature scores

- Unauthorized declared scope narrowing: zero for an accepted plan; a conflicting
  scope filter rejects compilation. Rejected attempts and semantic query-review
  findings must also be retained by the caller, not omitted from the report.
- Scope decision traceability: events with actor, original input, reference and
  time / all decision events; no events means unavailable, not 100%.
- Necessary clarification complete: all material scope fields resolved.

These measures verify the entry behavior separately from P1–P3. Unit tests do
not demonstrate better papers or authenticate a user's identity. The v3 rubric
and its ten criteria are unchanged.
