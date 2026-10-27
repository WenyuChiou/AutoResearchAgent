# Stage 3 planning in the project Wiki

The existing project Stage 3 link and the Stage 2 selection link open
`/project-stage3-planning.html#<project_ref>`. The page uses the existing
authenticated planning view. It neither admits a new source nor changes a choice.

For each saved SQ, it joins `question_ref` to `question_plans`, resource uses to
`resources`, and design/analysis/result IDs to their original records. It shows
necessary evidence, units, claim limits, materials and access conditions, method,
procedure, comparisons or justified non-applicability, uncertainty, possible result
interpretations, blockers and minimum outputs. Shared designs remain visibly shared.
Milestones retain their dependencies and duration basis; no fixed topic or duration
is imposed. Unknowns retain the original evidence requirement, deadline, owner,
trigger, fallback and scope condition. Plan 1.0 stays 1.0; absent 1.1 fields are
displayed as not supplied, without manufacturing condition resolution.

The evidence panel reports saved job/plan states and the five supplied authority
flags. It does not infer semantic acceptance, human plan confirmation or real-case
receiver acceptance. A missing value, empty recorded list, `null`, `false`, zero,
unknown, failure and not-run remain distinct. Unresolved references are visible;
no layout check upgrades availability or removes a blocker. Raw plan and receipt
views remain available. Source content is inserted with `textContent`, not HTML.

Opening, refreshing, changing language or switching projects only reads saved
state. Existing explicit prepare/run/inspect/recover controls retain their original
contract. There is no new API, resolver, timer, runner, permission or readiness gate.
Scientific results remain the recorded values; rendering never executes research.

Offline DOM coverage is invoked by `PlanningWikiTests` in the existing planning
HTTP test module. It exercises joins, shared designs, unknowns, legacy missing
fields, lawful alternatives, inert source text, languages and stale project reads.
Browser layout verification uses a separate synthetic UI fixture, not an actual
human selection or strict receiver test. It cannot establish scientific validity,
calibration, A/B improvement or experimental reproducibility.

Scientific review and P7–P9 definitions remain in
[the planning specification](stage3-scientific-planning.md) and
[evaluation guidance with sources](stage3-evaluation-guidance.v1.md).
