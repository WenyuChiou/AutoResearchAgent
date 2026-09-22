# Stage 1–3 evaluation workflow

這份流程用固定規則比較原生 Codex（baseline）與加入研究 harness 的 Codex
（treatment）。人類定義 rubric 與 private holdout；程式檢查硬事實；blinded AI judges
處理需判斷的內容；重大或不確定結果由人類 audit。P1–P9 永遠分開報告。

## 一張圖看懂

    Freeze case + rubric + holdout + prompt + runtime
                             │
                ┌────────────┴────────────┐
             baseline                  treatment
                └────────────┬────────────┘
                     deterministic checks
                ┌────────────┴────────────┐
              Auto-R1                   Auto-R2
                └────────────┬────────────┘
                      disagreement? ── yes ── Auto-ADJ
                             │
                        audit trigger? ── yes ── human audit
                             │
                     paired P1–P9 decision

## 執行前必須固定

Evaluation plan 要保存 case、研究模式、rubric 與 criterion-catalog hash、holdout ID 與
hash、prompt hash、模型、reasoning、mode、tools、baseline/treatment 版本、三對 run
順序、judge configs、target metrics，以及 improved、not-improved、inconclusive
規則。看到結果後不能改答案、門檻或 must-have 文獻；任何更動都建立新版本。

## Private holdout contract

Holdout 是受控答案包，不能成為 production 搜尋提示。每個 anchor 保存 identity、
version、DOI/URL、coverage cluster、研究角色、core/must-have、納入理由、原文
locator、classic/importance 判斷、兩位獨立人類 rater 結果，以及分歧時的 adjudication。
Frozen manifest 需要兩份有時間與 hash 的人類核准紀錄。

「經典」不是只看引用數：至少早於 cutoff 五年，field recognition、foundational role、
durability 都不能為 0，總分至少 5，並有兩個 authority evidence IDs。「must-have」
表示兩位 rater 都確認 directness=2、decision impact=2、evidence quality>=1，而且沒有
同樣直接的替代來源。

AI 可以找候選與整理證據，但只有人類能核准。Actor 的 attestation_ref 連到課程名冊或
其他外部身分系統；本 validator 只檢查紀錄形狀，不能自行證明某 ID 真的是人。Public
synthetic fixture 只示範 contract mechanics；單一假文獻不能作為真實 scientific
holdout。

Manifest validator 會檢查規則、安全的 private/ 相對路徑與 canonical SHA-256。它只
宣告 private-artifact boundary，不能證明檔案 bytes 正確，也不能靠 .gitignore 阻止
process 讀取答案。正式 runner 還必須核對 artifact hash，並證明 production process
沒有答案路徑或讀取權限；完成前不得宣稱 runtime isolation 已驗證。

## Run、judge 與 audit

每個 stage 做三組 paired repeats，順序交替 B→T、T→B、B→T。兩邊使用相同 prompt、
模型、reasoning、mode、stock tools、時間規則與資料 cutoff。保存 transcript、工具
事件、artifacts、版本、時間、中斷、resume、retry 與 human intervention；backend、
credential failure 與真正零結果要分開。

Deterministic checks 先確認 schema、存在性、hash、runtime 一致性、evaluation-unit
完整性、counts、identity、trace 與 failure state。硬事實優先；缺檔、hash 不符或 central
source mismatch 不能被流暢文字掩蓋。

Auto-R1 與 Auto-R2 分開執行，只看匿名 subject ID、frozen rubric 與 evidence。結果保存
criterion outcome、evidence IDs、hard-fact status、0–2 分、major-error IDs、missing
evidence、confidence 與 audit triggers。任一 unit 分數或 major-error IDs 不同就交給
Auto-ADJ，並保留兩份輸入與裁定理由。

`judge_bundle.py` 就像「兩份考卷的對答案機」：它先核對兩位 judge 是否真的看同一份
匿名作業、是否使用 plan 指定的模型與設定、檔案 hash 是否正確，再逐 unit 比較分數和
major error。兩人相同才可直接進入 paired comparison；不同就一定要 Auto-ADJ。若觸發
human audit，在人類完成並接受前，`usable_for_pairing` 必須保持 false。人類若拒絕或
判定資料不足，紀錄雖已完成，結果仍不能拿去宣稱 harness 改善。

