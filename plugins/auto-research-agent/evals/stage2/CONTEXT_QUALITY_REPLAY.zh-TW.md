# 補充語境校準：保存後如何查核

這個接口核對保存的評分紀錄，不會再次問模型，也不會重新做研究。白話說：不能只相信報告上寫「通過」，必須從當時真的送出的問題和收到的回答重新算一次。

`stage2_live.context_quality_replay.verify_context_quality_v3` 接受紀錄目錄、外部保存的 receipt、原始 dataset／reference，以及凍結的 expected config。Config 必須包含 codex、runtime_sha256、model、reasoning、R1／R2 homes 和 policy；receipt 必須包含 result_sha256 與全部 unit_receipts。

## 它會檢查什麼

- 使用現有 producer 的同一份問題、schema、匿名 ID 對照及來源版本，重建 native request；檢查資料、rubric、程式 bytes、runtime、角色目錄及 policy。
- 重用 `replay_unit` 查核每個角色的原始呼叫與必要的修正呼叫；不匯入或執行封包內的程式，不使用 runner 的 resume 作為查核。
- 從回答重新還原 12 個補充案例、24 個指定判斷，再計算逐類別與整體品質。原先的 native_qa_pass、評語、角色完成狀態及嘗試次數都必須與重算結果一致。
- 核對原始 archive 與供閱讀的 JSON、JSONL、stderr 副本；改動副本、漏掉呼叫、加入未被使用的 correction archive 或重新計算內部 hash，都不能遮住錯誤。
- 保留 unknown／evaluator_failure 和未通過的校準結果。Authentic 表示紀錄能查核，不等於評分正確，也不等於 QA 通過。

## 回傳與限制

回傳 authenticated、qa_pass、quality_report、還原後的 R1／R2 判斷、各 unit 的 archive hashes 和 actual_model_attempts。費用為 unknown，formal_ready 固定為 false。

這裡的嘗試次數只計已查核的根層模型 archive，不能代替完整的 inference、工具或子 agent 用量。嚴格 replay 需要保留原本的 executable 和 reviewer-home 路徑，不宣稱跨機器重播或 provider attestation。

接口只接受完整、目前格式的 native 紀錄；缺席 reviewer、injected adapter、錯誤來源或不完整 archive 必須拒絕。原始失敗仍保留，不能刪掉案例縮分母。未授權的舊版本遷移也不能用來讓紀錄通過。

## 放在完整評估的哪裡

原有九項 rubric 的 72 份呈現／144 個指定判斷由 `verify_quality_v3` 查核；本接口查核另外 12 份完整語境案例／24 個判斷。既有 combined quality gate 從兩份真實結果重新計算 84／168，不接受手填通過旗標。

這項工程測試不代表 84 份真實 judge 校準已完成。正式 readiness 還需要兩個研究預演、各角色的能力與隔離證據、完整用量和凍結投入政策；P4–P6 改善則由正式六次 A/B 與必要人工覆核判定。

一般使用者只跑 B，可閱讀 proposal、評語與未知狀態，不需要執行 A/B。此接口提供之後評估器共用的查核入口，不改動科學 rubric、研究選擇或 Stage 3 授權。

相關實作：[read-only verifier](../../cli/stage2_live/context_quality_replay.py)、[regression tests](../../tests/test_stage2_context_quality_replay.py)。Synthetic 測試只驗證機械行為，不能用作 native 執行證明。
