# Stage 2 單次原生評分呼叫入口

這個入口讓外面的控制器準備一份評分題目，再交給單一角色執行。
隔離區只需要本次的 prompt、JSON schema、固定設定與原生 Codex。
參考答案、代號對照表、其他角色的評分及正式 A/B 組別留在外面。

`stage2_live.judge_worker.execute_worker_unit` 沿用未修改的
`call_model_v31`。原生指令維持 ignore-user-config、read-only 及既有工具
停用設定；原始 prompt 不加字、不換成新的 rubric，也不在 worker 裡評分。
成功紀錄必須沒有工具事件。停用設定或沒有呼叫工具，不代表 runtime
沒有提供工具；實際 offered inventory 仍須由外面的原生 telemetry 核對。
一個單元可能有凍結政策允許的 transport retry。回傳的 root attempt 數
不能當成所有 inference、子 agent、工具或完整 tokens 的數量。

輸入 `Stage2NativeJudgeUnit` v1 包含角色、對應的穩定 label、prompt、
不含 `$ref`、`$dynamicRef` 或 `$recursiveRef` 的 inline object schema、
模型與 reasoning、執行檔 hash、worker hash 及完整政策。
呼叫端另保存原檔 SHA-256；worker 核對後才呼叫 Codex。角色支援 R1、
R2、ADJ。ADJ 是否需要啟動、content-first 次序與修正限額由外部控制器
處理；這個小入口不會自己授權新的修正或研究選擇。

輸出保留原生 model-call archive、原始 JSONL、stderr、顯示副本及
`worker-result.json`。外部保存 result hash 後，可用
`verify_worker_output` 唯讀重播：不呼叫模型、不覆寫結果，且改過的
分數、狀態、副本、額外檔案、worker 或執行檔都不能冒充原結果。
原生 archive 的 label 也必須屬於這次角色與單元；改名後重算 hash 仍拒絕。
同一輸出資料夾不可重新執行。逾時及解析失敗保留原始 attempt，列為
evaluator failure，不算研究方向的 0 分。

這個入口**不建立隔離環境**。宿主端仍要提供經查核的角色專用 namespace、
精確 runtime/package/rootfs bytes、私有檔案不可讀證據與逐 attempt trace。
worker 輸出明示 `semantic_validation=host-required`、隔離待外部查核、
nested usage 與 offered inventory 待外部核對、cost unknown、calibration pass
null、formal-ready false。
接到這個入口不會讓整批 QA 自動從 injected-test 升級為正式 native 校準。

控制器取得原始回覆後，才還原代號、執行原有科學 validator、決定是否
需要一次語意修正，最後依既定 rubric 計算結果。日常 B-only 評分與
正式 A/B 的來源、獨立性、audit、校準及投入政策門檻仍各自成立。
