# Stage 1 coverage planning

The coverage CLI freezes a plan, records saved execution rounds and preserves
version-bound coverage reviews. It does not contact providers or choose closest
works. Search completion is distinct from qualified coverage.

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

The executable synthetic tests compile both four and six clusters into
unexecuted queries, check the recent window, reject missing concepts and weak
stop obligations, and detect a changed query plan. The four-cluster fixture
tests the generic compiler; it does not prescribe coverage for every research
case. A run using `aging-bidirectional-rubric-v1` must use the six roles in its
[Stage 1 rubric](../evals/rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md).
Older four-cluster baseline results keep their original scoring contract.
Reproduce the compiler tests with:

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
verified works. The validator separately recomputes qualified-work yield from
current version-bound reviews. Empty results or budget exhaustion alone do not
permit `stop-sufficient`.

## Versioned work reviews and expansion

Use `review-work --run RUN --request review.json` to record an assessor's
coverage judgment. The request names `work_id`, `version_id`, `cluster_claims`
(cluster ID to relevance claim event ID), `closest`, `identity_status`,
`identity_claims`, `assessor` and `rationale`. The CLI binds the review to the
current candidate revision and include decision. A later discovery or screening
decision makes it stale; re-review appends a replacement event.

Identity claims have five keys: `title`, `authors`, `year`, `identifier`,
`version`. Use `null` for unavailable evidence and status `unverifiable` or
`conflict`. Status `verified` requires five distinct, supported, located claims
from saved full text for that version, without unresolved metadata conflict.
The assessor must read each source and explain the field comparison. A resolver
response, abstract or metadata match does not meet this contract. The validator
checks links and quotes, not the truth of those judgments, source authenticity
or a person's identity. The event explicitly says `reviewer-attestation` and
does not overwrite bibliographic comparisons or candidate identity state.

Use `expand --run RUN --request expansion.json` with `operation` (`references`
or `cited-by`), `work_id` and `version_id`. The seed must already have been
discovered in this run. Record backend output and a receipt using the same
ledger path as search. Expansion failures and truncation remain visible.

## Gate, checkpoint and human actions

Run the ledger's `validate`, `gate` and `checkpoint` commands after closing a
round. The validator report includes per-cluster work IDs, recent-sweep status,
verified closest-work attestations, each round's newly qualified work IDs,
outstanding human requests and explicit blockers. The checkpoint saves that
report immutably and rebuilds `coverage_and_stop.md`.

`stop-sufficient` requires all planned clusters to meet their declared minimum,
a complete recent sweep, enough currently reviewed closest works with all five
identity fields supported, both citation directions complete, no unprocessed or
unscreened discoveries and two consecutive complete rounds with no new qualified
works. Failed, truncated, unreviewed or partially extracted rounds reset that
streak. A subsequent review or screening reversal invalidates the prior coverage
snapshot. Budget exhaustion returns `human-review` when obligations remain.
This is an operational stopping rule based on recorded reviews; it does not
prove source authenticity, scientific truth or exhaustive literature retrieval.

`human-action --run RUN --request action.json` records `action` (`accept-stop`
or `request-cluster`), named `actor`, verbatim `user_input`, the exact
`reviewed_state_sha256` from the validator and optional `cluster_id`. Stale state
hashes fail. Acceptance preserves the choice without changing any verification
or blocker. A requested cluster requires all its planned queries to start after
that request and finish completely. Screening reversals use the ledger's
existing human-authorized `decide` command. These records preserve supplied
authorization; authentication of the named person remains the caller's duty.
