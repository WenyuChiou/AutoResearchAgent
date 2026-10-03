---
name: stage2-directions
description: This skill applies when the user asks to improve an existing research method, discuss a new concept, challenge an assumption, check proposed directions, revise an infeasible idea, or prepare a Stage 2 selection package from literature evidence. It guides open proposal development and fixed-candidate checking; full autonomous generation and Stage 3 design remain separate.
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
For evidence additions or multiple research actions, read the
[workflow contract](../../references/stage2-workflow.md). Its offline CLI records
immutable snapshots and action receipts; it does not yet dispatch the complete
research/review loop. Do not treat an action receipt as proof of model execution.
Keep native Codex search, reading, reasoning and code tools available. Reuse
`literature-triage-matrix` and `gap-to-topic` when installed and applicable;
their presence is not required to use the local checker.

Allow open proposal development before converging on candidate checks. Consider
assumption challenges, method combinations, transferred ideas, new mechanisms
and revisited failures as well as literature gaps; keep these examples open.
Do not require a paper to name a gap before considering a new method. Explore
in prose, sketches or short derivations without a forced nested schema, idea
quota or fixed reasoning path. Retain promising unfinished ideas for bounded
follow-up rather than treating admission to discussion as final recommendation.
Read the interface's open-proposal guidance when assessing a new method.
For structured comparison and ideation tasks, load the
[ideation interface](../../references/stage2-ideation.md). Save original prose
before a separate no-tool extraction. Its schema and exact spans check records,
not scientific support or native tool isolation. Retain the full extraction's
bibliography, source roles and shared-study relationships beside each snapshot.

Keep two equally valid entry routes: improve an existing method or design, and
propose a new concept, mechanism or design. For improvements, identify the
original limitation and the useful change relative to the original and closest
alternatives. For new concepts, explain the premises, difference from prior work
and a way to test the idea. Routes may combine or change during revision; do not
require both in each run or reward a novelty label over a valuable improvement.
Both routes use the same evidence checks, five axes and user selection gate.

1. Read the actual evidence and compare studies on meaningful shared dimensions.
   Distinguish source findings from inferences and missing evidence. Check the
   closest work, the remaining opportunity and evidence that could weaken it.
2. Discuss the candidates naturally before structuring records. Assess opportunity,
   value, answerability, materials and execution. Keep unknown separate from a
   demonstrated failure. Judge value by the useful knowledge or decision it can
   support, not complexity or promises of a breakthrough.
   Separate sourced facts, inferences and proposed mechanisms. Ask what changes,
   why it might help, which closest alternatives or ablations could test it, and
   when it could fail. Treat unmeasured effectiveness as the research question,
   not as established evidence or automatic infeasibility. Keep unknown enabling
   prerequisites subject to the existing recommendation gate.
3. Use a separate, tool-free extraction step to record the completed assessment.
   Bind each quote to the saved source, work, version and location. Never invent
   tool receipts, checks or human decisions to satisfy a schema.
   Preserve the original proposal if extraction fails; do not lose it or turn
   a conjecture into a verified finding to complete the record.
4. Apply the recorded assessment through `stage2_check`. Recommend, revise, park
   or reject with evidence and reasons. Supply a concrete next check for unknowns.
   A hard blocker cannot be offset by high scores on other axes.
   In a versioned workflow, first use `stage2_workflow review-plan` for isolated
   challenger and feasibility views, including the excluded-candidate audit.
   Preserve independent native results before synthesis, then use `reconcile`.
   Store results as action artifacts; do not mutate the snapshot's checker.
   A local binding check is not proof of independent native execution.
5. Keep earlier versions when revising. Recheck the new version; do not carry over
   its parent's approval. Preserve useful options when a different candidate fails.
   For missing evidence, identify a bounded lookup or a scope decision instead
   of claiming the missing fact is verified.
6. Export the choice package before human selection. Read its `selection.md` as
   a proposal report: inspect the opportunity, value, proposed approach, five
   checks, linked excerpts and revision history. Explain each source's actual
   role in the comparison or rationale (premise, precedent, counterevidence,
   limitation or inspiration); keep these examples open. Give verified citation
   details with source IDs in the comparison when available, and flag missing
   details. The v1 packet has no structured bibliography or evidence-role field;
   export cannot infer these or establish that an excerpt supports a whole idea.
   Explain tradeoffs, unresolved questions, costs and next steps. Zero
   recommendations can be honest, but needs an explanation; multiple
   recommendations are allowed. Ask the researcher to choose before authorizing
   Stage 3.
   For versioned workflows, use `stage2_workflow deliver` and
   [the proposal and dialogue interface](../../references/stage2-delivery.md).
   Explain the alternatives in chat, then link the exact Markdown/HTML report.
   Record the actual user message with `human-record`; never invent approval.
   Preserve edited drafts, create new candidate versions and recheck them.

Check only preliminary feasibility here. A data download or a few LLM calls do
not establish behavioral validity. The offline CLI records supplied scientific
judgments and checks their bindings; it does not decide whether the science is
true. Do not run experiments, unbounded searches or background agents merely
because a next-step field suggests them.

Keep independent evaluation outputs, condition labels and judge feedback outside
the production choice process. An internal recommendation is not an external
P4–P6 score. This first slice is experimental and has not demonstrated improvement.

When reviewing enabling requirements or several directions together, read the
[prerequisite and followup interface](../../evals/stage2/MATERIAL_PREREQUISITES_AND_FOLLOWUP.zh-TW.md).
Record data, tools, models, licenses, cost, premises and validation paths against
the current candidate and source versions. Use reasoned not-applicable entries
for theory; do not invent empirical requirements. Missing per-candidate estimates
or resource limits leave joint demand or capacity unknown. Count shared work once
only when its participating candidates and basis are explicit. These records check
bindings, not scientific truth. Opt-in material followup identifies the decision
that could change and its next check; it does not authorize a new search engine,
grant human approval, or require a new method to have proven effectiveness.

For real calls, load the [native execution interface](../../references/stage2-live.md)
only when needed. Preserve the native research environment, capture prose before
tool-free extraction, and run independent checks in separate host-isolated contexts.
Attach native receipts to workflow actions; missing reviewers or required human
audits remain pending. Separate profile paths alone do not prove isolation.
