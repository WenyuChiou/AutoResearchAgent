# Stage 2 四道 Gate（繁體中文）

這份文件保留 v2 四門檻的歷史診斷及正式 A/B 限制。
一般使用者的 v3 日常流程請看 [新版流程與透明評分](STAGE2_V3_EVALUATION.zh-TW.md)：
日常 B 可以驗證讀、寫、搜尋及子 agent；這不代表正式 A/B 的檔案隔離已通過。
下列七項評分與舊執行狀態不可當成 v3 九項評分或目前預演結果。

這份說明把 Stage 2 的「可執行」與「可宣稱」分開。三種結果必須分開記錄：已實作、已測試、已由 live run 驗證；本輪不能把前兩者寫成第三者。

## Gate 1：執行環境與隔離

先跑 preflight/profile，確認 code PR58 已合併。Windows fresh home 的 no-model 啟動紀錄顯示：sandbox=disabled 使 workspace-write 降為 read-only；先前實際模型讀檔也曾被拒絕。加入獨立 .git 根目錄與明確的 unelevated 設定後，啟動紀錄可保留 workspace-write，但該模式明確拒絕執行 deny-read 限制。這仍未證明完整原生工具成功。Linux Docker namespace 失敗，WSL Ubuntu 啟動回傳 `E_UNEXPECTED`。因此目前 isolation 沒有通過，也不能藉由放寬 sandbox 來補過。

## Gate 2：校準與重播

語義目標是 13 × 5 = 65 個 case outputs，由 5 次 primary native calls 產生；這不是 65 個獨立實驗。獨立 Terra audit 結果為 64 acceptable、0 majors、1 minor：S05 的 materials unknown 被錯誤寫成 0。保留原先 7-call verbatim attempt，不覆蓋 raw artifact；5 個 source-ID archives 已通過唯讀 replay。這些是校準證據，不是 A/B 結論。

## Gate 3：控制器與故障測試

controller、shared extraction/actions、pure judge/controller replay、immutable versions 與 workspace slots 已實作，並有 synthetic fault tests。US-aging 與 flaky tests 的 authentic full pilots 尚未執行，原因是 Gate 1 未通過。每個擬推薦候選仍需獨立查核；外部評分的真人覆核由既定 triggers 決定。

## Gate 4：正式計畫與結果

正式 plan/readiness/result validators 已在整合中實作。A/B 若獲准，使用同一 prompt、native capabilities、GPT-5.6 Sol High，順序 AB/BA/AB；七項 criteria P4/P5/P6 保持不變。目前 formal runs 為 0，frozen investment policy 尚未獲准；不要補造 API capability 或 ready=true 範例。Eric 的研究方向選擇與必要具名科學覆核保持為真人工作；工程測試不需他逐步批准。

## Why / What / How / Example

**Why**：四道 Gate 讓環境、校準、控制器和正式證據各自可追溯，避免把 synthetic passing 當成科學改善。

**What**：live controller 位於 [`stage2_live/controller.py`](../../cli/stage2_live/controller.py)；CLI 入口在 [`stage2_live/__main__.py`](../../cli/stage2_live/__main__.py) 提供 controller、verify-controller、extract-actions。正式流程在 [`stage2_eval/__main__.py`](../../cli/stage2_eval/__main__.py)：`freeze-formal-plan`、`validate-readiness`、`validate-formal-result`。

**How**：先完成 Gate 1，再以唯讀 archive 重播 Gate 2，跑 Gate 3 的 fault tests，最後才凍結 plan 並驗證 readiness/result。報告可輸出 editable Markdown/HTML，但必須 source-bound；archive 使用 strict same-host absolute paths。

**Example**：若 S05 的 materials 狀態被寫成 0，Gate 2 應標記 Terra minor，新增有來源支持的解釋／修正紀錄，必要時以新版本補測；唯讀重播只確認原始 bytes，不會修正語義；不能把 64/65 直接宣稱為 formal pass，也不能在 Gate 1 未通過時啟動 authentic full pilot。

## 操作順序與證據邊界

