# Stage 1 / T1：完整來源判讀視圖

舊 `make_packet` 只保存摘要的前 2,000 字元。合成範例的 5,187 字元摘要因此少了
3,187 字元，連末尾反證也消失。這是評估器的表示問題，不是 subject 的研究缺陷。

`audit_source_evidence.materialize_audit_sources(packet, source_records)` 接受原封不動的
舊 packet 和完整來源紀錄，產生另一份視圖與 `Stage1AuditSourceMaterialization.v1`
收據。上游先用原有來源收據和已合併的 research-hub `source validate` 核對來源；
這個函式不取得資料、不驗證來源真實性，也不判 claim。

摘要保留全部 UTF-8 文字和換行。題名、作者、年份等 metadata 另列，不冒充全文；
metadata-only 紀錄仍是 metadata。作品、版本、原始來源 hash、完整紀錄 hash、
衍生欄位位置與每次 catalogue 出現的位置全部保留。日期超過 cutoff 的排除也列出原因。

`verify_audit_materialization` 從原 packet 和完整 catalogue 重建結果；改文字後重算
外層 hash、改作品／版本／型別、缺紀錄或 ID 衝突仍拒絕。舊 packet 和舊結果不覆寫。

這是 T1 語義審計前的來源表示介面。完整來源不代表已送進模型，收據中的
`semantic_audit_completed` 固定為 false。後續 bounded units 必須逐一處理來源並保留
原文位置；逐篇身分、逐 claim 判讀、criterion 匯總與正式 A/B 另有執行／審查關卡。
本切片僅為 implementation-only，沒有 P1–P3 品質改善數字。
