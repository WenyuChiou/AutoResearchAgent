# Saved-observation automatic backlog

`S1-AUTOMATIC-BACKLOG-1.0.0` is an opt-in private JSON companion for an
externally pinned WorkspaceIndex. It reuses the original candidate/capture
validator. It performs saved identifier lookup and repeated-observation checks
before another source request or a researcher question.

The caller fixes the index hash, project and exact input-version value/type.
Original recovery manifest, selected proof files, original observations,
capture spans and complete candidate cohort must agree. DOI, arXiv, PMID,
PMCID and saved URLs are compared only in explicit source identity fields.
Titles never establish identity. An arXiv work match across versions does not
certify the observation's version. Conflicting saved works remain conflicts.

The companion keeps every pending observation and its original decision hash,
reason, need and capture reference. It records which local checks actually ran
and the next automatic step. Local identity work, complete-source reading and
academic include/exclude judgments have separate counts. A missing source or
an unexecuted review is not a demonstrated researcher-only decision.

Run from the plugin CLI import root, using host-selected private paths:

```text
python -m research_workspace.pending_backlog --index <saved-index> --expected-index-sha256 <external-pin> --project-id <original-project> --input-version-json '"original-string-version"' --output <new-private-file>
```

`--input-version-json 1` is an integer; `--input-version-json '"1"'` is a
string. They are not interchangeable. The output parent must already exist
outside Git. Existing files and frozen inputs are never overwritten. This is a
Python/CLI entry, not a browser-selected private-path or trust-root interface.

This component does not run retrieval, acquisition or a model. It is not the
complete Topic-to-Stage1 executor. The original trusted host still needs the
current run's actual permits/providers/budget, version/source verification,
complete-body semantic reading, automatic screening, full notes, actual
coverage rounds and complete-package validation. Each executed operation must
keep its durable result, source/work/version identity, real time, budget and
failure. UI trial allowances and historical exhausted resources are not grants
to this companion or another chat.

For actual automatic follow-up, retain separate outcomes for solved, not run,
retryable failure, technical block, evidence conflict and a demonstrated
researcher-only choice. Before presenting a researcher question, attach the
actual automatic attempts, remaining conflict, available choices and impact;
merge duplicate questions. Never clear the backlog by excluding everything or
reclassifying unfinished work as human work.

The original formal progress and coverage stop reasons remain visible.
Quantity target, budget exhaustion, source blocking, researcher stop and
measured coverage/marginal yield are different reasons. This companion ran no
new complete rounds, so new marginal yield is null and it never emits
`stop-sufficient`, scientific acceptance or Stage2 eligibility. A new-topic
delivery stops at Stage1 for researcher review; existing30 formal intake keeps
its separately authorized original acceptance gates.
