# Stage 1 evaluator inputs

This command copies a validated, checkpointed run into a new directory that an
evaluator can replay without the original directory. It is the Stage 1
**evaluation-input** slice. It does not run searches or scientific evaluation.

From the repository root:

```shell
python plugins/auto-research-agent/cli/stage1_export create --run RUN --output EXPORT
python plugins/auto-research-agent/cli/stage1_export validate EXPORT
```

Both commands return JSON and exit nonzero on failure. `EXPORT` must be a new
directory outside `RUN`. Complete the latest checkpoint first. Export takes the
writer lock, checks the source without repairing it, and copies only known run
files and referenced artifacts. Unrelated notes are not copied. Existing output
is never replaced. An interrupted copy has no completed export manifest; preserve
it and inspect the failure before choosing a new output directory.

The bundle contains `source/`, `metric_inputs.json`, `efficiency.json`, and
`export_manifest.json`. The manifest binds the source state, exact journal,
checkpoint, format version, and every copied file's bytes and SHA-256. Validation
checks those bytes, replays the source ledger and recomputes both input files.
Changing a count and updating its file hash still fails recomputation. Later
changes to the original run cannot alter an existing bundle.

| Input | Recorded meaning | What still needs external evidence |
| --- | --- | --- |
| P1 | Candidate, claim, identity comparison and coverage review event IDs | Final answer, central claims, source identity and claim support audits |
| P2 | Operational coverage, included works' consistent recorded years and recent fraction | Scientific coverage, private core and must-have matches |
| P3 | Included works with discovery paths; all annotated claims with locators; screening/checkpoint decisions with reasons | Central-claim denominator, source access dates and adequacy of trace |
| Efficiency | Saved queries, backend attempts/outcomes, pending attempts, recorded human actions and ledger time span | Complete research elapsed time, host calls, retries, model usage and cost |

An included work is one whose latest screening decision is `include`. A
conflicting or missing year is `null` and excluded from the recorded-year
denominator; all included work IDs and their recorded years remain visible.
The recent window is used only when recorded query arguments agree on a year
range. Operational coverage is the existing validator's replayed report, not a
second implementation of coverage rules. P3 reason counts include every
screening decision and checkpoint, including reversals and earlier checkpoints.

Zero denominators have a null ratio and `not-applicable` status. Unknown
numerators, denominators, audits and platform usage remain null/`unavailable`.
Save timestamps are not source access dates. A ledger time span is not full
research wall time, especially for imported observations. A saved claim locator
is not proof that the claim is correct. R1/R2/ADJ remain `not_scored`; the Major
Error Gate remains `not-assessed`.

For example, three queries with four backend attempts can include two successes
with records, one successful empty response and one HTTP 429. Export preserves
all four outcomes. If the only work was included and then excluded, the included
population is empty while both decisions and both discovery paths remain in
`source/`. This does not become a perfect coverage or quality score.

The production contract is `schemas/stage1-export.v1.schema.json`. It deliberately
does not claim to be a completed `Stage1EvaluationResult`: that existing
evaluation contract requires facts the ledger cannot supply. An independent
evaluator must bind this bundle to its frozen plan/builds, native logs, answer,
private holdout and required audits before using the existing evaluation
validators. Production export never reads the holdout or evaluation directory.
