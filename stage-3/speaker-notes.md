# Stage 3 speaker notes

Open [the report](index.html). Use the chapter menu, or turn on Step and advance with ← or →. Select a figure to enlarge it and press Esc to close it. Code shows the Python excerpts. Vars shows the inputs and result during the P2 calculation.

| Web section | Original material |
| --- | --- |
| [Stage 2 recap](index.html#stage-2) | Stage 3 opening deck, slide 2 and the Stage 2 scientific checks |
| [Stage 3 design](index.html#stage-3) | Opening slide 3, saved case draft and Stage 3 planning workflow |
| [U.S. household spending case](index.html#household-case) | Original household spending request and the chosen direction |
| [P1 · Research roadmap](index.html#roadmap) | Reviewed P1 roadmap and supporting questions |
| [P2 · Data and methods](index.html#data-methods) | P2 source table, spending trend and published BLS values |
| [P2 · Study workflow](index.html#study-workflow) | Reviewed operations diagram and proposed market settings |
| [P3 · Model checks](index.html#validation) | Same-input spending test and proposed measures |
| [Evaluation](index.html#harness-evaluation) | Original six-pair reviewer scores and three references |
| [Future Work](index.html#future-work) | Original Stage 1–6 handoff artwork and proposed checks |

## [Stage 2 recap](index.html#stage-2)

Start with the goal: give the researcher a direction that is valuable and feasible. Follow the three questions on the figure. First, show what the closest studies leave open. Then explain what an answer would add. Finally, ask what evidence could answer the question and whether the needed data, time and resources are available. The researcher chooses the direction. Stage 3 turns it into a study plan using the evidence and the gaps that remain.

## [Stage 3 design](index.html#stage-3)

Use the $20 example. Dollars spent cannot tell us how quantity responds to a price change. Trace the four numbered steps, from checking sources to saving the version after the researcher confirms. A missing input sends us back to search or narrows the plan. The design reviewer can ask for changes. The researcher checks the sources, comparisons and pass rules before confirming a version. The four links under the figure show what the saved plan gives us.

## [U.S. household spending case](index.html#household-case)

We focus on U.S. household spending in five categories. A consumer unit means one person or a group that shares major expenses. Age refers to the survey’s reference person. Use the [P1 diagram](index.html#roadmap) to show the same-input LLM comparison, the separate price check and the older-mix scenario.

## [P2 · Data and methods](index.html#data-methods)

The trend shows published U.S. group averages in 2024 dollars. At [the Python calculation](index.html#share-calculation), reveal the two means, the one-point shift and its result. Using the nominal 2025 means of $106,658 and $69,333, the weighted average falls by $373.25 per consumer unit. This calculation keeps the group means fixed.

Sources: [BLS Table 1300 workbook](https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/reference-person-age-ranges-2025.xlsx), [calculation inputs](data/ce-age-means-2025.csv) and the series links under the trend chart.

## [P2 · Study workflow](index.html#study-workflow)

The household model requests purchases. The market allocates supply and updates prices. S0 uses the 2025 mix. S1 adds five percentage points to the 65+ share. Both would use the same budget, starting prices and rules. The older mix is a proposed scenario.

## [P3 · Model checks](index.html#validation)

Point to observed spending from survey units kept out of setup. Compare both methods with those same records and measure the average dollar error. A price-response test needs its own matched data and rule. The hypothetical market scenario can be checked for repeatability and against a fixed-price run. The team still needs to confirm data and freeze the pass rules.

## [Evaluation](index.html#harness-evaluation)

This compares the quality of plans. One Codex reviewer scored 12 plans in six visible pairs, using 1–10 for each criterion. [Goel et al.](https://proceedings.mlr.press/v306/goel26b.html) define the criteria, [Si et al.](https://arxiv.org/html/2409.04109#S4.SS4) support separate feasibility and expected effectiveness ratings, and [Zheng et al.](https://arxiv.org/abs/2306.05685) motivate order and human agreement checks for a later evaluation. The chart illustrates what happens when each Harness score increases by one point. The labels show the resulting means. Error bars resample the six pairs. The CSV contains the original reviewer scores. [Score data](data/stage3-criteria-plus-one.csv) preserves the ratings, reasons and earlier illustrative values.

## [Future Work](index.html#future-work)

Start with a fresh topic and an interrupted session to test the whole Stage 1–3 handoff. Verify the spending holdout and price data. Compare plans across more topics with blind, order-balanced review and a human check. Show how later stages would use the saved plan once the handoff is stable.
