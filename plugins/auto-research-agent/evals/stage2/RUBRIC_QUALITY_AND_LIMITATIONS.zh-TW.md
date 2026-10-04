# Stage 2 rubric judge 品質與限制

> **本檔是 v2／QA01–QA03 的歷史紀錄。** 下方七項 rubric、56 案例及
> 0／2 預演，是 v3 上線前的快照，不是目前狀態；原始數字完整保留。
> 現行九項標準、盲化校準與操作請看 [Stage 2 v3](STAGE2_V3_EVALUATION.zh-TW.md)。
> [2026-10-04 的 B 預演紀錄](../evidence/stage2-v3-b-pilot-endpoints-2026-10-04.json)
> 記錄兩份自動選擇包及評分：US 待具名覆核，修訂後 flaky-test 的 R1／R2 一致。
> 這不代表方向已選定、實驗可執行或品質已改善；正式 A/B 仍為 0／6。

這套校準只檢查 evaluator 能否依固定 rubric、控制事實與 subject record 穩定判分。它是 diagnostic，不是正式 A/B，也不證明研究方向品質改善。

| 輪次 | 範圍正確率 | R1/R2 一致 | 風格不變性 | 結果 |
|---|---:|---:|---:|---|
| QA01 | 95.5357% | 98.2143% | 100% | 失敗：有 critical major-error 錯誤與五個重大分歧 |
| QA02 | 98.2143% | 100% | 100% | 失敗：零 critical 錯誤，但 P5 revision 的 major-error 判斷與 reference 邊界有分歧 |
| QA03 | 91.0714%（102/112） | 100%（56/56） | 100%（56/56） | 16 個 native calls 完成；零 critical／重大分歧，達到預先門檻；修正 validator 後只讀重驗通過 |

QA02 的獨立 ADJ 保留 score=0 並判 major error=true；private reference 是 score=1、major error=false。因此 `quality_accepted=false`。ADJ 不會改寫原始 110/112、56/56、56/56 計數，也不能把失敗結果補成通過。事後檢查顯示 reference 把「撤回錯誤的縱向結果與解釋、提出可行的縮小替代方案，但尚未完成 materials／answerability 重查」誤寫成仍保留 recovery outcome。QA03 以全新機制、事實與 opaque IDs 獨立測試這個邊界；rubric 與 guidance 不變。

`unavailable` 表示 evaluator 沒拿到 subject record，必須是 `unknown`、score=null、major_error=null；背景 facts 不能證明 subject 說過或漏掉什麼。`verified-absent` 才表示已檢查完整 deliverable 且確認缺項。

Deterministic 或 injected-fake 測試只能證明 schema、hash、分母、隔離介面與失敗路徑；不能證明 live judge 通過。所有 raw counts、分歧、失敗、calls 與 receipts 都要保留。迄今完整 Stage 2 live 預演通過數為 **0/2**；正式完成的 Stage 2 subject runs 為 **0/6**。QA03 通過的是控制案例校準，`formal_ready` 仍為 false。

QA03 的 10 個 out-of-range 判斷，是 R1／R2 對同一個 P5 REVISION 部分修訂 anchor 與四個等義變體，皆判 2 而參考為 1；不是十個獨立研究失敗。這是集中於「修訂充分程度」的殘留邊界風險，不能因整體達 90% 就不報告。正式 A/B 仍保留具名覆核與一分差異的 audit 規則。三輪 QA 題目不同，數字不構成 harness A/B 改善率。

Shipping review 另發現三個程式漏洞，現已補 regression tests：四個 base anchors 必須確實涵蓋 0／1／2／unknown，不能全部只考 1；ADJ 的 score／status／major flag 都必須符合參考範圍；錯誤容器與 evidence IDs 必須回傳 typed Stage2Error。QA03 原始 native 結果及舊 evaluator bytes 完整保留。修復後先重建原 16 個完成 archives，再用新 validator 檢查，未重發模型呼叫，原始 102／112、56／56、56／56 不變。重驗紀錄的 evaluator binding 與原始 binding 分開保存。

## 評估器先測什麼，為什麼

我們先確認「尺會量」，再用它比較有沒有 research harness。生產 checker 的五面向是幫研究者查方向；外部 evaluator 的七個 criterion 是判斷整份方向選擇包的品質。Checker 的 PASS、候選數量、篇幅、複雜度或 agent 數量都不直接加分。

