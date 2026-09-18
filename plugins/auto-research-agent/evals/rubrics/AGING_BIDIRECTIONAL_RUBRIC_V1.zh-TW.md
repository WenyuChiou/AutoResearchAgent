# Aging bidirectional rubric v1

這份文件只解釋 `aging-bidirectional-rubric-v1`。舊的 Stage 1 v1
baseline、四群組 probe 與原始人工評分規則仍照原版本解讀，不能拿這份
六群組規則回頭改分。

## 最簡單的理解方式

把 research agent 想成一位要交作業的研究助理：

1. Stage 1 要找對資料，不能把找不到寫成不存在。
2. Stage 2 要把研究放在同一張表比較，再說真正還缺什麼。
3. Stage 3 要把方向變成可以做、可以驗證、失敗時也有備案的研究。

每個主指標使用 0、1、2 分：

- **0 分**：缺少關鍵內容、內容矛盾，或會讓下一個研究決定出錯。
- **1 分**：方向合理，但證據或做法還沒補齊。
- **2 分**：證據與做法已足夠支撐下一個指定的研究決定。

硬資料優先於 AI judge。例如檔案不存在時，judge 不能因文字寫得漂亮而判定
「已驗證」。缺少或無法存取的證據要標成 `unverifiable`，不能猜成正確。

## Aging case 的雙向耦合

正向路徑是：人口與家戶狀態形成 consumer agents 的屬性、權重與決策情境。

回饋路徑是：消費、工作、儲蓄、市場、服務或政策結果，透過有資料依據的規則，
更新下一期的環境與 agent 狀態。

生育、死亡、遷移、退休、家戶組成與健康轉移，必須來自觀測資料、明確情境或
可查核的 transition model。LLM 不可以自行創造這些轉移，再把它們當成真實人口資料。

研究可以是 confirmatory、exploratory、method-development 或
simulation-discovery。探索型研究要先說明搜尋空間、分析單位、結果、pattern rule、
多重比較處理與後續確認方式，不必假裝已有實驗假設。

## Stage 1：找到可信且足夠的文獻

### P1 Evidence Reliability

白話問題：**這篇文獻真的是它聲稱的那篇，而且真的支持我們寫的話嗎？**

要檢查書目、DOI 或連結、claim 支持程度、原文位置、證據層級與 mismatch。
中央 claim 無法查核時，P1 最多 1 分；出現 P1 major error 時為 0 分。

### P2 Relevant Coverage

白話問題：**需要看的六種拼圖是否都有，而不是只找到很多篇文章？**

六個固定 clusters 是：

1. aging、life cycle、retirement 與 household-consumption mechanisms；
2. population synthesis、reweighting 與 dynamic demographic transitions；
3. household decision、microsimulation、ABM 與 macroeconomic models；
4. LLM consumer／household agents 與 behavioral fidelity；
5. bidirectional market、environment、social interaction 與 multi-period feedback；
6. calibration、independent validation、uncertainty 與 claim limitations。

正式 v2 benchmark 還要完成 private core／must-have anchor bundle 綁定。完成前，
六群組 rubric 可以開發與校準，但不能宣稱已完成正式 aging A/B。

### P3 Auditability

白話問題：**另一個人能不能沿著紀錄，重建 agent 做過的每一步？**

每次搜尋、include／exclude、反轉決定、來源版本、claim locator、工具失敗與停止理由
都要留下 append-only 記錄。429、credential failure 與真正的 zero result 必須分開。

## Stage 2：比較研究並提出有根據的方向

### P4 Comparison Quality

白話問題：**研究是否用同一把尺比較，而不是逐篇摘要？**

共同維度包含 objective、data/population、demographic transitions、decision mechanism、
bidirectional feedback、outcomes、validation 與 limitations。差異必須說明會如何改變後續決定。

### P5 Gap Validity

白話問題：**這個 gap 真的存在，而且範圍說得清楚嗎？**

每個 research direction 都要回答：closest work 做了什麼、已知與未知如何分開、
gap 在什麼條件下成立、我們新增什麼、什麼新證據會削弱它，以及每句話的證據在哪裡。

### P6 Research Value and Selection

白話問題：**這個方向值得做、做得到，而且為什麼選它？**

每個方向使用同一組維度比較：科學價值、相對 closest work 的增量、資料、validation、
16 週可行性、compute／LLM cost、風險與 fallback。最後推薦仍由人類留下決定紀錄。

## Stage 3：把方向變成可執行研究

### P7 Scientific Design Validity

白話問題：**問題、研究模式、雙向互動、時間更新與最後能說的結論是一件事嗎？**

設計必須說清楚 demographic-to-agent mapping、feedback loop、LLM 的輸入與可選行為、
period order、aggregation，以及哪些結論超出設計範圍。探索結果不能事後改稱預先假設。

### P8 Validation Strength

白話問題：**模型像真實世界，是因為真的拿獨立資料檢查，還是只因為看起來合理？**

四層 validation 是：

1. synthetic/reweighted population；
2. LLM decision behavior；
3. bidirectional feedback dynamics；
4. aggregate and distributional outcomes。

Calibration 與 final holdout 必須分開，並包含透明 non-LLM baseline 與
unconditioned/reduced-LLM ablation。LLM 輸給簡單 baseline 也要如實報告。

### P9 Feasibility

白話問題：**學生團隊能否在 16 週內，真的把最小版本做完？**

要列出 data access、MVP、schedule、compute/calls/cost、decision gates、risks 與
fallbacks。未知成本保持 unknown，不能填成 0。

## criterion 與 major error 怎麼查

`aging-bidirectional-criteria.v1.jsonl` 是逐條判分表。每個 criterion 都有定義、
必要證據與 0／1／2 分條件；每個 major error 都有穩定 ID。主 rubric 用 SHA-256
綁定這份 catalog，避免只改判分細節卻仍沿用同一個 frozen 版本。

P1 對 included work、central claim 與 stage summary 分別留下結果；P5 對每個
research direction 分別評分；P6 對每個 direction 與 final recommendation 分別評分。
不能把弱項平均掉。其他主指標依 rubric 的 `evaluation_units` 評分。

Auto-R1 與 Auto-R2 在不知道 baseline/treatment 身分的情況下獨立評分；兩者的分數或
major-error 判斷不同時才交給 Auto-ADJ。重大錯誤、低信心、中央證據無法存取、接近的
A/B 結果與對外研究主張，仍需要 targeted human audit。
