# Stage 2：可恢復的前置接線與 ProjectHost

這是 existing controller 的延伸（extend / wrap），不是第二套研究引擎。
工程測試不證明研究品質、正式 A/B 准入或真正使用者選案。

## 入口與真實身分

- 從 Stage 1 開始：先驗證固定交付包、Core 接受紀錄、當前 HostReplay、
  brief、resources 與外部 hashes，再經 ProjectHost 的 trusted import。
  project_id 和 input_version 保留來源的原值及型別；不偽造 UI 確認。
- 從研究需求開始：使用既有 direct-request 入口與外部 request hash，
  不建立虛構 Stage 1 lineage。
- scientific-v3 的新 seed 先選定適用的 rich profile，再初始化。舊 seed
  與舊研究／評分保持原綁定，不能升級後當作已執行。

ProjectHost 的匯入、Stage 2 啟動、研究交付、獨立評估、使用者選案與
Stage 3 接收是不同狀態。檔案存在或 awaiting-human 都不是整體完成。

## 原生前置配置

公開 controller 可加上 --preparation-config 與
--expected-preparation-sha256。兩個參數必須一起提供，hash 錯誤在
controller／模型進入前拒絕。不提供時保留既有入口行為。

配置 kind 為 Stage2NativePrerequisiteConfiguration，schema_version 為 1.0.0：

| 欄位 | 用途 |
|---|---|
| native_sha256 | 原始 spec.native 的 canonical hash |
| admission_context | 原 Host 接受的 model/runtime/policy、原 deadline 與剩餘容量 |
| output_root | 與 workflow、角色工作區分離的私有輸出根 |
| workspace_templates | 每個確實缺席角色的 paths、execution_policy、preflight、inventories、外部 receipt |
| prior_work | 使用同一 native 設定的 spec 和獨立、已證明的 home/workspace |

這份本地配置只由可信任 operator 提供；宣告不能取代真正的環境／權限證明。
缺少 fresh proved templates 時保留可讀 gate，不自造 canary、preflight 或
模型授權。設定不能從瀏覽器提交，也不載入可執行 callback。

needs-prior-work 使用原 capture adapter 產生 candidate/source-bound dossier。
提示有固定 byte 上限；不修改候選內容或把 metadata 變成 findings。
執行過的搜尋 query 必須精確對上原 capture，不接受字串片段比對。
只有 query／native stream、沒有完整遠端結果時，保留 partial、unknown
與實際限制，不能稱為全文取得、無前例或創新已成立。

## 整輪額度與斷點

原 deadline 是絕對時間，恢復時不重新起算。原 native 單次期限不變。
每個新的 production adapter unit 先預留其最大 native capture 及
no-tools attempt 容量（含原政策容許的 correction／transport retry），
並檢查最大所需時間能否放進原整輪期限；不符合就保留未完成狀態。

remaining_budget 的 native_captures 是原生 capture 容量，model_calls
是 no-tools attempt 容量。它們不是全局 inference／RPC／token／成本。
預留不是實際使用；沒有原始用量證據的值保持 unknown。合成 adapter
明確不派模型，不拿它當 live quota 或科學執行證明。

恢復進入 core 時，先合併 core 與前置 provider 已封存的剩餘容量，取較低值；
即使這一段全部復用已完成 action，也不能重新取得原設定額度。
持久化的 preparation、provider 與 Host driver 身分同時綁定
preparation.py／execution_admission.py 的 bytes；版本改變即拒絕舊綁定。

角色 policies／preflights 仍按 environment key；execution_inventories 保留
實際 thread ID，只接受所請求 role template 明確綁定的項目，不能改舊紀錄。

前置步驟先持久化 intent，再執行；最多兩個 gate transitions。缺結果、
失敗或模糊 outcome 不以新 run ID 重送。已接受 action 依 action_kind、
輸入、設定與 snapshot 精確復用。原失敗、raw captures、結果與 journal 保留。

Controller 在返回 Host 前封存小型 returned-result projection；若 Host
result 登記中斷，恢復必須先重新驗證原 manifest、全部 actions、來源、
版本、runtime、模型政策與交付，再登記同一份結果，不能重跑引擎。
只有 manifest、沒有真實 return seal 時仍是 unknown，不推測成功。

## ProjectHost 的正式本地接線

--controller-config 與 --controller-sha256 指向外部 hash 固定的
ProjectStage2ControllerConfiguration 1.0.0。bindings 每列必須包含：

project_ref、spec_path、spec_sha256、controller_root、delivery_root、
preparation_path、preparation_sha256。

所有路徑由本地 bootstrap 提供；同一 project 不能重複。讀取配置只
驗證及建立既有 driver，不啟動研究。要繼續既有已啟動的 Stage 2，
operator 明確提供 --continue-stage2 PROJECT_REF 與 --controller-key KEY。
同一 key 重新開啟時只驗證／復用；不再次進入已接受的 engine。

此路徑不新增 HTTP 原生派工介面，不接受瀏覽器傳入的政策或 deadline。
模型、工具、資料與預算都仍由原准入與各環境的 preflight 核對。

## 交付、選案與 Stage 3

正常研究結果產生選擇包，包含方向、科學問題、比較、資料／方法／工具、
參考材料、原評語、限制與版本。Unknown 不能在投影時消失。

正式 HTML 選案使用已合併的 ProjectHost selection service：
查看目前方向與材料 → 比較取捨 → 選擇可選版本 → 確認條件 →
保存實際 UI 使用者提交 → 驗證 planning package 與 Stage 3 intake。

所選 project/version、delivery、interaction、planning 的外部 hashes
必須全部吻合。過期版本、跨專案、篡改與衝突的重複提交拒絕；同一有效
重複提交只讀回原結果。不得偽裝為 Codex native-message 日誌。

零推薦仍交付完整決策／advisory 材料；沒有 current eligible 方向與真實
使用者選案，不接收 selected plan。工程合成選案不能代替真實研究包。
Stage 3 execution_authorized=false 保持不變；規劃接收不啟動科學實驗。

## 驗證邊界

離線測試覆蓋 CLI config、原期限／容量、前置 gate、結果封存、Host
斷點復用、匯入的 STRING 版本、正式 HTTP 選案及嚴格 Stage 3 接收。
Synthetic adapter／handler 只用於工程正向接線，不宣稱取得真實資料。

實際 Stage 1 包仍需通過其原 Core／producer 及目前 validator 的合法
分離認證。已有研究、模型、來源取得、評分與 Stage 3 生成不得因此重跑。
排程維持關閉；必要新的 live 路徑另以真正准入及不可變 source/runtime
驗證，不能執行歷史 archive 或把舊 proof 綁到新程式。
