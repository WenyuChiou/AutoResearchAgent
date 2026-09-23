# P1–P9 指標白話說明

這套指標回答一個簡單問題：研究 agent 的答案看起來很完整時，我們怎麼知道它真的可靠？

每個子指標的分子、分母與裁定規則請見 [評估指標操作型定義](OPERATIONAL_DEFINITIONS.zh-TW.md)。

## 先理解評分方式

每個指標由兩位評分者獨立給 `0–2` 分，再由第三人處理分歧。`0` 表示缺漏或不成立，`1` 表示有做到但不足，`2` 表示證據足以讓研究安全地進到下一步。各指標分開報告，不把 P1–P9 加成一個總分，避免一項高分掩蓋另一項嚴重問題。

- **硬量測**：電腦可以直接數或檢查，例如找到幾篇、多少 claim 有原文位置、紀錄是否符合 schema。
- **人工判斷**：需要人讀內容後判斷，例如某篇文獻是否真的支持 agent 寫的結論。
- **重大錯誤門檻**：若捏造文獻、錯配 DOI、用沒有證據的「從來沒有人做過」當主要創新，或把未完成結果說成完成，該次結果不能宣稱改善。

## Stage 1：文獻蒐集與證據

### P1 Evidence Reliability｜證據可靠性

**像在問：**「agent 說這本書裡有這句話，書、頁碼和內容都是真的嗎？」

- 硬量測：title、author、year、DOI 或網址是否正確；核心 claim 有沒有連到特定版本與原文位置；有幾筆無法查證或錯配。
- 人工判斷：原文是否真的支持 agent 對方法、結果與限制的描述。
- 壞例子：DOI 可以打開，但其實是另一篇文章；或文章存在，卻沒有說 agent 宣稱的結論。
- 好例子：書目資料核對正確，並能從 claim 回到文章版本、頁碼或段落。
- 為何重要：P1 不可靠，後面的 gap、假設與實驗都建立在錯誤地基上。

### P2 Relevant Coverage｜相關文獻覆蓋

**像在問：**「拼圖有很多片，但關鍵的四個角和最新幾片有沒有找到？」

- 硬量測：四個 coverage clusters 是否都有資料；frozen core 與 must-have 找到幾篇；是否執行 recent-work sweep；最新文獻年份。
- 人工判斷：漏掉的文章是否有同樣直接、同樣重要的替代來源；目前文獻是否足以支持研究決策。
- 壞例子：找到 15 篇人口老化文章，但沒有任何 LLM consumer agent、人口到 agent 的映射或 validation 研究。
- 好例子：所用 rubric 要求的每類文獻都有證據，另有最近研究與 closest-work search，停止搜尋的原因也說得清楚。
- 歷史 v1 development benchmark 的 baseline 問題：雖然當時廣義 clusters 為 4/4，frozen core 只有 7/10、must-have 0/2、近期研究 1/15，所以只能算部分充分。這些是舊四群評分，不能改用目前 [aging-bidirectional 六群 rubric](rubrics/AGING_BIDIRECTIONAL_RUBRIC_V1.zh-TW.md) 重新計分。
- 為何重要：漏掉最接近研究時，agent 很容易把已有人做過的事誤稱為新 gap。

### P3 Auditability｜可稽核性

**像在問：**「別人能不能沿著麵包屑，重走一次 agent 的搜尋和選擇？」

- 硬量測：每次 query、工具參數、時間、成功或失敗、raw output、候選文獻、納入排除理由、版本與 access date、claim locator、停止決定是否留下紀錄。
- 人工判斷：現有紀錄是否足以重建並質疑重要決定。
- 壞例子：只交出最後 15 篇 DOI，沒有人知道還看過什麼、為何刪除或為何停止。
- 好例子：每篇文獻可以回到 discovery path；include → exclude 的改變也保留兩次 decision events。
- baseline 問題：雖有 21 次 web calls，但沒有跨 query candidate ledger、decision history 或 claim locator。
- 為何重要：沒有 P3，就無法知道改善來自 harness，還是來自運氣、人工提示或未記錄的搜尋。

## Stage 2：比較研究並找出值得做的方向

### P4 Comparison Quality｜比較品質

**像在問：**「agent 是把每篇文章各講一次，還是真的把它們放在同一張表上比較？」

