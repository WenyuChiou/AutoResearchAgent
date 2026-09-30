# Stage 1 輸出排程操作指南

此實驗性工具在 evaluator 外層排程已保存輸出的評估與離線重播。它不啟動新受測者，
不改 evaluator、rubric、模型、來源選擇、R1／R2 獨立性或葉節點的重試規則。
目前證據只涵蓋 synthetic subprocess 測試，屬 `implementation-only`。
排程完成不等於 G1、Japan pilot、FREEZE_READY 或正式 A/B 通過。

## 使用前的核准與版本

核心組先 review／merge 實作，再對實際 amendment 檔案的 SHA-256 作外部明確核准。
`--approved-sha256` 是操作員傳入的已核准摘要；程式不會自行驗證核准者身分，
也不把 JSON 內的 `approved: true` 當作核准。核准紀錄必須在受控交接中另存。
實作核准、合併、精確摘要的執行核准與科學 gate 接受是不同紀錄。

amendment 使用 `kind: Stage1OutputSchedule.v1`。必要欄位如下：

| 欄位 | 內容 |
| --- | --- |
| `evidence_scope` | `synthetic-test` 或 `repair-diagnostic`；synthetic 結果不能冒充真實 gate |
| `max_jobs` | 整數 1 或 2；同時執行的單位是完整輸出，輸出內的 evaluator 仍依原序執行 |
| `control_root` | 尚不存在、位於 Git 外的獨立絕對路徑，保存 coordinator 與每份輸出的回執 |
| `executor_sha256` | 實際 `scheduler.py` bytes 的 SHA-256 |
| `bindings` | `{path, sha256}` 清單；每個階段重新核對執行檔、輸入與設定的實際 bytes |
| `jobs` | 按舊 plan 原順序列出的剩餘輸出，不能按完成先後改排序 |
| `legacy` | 舊批次與接管證據；只有 synthetic 才能為 `null` |
| `runtime` | 真實 repair 必填，內容見下文 |

每個 job 必須提供 `id`、`output`、`profile`、`cache`、`temp`、`cwd`、
`evaluate`、`replay`、`env`、`capture_root`、`capture_manifest` 及 `result`。
`capture_manifest` 將 capture 下的相對檔名映射至 SHA-256；`result` 是 output 內
的安全相對路徑。兩段 command 都是 argv 字串陣列，不經 shell 展開。
所有 writable 路徑必須互不重疊，不能與任何 capture 重疊或位於 Git checkout。
每份工作獨立使用 profile、source cache 及 `TEMP`／`TMP`／`TMPDIR`。
不得複製其他輸出的 judge 或 source-audit 結果當成新工作成果。

## 真實 repair 的固定執行條件

`runtime` 包含 `python_executable`、`cli_root`、`codex_executable`、`replay_guard`、
`evaluator_bundle_sha256`、完整 `execution_policy` 及 `research_hub_package_sha256`。
child interpreter 和 import root 必須對應目前受核對的執行環境。
`bindings` 至少包含 Python／Codex／replay guard 的 bytes；每個 job 的
`inputs`（`task`、`spec`、`subject`、`lock`、`background`）、`hub_config` 及
`profile/config.toml` 也必須有獨立 byte binding。

真實 job 的 `env` 只能是以下三個指定值；程式另設定獨立 profile、cache 和 temp：

```json
{
  "PYTHONPATH": "<runtime.cli_root>",
  "RESEARCH_HUB_CONFIG": "<job.hub_config>",
  "RESEARCH_HUB_ALLOW_EXTERNAL_ROOT": "1"
}
```

hub config 的 `knowledge_base.root` 必須指向該 job 的 cache，`no_zotero` 與
`disable_pdf_fallback` 必須為 `true`。尚未開始的真實工作，其 cache 和 temp
必須為空。認證檔留在私有 profile，不能進 Git 或公開交付包。

`live_commands()` 從上述欄位重建唯一可接受的 argv：evaluator v3.1、
`repair-diagnostic`、`portable-diagnostic`、`evidence-audited`、
`gpt-5.6-sol`／`high` 與既有 hub command。Python 使用 `-P` 保護 import 搜尋路徑。
replay 必須走已綁定的 guard，帶 `--resume-verified --replay-only`。
第一個保留目錄的工作才允許 evaluate 使用 `--resume-verified`；其他輸出須不存在。
profile 絕對路徑會進入模型請求 fingerprint，因此新路徑必須如實綁定；
不能把舊請求的 hash 改名後當成相同請求。

