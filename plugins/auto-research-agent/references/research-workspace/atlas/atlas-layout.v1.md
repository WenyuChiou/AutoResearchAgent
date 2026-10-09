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

The lower direction summary owns its short list and preview. Its selection can
highlight the network, while the main detail panel keeps its own selection.
Future styling changes should reuse this contract. A layout behavior change
requires a reviewed PR, updated regressions and a new layout-contract revision.
