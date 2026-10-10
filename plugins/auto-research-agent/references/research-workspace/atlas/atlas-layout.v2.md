# Atlas selection and relation contract v2

This visibility revision extends the retained [v1 layout contract](atlas-layout.v1.md).
Its coordinates, evidence semantics, category colors, node shapes, professional
presentation requirements and separate summary/detail panels remain applicable.

The initial graph displays nodes without relationship lines. A selected paper,
direction or method reveals only edges incident to that exact typed identity.
Both solid WebGL edges and dashed/dotted SVG overlays use the same selection.
The planar fallback follows the same rule. Hover can reveal a name, but cannot
expand relationships or replace the selected node's relationships. Showing all
names does not show all edges. Selecting the same node again clears focus and
hides every relationship line.

Projected names retain their exact typed identity and keyboard focus across
title changes and redraws. Keep the focused name inside the viewport, preferring
collision-free placement; when space is exhausted, retain that active control
at the viewport boundary. This focus exception does not select a graph node or
expand its relations. Other names retain normal collision avoidance.

Graph edges remain in the complete canonical presentation inventory. Visibility
does not remove papers, reseed positions, change memberships, recompute source
evidence, change scores or perform any native/research action. Lower summary and
whole-library selection still update the same upper detail and graph focus.

Recorded direction membership, recorded methods and labelled computed similarity
remain distinct; hidden links do not mean missing or rejected evidence. Geometry
does not measure evidence strength, similarity or scientific quality.