以下情況需要 targeted human audit：major error、low confidence、central evidence
inaccessible、judge disagreement、B/T 只差一個 ordinal point，或準備對外宣稱改善。
沒有 completed audit 時只能輸出 audit-required 或 inconclusive。

## Paired decision

每一對計算 treatment 相對 baseline 的變化。預設規則：

- target metric 至少兩對改善，而且沒有一對退步；
- non-target metric 不退步；
- treatment 沒有新增 major error；
- hard checks 與必要 audit 全部完成；
- runtime、tool calls、cost、human interventions 分開報告，不能抵銷品質退步。

`paired_evaluation.py` 像三場配對比賽的記分員：只接受 plan 指定的六個可用 bundle，
先核對每次 run 的 condition、build、runtime 與 process-boundary attestation，再分開比較
P1–P9。Target 至少兩場改善且零退步；non-target 不可退步；新增 major error 直接否決。
相鄰分數與 P5/P6 分布變化先 audit。輸出綁定 request hash，不算總分或核准對外宣稱。

三對 runs 只顯示方向與波動，沒有預先註冊且足夠樣本時不宣稱統計顯著。P1 用 stage
summary；P5 保留各方向分布與 minimum；P6 保留各方向與 final recommendation；其他
metric 使用完整 stage-level unit。不得把 P1–P9 加總成一個總分。

| Stage | Metrics | 問題 |
|---|---|---|
| 1 | P1–P3 | 文獻與 claim 可靠嗎？覆蓋完整嗎？過程可重建嗎？ |
| 2 | P4–P6 | 比較公平嗎？gap 有根據嗎？方向有價值且選擇合理嗎？ |
| 3 | P7–P9 | 問題／探索目標、雙向 coupling、validation 與 16 週計畫可執行嗎？ |

Confirmatory study 可以評 hypothesis；exploratory study 要評搜尋空間、pattern rule、
多重比較處理與後續確認方式，不能事後把發現改寫成預先假設。

## 開發節奏與責任

每個 PR 跑 deterministic tests，填 capability、rubric criteria、operational mapping、
required invariants、evaluation evidence、known limitations 與 improvement statement。
三種 readiness 是三個不同問題，不能互相取代：

| Readiness | 真正回答的問題 | 最低證據 | 可以宣稱什麼 |
|---|---|---|---|
| `implementation-only` | 這個工具遇到指定輸入時，行為正確嗎？ | deterministic/synthetic tests、每個 invariant 的真實 test selector | 行為已實作；尚未證明品質改善 |
| `stage-executable` | production Stage 能否真的跑完並被重建？ | live run、validator report、runtime/dependency hashes、resume evidence | Stage 可執行；尚未證明優於 baseline |
| `improvement-demonstrated` | treatment 是否真的比 baseline 好？ | frozen plan/holdout、三組 paired runs、R1/R2、必要 ADJ/audit、paired decision | 依 frozen rule 寫 improved 或 not improved |

工具通過測試時可寫 `not yet demonstrated`；只有 stage milestone 的 paired pipeline
通過才可寫 `improved`。CI 會核對 criterion 是否連到 frozen submetric 與 production
field/function，並由 criterion 自動推導不能缺少的 invariant。寫在 PR 裡但不存在的 test
path、test selector、placeholder 結果、open dependency 或錯誤 SHA 都會失敗。CI 依
`criterion-submetric-map.v1.json` 拒絕看似同指標但答非所問的 mapping，依
`invariant-registry.v1.json` 執行每個 invariant 的 exact test selector。Stage 以上的
readiness 使用同一份 hash-bound manifest；CI 會重算 manifest 與其中每個 artifact 的
SHA-256，`contract-fixture` 不能支撐真實 readiness claim。Level 3 還會重新執行既有
plan、judge-bundle 與 paired-evaluation validators，從六個 bundles 推導三組比較並
要求提交的 paired decision 與重算結果完全相同。
每個 stage milestone 跑三對正式 A/B；對外 generalization 前再跑一個 rubric 凍結後才
揭露的 blind case。

組員 AI 負責實作、測試、synthetic report、修 CI 與列出所有跨 repo PR。Core team
定義/凍結 rubric 與 holdout、review、決定 audit，並 merge 到本 fork。簡單 baseline
勝過 LLM 或結果不確定，也要如實保留。