## 先保留目錄，再等待舊批次結束

`legacy` 包含 `generation`、`active_target`、`fenced_target`、`runner_pid`、
`runner_script`、`runner_sha256`、`plan_sha256` 與非空 `processes`。
process identity 必須保存 `pid`、`parent_pid`、`created_utc`、`executable`；
真實執行還要有 `command_line`，並包含 runner 的 parent 與 active evaluator 鏈。
PID 本身不足以證明同一個程序。

真實接管另需 `expected_stderr` 和 `expected_commands`。
前者是完整的既有 output guard 訊息，明確選擇 LF 或 CRLF；不接受其他錯誤。
後者綁定 active target 的 evaluate／replay 以及 fenced target 的 evaluate
三個舊 `*-start.json` command 陣列。

```text
python -m stage1_operator reserve <amendment.json> --sha256 <digest> --approved-sha256 <approved-digest>
python -m stage1_operator run <amendment.json> --sha256 <digest> --approved-sha256 <approved-digest>
```

這是兩個分開的操作，不應直接串接執行。`reserve` 核對舊 plan、runner bytes、
batch-start、實際 process snapshot 及目前 active target，使用 exclusive mkdir
保留下一個尚未開始的 output。它只寫 `ownership-fence.json` 和 generation 下
的 `fence-reservation-<target>.json` 觀測紀錄，不啟動 successor evaluator。
target 已前進、目錄已存在或 reservation 與舊 admission 發生競爭時，一律保留現場並停止。

原 evaluator 與原離線 replay 按原碼完成後，舊 runner 遇到保留目錄，會在任何新
模型呼叫之前被 existing-output guard 拒絕。舊 runner 的 exit 2、stderr、
phase receipt 和 `batch-stop.json` 全部保留，明示為已核准的排程交接拒絕，
不能改寫成舊批次成功。若失敗來自 active evaluation／replay，便不符合交接條件。

`run` 必須看到精確的 reservation、命令與拒絕回執，確認原程序和 descendants
都已結束，才接受剩餘工作。它不會 suspend、kill 或修改任何在途模型呼叫。
這個方案不能加速目前 active output；它只在接管完成後並行處理剩餘輸出。

## 失敗、所有權及回執

control root 是永久的 exclusive claim；每個 output 的 sibling
`.<output-name>.scheduler-claim` 另阻止使用不同 control root 重複啟動。
claims 不會自動到期或被清除。遇到 crash、既有目錄或未明完成狀態時，不得換目錄、
刪 claim 或重新執行來掩蓋歷史；需要另外核對並取得恢復處置。

每份工作保存 claim、evaluate／replay 的 start、process、exit、stdout、stderr
和 terminal 回執。capture 在階段結束後須維持相同完整 inventory；replay 前後
output bytes 也必須完全相同。真實 replay stdout 最後一行還要包含 guard 回執：
`offline_guard=true`、`blocked_actions=[]`、`new_model_calls=0`、`exit_code=0`。
replacement 回執保存在新的 control namespace，不覆寫舊 runner 的同名日誌。

一旦觀察到 terminal failure，coordinator 關閉新 admission；已開始的工作完成
原呼叫並保存結果，不自動重試。這項 drain 行為須在 amendment 中被明確核准。
summary 依原目標順序保存 `complete`、`failed` 或 `not-admitted`，任何失敗或
未完成工作都不能產生成功的批次判定；`gate_accepted` 永遠是 `false`。

## 測試與證據邊界

`test_stage1_output_scheduler.py` 使用真正的本機 synthetic Python subprocess
驗證 exclusive ownership、重複／stale claim、兩工作上限、獨立 writable 路徑、
失敗後停止 admission 並 drain、順序無關的結果、capture／runtime binding 與
精確 fence 接受；它不呼叫模型或外部資料來源。
`test_stage1_output_scheduler_admission.py` 補充真實 command contract 的拒絕測試、
跨 control root 的重複 admission 以及記錄失敗時的 child drain。
這些測試不能證明 provider 容量、實際 throughput、G1 通過或 P1–P3 改善。
