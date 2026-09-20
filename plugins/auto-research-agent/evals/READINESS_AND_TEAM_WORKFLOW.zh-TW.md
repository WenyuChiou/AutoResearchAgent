# Evaluation readiness 與團隊分工

這份文件回答兩個問題：目前哪一部分真的可用，以及組員交付什麼，核心組才能安全地
決定下一步。判分規則以 [evaluation workflow](EVALUATION_WORKFLOW.zh-TW.md)、
[operational definitions](OPERATIONAL_DEFINITIONS.zh-TW.md) 與 frozen rubric 為準；
本文件不建立另一套分數。

## 四層 readiness

以下 Level 0–3 只表示系統準備程度，不是 judge 名稱。Judge 一律寫成
`Auto-R1`、`Auto-R2` 與 `Auto-ADJ`。

| Level | 白話問題 | 驗收證據 | 目前狀態 |
|---|---|---|---|
| Level 0 Instruction-ready | AI 是否先看到正確規範？ | root router、plugin `AGENTS.md`、連結檢查、fresh-session transcript | 已可用；[Codex 0.153.3 smoke](evidence/instruction-routing-smoke-2026-09-20.md) 通過 |
| Level 1 Evaluation-ready | 評估機器是否能拒絕不完整或不公平的資料？ | schemas、validators、synthetic fixtures、negative tests、三平台 CI | 已可用 |
| Level 2 Stage-executable | 該 Stage 的 production harness 是否真的能從輸入產生完整 artifacts？ | capability tests、一次 live smoke run、可重建 ledger、stage milestone PR | Stage 1 尚未完成 |
| Level 3 Improvement-demonstrated | Treatment 是否比 stock Codex 好？ | frozen private holdout、三組 paired A/B、Auto-R1／Auto-R2／Auto-ADJ、必要 human audit | 尚未執行 |

Level 0 或 Level 1 通過不能取代 Level 2；Level 2 通過也不能直接宣稱 Level 3。PR 的測試全部通過時，若尚未
完成正式 paired A/B，`Improvement statement` 必須寫 `not yet demonstrated`。

## 怎麼驗證 evaluation pipeline

### 1. 文件與 capability contract

- 從 repository root 開新的 Codex task，給一個 Stage 1 planning request。
- AI 在規劃或編輯前應指出 root `AGENTS.md`、plugin `AGENTS.md`、
  `CONTRIBUTING.md`、evaluation workflow、rubric、PR guide 與 capability map。
- 每個 production skill、tool、MCP、CLI、validator 或 gate 都要有唯一 capability ID、
  owner path、P1-P9 effects、criterion IDs、hard measures、guardrails 與 tests。

### 2. Deterministic 與 synthetic checks

從 repository root 執行：

```shell
uv run --no-project --python 3.11 --with-requirements plugins/auto-research-agent/requirements-test.txt python -m unittest discover -s plugins/auto-research-agent/tests -v
python -m unittest discover -s .github/scripts -p test_validate_research_pr.py -v
```

這些測試必須涵蓋 plugin loading、stage contracts、rubric、holdout manifest、evaluation
plan、judge outputs、Auto-R1／Auto-R2 disagreement、human audit、run attestations 與 paired decision。
負面案例至少包含 hash mismatch、錯誤 pairing、runtime drift、缺 audit、新增 major
error、target regression 與 non-target regression。

### 3. Stage executable milestone

每個 Stage 要有一次不使用 frozen benchmark title 當提示的 live smoke run。Stage 1 至少
要產生 query events、candidate／decision ledger、claim evidence、coverage clusters、recent
sweep、closest-work expansion、stop decision、failures 與成本。另一個人必須能從 artifacts
重建 run。這一步通過只代表 production path 可執行。

### 4. Frozen paired A/B

Core team 先凍結 case、rubric、private holdout、prompt、runtime、builds、judge configs 與
decision rule。依 B→T、T→B、B→T 跑三組。程式先檢查硬事實；Auto-R1 與 Auto-R2
盲評；有分歧才交 Auto-ADJ；有 trigger 再交 targeted human audit。每個 P1-P9 分開判斷：
target 至少兩組改善且零退步，non-target 零退步，treatment 不得新增 major error。

## 分工

| 工作 | 組員與其 AI | 核心組 |
|---|---|---|
| 搜尋現有 skills、MCP、CLI、research-hub | 執行並提出 reuse／wrap／extend／build-new | 檢查選擇是否合理 |
| Capability 實作與 deterministic tests | 負責 | 設定範圍與驗收條件 |
| Synthetic evidence、PR 說明、CI 修正 | 負責 | 檢查證據是否支持聲明 |
| 外部 repository PR | 開 Draft PR 並立即回報連結 | Review；核准前不合併 |
| Rubric、private holdout、正式 plan freeze | 不得自行改答案或門檻 | 兩位人類核准 |
| Auto-R1／Auto-R2／Auto-ADJ | 依 frozen config 自動執行 | 檢查 provenance 與例外 |
| Targeted human audit | 準備完整 evidence bundle | 具名人類執行並簽署 |
| AutoResearchAgent PR | 開 PR、回覆意見、修正 | Review 並 merge 到 fork |
| Improvement claim | 提供 paired artifacts | 決定是否可寫 `improved` |

## 組員每個 PR 必須交付

- 一句話說明改動改善什麼問題。
- Affected capability、P1-P9 與 exact criterion IDs。
- Why、What、How 與一個 before／after example。
- 實際測試命令、結果、artifact path 與已知限制。
- `improved`、`not improved` 或 `not yet demonstrated`，並附同一句 evidence。
- `complete`、`partial` 或 `blocked`；後兩者列出剩餘工作。
- 所有外部 PR 連結、commit 的 AI contribution 與 human verification。

## 目前可做與不可宣稱的事

目前可以使用 frozen rubric、schemas、validators、judge bundle 與 paired runner來開發並
檢查新的 Stage capability。Stage 1 skill 仍是 foundation；retrieval、append-only ledger、
full-text claim validation 與 coverage/stop gate 尚未形成完整 executable vertical slice。
因此下一個開發里程碑是 Level 2 Stage 1，而不是重新設計評估規則。完成 Level 2 與正式 Level 3 前，
不得宣稱 AutoResearchAgent 已經比 stock Codex 更會做科學研究。
