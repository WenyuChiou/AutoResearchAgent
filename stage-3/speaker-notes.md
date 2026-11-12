# Stage 3 speaker notes

Open [the report](index.html). Use the chapter menu, or turn on Step and advance with ← or →. Select a figure to enlarge it and press Esc to close it. Code shows the Python excerpts. Vars shows the inputs and result during the P2 calculation.

| Web section | Original material |
| --- | --- |
| [Stage 2 recap](index.html#stage-2) | Stage 3 opening deck, slide 2 and the Stage 2 scientific checks |
| [Stage 3 design](index.html#stage-3) | Opening slide 3, saved case draft and Stage 3 planning workflow |
| [U.S. household spending case](index.html#household-case) | Original household spending request and the chosen direction |
| [P1 · Research roadmap](index.html#roadmap) | Reviewed P1 roadmap and supporting questions |
| [P2 · Data and methods](index.html#data-methods) | P2 source table, spending trend and published BLS values |
| [P2 · Study workflow](index.html#study-workflow) | S0 and S1, the food market loop and the fixed-price control |
| [P3 · Study validation](index.html#validation) | Spending, price response and scenario comparisons |
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

Start with the timeline. We use the 2023 U.S. spending diaries to set a simple rule and show reference examples to the language model. Then we give both methods the same household profiles from January through December 2024 and ask for one week's spending on food at home. The survey's reported dollars are kept for scoring. The historical chart covers 2010–2025 and gives background on spending by age.

Now point to the top of the market figure. S0 uses the 2023 U.S. age mix from BLS Table 12. In S1, the share of consumer units with a reference person aged 65 or older rises from 27.63% to 32.63%. The two cases start with the same profile pool, weekly budgets, prices and supply. We propose running each case from week 1 to week 52. The older mix is hypothetical and has no forecast year.

Follow one week through the three boxes. The LLM sees the consumer unit’s age band, size and income band, its weekly food budget, the available foods and current unit prices. It asks for a quantity of each food. Code checks the budget and the market allocates available supply. The market then updates the prices that households see the following week. The price and quantity data still have to pass the check on the next page before we turn on that loop.

## [P3 · Study validation](index.html#validation)

Start with spending. Give the LLM and the simple rule the same household profiles from the reserved 2024 diary weeks. Keep both weeks from any one consumer unit together. The researcher holding the spending answers opens them only after both sets of predictions are saved. Score the average absolute error in dollars per unit per week, overall and by age band. Set the acceptance rules before opening the answers.

Next ask how well the model responds to prices. When a product’s price changes, compare the predicted change in quantity with what people actually bought. The two changes must refer to the same product, place and period. The matched data are still needed.

Finally, return to S0 and S1. After both checks pass, compare the two 52-week paths with price updates and repeat with the starting prices held fixed. The change in the gap shows what the price rule contributes inside this model. If the price check cannot pass, report the historical spending comparison.

## [Evaluation](index.html#harness-evaluation)

“We just covered how the proposed study would check its predictions. Now we’re comparing the quality of the plans themselves.” One Codex reviewer scored 12 plans in six visible pairs, using 1–10 for each criterion. Introduce the rubric and the reviewer’s access to the setup labels before showing the chart. [Goel et al.](https://proceedings.mlr.press/v306/goel26b.html) · [Si et al.](https://arxiv.org/html/2409.04109#S4.SS4) · [Zheng et al.](https://arxiv.org/abs/2306.05685)

Say which criteria each setup led on in the original ratings. Then introduce the chart aloud. “This illustration adds one point to every Harness rating before taking the six-pair averages.” The chart’s error bars resample the six pairs. [Original ratings and illustrated values](data/stage3-criteria-plus-one.csv)

## [Future Work](index.html#future-work)

“We’ve looked at one topic with one reviewer. Next we’ll see whether the workflow holds up on a fresh topic and when a session is interrupted.” Confirm the missing spending and price data. Compare plans across more topics with hidden setup labels, balanced order and human review. Once the Stage 1–3 handoff is stable, later stages can build on the saved plan.
