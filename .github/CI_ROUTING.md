# Project CI routing

This is a performance policy for the existing research-plugin CI runner. It does not establish scientific quality or change research/A-B budgets.

## Single routing table

The reviewed exact production owners and test patterns are in [.github/ci-test-routing.v1.json](ci-test-routing.v1.json). The selector reports route IDs, the table SHA256, changed paths and the final deduplicated module inventory. It unions mixed admitted routes and the existing reverse test-reference closure.

| Changed files | Automatic checks |
|---|---|
| Explicit Stage2 decision-card presentation owners | Stage2 and its ProjectHost/Stage3 consumer domain, loading/stage guards and current CI contracts |
| Dedicated Stage2 selection pane | Stage2/Stage3 Host, interaction/intake and native binding/transport checks plus required guards |
| Dedicated Stage3 planning pane | Stage3/selection consumer and native binding/transport checks plus required guards |
| Existing docs / test-only paths | Existing docs/test-reference selection and current CI contracts |
| Shared Host, stores, auth, runtime, source handling, dependencies, unknown production paths | Broad standard suite |
| Routing table, selector or workflow | Broad standard suite; the routing policy cannot optimize its own validation away |

Only an actual regular-file modification of an exact declared production owner can enter a route. Additions, deletions, renames, executable/symlink mode changes, incomplete metadata or mixed unknown paths keep broad checks. Invalid catalog fields or empty test patterns fail rather than becoming a loading-only success.

## What stays required

- Keep pr-contract and contracts (ubuntu-latest/windows-latest/macos-latest), including scope-failure rejection.
- Automatic runs remain standard, with the existing explicit long-test deferrals. Full long integration is manually requested; no new schedule is created.
- Windows standard keeps its existing loading/stage smoke and separate CI contracts; broad Windows integration remains not-run unless explicitly requested. A routed module inventory is not evidence that Windows executed that domain.
- Production source pushes run source CI; PR body edits run the separate metadata workflow. No skip-ci trailer or required-workflow path filter is introduced.

## Working sequence

1. Implement and run the affected local tests on an isolated branch. Batch fixes for one coherent capability.
2. Stabilize the source diff and finish the required independent reviews before pushing the candidate. Avoid source pushes for description-only corrections.
3. Push the reviewed candidate once. A new source fix requires current-head CI; reuse review evidence only for byte-identical scope.
4. Merge after the applicable human acceptance and actual required checks, then verify post-main.
5. Extend routes only with observed consumer coverage, negative/fallback tests and review. Do not infer independence merely from filenames.

To add a route, name exact existing owner files and conservative test patterns, demonstrate included failures propagate and unrelated fixtures are excluded, and retain explicit unknown/critical fallback. Any routing change itself takes broad CI. Counts and execution time must be measured separately; fewer selected modules alone do not establish a speedup.
