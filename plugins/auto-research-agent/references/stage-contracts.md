# Shared stage contracts v1.0.0

Validate records with JSON Schema Draft 2020-12 and date-time format checking
against `schemas/stage-contracts.v1.schema.json`. All fields are required; use
explicit null only where allowed. Unknown versions and extra fields fail.
The six tagged interfaces can also be addressed through their `$defs` names.

| Interface | Meaning |
|---|---|
| ResearchRun | Frozen objective, software/rules versions, constraints and input references; current stage is a projection of events. |
| StageRun | Unique stage attempt, phase, six-state status and inputs. New attempts get new IDs. Pending has no times; active attempts have a start; completed/failed attempts also have an end. |
| ArtifactRef | Run-relative POSIX path, SHA-256 of exact bytes, artifact type, producer stage-run ID and UTC creation time. Unicode is preserved. |
| DecisionEvent | Run-wide increasing sequence, actor, subject, prior/new decision, reason and references. Reversals point to the earlier event; they never replace it. Human actions retain verbatim input and the SHA-256 of the exact reviewed checkpoint bytes. |
| GateResult | Pass, fail or review-required plus reasons, blockers and evidence. Passing with blockers is invalid. |
| StageResult | Validated output references, validator report, metrics (null means unavailable), gate and next action. Stop-sufficient requires completed status and a passing gate. |

Stages use `plan -> execute -> extract -> validate -> gate -> checkpoint`.
State changes append DecisionEvents whose subject is the stage-run ID;
screening subjects are candidate IDs. Each stage defines its decision and
reason-code vocabulary. IDs must be unique within a run. `producer` refers to
the creating stage attempt; external inputs are attributed to an ingestion
attempt rather than inventing an upstream producer.

These schemas check shape, not scientific truth. A later validator must check
file existence, resolved path containment (including symlinks), exact hashes,
reference integrity, timestamp order, sequence/prior-decision continuity and
recomputed projections. A schema-valid stop is not evidence that coverage is
sufficient. The Stage 1 gate must separately check closest-work verification,
recent sweep, cluster coverage and complete marginal-yield rounds.

Work identity, version identity, evidence level and claim verification belong
to separate Stage 1 records. Resolving a DOI cannot establish any of the latter
three. Abstract-only evidence cannot support a full-text locator. Artifact
validation does not upgrade identity or claim evidence.

## Handoff interfaces (research logic deferred)

Every stage receives ArtifactRefs through StageRun and returns StageResult.
Artifact types describe the content contract; no Stage 2–6 executors ship here.

| Stage | Receives | Produces |
|---|---|---|
| 1 Literature Discovery and Evidence | research question, scope and constraints | manifest, query/candidate/decision/claim ledgers, coverage and stop report |
| 2 Comparison and Gap | validated Stage 1 records and unresolved obligations | literature-triage comparison matrix, gap hypotheses with evidence links |
| 3 Research Design and Feasibility | reviewed comparisons and gap hypotheses | design, feasibility checks, experiment plan |
| 4 Experiment Execution | approved design and experiment plan | execution records, raw results, failures |
| 5 Analysis and Figures | validated execution records and results | analysis, figures and uncertainty records |
| 6 Writing and Submission | reviewed evidence, analysis and figures | manuscript and submission artifacts |

Each handoff retains unresolved obligations and gate status. It grants no
authorization to run a later stage. Publication, human approval and evidence
verification are distinct decisions.