1. `stage2_live prepare-profile` 準備隔離設定，`preflight` 核對真正工具結果；無法隔離便停止 subject 執行。
2. `stage2_eval prepare-diagnostics` 保存固定輸入，`stage2_live calibrate` 保存實際模型呼叫。由獨立查核者對照原始事實評語義，不能只看 JSON 是否通過。
3. `stage2_live controller` 串接既有 workflow；`verify-controller` 只讀取並重建，不會再次呼叫模型。`apply_revision` 函式納入已查得的新證據與候選版本。缺工作空間或未完成呼叫分別保存為 needs-workspace／needs-recovery；不假裝已自動修復。
4. `stage2_live extract-actions` 用共同擷取器整理 A／B 自然語言的處置。原文未說明則 unresolved，不能補成推薦或淘汰。
5. `stage2_eval freeze-formal-plan` 綁定共同需求、來源封包、rubric、prompt、runtime、evaluator 與六次順序；凍結結構不等於 readiness 通過。
6. `validate-readiness` 重播環境、兩個預演與校準證據；`validate-formal-result` 重建六次輸出、共同擷取、R1／R2、ADJ、必要 audit 及配對判定。任一必要證據不足，CLI 返回非零及 evaluator_failure／inconclusive，不填科學零分。

各命令的必要路徑與 receipt 參數以 `python -m stage2_live <command> --help` 或 `python -m stage2_eval <command> --help` 為準，從 plugin 的 cli 目錄執行。需要原生 runtime、來源與獨立 profile，不能只複製 JSON 樣板宣告正式完成。

正式 plan 的 `stage1_source_manifest` 是完整共同 Stage 2 起始封包（含 brief、來源、片段），不是只有檔名的清單。校準 facts 和判分資料不傳給 subject。`config_bindings` 記錄 B 的 plugin 與依賴，A 不載入研究擴充；原生工具清單兩組一致。

目前 readonly archive replay 保留原執行環境的絕對路徑驗證。搬機器時須還原受控路徑與固定 runtime／code bytes；本輪沒有聲稱任意跨機器 replay 已驗證。Synthetic fixtures 永遠不能產生 formal-ready。現有正式接口仍需通過真實兩案例預演，才有端到端可用證據。

## 獨立審查後仍未完成的執行串接

正式入口目前 **刻意維持 blocked**：原生 capture 尚未收齊每個 subject 的完整即時 inventory，以及包含子 agent 的完整投入計數。因此 validator 會回報 `per-execution-inventory-collector-unavailable` 和 `complete-subagent-budget-accounting-unavailable`，不接受只填文字預算就宣告已遵守上限。這是尚待實作的接口，不只是等待真人簽字。

協定盤點及本機 Codex 0.153.3 的零模型呼叫另確認：app-server 沒有契約要求的 `tools/list` RPC，實際回傳 `-32600`、`unknown variant tools/list`。現有五個 inventory RPC 不代表完整原生工具清單；MCP 工具清單也不能取代它。須先新增符合實際原生介面的版本化證據契約，再串接 collector。不能補造第六個 RPC 回應，也不能宣稱換一台 host 就解決全部缺口。

每次執行須有專屬 workspace／CODEX_HOME 的 preflight；新環境不能借用舊 PASS。Controller 的 `execution_preflights` 以 home/workspace 的 canonical hash 為鍵；`execution_inventories` 須綁定實際 thread ID 與同一 native archive 的 RPC bytes。現有 CLI collector 尚未提供後者，所以目前不能宣稱 controller 已能完成真實 pilot。執行前應先補完 collector，避免在已知無法驗收時浪費模型呼叫。

正式六次紀錄另檢查六個不同 capture receipts、六個不同 thread ID 和實際 UTC 順序。兩個 pilot 不能共用同一 archive 或 brief。暫時只支援固定起始來源封包的 formal extraction；新增來源會明確拒絕為 `supplemental-evidence-not-supported`，待補上來源追加的原生取得鏈後才支援，不將合法補查算成受測者科學錯誤。
