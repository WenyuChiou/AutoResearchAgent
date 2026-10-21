# Producer publication CI repair

The release documents remain pinned at
`30fe8dda69ba8685c4929ecc3f11f4f1a895e11b`. Data producer
`1e8d3c16cc784a49c00ede80c88a6eef5cc204ac`, executed runtime
`7cbb6396d5a730ee364c7aa84278085120fd35f1`, private package bytes,
`SEAL.md` and `UI-HANDOFF.md` are unchanged by this CI repair.

## Observed failure

[Stage1 run 39591955014, attempt 1](https://github.com/WenyuChiou/AutoResearchAgent/actions/runs/39591955014)
used publication head `30fe8dda69ba8685c4929ecc3f11f4f1a895e11b`.
Scope correctly selected docs. macOS job `119195002282` and Ubuntu job
`119195002599` failed step 12 because the test plan selected plugin loading
although docs jobs deliberately do not install the Codex CLI. Each ran eight
tests: seven stage-contract passes and one missing-CLI failure. Step 13 did not
run. Windows job `119195002443` passed steps 12/13; governance step 14 was
skipped. The repository-required check set remains Unknown.

## Change and coverage

Reuse `ci_scope.plugin_test_scope` after every changed path has passed existence
and classification checks. Pure docs now select `test_stage_contracts` only,
matching the existing workflow and contributor contract. Selector/workflow edits
still select full tests; non-docs CI/test/UI changes retain plugin loading.
Deleted, runtime, mixed and unknown inputs retain their existing full path.
No workflow, platform job, deadline, long-integration policy or research gate
changes. This CI infrastructure is not a new scientific capability.

The new regressions failed before the selector repair. After the repair:

- Six CI/PR contract modules: 132 tests, zero failures/errors/skips.
- Exact P3 invariant, real plugin loading, stage contracts and capability
  registry: 14 tests, zero failures/errors/skips.
- Ruff format and check passed for both changed Python files.
- Pure-docs tests exercise default/Linux/macOS/Windows selection with a loading
  module that deliberately raises. A missing stage-contract module still fails;
  non-docs loading failures still propagate.

Platform parameters in local subprocess tests simulate selection; they do not
replace native three-platform CI. This repair changes the selector itself, so
the new PR revision must receive fresh full-scope CI, separately from the
original docs failure and the previously tested runtime. No automatic rerun or
CI cancellation was requested. Full/manual-only integration, receiver download,
Core review/merge and actual UI acceptance remain separate pending items.

## Independent local review records

Two separate read-only AI reviewers examined the two-file patch against
`30fe8dda69ba8685c4929ecc3f11f4f1a895e11b`:

- `/root/ci_scope_code_review`: no blocking correctness finding. Path validation,
  self-selector full scope and non-docs loading remain intact. The CI scripts
  have no existing capability owner and are not standardized production entry
  points requiring a new registry entry.
- `/root/docs_ci_scope_audit`: no blocking harness-drift finding. The patch
  matches CONTRIBUTING's docs-only stage-contract policy and preserves Windows
  standard smoke, full/manual policy, source data, research and approval gates.

These are local AI static reviews, not authenticated external Core review,
approval or acceptance. Core must perform its own review before merging.
Reviewers did not run tests or edit source; test results above were executed by
the producer. The exact reviewed two-file binary Git patch SHA-256 is
`4a1c1669df93d01a04dd2ffd92f148161d3960a88c4b729e49f50ba74801ab5c`.
Reviewed file SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `.github/scripts/stage1_test_scope.py` | `fcf1bdfa970cae6f2e8a4b4ec10a373de1c4743da8d655638174280d805e9d3d` |
| `.github/scripts/test_stage1_test_scope.py` | `bbfcf39b8279ed66145dde394b2d6af60353b9ef0ffaeff044f63e05b9160085` |

Producer 1.1.3 stays sealed for receiver integrity checks. This CI follow-up
does not certify receiver possession, UI display, research quality or Stage2
admission. UI must return same-version API/page/export evidence for all three
requirements from `UI-HANDOFF.md` before UI acceptance can be reported complete.
