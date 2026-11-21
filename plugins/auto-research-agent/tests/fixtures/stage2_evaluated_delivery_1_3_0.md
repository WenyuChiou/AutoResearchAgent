# Frozen Stage 2 evaluated delivery (presentation 1.3.0)

This synthetic package was produced at
`217e625a6ad68108bc835d1b872af4f83a42b7b2` and preserved before the 1.4.0
presentation update during [PR #479](https://github.com/WenyuChiou/AutoResearchAgent/pull/479)
review. It uses an authored fixture source and deterministic judge records.
There is no harvested source, private holdout, or actual human selection.

The ZIP contains only the nine members from the original review archive's
`legacy-1.3.0/` entry group, copied byte for byte with that prefix removed.
The original review seal is `b16c238cfc0cda2340132a4cbf637692cdcf2dc7`.

| Pin | Value |
| --- | --- |
| Delivery schema | 3.0.0 |
| Presentation version | 1.3.0 |
| Externally retained manifest SHA-256 | `db6ca1159e25e1478b90e4dc08bc0ff2e68eb39faf2624b76dd022ab8ff60478` |
| Original review ZIP SHA-256 | `0416013a40b299a27ba1db6851330973652d153c69f7bc602be5e812487f713c` |
| This fixture ZIP SHA-256 | `aa23e231d1b2616c58639a45283b092b0ff26048b71ab31e9dc08d388d08de7c` |

Keep the stored members unchanged. The regression exercises
`stage2_workflow verify-evaluated-delivery` against these bytes, with a
separate copy for the negative control. It does not rebuild an old report with
the current renderer.
