# Stage 1 A/B execution (experimental)

This CLI records a controlled six-subject comparison. It is an execution aid,
not an answer key or a second scoring rule. `judge_bundle.py` and
`paired_evaluation.py` remain authoritative for scores and the paired decision.
The v2 factual validator remains authoritative for hard counts.

Run `python -m stage1_ab --help` with `plugins/auto-research-agent/cli` on
`PYTHONPATH`. All output directories must be outside Git. Copy the exact
`evals/stage1/STAGE1_AB_SUBJECT_PROMPT_v1.txt` bytes to each condition; its
SHA-256 is `9a73fa53b1e660d5a800aa433db617858f24c7c031fe52b302a404fddb769dfd`.

## Separation and sequence

1. On the **private evaluator machine**, two named humans curate and approve
   the v2 answer package and frozen plan. Verify their identities against the
   trusted roster outside this CLI. The validator checks distinct actor
   records and artifact bytes, but cannot authenticate a human identity.
   Keep the private package under `evals/private/` only on that machine.
2. Run `freeze PLAN PROMPT MERGED_RESEARCH_HUB_CHECKOUT PUBLIC_LOCK` on the
   evaluator. It reuses `evaluation_plan.validate_plan`, verifies the prompt,
   private answer/approval bytes, PR #20 readiness evidence and the merged
   research-hub commit `9877f929587e7e44bc2533db118cbb89336bf94f`.
   Transfer only `PUBLIC_LOCK` and the public prompt to the subject host.
3. On the **subject host**, make two independent `CODEX_HOME` profiles and six
   initially empty workspaces. The baseline profile has no custom extensions;
   the treatment profile discovers only `auto-research-agent`. `probe` checks
   each profile's login, CLI version, GPT-5.6 Sol/High availability, native web
   search capability and plugin discovery. The treatment probe also asks the
   pinned model to read and hash the installed skill from inside its subject
   sandbox; discovery alone is insufficient. Confirm the same native tool
   configuration in both profiles. Run `host-preflight CODEX PUBLIC_LOCK
   B_PROFILE T_PROFILE B_WORKSPACE T_WORKSPACE PRIVATE_ROOT MERGED_HUB_CHECKOUT
   REPORT` and keep
   `REPORT` with the pilot bundle. Never put the private evaluator directory
   on this host. A readable decoy private file, changed plugin tree, or
   unverified profile blocks launch.
4. Run `capture CODEX PUBLIC_LOCK CONDITION REPEAT PROFILE WORKSPACE PROMPT
   OUTPUT PRIVATE_ROOT REPORT` in frozen B→T, T→B, B→T order. `capture` stores raw
   JSONL, stderr, final answer, every generated file, timings, usage and hashes.
   `verify OUTPUT` rechecks bytes. A failed or interrupted attempt can use
   `capture ... --resume`; it retains the same run ID and rejects a completed
   run, changed workspace or repeated completed search. A compromised pair is
   incomplete. Never rerun only a weak side.
5. After all subjects end, move blinded copies and needed source bytes to the
   evaluator. A human source checker creates a private annotation JSON per
   subject (see below). `facts ANNOTATIONS HOLDOUT PLAN CAPTURE_DIR EVAL_ROOT
   RESULT` derives v2 P1–P3 counts, checks every evidence byte and invokes
   `stage1_evaluation_result_v2.validate_result_v2`. Baseline evidence may be
   ordinary files or Codex native logs; no treatment ledger is required for B.
6. After checking source excerpts, run `blind-packet FACT_RESULT PLAN
   EVIDENCE_PACKET OUTPUT` under `evals/private/`. It binds the v2 hard facts
   and source-excerpt bytes while omitting the condition label. `judge CODEX
   PLAN PACKET RUBRIC R12_PROMPT
   ADJ_PROMPT R1_PROFILE R2_PROFILE ADJ_PROFILE PRIVATE_OUTPUT` runs R1 and R2
   in separate authenticated profiles. It runs ADJ only on a score or
   major-error disagreement. The output bundle is validated by
   `judge_bundle`; triggered named human audits leave it unusable until a
   completed accepted audit is attached and revalidated.
7. Create the canonical paired request with exactly six usable bundles and
   run `paired REQUEST DECISION`. The command delegates to
   `paired_evaluation.evaluate_request`. `report DECISION PLAN HOLDOUT
   RESULT1 ... RESULT6 --output REPORT` lists separate P1, P2 and P3 pair
   deltas, median and range, hard counts, failures and costs. There is no
   composite score or automatic external claim.

`export-ledger RUN EXPORT --native-capture CAPTURE` and
`validate-ledger-export EXPORT` delegate to the existing `stage1_export`
implementation when a Stage 1 ledger run exists. Preserve its manifest
alongside the raw subject bundle; it does not replace the six Codex subject
captures.

## Annotation input

`facts` expects `evidence` as an ID-to-`{path, sha256, locator}` mapping.
Paths must be below the evaluator's `evals/private/` and each byte hash is
verified. `works` has `work_id`, `identity_status`, `link_status`, optional
`identity_evidence_id`, `link_evidence_id`, `discovery_evidence_id`,
`anchor_evidence_id`, `cluster_evidence_id`, `matched_anchor_ids`,
`verified_clusters`, `year`, `recent`, `included`, `source_version` and
`access_date`. `claims` has `work_id`, `status`, `locator_evidence_id` and
`central_source_mismatch`. `decisions` has `reason_evidence_id`. `searches`
has `kind` (`recent`, `closest-work` or another path), `state` (results,
zero-results, backend-failure, credential-failure or rate-limited), and
`evidence_id`. Also provide `stop_evidence_id`, `major_issues`,
`human_interventions` and `actual_cost` (null if unavailable).

Every positive identity, link, anchor, cluster or claim finding requires a
source check. `unverifiable` remains distinct from `incorrect`. A DOI response
alone is insufficient to mark a central claim supported. The annotation JSON
and source bytes stay private. The saved count result is a mechanical
derivation from these reviewer labels, not an autonomous truth judgment.

## Stop conditions

The current checkout contains no formal private holdout or roster-verifiable
approvals. Do not execute the six South Korea subjects from this PR. The
non-South-Korea B/T pilot is unscored and may start only after both clean
profiles pass login, model, native search and functional plugin preflight. An
initial Canada pilot on 2026-09-23 exposed a treatment skill read denial even
though plugin discovery passed; its captures are retained as a failed pilot,
not paired evidence. The subject host must be configured and re-probed before
retrying it. Raw pilot bundles and preflight reports remain private. Three
formal pairs would describe case-specific direction and variation, not
statistical significance.
