# Stage 1 / T1：從受測原文提取身分欄位

舊 inventory 有作品 ID、標題和標識符，但不單獨保存作者、年份和版本。
`original_fields.audit_subject_sources` 現在先執行原值提取，再呼叫來源審計。
輸入是已重播核對的 subject、extraction、extraction provenance、packet、
完整來源 catalogue、輸出目錄及明確的模型設定；不重新取得論文。

`extract_original_fields` 重建原始 subject span index，核對 provenance 的
雜湊與每個作品的引用位置。每個引用 span 都有一個單元，附同檔前後各一段
上下文。原文為不可信資料，不能改變執行指示。初始與修正提示均限制在
9,000 UTF-8 bytes；超限明確失敗，不截掉原值。超過 1,000 tokens 的提示
需要核心團隊額外人工審查。

模型只選來源 span、逐字文字及該文字在 span 的第幾次出現。程式核對文字
確實存在，再從保存的原文還原值與位置；多片段必須在同一檔案連續，不能
拼接相隔的敘述。這驗證字串與位置，欄位語意是否判對仍需評估。

每篇作品的 title/authors/year/identifier/version 都保留所有觀察。
同一處因上下文重疊而再次提取時共用值，但保存所有產生單元 ID。
不同位置的 2019 與 2020 不被覆蓋或合併；各自成為來源審計目標。
沒有寫版本時保留缺失，不從資料庫的版本或內容 hash 補成受測原值。

新資料只加入 extraction 的副本，原始 extraction 與所有中央 claim 不變。
`Stage1OriginalFields.v1` 記錄計畫、原生模型回覆、缺失原因、位置及衍生結果；
`Stage1OriginalAndSourceAudit.v1` 綁定提取和來源審計兩份結果。失敗紀錄及
一次修正均保留，恢復要重播核對原生單元與結果，不能靠重算外層 hash 通過。

這已接通「原值提取 → 逐欄位／claim 來源審計」的可呼叫路徑。尚未接入
正式 evaluator 主入口、criterion 語意彙整與 R1/R2/ADJ 調度，不給品質分數。
合成測試的成功不等於原始六次診斷或正式 A/B 已完成。
