# Offline Stage 2 evaluation interface

This experimental interface validates supplied evidence and judge records. It
does not call a model, prove judge independence, or authorize formal A/B claims.
Read the [independent protocol](../evals/stage2/INDEPENDENT_EVALUATION_PROTOCOL.zh-TW.md)
for the seven criteria, unknowns, audit triggers and comparison rule.

Run from a Python environment with `requirements-test.txt` installed and the
plugin's `cli/` directory on `PYTHONPATH`. The common input is
`schemas/stage2-packet.v1.schema.json`: a confirmed ResearchBrief, resources,
comparison, source snapshots, exact evidence, candidate versions and unresolved
issues. Source paths are portable relative paths within the source root. Keep
the original packet and externally recorded hashes; a newly computed self-hash
alone is not proof that an artifact has never changed.

1. `python -m stage2_eval prepare-content --packet packet.json --source-root sources --subject-id opaque-id --input-sha256 INPUT_HASH --config-sha256 CONFIG_HASH --output content.json`
2. R1 and R2 independently assess the content before seeing checker scores or
   actions. Save each judge's `Stage2ContentAssessment` bound to that exact view,
   with source evidence. Their statements need not be identical.
3. `python -m stage2_eval prepare-action --packet packet.json --source-root sources --content-view content.json --content-assessment content-assessment.json --action-record actions.json --output action.json`
4. `python -m stage2_eval validate-judge --packet packet.json --source-root sources --content-view content.json --action-view action.json --judge r1.json`
5. Repeat step 3 for R2's assessment, saving `action-r2.json` separately.
   `python -m stage2_eval merge --packet packet.json --source-root sources --content-view content.json --action-view action.json --action-view-r2 action-r2.json --r1 r1.json --r2 r2.json --output bundle.json`
6. Add `--adj adj.json` for disagreement, `--action-view-adj` for ADJ's separate
   action view, and `--audit audit.json` when required.
   `python -m stage2_eval compare --pairs pairs.json --output comparison.json`
   applies the three-pair diagnostic rule only.

`INPUT_HASH` identifies the common starting evidence and prompt; `CONFIG_HASH`
identifies the common experimental settings. They are 64-character lowercase
SHA-256 values, not literal placeholders. Candidate outputs need not be identical
between A and B. `packet_sha256` binds each subject's actual candidate/evidence
packet separately from the common starting-input hash. Use fresh output paths.

The neutral action record contains candidate/version dispositions, actual
history, revision reasons, selected IDs and choice rationale. It does not require
a treatment-specific ledger from baseline Codex. Preserve all revised versions;
do not edit the initial packet in place. A later runner must verify extraction
against native outputs and attest model calls and source bytes.
The action phase also reveals retained candidate text and evidence from before
and after revisions. R1/R2 action views can differ in their own assessments while
binding the same subject, content and action record. Custom rubric overrides are
not supported by this first slice; the versioned bundled rubric is authoritative.

The first-slice fixtures in `tests/test_stage2_evaluation.py` show complete
synthetic JSON records. They test mechanics, not autonomous judgments. A named
audit JSON validates the recorded name and bindings; it is not authentication
of a human signature. Never fabricate such approval. A formal runner must
establish actual independent R1/R2 execution and named human review before
changing the `external_claim_ready=false` restriction.