- 看什麼：研究是否用共同欄位比較 population representation、agent behavior、data、method、outcome 與 validation。
- 壞例子：十篇各一段摘要，讀完仍不知道它們哪裡相同、衝突或互補。
- 好例子：同一個比較矩陣清楚指出方法差異，以及這些差異如何改變結論。
- 為何重要：沒有真正比較，就很難從文獻推導合理的 gap。

### P5 Gap Validity｜研究缺口有效性

**像在問：**「這個洞真的存在，還是 agent 沒找到已經補洞的人？」

- 看什麼：gap 是否連到 closest work；是否說清楚「已知什麼、缺什麼、範圍在哪裡」；是否避免沒有證據的全面性 absence claim。
- 壞例子：「沒有人研究人口老化與消費」，但其實已有大量 aging-consumption 文獻。
- 好例子：「既有研究估計平均消費效果，但尚未驗證人口情境如何透過 LLM household agents 形成分布結果」，並列出最接近研究。
- 為何重要：P5 決定研究是否真的有新意，也決定教授或 reviewer 是否會接受研究定位。

### P6 Research Value and Selection｜研究價值與方向選擇

**像在問：**「有三條路時，agent 有沒有用理由選出這學期最值得走、也走得完的一條？」

- 看什麼：每個方向的貢獻、資料、難度、風險與替代方案是否可比較；推薦是否明確連到研究價值與 16 週限制。
- 壞例子：因為題目聽起來新穎就推薦，沒有比較資料與驗證難度。
- 好例子：列出 2–3 個方向，用相同準則比較，並解釋為何推薦方向的價值和可行性最佳。
- 為何重要：好的 gap 不一定是學生團隊現在做得完的 gap。

## Stage 3：把方向變成可檢驗的研究設計

### P7 Scientific Design Validity｜科學設計有效性

**像在問：**「問題、假設、模型和最後能說的結論，是不是同一件事？」

- 看什麼：research question、estimand、hypotheses、人口到 agent 的 coupling、LLM 決策、情境比較與 claim boundary 是否一致。
- 壞例子：只模擬年齡不同的 agents，卻宣稱人口老化造成真實世界消費改變。
- 好例子：清楚定義外生人口情境、固定條件、agent 狀態、決策、聚合方式，以及結果只能支持哪一種 scenario claim。
- 為何重要：P7 防止模型跑得動，但回答了另一個問題。

### P8 Validation Strength｜驗證強度

**像在問：**「模型答對，是因為真的學會，還是我們拿答案教它再考同一題？」

- 看什麼：baseline 是否合理；calibration data 與 independent validation data 是否分開；是否檢查個體、分布與人口聚合三個層次。
- 壞例子：用同一份資料調參又宣稱驗證成功，或只說 LLM 回答看起來合理。
- 好例子：先用一部分資料校準，再用未參與校準的年份、地區或樣本驗證，並和簡單規則模型及無 LLM baseline 比較。
- 為何重要：P8 決定 simulation 結果是否有資格被當成研究證據。

### P9 Feasibility｜可行性

**像在問：**「這個計畫在 16 週、現有資料和普通電腦下，真的做得完嗎？」

- 看什麼：資料能否取得、授權是否允許、運算量、成本、時程、技能、主要風險與 fallback 是否具體。
- 壞例子：需要未公開的交易資料或幾百萬次昂貴 LLM calls，卻沒有替代方案。
- 好例子：先完成小型 MVP；若個體資料拿不到，就改用公開 household survey 的分組統計與 population weights。
- 為何重要：研究價值再高，無法執行就不能成為本學期的主方案。

## 每個工具要怎麼使用這些指標

每個 skill、MCP tool、CLI、validator 或 gate 都必須在 capability metric map 登錄：它要處理哪個問題、預期影響哪些 P 指標、每個 PR 能跑哪些 deterministic checks、哪些部分仍需人工判斷，以及何時跑 frozen live A/B。PR 測試證明工具沒有破壞 metric interface；stage milestone 的 paired A/B 才能證明研究品質真的改善。

Stage 1 的成功規則固定為：P2 與 P3 改善、P1 不下降，而且沒有新增重大錯誤。時間、tool calls、失敗次數與人工介入另外報告，不能拿「跑得快」抵銷「答案不可靠」。
