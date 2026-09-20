# Instruction routing smoke evidence

- Date: 2026-09-20 (America/New_York)
- Codex CLI: 0.153.3
- Mode: fresh ephemeral session, read-only sandbox
- Working root: AutoResearchAgent repository root
- Raw final-message SHA-256:
  `af9b45e5bd7570b09f6bf621cd2e9205c2bf12739ad9f4681062b66c60c78785`

The prompt asked Codex to plan a future Stage 1 literature change without
editing or implementing. Before proposing a change, it had to list the governing
repository and evaluation documents, identify implementation/review ownership,
state whether Stage 1 was executable, and name the evidence required before an
improvement claim.

The session loaded root `AGENTS.md`, followed its route to the plugin
`AGENTS.md`, and then listed the complete required contributor reading order. It
correctly reported that contributors and their AI implement and open PRs, the
core team reviews and merges into the fork, Stage 1 remains non-executable, and
scientific improvement requires the frozen three-pair A/B with blinded judges
and required human audits. It made no repository edits.

This record proves instruction discovery for the named CLI version and prompt.
It does not prove research-quality improvement, behavior for every future Codex
version, or completion of the Stage 1 production harness. The raw ephemeral
session is not committed; its final message is bound by the hash above.
