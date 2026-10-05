# Stage 2：原生評分紀錄如何驗證

這份說明涵蓋兩個 opt-in 接口。科學標準仍是 v3 的九項 rubric；
本次沒有增加總分、改變 anchors 或宣稱 A/B 已完成。

## 為什麼需要這兩個接口

評分器說「我跑完了」，還不足以知道它真的用了哪份資料、
呼叫了幾次，以及有沒有漏掉重試。另一方面，judge 能指出問題，
不代表受測報告已經把問題處理好。

因此分開處理：

- `verify_judge_trace_unit` 把原生輸出和當時封存的 trace 對起來。
- `run_daily_evaluation_v3` 可明確載入 assessment-target policy 3.1，
  讓 judge 評受測報告實際交付的內容，而不是替自己的評論打分。

## 原生 trace 接口怎麼做

使用者保存的原始 seal SHA 必須來自執行當時的可信 host 紀錄。
讀取一份結果後才自己重算 seal，不能證明那是原始結果。

`stage2_live.judge_trace_replay.verify_judge_trace_unit` 在原本角色的
唯讀環境執行，接收原始 request、worker result、runtime、profile、
trace 目錄、seal、外部保存的 seal SHA，以及 generation envelope。

驗證順序是：

1. 核對 seal 的原始 bytes、角色、request 與結果 SHA。
2. 核對外層 generation 的 stdout、stderr、result bytes。
3. 重用 `verify_worker_output`，重新檢查模型輸出與原生 archive。
4. 每個 attempt 的 root thread，必須對上唯一一份原始 trace。
5. 重用 `inspect_native_trace`，核對事件、工具清單及用量。
6. 缺 trace、未知用量、tool 或 child activity、路徑連結或內容篡改，
   都拒絕完整驗證；不把缺資料換成零次呼叫或零 tokens。

這個接口不呼叫模型，不寫原始檔，也不讀登入憑證。
Replay profile 若仍有 `auth.json`，必須先完成原執行程序的安全收尾。
它保留實際 offered tools，不把「沒有用工具」說成「沒有工具」。

**它驗證呼叫與用量，不能獨自證明 namespace 隔離、科學分數正確、
calibration 通過或正式 A/B 可用。** Generation envelope 的 hash
只能綁定其內容，不能把 envelope 的旗標當成隔離證明。

例子：一個 worker 記錄兩次 attempt，卻只保存一份 trace，
這個接口會拒絕完整計數，而不是忽略第一次成本。

## 日常評分怎麼啟用 3.1

呼叫者先用 `assessment_target_policy.target_policy_binding()` 取得
實際 policy 的版本與 bytes binding，將它放入凍結設定，再以
`assessment_target_policy=...` 傳入 `run_daily_evaluation_v3`。

接口在任何 judge 呼叫前核對 binding。它將 policy 納入 request、
config、code 與結果，並在 content-first 和後續 judgment prompt
都加上同一份 framing。R1/R2 隔離、ADJ、null、原始評語及具名
覆核規則保持原樣。它仍使用真實 `call_model_v31`，不因加入
framing 就改成 injected-test adapter。

省略參數時保留原 prompt 和欄位語義。程式 bytes 變更仍會使 code
binding 改變；舊結果應以保留的舊版本重播，不能偷偷改 hash。
啟用、停用或變更 policy 都不能重用舊設定的 resume 結果。

日常評分 bundle 可以產生 Markdown、HTML 與 wiki 投影，完整保留
分數、原始評語、來源位置、未知及待覆核。實際 Wiki 匯入與 UI
呈現須另外通過一致性驗收；有投影檔不代表 UI 已接好。

## 本輪驗證範圍

工程測試使用 synthetic native protocol，不冒充真實科學改善。
另以已保存的 22 次真實 judge 呼叫驗證此公開接口：全部可重播，
結果與原 trace observation 相同，新增模型呼叫為 0。
這是原始紀錄的驗證，不能取代兩個完整研究預演或六次正式 A/B。
