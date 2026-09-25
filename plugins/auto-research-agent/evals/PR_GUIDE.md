# Research harness pull-request contract

Every research-harness PR must explain why the change is needed, what options
were considered, how the selected mechanism works, and what observable behavior
changes. The default repository template is checked in CI.

Write every section in plain language that a new teammate can understand on the
first read. Use short sentences and concrete examples, and define necessary
technical terms. The `Plain-language summary` gives the problem, change and
benefit in one sentence. CI checks its presence; the core team reviews actual
clarity.

## Required sections

### Why

Name the target primary metric, cite the baseline or failure artifact, and
explain why the failure matters to a later research decision. A statement such
as “improve literature search” is insufficient without a measured failure.
Start with the one-sentence plain-language summary.

### What

Name every affected capability ID from the capability metric map. Describe the
methods considered and classify every capability as `reuse`,
`wrap`, `extend`, or `build-new`. Explain why the chosen option is the smallest
adequate intervention and identify out-of-scope work.

List every related cross-repository PR as a GitHub PR URL, separated by
semicolons, including `research-hub` or `ai-research-skills` changes. Do not put
the current AutoResearchAgent PR in this field. Write `None` when no external
PR exists. The core team must be notified when any related PR is opened so it
can review the whole change rather than only the local adapter.

### How

Describe the concrete interfaces, artifacts, events, validation, error states,
human gate and stopping behavior. State how production logic stays isolated
from benchmark answers.

### Example

Show a representative before/after input and output or artifact. Use synthetic
identifiers unless the example is already public production evidence. Do not
paste frozen core-source titles or adjudication keys into production prompts.

### Evaluation

For the experimental, gold-set-free Stage 1 path, choose rubric
`stage1-general-v3` and its `P1V3`/`P2V3`/`P3V3` criteria. Map these to
the matching `S1V3_*` definitions; never map `P2V3.CORE_SELECTION` to the
historical `S1_CORE_RECALL`. This experimental rubric currently permits only
`implementation-only`. A later PR must bind the topic spec, v3 rubric hash,
and v3 evaluation result to a new readiness manifest before it can claim
`stage-executable`; `improvement-demonstrated` additionally needs a frozen
paired protocol and reviewed evidence. Routine automatic v3 scoring needs
no human paper answer list; publication and PR merge remain core-team decisions.

State the baseline, treatment, registered rubric version, exact criterion IDs,
evaluation mode, hard measures, AI-judge evidence, major-error guardrail and
cost measures. Include the actual per-PR metric evidence and the live A/B
decision. Routine PRs need deterministic checks; a stage milestone needs the
frozen paired live A/B protocol.

Add one `Improvement statement` beginning with `improved`, `not improved`, or
`not yet demonstrated`. State the behavior, then add `; evidence:` followed by
a measurement, passed/failed test, artifact, or explicit milestone deferral in
the same sentence. This prevents a completed coding task from being mistaken
for a useful harness improvement.

### Validation

List commands and actual results, review evidence, limitations, and whether a
live A/B run is required now or deferred to the milestone.

Treat the completed PR description as the executor's short progress report to
the organizing core team. Record `Execution status` as `complete`, `partial`,
or `blocked`, and state the remaining work or blocker. A partial or blocked PR
must name what prevents completion. The core team uses this report, test
results, improvement statement and external PR links to supervise progress and
choose the next task.

When any affected capability ID starts with `skill:`, add the five-line skill
test mini-report from the PR template. The report names the scenario, exact
command, expected result, actual result and limitations. The test must cover
loading/discovery, one representative behavior, and one relevant guardrail or
explicit failure state. Contract/schema tests with a synthetic fixture are
acceptable for a declarative workflow skill. Executable skills must exercise
their executable path. This report does not replace milestone A/B evidence or
blinded scientific scoring.

## 三種 evaluation readiness，用最白話的方式理解

把 harness 想成一台新做的機器：

1. `implementation-only` 表示「按按鈕時，零件照設計動」。可以用小型、假的資料測試。
   這只能證明程式有做指定行為，所以 Improvement statement 只能寫
   `not yet demonstrated` 或 `not improved`。
