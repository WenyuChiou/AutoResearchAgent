# Stage3 planning jobs

`stage3_plan.jobs.PlanningJobs` wraps the existing host-owned `Journal`,
`draft_plan` and immutable workflow; it adds no session/process manager or gate.
The host retains authentication, current-frontier selection and ownership.
Supply a bound project, owner token, private root, externally pinned current
checkpoint and adapter context with its existing deadline. Stage2 is unchanged.

1. `prepare` binds project/index/workflow/source, selected versions, all SQ,
   separate human/reviewer hashes, schema/configuration/runtime, then saves an intent.
2. `run` persists dispatching before one existing planner callback. NativePlanner
   retains actual native deadline/capture enforcement and zero retries.
3. Raw output passes existing source-aware validation before an immutable workflow
   checkpoint is attached. Drafts still need semantic review; blockers stay visible.
4. `inspect` and same-key replay make no calls. Source, checkpoint, adapter or
   runtime drift requires an explicit new version/key. Failure streams are pinned.
5. Partial/uncertain attempts never resend. `recover` requires an explicitly pinned
   saved plan manifest and validates artifacts before reconciling the journal.

Journal completed is terminal bookkeeping: inspect outcome=saved versus failed.
Interrupted jobs can remain dispatching/execution-unknown. Exit0 or file presence
alone cannot complete them. Missing streams/exit data stays unknown; oversized
exception streams retain size/hash with retained=false rather than fabricated bytes.

Registered tests use authored admission mocks and stub callbacks; native/process
calls are forbidden. Real choice, deadline enforcement, identity/isolation, provider
recovery, external exactly-once and scientific quality remain unverified. All five
authority/formal-pairing flags stay false. Evaluation/campaign and host HTTP wiring
remain host-owned.

`evaluation_jobs.EvaluationJobs` adds a single configured R1/R2/ADJ job over the
same journal and existing request/record validators. It retains exact raw/prose,
streams, errors and null vectors; inspect/recover never calls the evaluator.
Optional campaign receipts/index use Delivery A's pinned modules, not a new
evaluator. Missing campaign dependencies reject before dispatch; that integration
requires the combined candidate. Native identity/isolation remain unverified.
