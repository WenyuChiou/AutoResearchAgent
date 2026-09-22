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

## Attach an existing public execution capture

Use the documented [Codex exec JSONL stream](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)
when the approved research runner already captures it. This exporter launches no
agent and does not read private desktop session files. Supplying a capture does
not select or change the frozen model, prompt, tool configuration or runtime.

```shell
python plugins/auto-research-agent/cli/stage1_export create --run RUN --output EXPORT --native-capture CAPTURE
python plugins/auto-research-agent/cli/stage1_export validate EXPORT
```

`CAPTURE` contains exactly the two inputs used here: `events.jsonl` (saved stdout
from `codex exec --json`) and `capture.json`. Other files are not copied. The
runner records time bounds and process exit code and binds the finished stream
to the intended checkpoint. `capture.json` follows `Stage1NativeCaptureSpec` in
the production export schema. Its required fields are:

| Fields | Source |
| --- | --- |
| kind, schema_version, format, scope | `Stage1NativeCaptureSpec`, `1.0.0`, `codex-exec-json-v1`, `captured-invocation` |
| source_run_id | ResearchRun run_id |
| source_state_sha256, source_journal_sha256 | Current checkpoint state and SHA-256 of exact stage_events.jsonl bytes |
| expected_thread_id, events_sha256 | Captured thread ID and SHA-256 of exact events.jsonl bytes |
| runtime_version | Actual runner CLI version, recorded externally |
| started_at, ended_at, exit_code | Runner-observed timezone-aware process bounds and exit code |

Only one thread and one turn per capture are supported. Multiple turns/threads,
duplicate terminals, invalid usage, wrong bindings, malformed JSON and a torn
last line are rejected. Pending items, unknown event/item types and absent turn
completion remain incomplete. Turn failures and fatal errors remain failed.
An individual failed tool does not prevent the agent from finishing its turn.

The export adds `native/capture.json`, `native/events.jsonl`, `native_usage.json`
and manifest flag `native_capture_contract: codex-exec-json-v1`. The derived report
replays tool IDs and line locators, outcomes, elapsed time and reported turn
usage. Updates to one item do not count as extra calls. Command/MCP/file-change/
collaboration status determines known outcomes; completed web items without an
explicit status remain unknown. Changing derived counts and rehashing them fails
validation. Legacy bundles without the flag retain their original format.

These are **captured invocation** observations. They do not establish complete
Stage 1 time, hidden model calls, human interventions, retries or billed cost.
Top-level unknown efficiency totals remain null; `efficiency.json.native_capture`
points to the measured subset. Input/cache/output counters are preserved without
adding cache tokens a second time or treating turns as model calls. Runtime and
time declarations are not authenticated by this validator. The integrator must
verify capture provenance and coverage before using it in a formal comparison.
Keep raw streams private until their task content has been reviewed for sharing.

## Stop fields are not frozen scientific scores

`coverage_rounds_recorded` only says at least one coverage round was recorded.
`operational_stop_checks_satisfied` says the recorded operational gate has no
blockers and chose stop-sufficient. Neither field implements or aliases the frozen
`S1_STOP_EVIDENCE` metric. An evaluator must assess all five frozen components
from the exported evidence. The ambiguous `stop_inputs_recorded` field has been
removed; older input bundles must be re-exported, never silently interpreted as
a frozen-metric result. Failed rounds, unverified closest works and unsaturated
yield cannot make the operational check true. Frozen metric rules are unchanged.
