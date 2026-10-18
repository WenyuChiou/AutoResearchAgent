# Generic Stage 3 planning operational definitions v1

Experimental, implementation-only. Historical topic-specific P7–P9 definitions,
rubrics and scores retain their original meaning. No new research was run.
The catalog `stage23-general-v1` copies Stage2 v3 criteria without changing them
and adds the following generic Stage3 criteria. Stage1 v3 criteria are also
copied unchanged for PR coverage of the reused native primitive; no Stage1
research or historical scoring is rerun. Dimensions remain separate.

| Submetric | Observable contract and denominator | Metric |
|---|---|---|
| `S3V1_QUESTION_PATH` | Source-bound core questions with justified question/evidence/design/analysis/result paths, or visible blockers / all core questions in each selected candidate version. Empty denominator is invalid. Mechanical closure is separate from scientific adequacy. | P7 |
| `S3V1_EVIDENCE_RESULT` | Questions with source/resource fit, appropriate credibility and uncertainty procedures, and support/contradiction/inconclusive interpretations / all selected scientific questions. Unrun values stay null. Necessary unavailable evidence is unknown. | P8 |
| `S3V1_DEPENDENCIES` | Designs with explicit scale estimates, minimum output, dependencies, milestones and failure/stop conditions / all designs. A separate current version-bound human plan decision never grants research execution. | P9 |

Each new criterion uses 0/1/2 anchors in the catalog; missing necessary evidence
is null and evaluator error remains separate. No combined P7–P9 score is defined.
Registered deterministic tests exercise implementation behavior. They cannot
establish scientific adequacy, authentic native execution, improvement or formal
Stage3 acceptance. A future evaluation must freeze its own topic-neutral case,
plan, rubric, independent judgments and authority before any new calls.
