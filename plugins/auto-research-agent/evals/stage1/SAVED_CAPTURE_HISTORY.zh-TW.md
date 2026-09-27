# 已保存工作區歷史：T3 的第一個切片

舊 `capture_subject` 已保留每個 attempt 的原生 transcript，但只交出最後一次
workspace snapshot；`attach_workspace` 還會把未交付檔案縮成短摘錄。
較早的檔案版本、刪除前的理由或檔案末尾因此可能未進入 evaluator。

`capture_saved_history` 先呼叫既有完整 capture/runtime 驗證，再讀每個已保存 snapshot。
每次保留原檔案 hash、bytes、相對路徑、建立／修改／未變動狀態與相鄰快照間的刪除。
可解碼 UTF-8 的檔案保留完整文字；二進位檔案仍列 hash 和路徑，不假裝有可讀原文。
原生 JSON 事件保留 command、arguments、exit code、status 與其他實際欄位。
本收集器不搜尋、不讀新來源、不向受測組提供建議，也不按 A/B 選擇不同路徑。

輸入是既有 runner 保存的 capture，輸出是全新目錄：

```text
python -m stage1_ab.capture_history CAPTURE NEW_OUTPUT
```

三個產物是 `subject.json`、`workspace-history.json` 和
`native-field-availability.json`。CLI 強制驗證 runtime，不提供跳過選項。
缺檔、改 bytes、多出未登記檔案、錯 attempt 路徑或輸出目錄已存在時報
`evaluator-error`，不能換算成研究品質零分。

`Stage1SavedCaptureHistory.v1` 與 `Stage1NativeFieldAvailability.v1` 是新契約。
只有最後快照中被最後回答明確提及的既有支援文字格式，才標為 delivered artifact；
其他版本保留為 process evidence，避免把刪除前的候選誤加到最終論文 inventory。

Availability 只列固定 JSON 路徑的原始值及欄位路徑；未見值為 null。
`item.aggregated_output` 單獨保存，不冒充分離的 stdout／stderr。
`observed_at` 是 runner 保存的 attempt 結束觀察時間；不是檔案寫入時間或工具起止時間。
若原生事件有 timestamp，照原值記錄，不能推出它的起止語義。

這裡只恢復**已保存快照**的順序，不能恢復兩次 snapshot 中間未保存的版本。
沒有因果證據時，不把某次寫檔配到某個 action。這些限制留在 manifest。
原生 transcript／answer 的既有 bytes 上限仍明確失敗，不會靜默截短。
尚需 T3 的共同即時 observer 與新 evaluator 整合；此切片 readiness 為
`implementation-only`，不啟動新 subject、不給新分數。舊 v3.1 路徑不變。
