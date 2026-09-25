# 評估指標操作型定義

這份文件定義「實際要數什麼、誰來判斷、分母是什麼」。白話概念請先看 [P1–P9 指標白話說明](METRICS_EXPLAINED.zh-TW.md)。

以下 Stage 1 四群與 10／2 文獻分母只屬於歷史 v1。南韓雙向耦合正式 A/B 使用
[六群 v2 操作型定義](stage1/OPERATIONAL_DEFINITIONS_V2.zh-TW.md)。v2.0 使用兩人一致納入；
[v2.1 單人策展修訂](stage1/SINGLE_HUMAN_CURATION_V2_1.zh-TW.md)由 Eric 獨立核准。
不能混用兩個版本的分母或舊 run01 分數。

## 1. 核心文獻從哪裡來

目前的 `10` 篇 frozen core 是歷史四群 `aging-llm-coupling-tw-v1` development benchmark 的**最小 anchor set**。它放在外部受控 benchmark bundle，production harness 不能讀取。repo 只保存數量、評分規則、版本與 bundle SHA-256，不保存 title hints。這些數字與下文四群定義維持 v1 原義；目前 [aging-bidirectional 六群 rubric](rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md) 是另一個版本，不能拿來重算舊 baseline。

這份 anchor set 依四個 coverage clusters、基礎方法、closest consumer-facing LLM work 與 validation 需求整理，每篇都有 inclusion reason。它受到 exploratory run01 的缺漏分析影響，因此適合在相同案例做固定 paired A/B，但有三個限制：

1. 它不是全領域真值全集，也不代表研究只能引用這些文章。
2. 它不是 unseen holdout；run01 已參與 benchmark 與 rubric 的形成。
3. 現有 bundle 記錄了來源與納入理由，但未完整記錄獨立雙評分者的候選篩選過程，所以不能宣稱這 10 篇由完整 systematic review 得出。

因此 v1 的 `classic / most-important` claim 狀態是 **not established**。要改成已確認，curation audit 必須同時檢查六種角色：理論機制、量化實證、人口到 agent 的耦合、simulation／reweighting 方法、跨國或跨情境案例，以及三層 validation。每個角色都要保存候選來源、納入排除理由與 reviewer 裁定；citation count 只能作為參考，不能代替與本題的直接性。

未來 blind case 的 anchor set 必須在 harness 與 rubric 凍結後建立：先定義題目、截止日、clusters 和上述六種角色；由資料庫搜尋、backward/forward citation chaining 與 expert seeds 產生候選；核對來源；兩位評分者獨立判斷 directness、role 與 inclusion；分歧交由第三人裁定；最後保存納入排除理由、版本、日期與 manifest hash。被測 agent 不可參與選答案。

### 如何定義「經典」與「重要」

`classic` 和 `decision-critical` 分開評，因為剛出版的 closest work 可能非常重要，但還沒有足夠時間成為經典。

| 判斷 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| Classic—領域認可 | 找不到獨立認可證據 | 一個可靠 review／guideline／textbook 採用，或有初步引用延續 | 至少兩個獨立權威來源視為基礎，或有五年以上可追查的持續採用 |
| Classic—理論／方法奠基 | 只做小幅應用 | 明確擴展既有理論或方法 | 首創、正式化或成為後續研究反覆使用的標準方法 |
| Classic—耐久性 | 尚無跨時間使用證據 | 在另一資料、國家或情境被使用 | 五年以上持續在多個獨立情境被使用或檢驗 |
| Importance—與本題直接性 | 只碰到關鍵字 | 提供間接機制或一般方法 | 直接研究本題的 population、decision、outcome 或 validation link |
| Importance—決策影響 | 漏掉不改變判斷 | 會補充理由但不改變選擇 | 漏掉會改變 closest work、gap、方法、baseline 或 claim boundary |
| Importance—證據品質 | 身份或內容無法核實 | 可核實但資料／方法有明顯限制 | primary source 可核實，方法與限制足以支持指定角色 |
| Importance—替代性 | 有多個等價來源 | 有部分替代但證據不完全相同 | 沒有 equally direct substitute，或替代後仍失去關鍵資訊 |

Classic 候選必須在 benchmark 截止日前至少出版五年、三個 Classic 項目都不為 0，且合計至少 `5/6`。這個時間條件不適用於 recent closest work。`must-have` 必須在 directness 與 decision impact 都得 2、evidence quality 至少 1，且兩位評分者確認沒有 equally direct substitute。門檻、原始證據與不同門檻下的 sensitivity check 都要在凍結前保存。

`core anchor` 可以是符合 Classic 門檻的 foundational work，也可以是未滿五年但符合 must-have 規則的 decision-critical work。不能因 citation count 高就自動列入，也不能因文章新就排除 closest work。

### Core、must-have 與替代來源

