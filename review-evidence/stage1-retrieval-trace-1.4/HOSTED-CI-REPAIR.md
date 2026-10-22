# Hosted test portability repair

PR366 head2b124808 failed Stage1 run39631145301, attempt1. Preserve this
failure separately from the earlier local run and superseded471718 run.
Ubuntu ran3348 tests with1 failure,0 errors,9 skips,0 incomplete. macOS ran3348
with0 failures,2 errors,9 skips,0 incomplete. Their stage-contract step12
failed and step13 was skipped. Windows9-13 passed only its standard smoke.
The complete required-check set is unknown. No unchanged CI was rerun.

The complete Ubuntu job119329500136 log has SHA-256
`13999aa0a0f71596f9a9a2717c4aa2bf2efa3b18280bbfcda80b379ebd8eab7d`.
The complete macOS job119329500081 log has SHA-256
`ef41471ef2e32d67b8bd220ef5851908e06dd8f7beddc57b0b9a50b61b9122d9`.
Both were read once and saved locally; their hashes match Core's independent
triage in PR366 comment6321334934. No full log or private data is copied here.

## Exact causes and bounded repair

The unchanged legacy XLSX writer retains the host ZIP creator system: Windows0
and Unix3. The original37 golden hashes were captured on Windows. An isolated
probe loads the four old formatter modules directly from373f git blobs and
compares them with the treatment. Both profiles produce exactly equal37-file
maps between base and treatment. Only five XLSX hashes differ between host
profiles: each uncompressed member is identical, all visible ZIP metadata is
identical except create_system, and the only raw-byte changes are the creator
OS byte of each central-directory header. There is no source content or
formatter regression in this failure.

Keep the original37 Windows hashes unchanged. Add only the five independently
derived373f Unix XLSX hashes and select the exact native creator profile0 or3
in the compatibility test. Continue comparing whole-file SHA-256 values;
never normalize the tested exports or blindly refresh hashes from treatment.
Unexpected creator profiles are rejected. Full mismatch output identifies
the contract and native profile if this check fails again.

The macOS errors are the two new tests passing an aliased temporary root to
private_output. That guard deliberately rejects links among all ancestors.
Construct only these synthetic fixtures under the resolved system temporary
parent, as existing repository tests already do, and assert that the fixture
root is physical. Do not resolve user-provided production paths, alter
reject_links, or weaken identity, byte, credential or path boundaries.

## Scope and verification boundary

This repair changes tests, one test hash profile and this note only. It changes
no producer CLI byte or frozen1.1.4 package. The producer/runtime remains
471718ea7b63388a19d47760d8f9da10ed31af13; the later publication/test head and
fresh necessary CI must be recorded separately. Seven trace tests passed on
Windows and seven passed with a simulated Unix ZIP creator. Two retained path
refusal tests passed; one actual directory-link test was skipped because this
Windows account lacks symlink creation privileges.132 PR/CI contracts, ruff
check/format and codespell passed. The independent baseline/profile evidence
has SHA eaa5e2a53053992b648a1ed1576859cf26bc6e85ff175acc536da58ef5a686dd.
Simulating ZIP metadata on Windows is not actual macOS execution;
native Linux/macOS full-standard CI remains necessary before producer seal.
Exact commands and outcomes are recorded in the PR and local receipts.

Core's original361/362/365 delivery stays frozen and separate. The latest UI
keyboard/folding/current-detail acceptance is bound to sealed1.1.3 only.
New1.1.4 consumption, portable fresh-extraction acceptance, review/merge and
formal scientific/Stage2 admission are not established by this repair.
