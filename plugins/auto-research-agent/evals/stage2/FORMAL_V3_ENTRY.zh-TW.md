# Stage 2 v3 正式評估入口：凍結計畫不是完成測試

## Why

舊正式入口使用七項 v2 rubric。不能把它的計画或成績換個名稱，
就當成九項 v3 的結果。兩組也不能拿到不同的起始證據，或讓 A
先看到先前 B 已經產生的候選與 judge 評語。

## What / How

新增 `freeze-formal-plan-v3`，使用版本 2.0.0 的計畫契約；科學 rubric
仍是 stage2-general-v3。每個面向固定三項、六分，保留舊入口與結果。
計畫核對 brief、rubric、起始來源、prompt、工具／模型／依賴版本、
投入政策及六次執行順序。A 與 B 的原生政策必須相同。

共同來源 manifest 是 Stage2FormalCommonEvidence v1，只包含
brief reference、sources、claims 與 unknowns。来源記錄 work、version、
bytes hash 及證據層級；claims 保留其驗證狀態與位置。它不能包含
候選、checker 判斷或外部 judge 評語。來源文字與 claim 仍是研究
資料；凍結與 hash 正確不代表已經證實其科學內容。

## Example

同一份原文可以供 A 與 B 比較文獻。先前 B 提出的研究方向，不能
放进共同輸入，否則測到的可能是 B 已先做完一部分工作的效果。
重算 manifest hash 也不能讓不合法的欄位變成合法。

## 三種狀態，不能混用

| 狀態 | 真正證明的事情 |
|---|---|
| frozen | 計畫與共同輸入已保存且可重建 |
| formal-ready | 實際原生能力、隔離、用量、校準與預演證據通過 |
| formal completed | 六次真實 run、盲評、必要覆核及配對結果通過驗證 |

目前新增的是第一列。後兩列的 v3 接口與可信 evidence collector
仍需完成；不能手填 formal-ready=true，也不能改名套用舊版驗證。
Linux native sandbox 失敗時停止正式執行，保留阻塞，不關閉 sandbox。

P5／P6 各至少兩對改善且零退步；P4 零退步；B 不新增重大錯誤。
Unknown 不算零分，必要項目缺失為 inconclusive。日常 B-only 的
選擇包與評語仍可交付，與正式 A/B 完成狀態分開呈現。
