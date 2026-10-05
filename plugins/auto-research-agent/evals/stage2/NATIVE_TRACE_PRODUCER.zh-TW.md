# 每次原生呼叫的取得與封存

`capture_observed_native` 先查核完整 named policy，再取得 config、skills、plugins 與 MCP 的原生 API 清單；接著只執行一次 Codex，封存該次 raw trace、工具／子 agent 紀錄及 capture。完成後交回獨立保存的 `producer_receipt`。恢復要提供這個 receipt，重新查核來源、設定、模型、時間及封存內容，不能重跑模型。

呼叫者準備分離的 workspace、profile、capture 與 telemetry 目錄。`CODEX_ROLLOUT_TRACE_ROOT` 必須已等於 policy 的 telemetry 路徑；接口不修改 sandbox 或環境變數。Subject 的 named policy 必須拒絕整個 telemetry、profile 和 capture 目錄。新呼叫只接受空 telemetry；來源 trace 與 `bundle` 分開，後者存放 inventory、seal 及 control record。

API 清單不等於模型實際收到的工具及指令；仍須核對 raw request。`host-observed-producer` 也不是 provider 的獨立簽章，`formal_ready` 固定 false。未知費用維持 unknown，失敗不變成完整紀錄。完成的封存可以恢復；失敗、來源變更或不完整的輸出保留供診斷，不能冒充可恢復的成功。

10 個合成 regression tests 查核一次執行與恢復、stale／多份 trace、根 thread／模型／時間、來源／設定／runtime 變更、失敗、無效 policy、混合注入與重新計算 hash 的 JSON 型別篡改，以及 inventory 目錄替換與來源綁定錯配。這些測試驗證工程接口；真實角色隔離、研究預演及正式 A/B 另行驗收。
