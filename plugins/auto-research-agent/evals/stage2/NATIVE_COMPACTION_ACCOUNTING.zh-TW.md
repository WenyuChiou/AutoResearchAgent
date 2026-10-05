# 壓縮紀錄與用量

**Why**：同一次模型呼叫不能被加兩次；同一壓縮工作重試，也不能被當成只花一次。

**What**：`trace_compaction.CompactionState` 依每個原生 request ID 保存嘗試，
綁定原始輸入、回應、thread 和 turn。重複的相同完成紀錄只計一次；矛盾紀錄拒絕。

**How**：重用 receipt-bound reader 和 typed token validator。
原生 `compaction_request_*` 的每個 request 分開保存，失敗與缺少用量都留下。
若 ID 與普通 inference 重疊，完整加總不能成立。

**Example**：目前原生壓縮回應只保存 output items，沒有 tokens。
即使它成功，也必須報 unknown，不能猜成零或用另一筆呼叫的 tokens 代替。
後續原生版本若提供用量，仍需通過同一套 typed validation。

這是離線解析能力，不會派出模型，也不代表正式 A/B 可啟動或科學品質已改善。
