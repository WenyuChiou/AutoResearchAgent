# 已封存工具紀錄的解析

`preflight_trace_witnesses.project_tool_witness` 整理一個實際工具呼叫的
開始、結束、參數、結果及可用的 runtime 事件，保留原文位置與 hash。
它接受已驗證 inventory 的原始 bytes，不讀檔、不執行工具，也不判定
研究品質或正式測試已準備好。呼叫端仍須核對 trace 與外部 receipt。

缺少結束、事件重複、跨 thread、順序錯誤、失敗或引用不符時拒絕。
沒有 runtime 事件的 web 紀錄，以及只有結束事件的 spawn 紀錄，按各自
實際格式保存；不能因沒有 shell 的事件格式就說原生工具沒有執行。

測試是合成紀錄，用來驗證解析規則，不能冒充真實研究預演或 A/B。
