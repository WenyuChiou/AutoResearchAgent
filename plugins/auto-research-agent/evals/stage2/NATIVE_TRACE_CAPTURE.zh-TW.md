# 原生 capture 與 trace 的封存接口

## 為何需要

只有最終回答，無法查回實際的子 agent、工具、失敗及用量。本接口把已驗證的 capture 與原始 trace 封成不可變的內容包，便於保存、查核及恢復。

## 怎麼使用

`seal_trace_capture` 接收 capture 目錄與 SHA-256 receipt、trace 目錄與完整 inventory receipt，寫入獨立的新目錄。它重用既有 capture validator、有限讀取器及 trace observer，核對根 thread 與每次推論的模型。`verify_trace_capture` 重算內容；resume 只查核，沒有模型或工具重跑。

來源、工作目錄、profile 與輸出不可互相包含。多餘檔案、錯誤版本、hash、符號連結、Windows reparse point、篡改及不完整來源都會被拒絕。驗證 control 檔案使用有上限的 buffered read，避免 WSL 檔案只回傳一部分。失敗輸出保留，由呼叫者另建修正後的嘗試。

## 它能證明什麼

證據類別固定為 `receipt-bound-content-link`，`formal_ready` 固定為 false。這只建立執行後的內容連結，不能證明原始取得過程、A/B 隔離、研究品質或 provider 帳單。測試注入標記、未知用量及未完成事件仍保留；不能因封存成功就宣稱正式 A/B 可以開始。

10 個 deterministic tests 涵蓋 resume 不寫入、跨 capture 錯配、模型錯配、篡改、注入標記、大 control 檔案、目錄替換及 JSON 布林值／整數混淆。檔案建立重用保留目錄 handle 的 I/O 接口，不能被換掉的路徑導向其他目錄。另用封存的真實 Linux 日誌做不連網、不掛載憑證、零模型呼叫的回放；它是診斷證據，並非新的研究試驗。
