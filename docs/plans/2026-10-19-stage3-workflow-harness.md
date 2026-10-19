# Stage 3 Workflow Harness Implementation Plan

**Goal:** Provide a topic-neutral, offline coordinator for the existing strict
selected intake, saved plans, semantic reviews and A/B preparation.

**Architecture:** Extend `cli:stage3-plan`; reuse admission, private storage,
saved-plan inspection and semantic status functions. Save a new immutable,
externally pinned checkpoint for each explicit action. No coordinator command
launches a model, downloads data, executes research or authenticates a person.

**Tech Stack:** Python standard library, existing Stage2/Stage3 contracts and unittest.

The user has authorized implementation in this session. Native Codex owns
execution and review; unavailable legacy superpowers executors are not required.

1. Add `cli/stage3_plan/workflow.py`: start, inspect and explicit attachment
   transitions; preserve source bindings, failures and previous checkpoints.
   Re-admit source and reconstruct current status on every inspection.
2. Add `cli/stage3_plan/preparation.py`: validate a user/host-supplied A/B
   preparation definition; bind the same intake, common settings, separate arm
   protocols, rubric and reviewer settings. Emit three alternating unrun pairs,
   separate null P7/P8/P9 scores and explicit missing formal authority.
3. Extend `cli/stage3_plan/__main__.py` with offline `workflow-*` commands.
   Actual generation and trusted-host plan decisions retain their existing
   explicit interfaces. A saved selection is reused, never inferred.
4. Add `tests/test_stage3_workflow.py`: exercise saved-plan/review attachment,
   stale bindings, external tampering, failed and legacy inputs, private outputs,
   resume without callbacks, source revision invalidation and A/B preparation.
5. Extend the existing Stage3 capability registration and reference document;
   preserve all frozen historical contracts, scores and accepted evidence.
6. Run focused tests, quality checks and the registered standard plugin suite.
   Stage only explicit files, obtain independent code review on the stable diff,
   correct findings, then deliver a fork PR under the existing dependency rules.

Acceptance: all workflow actions retain `execution_authorized=false`; no model
or research callback is invoked; source/plan/review versions cannot silently
change; unknown and failed results remain visible; preparation cannot become
formal A/B or a human confirmation. Live receiver, native host authentication,
UI and scientific-quality improvement remain separate unverified milestones.
