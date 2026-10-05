# 原生執行紀錄觀察器
**Why／What：** 最後一段回答不能證明子 agent 完成、工具成功，或用量沒有漏算；`stage2_live.trace_observation.inspect_native_trace` 整理原生日誌、模型呼叫、工具、父子關係、失敗、未完成事件及 tokens。
**How：** 先核對原檔與外部 receipt，再查 thread／turn／call 關係。完成事件必須在同一個 active turn；rollout 結束後只接受 context 相符的 terminal、已完成 thread 的結束事件，以及 receipt-bound `shutdown_complete`。矛盾結果或新工作拒絕。Compaction 重用 `CompactionState`，缺用量或 ID 重疊保持 unknown。
**Example／tests：** 未完成 child 或失敗工具會如實列出。生命週期與來源鏈在此整合測試；工具繼承／用量格式由 `test_stage2_trace_parsing.py`，compaction 由 `test_stage2_trace_compaction.py` 驗證。 這是離線觀察器，不發模型呼叫、不改原檔。`formal_ready` 永遠為 false；正式評估仍須綁定真實執行、runtime、版本、角色隔離及外部 receipt，不能從解析成功宣稱科學改善。
