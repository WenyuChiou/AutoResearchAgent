# AutoResearchAgent Stage 1 plugin

The plugin can be discovered and its skill loaded by Codex. It now includes an
experimental [saved-observation ledger](references/stage1-ledger.md), with local
extraction, validation, decision history, conservative readiness and checkpoint.
Live retrieval, identity verification, scientific coverage policy and metric
export remain later milestones. Installation does not establish a complete
Stage 1 research run.

The experimental [coverage compiler](references/stage1-coverage.md) freezes an
authored question decomposition and its unexecuted query families before search.
Saved execution rounds now bind exact queries to that plan and reject failed,
missing or truncated results as evidence of search completion. Qualified-work
coverage and the sufficient-stop policy are still under development.

## Install from this checkout

From the repository root, use the public Codex CLI:

```shell
codex plugin marketplace add .
codex plugin add auto-research-agent@auto-research-agent-local
```

Start a new Codex session after installation. The skill is
`auto-research-agent:stage1-literature`. The marketplace source resolves relative
to the repository root. This plugin uses the root Agent Plugins v1 manifest
supported by this checkout, not the legacy `.codex-plugin` manifest layout.

## Regression checks

The supported test runtime is Python 3.11 and Codex CLI 0.153.0. The loading test
uses actual `plugin/list` and `plugin/read` JSON-RPC calls against `codex
app-server`; it does not implement a substitute loader. It copies only this
plugin and marketplace into a disposable repository and isolates the Codex
home, without installing into the operator's profile or making model calls.

```shell
uv run --no-project --python 3.11 --with-requirements plugins/auto-research-agent/requirements-test.txt python -m unittest discover -s plugins/auto-research-agent/tests -v
```

Set `CODEX_TEST_BIN` to an alternate executable path when needed. Set
`STAGE1_TEST_EVIDENCE_DIR` to retain the RPC transcript and server stderr.
The CLI test version is recorded explicitly; passing it does not establish
that an arbitrary other Codex version can load the plugin.

The [shared contracts](references/stage-contracts.md) describe all six research
stages. Their tests exercise valid records, malformed references, missing
fields, version rejection, human authorization and blocked stop decisions.
The local ledger validator checks artifact integrity and replay consistency.
The conservative readiness gate never reports sufficient scientific coverage.

The [evaluation contract](evals/README.md) freezes the primary P1-P9 scorecard
and operationalizes Stage 1 P1-P3 without committing benchmark answer keys.
Routine CI validates only schemas and synthetic examples. Paired live A/B runs
use the separately controlled frozen benchmark bundle.

All contributors must follow [CONTRIBUTING.md](CONTRIBUTING.md). Every new
skill, tool, validator or gate must declare its target metrics and tests in the
[capability metric map](evals/capability-metric-map.v1.json).

Codex contributors must also follow the plugin-scoped [AGENTS.md](AGENTS.md),
which fixes the required reading order and delivery responsibilities. The
[readiness and team workflow](evals/READINESS_AND_TEAM_WORKFLOW.zh-TW.md)
separates instruction readiness, evaluation readiness, an executable Stage
harness, and a demonstrated live A/B improvement.
