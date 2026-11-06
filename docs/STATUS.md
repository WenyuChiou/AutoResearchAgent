# Research plugin contribution status

Updated: 2026-10-30. This page tracks the current Stage 2 compatibility change;
the plugin README and versioned evaluation contracts remain the capability record.

## Current behavior

The experimental Stage 2 workflow compares supplied evidence, checks candidates,
preserves revisions and prepares a human choice. The current change makes
read-only legacy daily-v3 replay retain the JSON key order of the verified native
output, including a verified semantic correction. It preserves receipt, archive,
prompt, schema, provenance and source validation, and never redispatches a model.

Readiness remains `implementation-only`; research-quality improvement is
`not yet demonstrated`. Human choice, named audit, deployment and formal pairing
are separate. `execution_authorized`, `evaluation_calls_authorized`,
`formal_execution_enabled`, `external_claim_ready` and `usable_for_formal_pairing`
remain false for this contribution.

## Local checks

With Python 3.11 and the pinned plugin test requirements installed:

```powershell
python -B -m unittest discover -s plugins/auto-research-agent/tests -p test_stage2_legacy_prompt_replay.py -v
python -B .github/scripts/stage1_test_scope.py --contracts
```

The new archive fixtures use an injected OS process and synthetic judgments;
they are engineering tests, not real research, model calls or scientific scores.
The PR records actual commands, results, existing skips and deferred checks.

## Next three actions

1. Check the Draft PR's exact-head CI results; local tests do not replace CI.
2. Have the core team review the replay change and retained rejection checks.
3. After core acceptance, let the owner decide whether a separately authorized
   private archive readback is needed; retain unavailable originals as unknown.

## Awaiting owner verification — 2026-10-30

- Actual private legacy archives and the deployed workflow were not exercised by
  this change. No real user choice, audit acceptance or scientific gain is claimed.