| 維度 | Criterion | 白話意思 |
|---|---|---|
| P4 | COMPARISON | 比較研究時，有沒有把相同與不同條件講清楚？ |
| P5 | OPPORTUNITY | 新增的東西真的還沒被前人做完嗎？邊界與反例有沒有查？ |
| P5 | REVISION | 發現問題後，有沒有真的改掉，而非只換字？ |
| P6 | VALUE | 回答後誰會更理解問題、量得更好或做出更好的決定？ |
| P6 | FEASIBILITY | 材料、可回答性、授權與資源的判斷有沒有根據？ |
| P6 | DISPOSITION | 推薦、修正、暫存與淘汰是否符合證據？ |
| P6 | PORTFOLIO | 使用者能否拿到有用選項、取捨與下一步？ |

凍結 anchors 在 `stage2-general.v2.json`：0 表示有根據的缺失或錯誤；1 部分充分；2 充分。拿不到必要查核材料是 null，不算 0。某方向不成立，卻有根據地被淘汰，仍可以得到高品質分數；全部淘汰也不自動滿分。

## 56 案例如何計數

七個 criterion 各有 0／1／2／unknown，先得到 28 個 anchor。每個 criterion 選一個 anchor，另做順序、篇幅、聲望提示與偏好措辭四種等義變體，再得到 28 個。來源事實與真正的使用者限制不能改。

- 參考範圍符合率：R1 與 R2 各判 56 個指定 criterion，分母固定 **112**，要求至少 90%。不加入其他無關 null 來增加命中。
- 完全一致率：每案例比較 R1／R2 的 score 與 status，分母 **56**，要求至少 85%。重大錯誤標記分歧另外保存，不能被這個數字掩蓋。
- 等義變體一致率：兩位 judge 各比較 28 個變體與其 anchor，分母 **56**，要求至少 90%。重大錯誤標記也不得因修辭改變。
- 明確事實／重大錯誤的 critical 案例不能誤判；significant disagreement 必須全部釐清。缺呼叫、evaluator failure 或缺案例阻擋驗收，不能刪掉案例縮分母。

R1／R2 使用不同 evaluator home。每批最多七個案例，各八批，共 **16 個完成單元**；实际 transport retry 或語意修正會增加模型呼叫數，另從 archived attempt records 計算。Reference 不進 judge prompt。成本不可得時是 unknown。

## API、證據與恢復邊界

`stage2_eval.rubric_quality.evaluate_quality` 只做 deterministic 計算。`stage2_live.rubric_quality.run_rubric_quality` 才執行 native judge，需固定 dataset／reference hash、model、reasoning、runtime、guidance 及 policy。輸出保留 request、result、16 個 unit receipt、schema、prompt 和完整 call archive。Injected adapter 永遠不能建立 native QA pass。

新 QA run 的目錄必須是空的；目前此入口**不支援中断續跑**，已有紀錄不得覆寫。完成 run 的 ADJ 使用 `stage2_live.rubric_adjudication.resolve_rubric_quality`：先用外部保存的 result hash 重建 16 個已完成單元，禁止重發 R1／R2 呼叫；第三個獨立 home 先保存自己的初判，再看匿名 R1／R2 判斷並解釋改判。

ADJ 不改原始計數、答案或分數；critical 原始錯誤不能靠裁決洗成通過。裁決的來源、設定、結果及 receipts 全部保留；`quality_accepted` 和 `formal_ready` 是不同狀態。

## 與正式 A/B 的關係

正式 A/B 是同 brief、起始證據、原生工具與投入政策下，A＝原生 Codex、B＝相同 Codex加 Stage 2 harness；固定三對順序 AB／BA／AB。P5、P6 各至少兩對改善且零退步，P4 零退步，B 不新增重大錯誤。不合成總分、不以三對宣稱統計顯著。

此 QA 入口不會自動寫入正式 readiness。仍需完成實際 inventory collector、子 agent 用量、隔離、補充來源驗證、兩個完整預演及 QA 到正式 gate 的整合。既有 formal validator 對缺少 collector／完整用量持續 fail closed。正式品質改善依然是 `not yet demonstrated`。
