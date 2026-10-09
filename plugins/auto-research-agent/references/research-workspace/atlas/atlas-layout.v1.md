# Stage 1 network layout contract v1

`AtlasModel.networkLayout(records, {singleMethods: true})` is the pure layout
engine. The renderer consumes its 600-wide, at least 816-high coordinates, literal category
memberships, method memberships and color indices. It does not create sources,
claims, citations, embeddings or evaluation scores.

Paper positions and category colors are stable under record order, language,
focus, refresh and sidebar selection. Methods use their recorded memberships,
stable keyed offsets and bounded collision avoidance for an organic layout.
Focus never reseeds or recomputes a different arrangement. Shared methods stay
shared; independent method descriptions are never silently merged.

The default method inventory contains shared labels. `singleMethods: true`
also provides coordinates for exact single-paper labels. The renderer can show
shared hubs and explicitly focused methods without changing paper positions.
Dense arbitrary tag inventories are not guaranteed collision-free.

Label rectangles reserve 88 × 64 units for papers, 38 × 38 for method aliases,
and 132 × 58 for category captions, with six-unit separation. The renderer must
keep the canvas at least 600 pixels wide or scale the labels accordingly.
Optional bounded `spatial: {yaw, pitch}` projects display targets before the same
packing step. It is a layout projection, not a WebGL camera or evidence metric.

Solid links identify recorded direction membership; dashed links identify
recorded methods; dotted percentages use literal method-label Jaccard. Layout
distance is never similarity, evidence strength or research quality. P/M display
aliases are separate from discovery sequence and retained work/version IDs.

The lower direction summary owns its compact list and preview. Selecting a
direction highlights the network and shows that direction's papers in the upper
detail panel. Selecting a paper updates the same upper paper detail and scrolls
to it; selecting it again keeps the detail available rather than toggling it away.
Summary focus uses the retained scope and its own graph page, so a library topic
filter cannot hide the requested direction. Clearing summary focus restores the
library context without changing its saved filter, order, page or scroll.
Future styling changes should reuse this contract. A layout behavior change
requires a reviewed PR, updated regressions and a new layout-contract revision.

## Professional presentation requirements for the v6 companion

These requirements extend the reviewed v6 outer layout: retain its navy research
workspace, stage rail, workflow strip, primary network, paper detail, compact
direction summary and private source navigation. The network is the main visual;
controls, summaries and process records support it. Prefer clear alignment,
consistent spacing and restrained decoration over adding equal-weight panels.