2. `stage-executable` 表示「整台機器真的跑過一次，而且別人拿紀錄可以重播」。PR 要附
   live run、validator report、實際 runtime bytes 的 hash、dependency merge SHA 與 resume
   結果。這仍然沒有證明它比原本 Codex 好。
3. `improvement-demonstrated` 表示「用相同且事先固定的判準比過舊機器和新機器」。PR
   要附三組 paired runs、Auto-R1、Auto-R2、必要 Auto-ADJ／audit 與 paired decision。
   舊 v1／v2 另需 private holdout hash；通用 Stage 1 v3 則需執行前凍結的題目規格、
   rubric、評估器與原生擷取鎖，**不需論文答案表**。目前 CI 仍只允許 v3
   `implementation-only`，新版 readiness validator 通過前不可宣稱正式改善。

`Operational-definition mapping` 告訴 reviewer 每個分數是怎麼從程式資料算出來。例如：

```text
P3.STOP_EVIDENCE -> S1_STOP_EVIDENCE -> policy.evaluate
```

左邊是 rubric 問的問題，中間是 frozen 計量規則，右邊是實際產生資料的 field 或
function。每個 criterion 都要有一列，避免 PR 寫了想改善 P3，程式卻沒有可量的輸出。

Invariant 是「無論資料怎麼變，都不能被破壞的安全規則」。PR validator 會依 criterion
自動要求以下測試；作者不能只挑容易通過的測試：

| 宣告的能力 | CI 必須看到的 invariant |
|---|---|
| P1 identity、claim 或 locator | `artifact-producer-bound`, `evidence-work-version-bound`, `missing-evidence-fails-closed` |
| P2 closest work | `unverified-closest-blocks-stop` |
| P3 failure state | `failure-distinct-from-empty` |
| P3 stop evidence | `all-stop-inputs-required` |
| Capability registered with `runtime_integrity_required: true` (live CLI/runtime wrapper) | `runtime-bytes-bound`, `dependency-sha-bound`, `resume-no-reexecution` |

Every registered CLI must set `runtime_integrity_required` explicitly. Use
`false` for an offline-only ledger or transformation. Use `true` when the
capability launches or wraps the live research runtime or an external tool.
| Plugin production evaluator validator 或 gate artifact | `rehash-tamper-rejected` |

每個 invariant evidence 使用可由 CI 查到的實際 test selector：

```text
all-stop-inputs-required -> plugins/auto-research-agent/tests/test_stop.py::StopTests.test_missing_recent_sweep_continues -> passed
```

CI 不相信作者自己打的 `passed`。它會讀
`.github/scripts/invariant-registry.v1.json`，確認這個 selector 確實屬於該
invariant、不是 skipped test，並實際執行該 selector。白話說，測試像有
名字的鑰匙：測前門的鑰匙不能拿來假裝測過火警器。

criterion 可以對應哪些 frozen submetric，固定在
`.github/scripts/criterion-submetric-map.v1.json`。例如 closest work 不能因為
同屬 P2 就改用 paper count。CI 也會確認 mapping 右側的 production field 或
function，真的存在於已宣告 capability 的 owner path 裡。

`stage-executable` 與 `improvement-demonstrated` 的 artifact 欄位使用同一種格式：

```text
artifact: manifest=path/to/readiness-manifest.json; sha256=<64 hex characters>
```

每個必要欄位必須指向同一份 manifest bytes。CI 會打開 manifest、重算它的
SHA-256，再打開清單內每個 artifact 並重算各自的 SHA-256；也會檢查 execution
complete、validator passed、resume passed。`improvement-demonstrated` 另外要求
三組 paired runs、R1、R2、必要的 ADJ 狀態、accepted human
audit 與 paired decision。標成 `contract-fixture` 的檔案只能測 validator，本身
不能支撐真實 PR 的 readiness claim。白話說，不能只寫「證據在箱子裡」；要把
封條、裝箱單和每一件物品都交給 CI 對過。

