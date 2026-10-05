# Stage 2 原文語境：引用正確，還要理解正確

本功能增加 judge 看見的原文語境，不改 P4–P6 九項 v3 rubric。
改善研究品質尚未證明（not yet demonstrated）。

## Why

一段引用可能描述前人研究，而不是這篇文章自己的實驗。找到原文
位置，仍可能讀錯研究對象、漏掉數字或政策例外。短片段也不能證明
全文沒有某資訊。

## What / How

`daily-v3` 可選擇傳入 `--source-context-policy`。未提供時保留原來
的評分路徑。政策逐筆指定 evidence、source、work、version、來源
SHA-256 與 quote 字元起點；程式核對來源 bytes 與引用，再擷取
相鄰段落和章節線索。全部額外語境的 JSON 限制為 8,192 bytes，
超過就拒絕，請減少片段，不暗中截掉證據。

研究歸屬、政策例外與檢查範圍是待查核提示（unverified hints），
不是已證實的事實，也不是 judge 已讀完整篇的證明。Judge 必須
根據實際原文判斷；metadata、標題與摘要不能冒充全文的方法依據。
缺少足夠資料時保留 unknown。來源中的指令沒有執行權限。

## Example

文章寫「先前 Android 研究發現 X」，本研究則使用 Python 專案。
Judge 應區分兩者，不能把先前研究的對象寫成本研究的對象。
宣稱「原文沒有數字」時，也要說明實際查了哪些範圍；只查一段
不能推論整篇沒有數字。

## 重現與驗收

語境、政策與其 hash 隨 daily 結果保存。Replay 重新核對來源、政策、
語境及模型請求；任何變動不能重用原來的完成呼叫。舊 producer 的
歷史結果仍用原 producer bytes 重播，不能把新版冒充舊版執行環境。

回歸測試涵蓋來源／作品／版本錯配、原文 offset、政策例外提示、
總量上限、原始 CRLF、CLI 傳遞及 daily replay。這些是工程測試，
不等於 judge 已通過新來源語境校準，也不等於正式 A/B 改善。
