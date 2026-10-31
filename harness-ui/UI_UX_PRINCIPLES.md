# Wiki UI and UX acceptance principles

This contract applies to the six-stage Wiki, embedded selection, standalone
planning pages, materials, history, settings and future HTML entry points.
It preserves the existing research-workbench visual language. It does not
change research, eligibility, evaluation, permissions or execution authority.

## Information before detail

- A page first answers: where am I, what is saved, what matters for my decision,
  and what can I do next? Use one page title and one primary next action.
- Direction summaries retain the question, method, material summary, important
  limitation and next check. Do not hide a blocker or execution boundary.
- Full quotes, receipts, hashes, earlier versions and detailed explanations
  belong in named, keyboard-operable disclosures, closed initially.
- A saved plan starts with a readable summary and its draft/not-run boundary.
  The question-to-material/method/design/analysis/validation/interpretation/output
  planning flow stays visible; full source text and technical references can
  expand. It must not be reduced to a graph of opaque record IDs.
- Optional does not mean absent: complete content remains reachable. Do not
  replace missing evidence with an optimistic status.

## Shared layout and type

- Use the shared semantic tokens for panel inset, section gap, control size,
  body size/leading and reading width. Embedded shadow roots must consume an
  explicit type contract; a rule targeting `body` cannot style a shadow root.
- Unwrapped panel content has 24px desktop and 16px narrow-screen insets.
  Header/body components with existing gutters must not receive duplicate ones.
  Measure text or heading distance to the visible panel edge: at least 20px
  desktop and 16px narrow, allowing a one-pixel border tolerance.
- Use 12px within a related group and 20–24px between sections. Prefer flex/grid
  gaps. Keep headings attached to the content they introduce.
- Body text uses at least 16 CSS px and 1.6 leading. Long prose is at most
  72ch; cards may be narrower. Tables and diagrams use their own scroll regions.
- Preserve the established navy/teal palette and meaningful icons. Avoid new
  decorative gradients, repeated containers, arbitrary fonts or dependencies.

## Controls and responsive behavior

- Use a 44px minimum target for application actions and disclosure summaries.
  A checkbox may be smaller when its associated label supplies the full target.
  This is the project target, stricter than WCAG 2.2's 24px minimum criterion.
- Controls have visible focus, explicit labels and distinguishable primary,
  secondary, disabled, loading, failed and saved states. Enter must not silently
  upgrade a save action into model execution.
- At 320px and 390px widths, prose and controls reflow without page-level
  horizontal scrolling. Two-dimensional tables/graphs remain within a labelled
  local region. Test 200% text enlargement as well as ordinary device widths.
- Sticky summaries must not cover fields, focus or error messages. On narrow
  screens stack actions and multi-column material/method descriptions.

## Acceptance evidence

- Record route, locale, source commit, actual CSS viewport and screenshot pixel
  dimensions separately. A filename, element bound or exit0 is not visual QA.
- Inspect visible pixels for panel edges, type hierarchy, alignment, whitespace,
  clipping, table/graph readability and expanded states. A mobile screenshot must
  include the actual target, not just the page header.
- Cover Stage1, Stage2, Stage3, files/materials, history and settings. Stages4–6
  remain labelled previews; visual QA does not establish their execution.
- Cover desktop/narrow, English/Traditional/Simplified Chinese, keyboard focus,
  empty/loading/error/saved and expanded-detail states where applicable.
- Bind regression checks and independent review to the final diff. Keep old
  failures and unverified states. Never resubmit a saved choice or rerun a model
  to obtain a screenshot. Use the saved plan and the original request key.

## Sources

- [GOV.UK details](https://design-system.service.gov.uk/components/details/):
  secondary detail may be disclosed on demand; information most users need
  remains visible.
- [WCAG reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html):
  preserve content/function at 320 CSS px, with appropriate exceptions for
  intrinsically two-dimensional content.
- [WCAG target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html):
  distinguish the 24px AA requirement and its exceptions from this project's
  44px application target. Do not claim full WCAG compliance from this checklist.
