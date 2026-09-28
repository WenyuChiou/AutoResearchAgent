# Literature comparison and open ideation

This interface prepares model tasks and validates supplied extraction results.
It does not itself launch a model, certify tool isolation, or make a scientific
recommendation. Native execution is a separate host responsibility.

## Ordered use

1. Validate the confirmed Stage 2 packet and source bytes with `validate_packet`.
   Initialize or inspect its `stage2_workflow` snapshot and retain the head hash.
2. `stage2_ideation.build_research_task(packet, snapshot_sha256)` returns a prose
   research prompt. Keep native search, reading, code and bounded subagents.
   Provide the saved source directory to the host. The researcher compares actual
   questions, populations, measurements, conditions, methods and limitations;
   noncomparable results and shared datasets must remain visible.
3. Save the original proposal and native call record with a workflow action
   before extraction. Even a failed extraction must leave these artifacts intact.
   Register newly discovered sources in a new verified snapshot before using
   them as evidence IDs. A mention in prose does not register a source.
4. `build_extraction_task(raw_proposal, packet, snapshot_sha256)` returns the
   separate no-tool task. Use its complete versioned schema. The host must disable
   tools and check the native transcript; model-written receipt fields alone are
   not proof that no tools ran.
5. `validate_extraction` checks exact saved prose spans, source/work/version IDs,
   known evidence IDs and structure. These checks do not prove that a cited paper
   supports a claim, or that the extraction accurately interprets the prose.
6. `integration.build_next_packet(packet, source_root, raw_proposal, extraction,
   snapshot_sha256)` returns a new packet and parent bindings. It validates source
   bytes and candidate history, keeps earlier candidates, and records new unknowns.
   Append it through the workflow snapshot interface, with an impact explanation.
   All current candidates require new checks. Keep the rich extraction artifact
   alongside the packet for bibliography, source roles and idea provenance.

Both improvement and new-concept routes are welcome; neither has a quota or an
automatic novelty bonus. Zero candidates is legitimate. Unknown effectiveness
may be the research question. Missing enabling data or a way to answer the
question remains an unresolved prerequisite.

If extraction fails, record the exact failure and preserve raw output. Follow
the host's canonical retry policy; do not invent missing values to pass a schema.
This interface adds no retry budget or background engine. Reviewers check
scientific support independently before a direction enters the choice package.

## Editable draft report

`python -m stage2_ideation report --packet PACKET --source-root SOURCES
--raw-proposal RAW --extraction EXTRACTION --snapshot-sha256 SNAPSHOT --output NEW_DIR`
exports `proposal-view.json`, editable `proposal.md`, standalone `proposal.html`
and a file-hash manifest. Set `PYTHONPATH` to this plugin's `cli` directory.
Supply the original packet and snapshot used for extraction, not the newer packet
containing its candidates. Validation completes before creating a fresh directory;
existing exports and human edits are never overwritten. A partial export without
its manifest is incomplete.

The common view preserves bibliography, evidence levels and exact excerpts,
comparability, shared-data relationships, mechanisms, alternatives, uncertainty and
raw prose. Public HTTP(S) source links are clickable; other identifiers remain
inert text. Citation text cannot run HTML or become workflow instructions.
Source hashes and excerpt bindings are checked; bibliographic identity and
scientific support still require independent verification.

This is a **draft companion**, not the checked selection package. The latter is
produced by `stage2_workflow deliver` after review reconciliation. No report export
records a user choice. Human edits must be retained as a new input and rechecked
before a later selection package can be approved.

## What the tests establish

Tests cover valid and invalid extraction structure, exact provenance, changed
sources, candidate version preservation and open idea routes. They establish
implementation behavior. They do not show that an AI finds valuable new methods
or that P4–P6 improved; those claims require independent live evaluation.
