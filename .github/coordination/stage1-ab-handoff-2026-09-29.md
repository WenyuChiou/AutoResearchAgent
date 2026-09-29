# Stage 1 A/B operator handoff (2026-09-29)

This is a coordination record for the designated teammate. It changes no harness code or evaluation rule. Keep this PR open while the operator completes the gates below; the core team owns review, freeze approval, and merge decisions.

## Download and verify

- [Public operator packet v2](https://drive.google.com/file/d/1c0BlFozOl5iDRzS2GTzB7L3Ap9_P49ib/view?usp=drivesdk), SHA-256 `75a507f81c3ca8406d52a3cdc0443ed16970b93d92b0c52dee9724379323d718`. It contains the exact English prompt, public inputs, return checklist, and pinned state.
- The restricted v33 saved-output archive is shared with the designated operator on Drive. Download [part 1](https://drive.google.com/file/d/1xD3DgJTEPAczAQ1KJClFWLNi396EtEFC/view?usp=drivesdk), [part 2](https://drive.google.com/file/d/1dvOhsBxbwY9TGCsWhWfMnmA2zY7jgDYj/view?usp=drivesdk), and [part 3](https://drive.google.com/file/d/1GUqPpOWYfCOTUqCr9kIv23oR0Xt3iycZ/view?usp=drivesdk) into a private directory outside Git and the A/B subject workspaces.
- Use the [transfer manifest](https://drive.google.com/file/d/106j4lczBMiGmOC7jDdSrVghBosYzrsm7/view?usp=drivesdk) and [assembly instructions](https://drive.google.com/file/d/18eBY2zlomLQwruxbyJGd4ofyVolKypOF/view?usp=drivesdk). The assembled archive must be 194,398,726 bytes with SHA-256 `1cf1df8176bf64c3be30c24f04cf33598efe1c979c32b41eccff8e45c37c14d7`.
- The pinned fork `main` is `1de466ceb5d9788713899a1c366197c6e7818ac0`; the Stage 1 plugin tree is `f78f488b9a341c8b1250fe481951adb67b8e9bd5`. If either differs, report the mismatch before launching a subject.

## Operator sequence

1. Start a new GPT-6 Astra / High / Goal Mode coordination task and paste the packet's `TEAMMATE_CODEX_PROMPT_EN.txt`. The A/B subject model remains GPT-5.6 Sol / High / Task or Default mode.
2. Verify clean, separate A and B profiles, identical native Codex search and reading abilities, plugin isolation, runtime bytes, and all frozen hashes. A uses native Codex; B adds only the reviewed Stage 1 research harness.
3. Replay the six saved U.S. outputs for the unscored G1 diagnostic; do not rerun those subjects. Then run one new, unscored Japan A/B pilot, including source audit, researcher deliverable, and Stage 1 to Stage 2 import validation.
4. Return a `FREEZE_READY` manifest and exact SHA-256 to Eric. **Stop before formal A/B** until Eric replies with `FREEZE_APPROVED` for that exact digest. A changed byte invalidates approval.
5. After approval, run the prospective U.S. pairs in order A→B, B→A, A→B. Preserve all runs, unknowns, judge and human-audit status, costs, failures, and paired decisions. Never selectively rerun one arm.
6. Return the private evidence ZIP and public-safe CSV/JSON/HTML summary. The ten frozen Stage 1 criteria must show P1, P2, and P3 separately; the final outcome may be improved, not improved, or inconclusive.

Do not commit source PDFs, private excerpts, saved subject answers, credentials, or answer keys to GitHub. If a gate fails, return the exact evidence and the smallest focused fix PR for core-team review; do not silently change the frozen experiment.