- `core`：對某個 cluster、基礎方法或驗證風險有直接且必要作用的最小 anchor。命中是「同一作品」命中，preprint、正式出版版或可確認的版本替代均可。
- `must-have`：若漏掉會實質改變 closest-work 或 gap 判斷的來源。它在 run 前凍結，不能看完 treatment 後再新增來扣分。
- `equally direct substitute`：不是 frozen title，但對同一問題提供同等直接、同等可信的證據。它不改寫 frozen core recall，評分者另在 relevance、coverage 與 P2 裁定中記錄，避免只認 title 的機械評分。

## 2. 共通計分規則

- 事實項目報 `n/N`；分母為 0 時填 `NA`，不能填 0%。
- `unverifiable` 表示現有證據無法查核，不等於已證實錯誤。
- 每個可查核 claim 先拆成一個可判真的 method 或 finding 子句，不能把整段文字算一項。
- 研究判斷由 R1、R2 獨立給 0–2 分，ADJ 保存協議後結果；三個分數都保留。
- treatment 寫得較少時，不能只報較高正確率；必須同時報交付量、coverage 與遺漏。
- P1–P9 不相加。重大錯誤、耗時、工具數與人工介入分開報。

## 3. Stage 1 子指標

| ID | 操作型定義 | 對應主要指標 |
|---|---|---|
| `S1_DELIVERY` | 去重後有效 scholarly works 數；有效表示至少有可辨識 title 與可追查來源。另報是否在 prompt 要求篇數內、四群是否都有內容。 | P2 |
| `S1_FIELD` | 每篇已填且有實質內容的適用欄位數／適用欄位數。固定欄位為 title、authors、year、venue/version、DOI/link、data、method、findings、limitations、relevance。 | P1、P3 |
| `S1_META` | 實際提供的 title、author、year、venue 各欄逐項查核，報 `correct / incorrect / unverifiable` 與總數。 | P1 |
| `S1_DOI` | 每個 DOI 或 source link 是否對應同一作品與版本，報 `correct / incorrect / unverifiable`。網址能開但指向別篇算 incorrect。 | P1 |
| `S1_CLAIM` | 每個主要 method/finding 子句依原文評為 `supported / partial / contradicted / unverifiable`。只有 metadata 或 abstract 時必須標示 evidence level。 | P1 |
| `S1_CENTRAL_MISMATCH` | 影響 gap、方法選擇或設計的核心來源、DOI、方法或 finding 錯配數。大於 0 時另檢查 major-error gate。 | P1 |
| `S1_REL` | 每篇 0–2：2=直接回答題目或提供必要方法／驗證；1=間接但用途合理；0=對研究決策沒有實質用途。兩位評分者獨立判斷。 | P2 |
| `S1_CORE_RECALL` | 命中的 frozen core works／10。同一作品的版本替代可算命中；equally direct substitute 另記，不改分母。 | P2 |
| `S1_MUST_HAVE` | 命中的 frozen must-have works／2。must-have 表示其缺漏會改變 closest-work 或 gap 判斷。 | P2 |
| `S1_RECENT` | 執行年 `Y` 的 `Y−2` 至 `Y` 作品數／年份可確認作品數；另報 latest year 與 unknown-year count。舊經典不因年份舊自動扣分。 | P2 |
| `S1_COVER` | 有至少一篇已核實且實質支持的 cluster 數／4。只有關鍵字擦邊或未核實來源不算 hit。 | P2 |
| `S1_SEARCH_TRACE` | 能從 transcript 或 ledger 回到 query/citation path、工具結果與落地來源的 works／實際列出 works。 | P3 |
| `S1_CLAIM_LOCATOR` | 有 version、page/section/paragraph 或可重現 locator 的 central claims／全部 central claims。 | P1, P3 |
| `S1_DECISION_REASON` | 有 reason code 與 evidence reference 的 include、exclude、reversal、stop decisions／全部 decisions。 | P3 |
| `S1_VERSION_DATE` | 同時保存 source version 與 access date 的 included works／全部 included works。 | P3 |
| `S1_STOP_EVIDENCE` | 布林值；只有 coverage、recent sweep、closest-work check、失敗狀態與 marginal yield 都有紀錄時才為 true。 | P3 |

歷史 v1 development benchmark 的四個固定 clusters 為：aging／life cycle／retirement／household consumption；population projection 到 synthetic 或 reweighted agents；consumer/economic ABM 與 LLM decisions；calibration、independent validation、distributional alignment 與 limitations。這裡的 `S1_COVER` 分母 4 和上述 v1 計數不變；目前 aging-bidirectional case 依其 [六群 rubric](rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md) 規劃與評估，不可默默替換這個分母。

## 4. Stage 2 子指標

Stage 2 的固定評分單位是「整份回答」或「每個 research direction」，依下表標示。得到 2 分表示足以支持下一個研究選擇。