其中歷史 v1／v2 再綁 private holdout hash；v3 改綁執行前的題目規格、rubric、
評估器與原生 capture lock，沒有論文答案表。v3 的 Level 2／3 CI 契約尚未完成，
目前仍只能提交 `implementation-only`。

Manifest 的共通欄位是 `kind=ReadinessEvidenceManifest`、
`schema_version=1.0.0`、與 PR 相同的 `readiness`、`evidence_scope`、
`execution_status=complete`、`validator_status=passed`、
`resume_status=passed`，以及 `artifacts` 清單。每個 artifact 都要有唯一 `role`、
repository-relative `path` 與該檔案的 `sha256`。

| readiness | `evidence_scope` | 必要 artifact roles |
|---|---|---|
| `stage-executable` | `live-smoke` | `live-run`, `validator-report`, `runtime-bytes`, `dependency-bytes`, `resume-report` |
| `improvement-demonstrated` | `formal-paired` | 上述全部，加上 `frozen-plan`, `paired-request`, `paired-decision`；request 會再綁定六個 judge bundles 與必要 audits |

`live-run` JSON 的 status 必須是 `complete`；`validator-report` 必須是
`passed`；`resume-report` 必須是 `passed` 且 `reexecuted=false`。Level 3 的 plan
必須是 frozen formal `EvaluationPlan`。CI 會把 `paired-request` 交給現有
`paired_evaluation.py`：它會重新驗證 plan、六個 bundles、每個 bundle 的 R1/R2、
必要 ADJ/human audit、run attestations 與三組 pairs，再重算 decision。提交的
`paired-decision` 必須逐欄等於重算結果，且與 PR 的 improved/not-improved 敘述相同。
Manifest 仍要記錄 `pair_count=3` 與 private holdout SHA-256，但 CI 會由正式 request
再次推導 pair count，不能只相信這兩個字面值。

`Internal prerequisite PR(s)` 用於本 repository 的 stacked PR。Draft 可以指向尚未合併的
前置 PR；Ready PR 的前置 PR 必須已合併且不可維持 Changes requested。跨 repository
依賴同時填 `Related external PR(s)` 與 `External dependency pin(s)`：

```text
https://github.com/WenyuChiou/research-hub/pull/137 @ 0123456789012345678901234567890123456789 @ merged
```

Open dependency 使用當下 head SHA；merged dependency 使用 immutable merge SHA。
每個 Ready PR 的 prerequisite 都必須已 merged。`stage-executable` 和
`improvement-demonstrated` 另外要求 external dependency 已核准。跨 repository
PR 不能填進 internal 欄位來繞過 immutable SHA pin。

## Filled example

### Why

- Plain-language summary: Keep the search trail so another person can see what
  was tried, why papers were kept, and why the search stopped.
- Target primary metric(s): P2 Relevant Coverage and P3 Auditability.
- Observed problem and evidence: the exploratory baseline covered 4/4 broad clusters but reached
  only 7/10 frozen anchors and recorded no candidate decision ledger.
- Why this matters to the research workflow: a plausible literature table can still miss the closest work,
  which makes the downstream novelty claim unreliable.

### What

- Affected capability ID(s): skill:stage1-literature
- Options considered: hard-code missed titles; add another search provider;
  wrap existing search with coverage planning and an append-only ledger.
- Capability decision: wrap
- Decision reason: reuse existing search and verification commands.
- Chosen change: add query-family planning, candidate decisions and a coverage
  stop gate. Benchmark titles remain outside production logic.
- Out of scope: live scientific-quality claims before the Stage 1 milestone.
- Related external PR(s): None
- Internal prerequisite PR(s): None
- External dependency pin(s): None

### How

- Emit `query_events.jsonl`, `candidates.jsonl` and
  `decision_events.jsonl` with source references and reason codes.
- Treat backend failure separately from a valid empty result.
- Return `continue` when the closest-work cluster lacks verified evidence.
- Allow a human to continue, revise the query, or accept the stop decision.

### Example

Before: `15 papers collected -> stop`.

