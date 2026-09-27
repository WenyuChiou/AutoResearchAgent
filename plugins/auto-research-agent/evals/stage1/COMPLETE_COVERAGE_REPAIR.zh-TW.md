# 完整證據處理修復：第一個可審查切片

目前交付的是 **T2 的離線分派與重建檢查**。它把每段已保存證據安排到有界單元，
不修改 frozen rubric v3，不執行受測研究，也不產生新分數。T1 逐篇／claim 查核、
T2 實際模型判讀及其彙合仍待後續切片。Readiness 是 `implementation-only`。

舊 evaluator v3.1 的單一視窗最多使用 60,000 個文字字元、每作品 12,000 個字元。
有完整索引不表示每個片段都進入模型。例如保存的診斷指出一份 83 個片段的文件，
只有 3 個進入 process-R1。不能因此說研究 agent 沒有寫取捨理由。

## 這個切片怎麼做

從 `content_evidence` 或 `process_evidence` 重新生成既有 immutable span index。
每個片段保留檔案 hash、work、version、locator、view 及文字範圍。
按檔案與位置分成多個單元，每個單元的**序列化證據 UTF-8 bytes**不超過 60,000；
這是證據部分的上限，不是完整未來 model prompt 的上限。相鄰單元保留同一檔案／view
的一個前文片段；前文不重複計入主要覆蓋。所有主要片段恰好分派一次，不用 top-k。

保留 raw native JSON 和 decoded output 兩個 view。解碼後的回覆不能代替原事件的
命令、參數、exit code 或失敗欄位。這個版本不自動宣告任何片段不適用或重複排除。
換檔名或格式不會得到分數，因為這裡根本不評分。

`Stage1CriterionCoveragePlan.v1` 的每個 unit 保存 `unit_id`、`criterion_ids`、
`assigned_span_ids`、`context_span_ids` 和 `input_sha256`。criterion 保存完整
`expected_unit_ids`。`verify_coverage_plan` 從原 packet 重建全部欄位並逐欄比較，
不能靠修改 totals 或重算外層 hash 接受刪塊、重複塊、錯版本或改定位。

`Stage1CriterionCoverageManifest.v1` 目前只有 `pending` 狀態：completed 為空，
全部 expected units 留在 pending。這防止把「已安排讀」冒充「已實際送入模型且
輸出通過驗證」。後續執行器要從獨立模型 archives 重播完成證據，不能相信手填 passed。

## 可重現入口

將 plugin 的 `cli/` 加到 Python module path 後：

```text
python -m stage1_eval.coverage_plan PACKET.json NEW_OUTPUT --phase process
```

輸出 `span-index.json`、`coverage-plan.json`、`coverage-manifest.json`。
既有輸出目錄拒絕覆寫；不存在或損壞的輸入回報 `evaluator-error`，不給 subject 零分。
這條路不搜尋、不取得新來源、不呼叫模型。原 `judge_packet_v31` 保持原行為供歷史重播。
舊 lock 的重播仍必須 checkout 它綁定的舊 commit；新增 module 會改變 evaluator bundle
hash，不能在新樹上沿用舊 lock 或把新 hash 寫回舊結果。

## 驗證與限制

`tests/test_criterion_coverage.py` 包含 83 片段全分派、僅保留 3 片段的拒絕、
末尾反證與填充文字、Markdown／JSON、Unicode bytes 上限、缺塊／重複塊、
版本／locator／schema 變動、raw failure 欄位、鄰接上下文和目錄覆寫拒絕。

完整分派不能證明模型理解文字、來源是真的、claim 被支持或 B 優於 A。
它也不檢查 packet 之前的 acquisition／capture 完整性；那些原檔必須由既有驗證器
先核對。正式比較仍需共同新 evaluator、舊六份診斷、不計分預演、核心組 review／merge
與正式配置凍結。凍結前不啟動新六次 subject runs。