The design reference is the user-specified
[nature-figure skill](https://github.com/Yuan1z0825/nature-skills/blob/2a20e4a0868ef9094257cb5386cfe623454ae092/skills/nature-figure/SKILL.md),
manifest version 2.8.0, at commit
`2a20e4a0868ef9094257cb5386cfe623454ae092`. Its scope excludes interactive
dashboards and primarily 3D workflows. This companion adapts only independent
design principles from its [core contract](https://github.com/Yuan1z0825/nature-skills/blob/2a20e4a0868ef9094257cb5386cfe623454ae092/skills/nature-figure/static/core/contract.md),
[stance](https://github.com/Yuan1z0825/nature-skills/blob/2a20e4a0868ef9094257cb5386cfe623454ae092/skills/nature-figure/static/core/stance.md),
[design theory](https://github.com/Yuan1z0825/nature-skills/blob/2a20e4a0868ef9094257cb5386cfe623454ae092/skills/nature-figure/references/design-theory.md)
and [QA contract](https://github.com/Yuan1z0825/nature-skills/blob/2a20e4a0868ef9094257cb5386cfe623454ae092/skills/nature-figure/references/qa-contract.md).
It does not run a manuscript plotting backend or PDF submission workflow, and
does not claim Nature endorsement, manuscript acceptance or publication QA.

- Use one sans-serif hierarchy with Arial/Helvetica and legible system Chinese
  fallbacks. Ordinary interface text should remain 16–18 CSS pixels;
  secondary captions may use 14–16 pixels, graph labels at least 15 and matrix text at least 16 at their
  displayed size. Larger headings establish order. Do not shrink text to fit
  an overcrowded chart; expand the viewport, wrap labels or use scrolling.
- Keep a small, subdued category palette with stable identity-to-color mapping
  across both stages, graph modes, cards and filters. Use muted fills and stronger
  outlines for focus. Reserve status colors for actual status, and distinguish
  categories and relations through text, marker shapes and line styles as well
  as color. Unknown remains neutral. Magnitude scales must not masquerade as
  unrelated categorical colors.
- Give the primary graph room to read. Repeated rows, cards, panel edges and
  gutters align consistently. Direct labels and one nearby relation legend
  reduce repeated lookup. Thin, lower-contrast links sit behind markers and text.
- Check rendered text rectangles, marker clearance, edge crossings and viewport
  clipping after projection, font loading and resize. Inspect the complete
  page and each panel in English and both Chinese modes at normal display size,
  including a narrow screen. A source test cannot establish visual readability.

### One network with two camera modes

The 2D and 3D modes must use the same network component, canonical work/version
identities, relation inventory and selection state. A mode switch changes only
the camera or projection. It must not replace the dataset, fabricate depth as
evidence, reseed paper identity or silently remove a category. Camera drag,
zoom, reset and keyboard interaction belong to that component; text stays
upright and legible. Preserve a usable 2D mode when 3D is unavailable.

Every mode displays a nearby statement that position, depth and distance are
for layout. They do not measure citation, scientific similarity, confidence,
source availability, evidence strength or P1–P9 quality. Selection may highlight
incident links and retain context; it must not hide the rest of the saved
collection to make the graph appear simpler.

### Recorded and derived associations

All literal topic memberships are retained and connected. A placement algorithm
may choose one primary group for geometry, but that choice cannot discard other
recorded memberships. Exact shared topic or method labels and shared-paper
topic overlaps are recorded associations, not inferred citations.

The separately labeled `AtlasAssociations` projection compares saved
findings fields and literal topic-label text. Its English stop words, Chinese
bigrams and deterministic TF-IDF cosine produce lexical paper links and topic
aggregate links. Keep these distinct from recorded relationships, method-label
Jaccard and any bound original-source relation. Relationship details expose the basis,
score, shared terms and, for topic aggregates, contributing paper identities.
They describe similar words, not stronger evidence or verified scientific
agreement. The union of each node's top two qualifying neighbors limits clutter;
the shared UI uses a cosine threshold of `0.09`, while the pure helper default is
`0.12`. This is a declared presentation parameter, not an evidence cutoff. Never insert a link solely to force
one connected component. Preserve unresolved groups and disclose absent original
source relationships instead of inferring a citation from shared terminology.

### Paper detail and Stage 2 views

Use larger paper spheres, projected direction diamonds and distinct method
cubes in 3D (squares in 2D); size is an interaction aid, not a quality score.
Reserve each sphere's actual projected screen bounds when placing labels.
Initially show direction names only.
Hovering reveals that node and its direct neighbors; leaving restores the
selected neighborhood, or direction names when nothing is selected. A selected
paper retains its detail independently of label visibility. Offer a three-language
"Show all names" control without rebuilding the graph or resetting the camera.
Label collision avoidance applies in every mode. Hidden labels never remove
canonical nodes, recorded memberships or computed links from the inventory.

Immediately after title, work/version, authors, year/venue, selection and
evidence level, show an always-visible source section: public URL, recorded
URL/DOI, source IDs, accepted saved-source links and the complete Markdown note.
This section precedes findings. Source attempts, historical decisions, claim
records and raw provenance may remain collapsed. Preserve URL/path and hash
guards, source access failures, Unknowns and exact work/version bindings.

The selected paper detail lists canonical related paper versions from the
current working/archive collection. Merge exact shared directions, literal
method labels and separately labeled computed text links into one card per
version. Show five cards and collapse the rest. Keep topic-aggregate links out
of this direct-paper list; text cosine and normalized shared terms are neither
source quotations nor scientific agreement. Clicking a card focuses its exact
upper detail and graph node while retaining library filters, ordering and page.
Use circles for paper nodes, projected diamonds for direction nodes, and
cube/square method nodes, with a visible shape legend in both camera modes.

Show saved screening reasons, discovery paths and dates in a readable ledger.
Keep historical screening distinct from current source admission. Source
acquisition attempts are not search attempts; missing per-paper search counts,
first-discovery order and relevance ranks stay unavailable. Never infer them
from reference-token suffixes or fill them with zero. Source receipt details
retain exact work/version binding and the original receipt file hash.

Place a stage-review request after direction/results summaries. It prepares a
project/index-bound message for the matching existing Codex conversation only;
it cannot approve a stage, change readiness or begin execution. If disconnected,
retain the draft for copying. A Stage 2 preview changes presentation only.

Stage 1 and Stage 2 put results first, then the within-stage workflow and collapsed
process history. Future stages retain this order while choosing visualizations
suited to their actual delivered artifacts.

Stage 2 places the relation graph alongside its source-bound comparison matrix
and recorded route cards. The matrix uses explicit comparison dimensions, clear
row/column labels, readable cells and horizontal scrolling when needed. Route
cards show the actual saved proposal, literature/evidence bindings, unresolved
items and assessment status. Their links must point to bound records; lexical
associations cannot supply a missing route citation. A simulated preview remains
visibly simulated. Empty, missing, pending audit and failed reviewer states
remain explicit; presentation never starts research, changes rubric denominators
or upgrades Stage 1/Stage 2 readiness.
