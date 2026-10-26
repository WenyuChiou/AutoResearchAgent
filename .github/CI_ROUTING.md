# Project CI routing

This is a performance policy for the existing research-plugin CI runner. It does not establish scientific quality or change research/A-B budgets.

## Single routing table

The reviewed exact production owners and test patterns are in [.github/ci-test-routing.v1.json](ci-test-routing.v1.json). The selector reports route IDs, the table SHA256, changed paths and the final deduplicated module inventory. It unions mixed admitted routes and the existing reverse test-reference closure.

| Changed files | Automatic checks |
|---|---|
| Explicit Stage2 decision-card presentation owners | Stage2 and its ProjectHost/Stage3 consumer domain, loading/stage guards and current CI contracts |
| Dedicated Stage2 selection pane | Stage2/Stage3 Host, interaction/intake and native binding/transport checks plus required guards |
| Dedicated Stage3 planning pane | Stage3/selection consumer and native binding/transport checks plus required guards |
| Registered Stage2 workflow/check/live backend and Stage2 Host services | Stage2/Stage3 domains and actual Stage1→2/saved-source/Stage123 bridges; unrelated Stage1 search/deliverable suites are excluded |
| Registered Stage3 planning backend | Stage3 and selection/intake, provider and Stage123 bridge checks; unrelated Stage1 search/deliverable suites are excluded |
| Existing docs / test-only paths | Existing docs/test-reference selection and current CI contracts |
| Modified shared Host, cross-stage stores/auth/native runtime/source handling, dependencies or unknown production paths | Broad standard suite |
| Routing table, selector or workflow | Broad standard suite; the routing policy cannot optimize its own validation away |

Only an actual regular-file modification of an exact declared production owner can enter a route. Additions, deletions, renames, executable/symlink mode changes, incomplete metadata or mixed unknown paths keep broad checks. Invalid catalog fields or empty test patterns fail rather than becoming a loading-only success.

## Stage scope and duration profile

Stage scope chooses affected modules. The standard/full profile independently decides whether long integration cases run. A Stage3-only backend edit does not become a Stage1 change merely because it imports an unchanged shared helper. Conversely, modifying the shared helper itself still needs its consumers.

Backend owners are exact existing files, not an unchecked directory shortcut. The initial reverse-import inventory found Stage1 model calls consuming Stage2 native/namespace/process code and their policy/trace-file/handle/seal dependencies; those seven files retain broad checks. Stage2-owned workflow storage is routed with its Stage2/Stage3 consumers and prompt-boundary tests. Native provider error handling and saved-source/Stage123 bridges stay in the relevant backend suites. New or unclassified files still need review before a route is added.

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