| ID | 單位與 2 分條件 | 對應主要指標 |
|---|---|---|
| `S2_COMPARE` | 整份回答；用共同尺度比較 objective、data、population representation、decision mechanism、outcome 與 validation，並連回 evidence ID。 | P4 |
| `S2_NEAREST` | 每個方向；指出真正 closest work，分開寫出它已完成什麼與本案新增什麼。 | P5 |
| `S2_GAP` | 每個方向；gap 範圍有限、有 evidence 支持，且寫出會推翻或削弱 gap 的證據。 | P5 |
| `S2_TRACE` | 有一個以上 evidence ID 的主要 comparison/gap judgments／全部主要 judgments。 | P5 |
| `S2_UNCERTAINTY` | 整份回答；不把 packet 沒涵蓋的 absence、資料可用性或因果機制寫成事實，清楚標示證據邊界。 | P5 |
| `S2_VALUE` | 每個方向；說明增量改善哪種理解、測量、預測、驗證或決策，以及誰受益。 | P6 |
| `S2_FEASIBILITY` | 每個方向；依資料、16 週、驗證與運算限制列出關鍵依賴與 fallback。 | P6 |
| `S2_SELECT` | 最終推薦；用同一尺度比較替代方向的價值、證據、資料、驗證與風險後選擇。 | P6 |
| `S2_GAP_SUPPORTED` | gap 得 2 分的方向數／實際提出方向數。 | P5 |

## 5. Stage 3 子指標

Stage 3 各項以整份 proposal 為單位給 0–2 分。2 分條件如下。

| ID | 2 分條件 | 對應主要指標 |
|---|---|---|
| `S3_QUESTION` | 定義研究對象、分析單位、scenario、outcome 與 estimand。 | P7 |
| `S3_ESTIMAND` | 分開 composition、behavioral aging、cohort 與 period effect，主要 estimand 能由實作計算。 | P7 |
| `S3_HYPOTHESIS` | 每個核心假設有可觀察預期、比較對象與會削弱它的結果。 | P7 |
| `S3_COUPLING` | 說明人口情境如何變成 agents、states 或 weights，如何進入決策並聚合，並處理 universe mismatch、joint distribution 與 extreme weights。 | P7 |
| `S3_METHOD_LABEL` | 依實際 state、time、interaction 與 reweighting 誠實稱為 ABM、microsimulation、reweighting 或 hybrid。 | P7 |
| `S3_LLM_ROLE` | 定義 LLM input、choice set、output schema、constraints、replication、state update 與 failure handling。 | P7 |
| `S3_AGGREGATION` | 權重、budget、category shares 與 scenario comparison 的聚合規則和單位一致。 | P7 |
| `S3_CLAIM_SCOPE` | 結論限制在設計可支持的 descriptive、predictive 或 conditional scenario 範圍。 | P7 |
| `S3_VALIDATION` | 分開驗證 synthetic population、LLM choices 與 population outcomes，且每層有對應真實資料與指標。 | P8 |
| `S3_BASELINES` | 至少有透明 non-LLM baseline 與 unconditioned 或 ablated LLM；LLM 輸給 baseline 仍被接受為有效結果。 | P8 |
| `S3_LEAKAGE` | calibration、prompt/model selection 與 final validation 分離；資料少時使用預先定義的 holdout 或 cross-fitting。 | P8 |
| `S3_DATA` | 說明來源、存取條件、必要變數、粒度、母體、授權與可執行備案。 | P9 |
| `S3_FEASIBILITY` | MVP、16 週 schedule、decision gates、calls/compute、主要依賴、風險與 fallback 具體。 | P9 |

## 6. 可觀察性與成本

| ID | 定義 |
|---|---|
| `O1_PROMPT_MATCH` | 實際 prompt SHA-256 是否等於 manifest；不等時保存差異。 |
| `O2_CONFIG` | model、reasoning、mode、skills、plugins 與 MCP 是否能由 screenshot 或 log 核實。 |
| `O3_LINEAGE` | 每個重要 output 是否能追到 input、source/tool call、stage 與 timestamp。 |
| `O4_RECOVERY` | interruption、resume 與 retry 是否保留；是否產生互相矛盾的 final versions。 |
| `C1_TIME` | 從開始到結束的 elapsed seconds，包含等待，timestamp 必須含 timezone。 |
| `C2_TOOLS` | 各 tool/search call 次數、成功數、失敗數；empty result 必須和 backend failure 分開。 |
| `C3_HUMAN` | clarification、補文獻、方向提示與人工改錯次數。 |
| `C4_USAGE` | tokens 與 cost 只記平台實際提供值；不可把 unknown 填成 0。 |

這些成本不能抵銷 P1–P9。比較 A/B 時，同一 stage、同一 repeat 使用 `delta = treatment − baseline`；三對 runs 只描述方向與波動，不宣稱統計顯著。
