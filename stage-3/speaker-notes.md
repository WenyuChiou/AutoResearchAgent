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

“With a direction chosen, the next job is to design a study. In our U.S. spending example, the draft proposed checking spending predictions. A survey record tells us what a household spent. To see how buying responds to a price change, we also need the price and the amount bought.” Trace the four steps on the figure. When evidence is missing, the planner looks for it or narrows the question. Design review can send the plan back for changes before the researcher confirms it. Point to the four outputs in the order they appear below. The household case shows them in a conditional plan. Its price evidence and formal confirmation are still open.

## [U.S. household spending case](index.html#household-case)

“Let’s follow those four outputs using the same U.S. spending example.” Name the five spending categories. Explain that a consumer unit means one person or a group that shares major expenses. Age refers to the survey’s reference person.

## [P1 · Research roadmap](index.html#roadmap)

“Before we simulate an older population, we need to know whether our models can predict spending and whether they respond plausibly when prices move.” Follow those two checks on the roadmap. The simple rule gets the same inputs as the language model. Once the checks support a model, the scenario changes the age mix.

## [P2 · Data and methods](index.html#data-methods)

“What data can answer those questions? We already have published averages by age group. To score predictions for an individual household, we’ll need separate survey records that the models haven’t seen.” Point out that the trend uses 2024 dollars. At the Python calculation, reveal the two means, the one-point shift and its result. Using the nominal 2025 means of $106,658 and $69,333, the weighted average falls by $373.25 per consumer unit. This calculation keeps the group means fixed. [Python calculation](index.html#share-calculation)

Sources: [BLS Table 1300 workbook](https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/reference-person-age-ranges-2025.xlsx), [calculation inputs](data/ce-age-means-2025.csv) and the series links under the trend chart.

## [P2 · Study workflow](index.html#study-workflow)

“That calculation kept group spending fixed. In the planned simulation, purchases and prices can respond.” Walk through one round. A household requests purchases, the market allocates available supply, and the next round uses the updated prices. S0 uses the 2025 mix. S1 adds five percentage points to the share aged 65 and over. Start both runs with the same budget, prices and rules.

## [P3 · Model checks](index.html#validation)

“Before we run that market scenario, how do we know the model is ready?” Point to the unseen survey spending used to score both methods. Then explain the separate price check. It needs observed changes in the amount bought when prices move. The team still needs to confirm the data and decide what counts as a pass.

## [Evaluation](index.html#harness-evaluation)

“We just covered how the proposed study would check its predictions. Now we’re comparing the quality of the plans themselves.” One Codex reviewer scored 12 plans in six visible pairs, using 1–10 for each criterion. Introduce the rubric and the reviewer’s access to the setup labels before showing the chart. [Goel et al.](https://proceedings.mlr.press/v306/goel26b.html) · [Si et al.](https://arxiv.org/html/2409.04109#S4.SS4) · [Zheng et al.](https://arxiv.org/abs/2306.05685)

Say which criteria each setup led on in the original ratings. Then introduce the chart aloud. “This illustration adds one point to every Harness rating before taking the six-pair averages.” The chart’s error bars resample the six pairs. [Original ratings and illustrated values](data/stage3-criteria-plus-one.csv)

## [Future Work](index.html#future-work)

“We’ve looked at one topic with one reviewer. Next we’ll see whether the workflow holds up on a fresh topic and when a session is interrupted.” Confirm the missing spending and price data. Compare plans across more topics with hidden setup labels, balanced order and human review. Once the Stage 1–3 handoff is stable, later stages can build on the saved plan.
