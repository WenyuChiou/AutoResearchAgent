# 原生 Rubric 校準如何接入正式門檻

更新：2026-10-03。這份文件是工程驗收說明，不是 A/B 改善證明。

## 為什麼還需要這一層

「校準 JSON 寫著通過」不夠。正式入口必須重讀實際模型呼叫、核對原文判斷，再重算七項指定查核的固定分母。否則可以拿錯模型、舊 guidance 或假的 aggregate 來通過。

`stage2_eval.rubric_admission.verify_rubric_quality_admission` 只讀資料，不呼叫模型，也不改寫原結果。它沿用已有 native receipt replay，檢查：

- 56 個案例與 reference 的版本、hash、各 criterion 的 0／1／2／unknown anchors。
- 完成的 native QA run、16 份 unit receipts、原 request、execution policy 與歷史 code binding。
- 實際 Codex runtime bytes、目前 frozen rubric 與共用 judge guidance。
- 重驗的 R1／R2 與原結果一致，再重算 112／56／56 分母、重大錯誤與分歧。

成功輸出 `Stage2RubricQualityAdmission`，含 accepted、理由、current verifier code hash、歷史 code／policy hash、counts／rates、`replayed_model_units=16`、`new_model_calls=0`。**它自己的 formal_ready 永遠 false。** Synthetic 測試只能證明程式行為，不能取得 accepted。

本版本只接納原始 QA 已完整通過的 native evidence。若需要 ADJ，回報不接受；不在正式入口偷偷啟動 ADJ，也不因 ADJ 可能通過而洗掉 critical 錯誤。以後若要接入已完成 ADJ，另建明確版本與回執查核。

## Readiness manifest 1.1.0

沿用 `validate_readiness_v1` 的 v1 family，增加 readiness schema 1.1.0。原本 preflights、pilots、13-case 診斷 calibration 與 formal_plan 仍然必需，另必須有 `rubric_quality`：

| 欄位 | 用途 |
|---|---|
| dataset、reference | `{path, sha256}`，只能是 evidence root 內的不可變檔案 |
| run_dir | evidence root 內的 native run directory，不能跳出目錄 |
| run_result_sha256_receipt | 外部留存的原 run result SHA-256 |
| codex_executable | 真正驗證 runtime 的絕對路徑 |
| verification_code_sha256 | 目前 admission／deterministic QA／native replay／live QA 四個模組的 byte hashes 組成 canonical hash |
| model、reasoning、runtime_sha256 | 必須同時符合重驗結果與 frozen formal plan 的 judge contract |
| rubric_sha256、guidance_sha256、execution_policy_sha256 | 綁定這次實際校準使用的評分與執行條件 |

Reference 留在 private evidence root；不放 Git，不供 subject 使用。校準 policy 與正式 judge policy 分別凍結，不把 QA 的模型呼叫成本當成 subject 成本。

舊 1.0.0 manifest 仍能讀取；真實正式驗證會明示 `legacy-rubric-quality-evidence-unbound`。沒有默默把舊紀錄改成 1.1.0，也不覆寫舊結果。

## 哪些情況必須阻擋

錯 hash、缺 archive、換 runtime／guidance／verifier、拿其他 judge 的校準、未知紀錄填分、缺必要 judgments 或 evaluator failure 都不能接受。正式入口不能相信 caller 的 `accepted=true` 摘要。

現有 `per-execution-inventory-collector-unavailable` 與 `complete-subagent-budget-accounting-unavailable` 阻塞保留。完整 A／B isolation、兩個真實 pilots、來源補查 provenance、凍結投入政策及必要人類 audit 也沒有被免除。1.1 的 QA 通過只代表這一項證據被驗證，**不代表 formal-ready**。

測試位於 `test_stage2_rubric_admission.py`、`test_stage2_formal_rubric_gate.py`，並保持既有 `test_stage2_formal.py` 相容。真實 QA03 已 readonly replay：102／112、56／56、56／56；210 個原 archive 檔案未改寫，新增模型呼叫 0。相關部分修正的十次 correlated 超評仍是限制，詳見 `RUBRIC_QUALITY_AND_LIMITATIONS.zh-TW.md`。
