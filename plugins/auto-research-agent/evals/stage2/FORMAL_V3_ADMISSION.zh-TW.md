# Stage 2 v3 正式驗證橋接：核對檔案不等於實驗完成

## Why

舊入口只認七項 rubric；新版九項需要自己的驗證入口。
更重要的是，資料夾存在或作者寫了 passed，不代表原生工具真的成功。

## What / How

新增 validate-readiness-v3 與 validate-formal-result-v3，manifest 版本2.0.0。
呼叫須提供 manifest、evidence-root、外部保存的 receipt、output；
result 另需 plan。Receipt 是 manifest 原始 bytes 的 SHA-256。
所有內部檔案須在 evidence-root 內且核對 hash；內部 receipt 只提供
檔案綁定，不是另一份獨立的執行證明。輸出不覆寫既有檔案。

readiness 核對新版計畫、共同來源、A/B 預檢、兩份預演及校準的檔案
綁定。未支援的預檢／controller 格式不當成語意驗證成功。
result 另重播六份 v3 judge bundle，核對原始評語／判斷、九項分數、
P4/P5/P6 各六分及 AB/BA/AB 配對；unknown 維持原規則。

## 目前仍關閉正式宣告

原生 inventory collector、完整子agent用量、v3原生校準及新版本
預檢／controller replay 尚未完成。入口列出這些 blockers，
formal_ready 與 external_claim_ready 保持 false，正式結果為
inconclusive。CLI 回傳2，讓後續程式不能把它當成通過。
這是 implementation-only 橋接，不是 formal-ready 或改善證明。

## Example

六份 JSON 的 hash 都正確，但沒有可信的工具與用量紀錄：
可以重建九項評分與配對，仍不能宣稱已完成正式 A/B。
只有重新計算 hash，也不能把改過的分數冒充原始 judge 的判斷。

舊七項入口與歷史結果保留。新的證據 collector 完成後，需要
獨立 review 與 regression tests 才能另行擴充此驗收門檻。
本輪不製造 Eric 覆核、選題或 Stage 3 授權。
