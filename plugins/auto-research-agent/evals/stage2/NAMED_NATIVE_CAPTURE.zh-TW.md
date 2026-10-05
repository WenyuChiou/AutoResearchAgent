# 原生權限：明確使用已核對的 profile

舊 capture 保持 `workspace-write` 參數及 v1 紀錄。新增 opt-in v2 capture，
讓需要原生 managed network proxy 的環境使用 named permissions。
它不關閉 sandbox，也不修改 Rust runtime。
## 必要設定

`Stage2NamedPermissionsPolicy` v1 指定 profile 名稱、config 的實際 bytes
SHA-256 及 telemetry 目錄。只接受已定義的模型、reasoning、原生 live
搜尋、子 agent 及 network proxy 設定；未知的設定組合先拒絕。

檔案權限必須是：根目錄唯讀、自己的 workspace 可寫，profile、telemetry
及 capture output 不可被工具讀寫。四個角色目錄不得重疊。
網路允許研究搜尋，但禁止 local binding 與 loopback domains。

capture 以 `default_permissions` 明確選擇這份原生 policy，避免另外的
`--sandbox` 參數蓋掉 named profile。不存在、被改過或限制不同的 config
會在啟動前失敗。完整紀錄綁定 archived config，resume 不再執行模型。
受控 named run 拒絕 workspace／ancestor config，並以 runtime 參數固定
untrusted project 與必要功能，避免 project 設定覆蓋權限。此模式仍可
讀寫、搜尋與使用子 agent；舊的日常 project 設定流程維持原規則。

## Example
原本：runner 要求 workspace-write，但與真正載入的權限不一致。
現在：先核對 profile 的原始 bytes 與限制，再用同一名稱啟動並保存紀錄。
preflight 仍然查真正 session 中的有效權限及實際工具結果，不相信設定
檔本身已證明成功。

本接口只處理原生 dispatch 與 requested policy。角色專用掛載、實際拒絕證據、完整工具清單、所有子 agent 用量及正式 readiness 仍需另外驗收。
不能把 config 通過檢查或 synthetic capture 當成正式 A/B 隔離證明。
