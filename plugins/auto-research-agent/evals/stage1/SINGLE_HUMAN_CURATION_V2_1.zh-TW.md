# Stage 1 v2.1：單一真人策展修訂

2026-09-24 的專案決定由 Eric 一人評估私有文獻答案包與必要的人類覆核，組員只負責執行與提供原始紀錄。這是相對於 v2.0「兩位真人獨立初評」的**評估設計變更**；不能把 Eric 登記兩次，也不能把 AI judge 假裝成第二位真人。

`holdout-manifest` 的 `schema_version: 2.1.0` 明確選擇單人模式。它要求一位具名真人、一份逐篇初評、一份最終答案包核准，以及 evaluation plan 中由**同一人**簽署的一份核准。候選的納入、排除、來源版本、原文位置、六群與六種角色、經典與 must-have 判斷，仍須留在私有 screening log。單人模式不得聲稱有「評審間分歧」，其 `disagreements` 必須為空；排除與反覆決定都應在 screening log 留痕。經典文獻仍需兩項獨立的*權威證據*，這不是兩個人簽名。

P1–P3 的定義、六群分母、來源核實、三組配對順序、P2/P3 至少兩對改善且零退步、P1 零退步、T 不新增重大錯誤，均維持不變。Auto-R1 和 Auto-R2 仍在不同 context 匿名評分；分數或重大錯誤判斷不同才呼叫 Auto-ADJ。Eric 針對重大錯誤、低信心、不可取得的中央證據、judge 分歧、相差一分的配對，以及任何對外改善主張執行必要 audit。硬事實優先於 AI 分數。

單人策展降低了答案包的獨立人類交叉檢查。報告須把它列為限制；三對 A/B 僅能支持南韓開發案例的方向與波動，不能聲稱統計顯著、普遍適用，或「兩位真人一致認可」。在第一個正式 subject 開始前，Eric 須核對來源與所有私有檔案的 hash，簽署實際答案包與 plan，並固定 cutoff、prompt、rubric、runtime、build、judge 與 pair order。看到正式輸出後改答案或標準，必須另開版本並作廢受影響的 series。

此修訂**不回改** `schema_version: 2.0.0` 的兩人契約與歷史資料。`stage1-primary-metrics-v2.1` 適用於 2.1.0 答案包；`stage1-primary-metrics-v2` 仍適用於 2.0.0。兩者不能互換。正式 B/T 的 subject host 不得讀取私有答案包，AI judges 只接收匿名來源證據包。