After: `15 papers collected -> closest-work cluster incomplete -> continue`,
with the triggering query and candidate decisions linked from the gate result.

### Evaluation

- Evaluation readiness: implementation-only.
- Baseline and treatment: stock search versus the same search wrapped with the
  candidate ledger and coverage gate.
- Rubric version: aging-bidirectional-rubric-v1.
- Rubric criterion ID(s): P2.CLUSTERS, P2.CLOSEST_WORK,
  P3.DECISION_TRACE, P3.FAILURE_STATE, P3.STOP_EVIDENCE.
- Operational-definition mapping: P2.CLUSTERS -> S1_COVER ->
  coverage.cluster_status; P2.CLOSEST_WORK -> S1_COVER ->
  coverage.closest_work_verified; P3.DECISION_TRACE -> S1_DECISION_REASON ->
  ledger.reason_code; P3.FAILURE_STATE -> S1_SEARCH_TRACE ->
  query_event.status; P3.STOP_EVIDENCE -> S1_STOP_EVIDENCE ->
  policy.evaluate.
- Required invariant IDs: unverified-closest-blocks-stop,
  failure-distinct-from-empty, all-stop-inputs-required.
- Invariant test evidence: unverified-closest-blocks-stop ->
  plugins/auto-research-agent/tests/test_stage1.py::Stage1Tests.test_unverified_closest_continues
  -> passed; failure-distinct-from-empty ->
  plugins/auto-research-agent/tests/test_stage1.py::Stage1Tests.test_failure_is_not_empty
  -> passed; all-stop-inputs-required ->
  plugins/auto-research-agent/tests/test_stage1.py::Stage1Tests.test_all_stop_inputs_required
  -> passed.
- Evaluation mode: hybrid.
- Hard measures: cluster coverage, frozen-anchor recall, decision-reason
  completeness, trace completeness, failures, time and tool calls.
- AI-judge evidence: deferred: waiting for the Stage 1 executable milestone; this PR
  provides deterministic synthetic artifacts only.
- Major-error guardrail: no benchmark title enters production logic and no
  backend failure is reported as an empty result.
- Per-PR metric evidence: synthetic missing-cluster, backend-failure and reversal tests
  pass and produce schema-valid artifacts.
- Improvement statement: not yet demonstrated — deterministic behavior is implemented but live quality remains unknown; evidence: synthetic tests passed and live A/B is deferred to the Stage 1 milestone
- Live smoke evidence: deferred: the stage milestone will save a live run and validator report.
- Paired evaluation evidence: deferred: three frozen pairs run only after stage execution is complete.
- Runtime integrity evidence: deferred: runtime hashes and resume checks are produced at the stage milestone.
- Time, tools, failures, and human-intervention guardrails: report all calls,
  failures and interventions separately from P2 and P3.
- Live paired A/B: deferred to the Stage 1 executable milestone.
- Success: paired P2 and P3 improve, P1 does not regress, and no major error is
  added.

### Validation

- Synthetic backend failure and decision-reversal tests pass.
- Stage 1 evaluation artifact validates against the public schema.
- Three paired live A/B repeats are deferred to the Stage 1 milestone.
- Execution status: complete
- Remaining work or blocker: None
- Review and merge owner: core team
- Skill test scenario: synthetic incomplete closest-work cluster with one
  backend failure and one include-to-exclude reversal.
- Skill test command: `python -m unittest discover -s plugins/auto-research-agent/tests -p "test_*.py"`.
- Skill test expected: the skill loads, preserves both decisions, records the
  backend failure, and returns `continue`.
- Skill test actual: all targeted tests pass and the synthetic artifacts
  validate; attach the test count and artifact path from the current run.
- Skill test limitations: deterministic fixtures do not establish a P2 or P3
  improvement on live literature retrieval.

## Commit and merge record

Commits remain single-purpose and record `Why`, `What`, `Tests`,
`AI contribution`, and `Human verification`. Contributors open PRs and address
feedback; the core team reviews and merges them. Use a merge commit so the
commit history remains inspectable. Delete the merged branch after the `main`
Stage 1 checks pass.
