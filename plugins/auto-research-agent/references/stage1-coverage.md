# Stage 1 coverage planning

The coverage CLI freezes a plan and records saved execution rounds against it.
It does not contact providers, choose closest works, or implement a
sufficient-stop gate. Search completion is distinct from qualified coverage.

The skill authors the decomposition using the actual question. Identify the
population, phenomenon, proposed method and validation question. Split the
question into coverage clusters that cover its substance and method; each
cluster needs a concrete subquestion and at least one query family. Record
inclusion and exclusion criteria before screening. Represent concepts with
terms and synonyms; use explicit adversarial queries to look for contrary
findings, alternative methods or missing perspectives. The compiler checks
structure and references; the skill and reviewer judge scientific adequacy.

Use the `Proposal` definition in
[the versioned schema](../schemas/stage1-coverage-plan.v1.schema.json).
Each `concept` has `concept_id` and `terms`. Each cluster has `cluster_id`,
`label`, `question`, `min_included_works`, and `query_families`. Each family has
`family_id`, `concept_ids`, and `adversarial_queries`. IDs must be unique;
references must exist. Required `stop_policy` fields are `max_rounds`,
`consecutive_zero_yield_rounds` (at least two), `closest_min_verified` (at least
one), `require_references: true`, and `require_cited_by: true`. These are
obligations for the eventual gate, not assertions that they have been met.

With the plugin's existing Python 3.11 dependencies, run:

```shell
python plugins/auto-research-agent/cli/stage1_coverage compile --input proposal.json --output ../coverage-plan --as-of 2026-09-20 --actor named-planner
python plugins/auto-research-agent/cli/stage1_coverage validate ../coverage-plan
```

Use the actual run's frozen as-of date. The recent window is that calendar year
and the previous two years. The compiler creates `coverage_plan.json`,
`query_plan.jsonl`, and `plan_manifest.json` in a new directory. It keeps topical,
adversarial and recent queries separate, and stores their cluster/family links.
Recent queries carry the exact year filter and year ranking. Every query has
`execution_status: not-executed`. Never copy these counts into completed-search
or coverage numerators.

The manifest uses shared ArtifactRef records plus byte counts. Validation checks
the hashes, regenerates the plan/query records, and rejects mismatches. It does
not authenticate the planner or certify the question decomposition. An amended
plan goes to a new directory; do not overwrite an accepted plan or silently
change its as-of date. Later run integration must record which plan hash applies
to each attempt and require review when the obligations change.

The executable synthetic test compiles four clusters into twelve unexecuted
queries, checks the recent window, rejects missing concepts and weak stop
obligations, and detects a changed query plan. Reproduce it with:

```shell
python -m unittest discover -s plugins/auto-research-agent/tests -p test_stage1_coverage.py -v
```
# Saved execution rounds

After compiling, initialize a ledger with the same objective as the plan topic.
Bind it once before any search. For example, `bind.json` contains
`{"backends":["synthetic"],"limit":10}` for an offline test:

```shell
python plugins/auto-research-agent/cli/stage1_coverage bind --run RUN --plan PLAN --request bind.json
python plugins/auto-research-agent/cli/stage1_coverage open-round --run RUN
python plugins/auto-research-agent/cli/stage1_coverage start-query --run RUN --planned-id PLANNED_ID
```

`start-query` records an attempt and returns its ID. It does not contact a
provider. Record the actual backend attempts, saved stdout/stderr/results and
query completion with the ledger CLI. Then record a receipt, for example
`{"query_event_id":"e000012","truncated":false,"note":"Saved provider response has no continuation token."}`:

```shell
python plugins/auto-research-agent/cli/stage1_coverage receipt --run RUN --request receipt.json
python plugins/auto-research-agent/cli/stage1_coverage close-round --run RUN
```

The query text, year window, ordering, result cap, plan and round are bound
before execution. Validation replays these links. A round is complete only
when every planned query finished on every declared backend, without failures
or truncation. Unknown truncation is `null`; missing receipts and results at
the cap remain incomplete. This conservative cap rule may require a larger
bounded rerun. Receipt corrections append a replacement link during the open
round. Closed rounds and failures remain immutable, including after recovery.

The round records newly discovered work IDs, which are not qualified or
verified works. Completing an empty round or exhausting the three-round budget
does not establish coverage or permit `stop-sufficient`.
