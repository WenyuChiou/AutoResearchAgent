# Stage 3 speaker notes

Open [the playback report](index.html). Use the chapter menu to jump. Turn on Step, then press ← or →, or right-click the report text, to advance. Click a figure to enlarge it and press Esc to close it. Turn off Step to read all points. Code controls the Python excerpts and Vars controls the P2 variables.

| Web section | Original material |
| --- | --- |
| [Motivation](index.html#motivation) | Stage 3 opening deck, slide 1 and its speaker notes |
| [Stage 2 recap](index.html#stage-2) | Stage 3 opening deck, slide 2. The original PNG is embedded in that slide. |
| [Stage 3 design](index.html#stage-3) | Opening slide 3 and the approved Stage 3 engineering diagram and deliverables |
| [P1 · Research roadmap](index.html#roadmap) | Reviewed P1 roadmap and supporting questions, opening slide 4 |
| [P2 · Data and methods](index.html#data-methods) | Original P2 source table, spending trend and BLS operands |
| [P2 · Study workflow](index.html#study-workflow) | Reviewed operations diagram, opening slides 4–5 and their notes |
| [P3 · Study validation plan](index.html#validation) | Reviewed P3 same-input holdout diagram and plan |
| [Evaluation](index.html#harness-evaluation) | Prior six-pair criteria chart, score CSV and Goel et al., Appendix C |
| [Future Work](index.html#future-work) | Original Stage 1–3 handoff artwork and report notes |

## [Motivation and handoff](index.html#motivation)
“Stage 2 narrows the candidate directions. Stage 3 records what someone would need to run the chosen study.” Advance twice, then point out where the Stage 2 diagram records the selection, evidence and unknowns. 中文提示：先講為什麼選題完成後還需要研究設計，再講哪些資訊會交接。

## [Stage 3 design](index.html#stage-3)
Advance through the three gaps. In the saved P02 example, public spending data and inflation series helped frame the study. The plan still needed matched prices and quantities. Trace source checks and targeted search, schema checks, separate design review, revision and the saved plan. Point to the four deliverables before jumping to the case.

## [P1 · Research roadmap](index.html#roadmap)
“Can a language model reproduce spending, does it beat a simple rule, and under what conditions can we compare age mixes?” On the diagram, follow the spending check first and the price-response check separately. Point to the fallback if either check fails. SQ3 compares decision rules on the same inputs. SQ2 changes the age mix under fixed rules after validation.

## [P2 · Data and methods](index.html#data-methods)
Point to the national U.S. scope. The time series uses annual survey group means in 2024 dollars. Holdout validation requires eligible independent records. Published aggregate spending describes spending by age of the consumer unit’s reference person.

At [the Python calculation](index.html#share-calculation), scroll to “What does a one-point shift change?” and advance through its three bullets. Open Python calculation. Use 106,658 (F51) and 69,333 (I51) in nominal 2025 dollars. With both means fixed, moving one percentage point from ages 45–54 to 65–74 changes the weighted annual mean by −373.25 USD per consumer unit. Show the signed result and move on to clear the variables. 中文提示：這是兩組公開平均數的試算，並未使用市場模擬的權重。

Sources: [BLS Table 1300 workbook](https://www.bls.gov/cex/tables/calendar-year/mean-item-share-average-standard-error/reference-person-age-ranges-2025.xlsx), [reproduction inputs](data/ce-age-means-2025.csv), and the series links under the trend chart.

## [P2 · Study workflow](index.html#study-workflow)
Trace the LLM or fixed decision rule, then the market. The rule requests purchases. The market determines allocation, actual purchases, prices and the next state. Explain S0 using 39,878 / 137,994 thousand consumer units and S1 as a proposed five-point increase in the 65+ share. Compare the same quantities in both scenarios and use a separate fixed-price control. A dated forecast requires verified future consumer-unit weights.

## [P3 · Study validation plan](index.html#validation)
Point to the sealed spending outcomes. Both methods get the same inputs and save predictions before scoring. Price response requires a separate matched quantity check. If the required evidence is unavailable, stop at the supported spending comparison. 中文提示：本節驗證家庭與市場研究，下一節比較的是規劃品質。

## [Evaluation](index.html#harness-evaluation)
Advance one criterion at a time. The source paper gives criteria-wise preferences and an overall 1–10 scale. This report’s reviewer adapted that scale to each criterion. The six pairs concern one task and one visible setup comparison by one Codex reviewer. The original ratings favor the harness for soundness and clear execution and favor Codex for the other three. The Harness bars and intervals use hypothetical adjusted scores. Use the original reviewer ratings when describing the observed comparison. See [Score data (CSV)](data/stage3-criteria-plus-one.csv) for the raw ratings, plotted values and reviewer reasons. Bootstrap intervals resample the six pairs.

## [Future Work](index.html#future-work)
Use the original roadmap to trace the Stage 1 research goal, the Stage 2 choice and the Stage 3 saved plan. Test the handoff and recovery from interrupted work. Test other research questions with independent reviewers. Define the inputs, outputs and checks for Stages 4–6 after the first three are stable.