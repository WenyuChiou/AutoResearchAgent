---
name: stage2-directions
description: This skill applies when the user asks to check proposed research directions, compare candidate gaps, revise an infeasible idea, or prepare a Stage 2 selection package from literature evidence. It supports fixed-candidate checking and preliminary feasibility; full autonomous direction generation and Stage 3 design remain separate.
---

# Stage 2 direction checking

Start only when the user requests Stage 2 work. A Stage 1 handoff supplies evidence;
it does not authorize a new stage. Read the confirmed ResearchBrief and resource
limits before evaluating candidates. Preserve exploratory questions, simple
methods, theory, replication and validation as legitimate research modes.
Never choose a different country or narrow scope without the user's decision.

Read [the checker interface](../../references/stage2-directions.md) when creating
or resuming a fixed-candidate run. Load source records and relevant candidate
versions as needed; do not fill the context with every historical artifact.
Keep native Codex search, reading, reasoning and code tools available. Reuse
`literature-triage-matrix` and `gap-to-topic` when installed and applicable;
their presence is not required to use the local checker.

1. Read the actual evidence and compare studies on meaningful shared dimensions.
   Distinguish source findings from inferences and missing evidence. Check the
   closest work, the remaining opportunity and evidence that could weaken it.
2. Discuss the candidates naturally before structuring records. Assess opportunity,
   value, answerability, materials and execution. Keep unknown separate from a
   demonstrated failure. Judge value by the useful knowledge or decision it can
   support, not complexity or promises of a breakthrough.
3. Use a separate, tool-free extraction step to record the completed assessment.
   Bind each quote to the saved source, work, version and location. Never invent
   tool receipts, checks or human decisions to satisfy a schema.
4. Apply the recorded assessment through `stage2_check`. Recommend, revise, park
   or reject with evidence and reasons. Supply a concrete next check for unknowns.
   A hard blocker cannot be offset by high scores on other axes.
5. Keep earlier versions when revising. Recheck the new version; do not carry over
   its parent's approval. Preserve useful options when a different candidate fails.
   For missing evidence, identify a bounded lookup or a scope decision instead
   of claiming the missing fact is verified.
6. Export the choice package before human selection. Explain tradeoffs, unresolved
   questions, costs and next steps. Zero recommendations can be honest, but needs
   an explanation; multiple recommendations are allowed. Ask the researcher to
   choose before authorizing Stage 3.

Check only preliminary feasibility here. A data download or a few LLM calls do
not establish behavioral validity. The offline CLI records supplied scientific
judgments and checks their bindings; it does not decide whether the science is
true. Do not run experiments, unbounded searches or background agents merely
because a next-step field suggests them.

Keep independent evaluation outputs, condition labels and judge feedback outside
the production choice process. An internal recommendation is not an external
P4–P6 score. This first slice is experimental and has not demonstrated improvement.
