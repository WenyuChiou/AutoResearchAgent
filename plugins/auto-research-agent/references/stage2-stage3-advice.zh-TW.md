# Stage 3 方向建議的輸入

Stage 2 的完整交付可以先送入 Stage 3，討論方向、資料條件與設計選項。
`prepare-stage3-advice` 接收普通交付目錄及外部保存的 delivery manifest hash，
產生獨立的 advisory package。`inspect-stage3-advice` 重新驗證它與原交付一致。

這個入口保留全部目前候選、原評語、修訂歷史、來源、矩陣、資源、未解事項
及零推薦；不需要先假造人類選案。資料、粒度或研究範圍的替代方案仍是待決選項。
它不執行模型、搜尋或研究，也不重新修改 Stage 2 內容。

輸出明示 `mode=direction-advice`、`human_selection=pending`、
`selected_options=[]` 和 `execution_authorized=false`。接收驗證只證明這份建議
材料與保存的交付相符，不代表科學接受、具名覆核、選案或正式 A/B 完成。

實際選定當前有效方向後，繼續使用既有 `human-record`、
`prepare-stage3-input` 與 `inspect-stage3-input`。既有選案與執行邊界不變；
advisory package 不能冒充已選案的 planning package。

正式 Stage 2 A/B 的評分終點是人類選題前的選擇包。A 是原生 Codex，B 是同一
Codex 加 Stage 2 harness；兩組的正式准入、隔離、用量與凍結計畫另行驗證。
