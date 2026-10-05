# LLM Wiki＋主 HTML 研究工作空間

核准範圍：Windows 本機第一版；Stage 1、2 完整接通，Stage 3–6 保留用途、輸入、交付與登錄位置。
本文件是實作與驗收計畫。附帶的 [離線小樣](prototype.html) 只有合成資料與導覽，沒有研究執行器；不表示下列功能已完成。
既有 Stage 1 freeze、歷史研究結果、失敗與 retry budgets 保持不變。

## 1. 目標與第一版範圍

研究者打開一個主 HTML，就能找到目前進度、卡住原因、交付物、評估與可做的下一步。
Wiki 整理研究內容，HTML 提供統一入口；原始交付物與可查證紀錄仍是依據。

- 使用本機小執行器，為每個專案建立並續用一個 Codex base-agent session。
- 研究、查核與評分由 base agent 統籌；評分透過原生 subagents 執行。
- 第一版完整接通 Stage 1、2；Stage 3–6 顯示「尚未接通執行」。
- 節點完成後檢查必要證據；Stage 交付後自動評分。低分先診斷，使用者選擇補查、修訂或重跑節點。

本次選擇：wrap 既有 CLI、validator、交付物與 app-server；extend 資料投影與版本定位；
build-new 主 HTML。不另造評分 rubric，不將 UI 檔案數當作研究覆蓋率。

## 2. 使用者流程與各 Stage 節點

上方固定呈現 Stage 1–6；每個 Stage 有節點進度、Wiki、交付與來源、評估和歷史。
每個節點显示必要輸入、輸出、阻塞原因、允許的下一步與目前 attempt。

| Stage | 節點流程 | 必要輸入／預期交付 |
|---|---|---|
| 1：文獻與證據 | 確認研究方向／地域 → 關鍵字與搜尋需求 → 搜尋與閱讀 → 分類、core/classic/closest-work 判定 → claims／來源檢查 → coverage／停止判斷 → 研究交付包 → P1–P3 | 已確認 ResearchBrief；文獻、來源版本、claims、篩選、搜尋紀錄、coverage、停止理由及 manifest |
| 2：比較與方向 | 驗證 Stage 1 匯入 → 文獻比較 → 開放發想 → 擷取候選 → 獨立挑戰與可行性查核 → 修正／補查／暫存／淘汰 → 選擇包 → P4–P6 → 使用者選擇與 Stage 3 handoff | 經驗證來源封包、資源限制；比較、候選版本、查核、處置、評估、使用者決定及未解事項 |
| 3：研究設計 | 接收選定方向 → 設計／驗證／可行性／實驗計畫（預留） | 選定方向、證據與未解事項；研究設計、核准計畫 |
| 4：實驗執行 | 接收核准計畫 → 執行及失敗紀錄（預留） | 核准計畫；原始結果、執行紀錄、失敗與中斷 |
| 5：分析與圖表 | 接收有效結果 → 分析與圖表（預留） | 有效原始結果；分析、圖表與不確定性 |
| 6：寫作與投稿 | 接收已審查證據 → 寫作與投稿（預留） | 證據、分析及圖表；稿件、引用與投稿交付物 |

Stage 1 不決定最後研究方向。Stage 2 可以保留多個候選或零推薦；只有研究者的有效選擇紀錄
才支持 Stage 3 handoff，handoff 本身不啟動 Stage 3。
未講地域時，沿用既有 ResearchBrief clarification，不自動填國家。
core、classic 和 closest work 為不同文獻角色，依既有證據判定，不以引用數直接替代。

後續 Stage 使用同一登錄介面新增，不修改歷史 stage-registry v1。
登錄至少含 stage ID、node IDs、用途、必要輸入、交付、validator、adapter 與 support status。
不存在 adapter 的節點不得因為有按鈕或敘述就顯示可執行。

## 3. 實作架構與評分方式

### Wiki 與 HTML

保留 Markdown、Excel、BibTeX、JSON、來源檔與 manifest。Wiki 包含研究需求、文獻、claims、
比較、候選、決策與未解事項；每個研究敘述連回 canonical record／實際來源版本。
檔案不存在、版本不符或來源不可讀時顯示原因，不產生假連結或確認結論。

已驗證紀錄是資料來源；Wiki／HTML 可重建。使用者修改形成 draft 與修訂事件，經檢查產生新版本；
不得直接修改 accepted records、原始來源、歷史評分或凍結輸出。
原文、agent 判斷、待檢驗構想與研究者決定分開呈現，不要求揭露模型內部思考。
離線 HTML 可閱讀；本機服務啟動後才提供執行、回答、停止與重跑。

### 本機執行與介面

使用公開原生 app-server thread／turn 介面，沿用原生 sandbox、approval 與既有預算政策。
本機執行器不是另一個研究 agent，也不使用 provider API daemon 代替 base-agent 原生分工。

新增 `WorkspaceIndex v1`，作為單獨的投影介面；既有嚴格 StageRun／StageResult schema 不增加任意欄位。
索引連結 project ID、session thread ID、Stage／node、attempt、交付及 evaluation。
每份索引綁定 canonical input refs、版本／hash、validator 狀態與 rebuild recipe。
私有檔案和 paper 內容留在 Git checkout 外；public 小樣只用合成資料。

操作請求至少綁定 project ID、Stage／node ID、attempt ID、viewed revision/hash、action、request ID。
舊畫面與目前版本不符則拒絕；重複 request ID 回傳原結果，不再次啟動工作。
先保存 action intent，再呼叫外部工具；崩潰時保留 interrupted／execution-unknown，不能自動重送不確定操作。
重新整理、重新連線與查看歷史都不執行研究；歷史操作使用明確 run/attempt/version，不重新比對輸入框 topic。

| 原生介面 | 本機執行器責任 |
|---|---|
| `initialize`／`initialized` | 完成 handshake；記錄實際 Codex 版本與所用 public protocol |
| `thread/start`／`thread/resume` | 第一次建立專案 session，後續續用；恢復本身不重送 turn |
| `turn/start`／`turn/interrupt` | 綁定操作與 turn；中斷等待實際 native terminal event，不能提早標完成 |
| `item/tool/requestUserInput` | 保留原生 request identity 與題目，回覆綁定正確 request 和所見版本 |
| `item/commandExecution/requestApproval` | 保留原始 command、限制及 pending request，使用者回答前不自動允許 |
| `item/fileChange/requestApproval` | 保留原始檔案修改要求與 native request，不由 UI 假造核准 |

目前方法名稱已在本 repository 原生 protocol 中核對；installed CLI 0.153.3 僅做過 version/help 檢查，資料形狀仍須對實際 binary 驗收。
不能把僅測通 handshake 當成模型、skills、subagents 或 Stage 執行成功。
第一版驗收 Windows 本機路徑。Linux 保留 adapter 介面，未验收平台顯示未支援原因。
private config、auth、profiles、完整論文及敏感 native events 不公開。

本機服務只綁 loopback；拒絕非預期 Host/Origin，不提供寬鬆 CORS。
token 使用不可預測的 URL-safe alphabet，不進入 public HTML、artifact、原生 prompt 或 event export。
檔案端點只接受已登錄 artifact ID；驗證允許根目錄、lexical components、symlink/reparse 與檔案 hash，
不以使用者提供的任意絕對路徑讀檔。原始 HTML/text 下載和安全閱讀視圖分開。

### 由 base agent 呼叫評分 subagents

1. Stage 交付先檢查必要檔案、來源綁定、紀錄完整性；檢查失败顯示失敗原因。
2. Base agent 固定 rubric 和證據視圖，分別呼叫獨立 R1、R2；子任務只接收這些輸入，
   不傳研究 agent 的自評、完整對話或另一位 reviewer 的答案。
3. 依既有 validator 判定實質分歧，再呼叫 ADJ；必要具名人類 audit 保持 pending。
4. 研究／查核先保留自然語言產出；需結構化時，使用獨立、無工具整理步驟，
   再交既有 validator。擷取失敗保留原文與錯誤，不把缺失角色丟掉後假裝完整。
5. 程式依既有 rubric 計分；保存 input/view/rubric hashes、native child IDs、原始輸出、擷取、
   validator report、評分結果與必要 audit。HTML 展開主指標、子指標、證據與失分原因。

Stage 1 沿用 general v3 P1–P3；Stage 2 沿用 general v2 P4–P6。
候選的五面向 checker 與獨立品質分數分開；不新增總分，不將材料不足直接當作判斷品質差。
未知證據、已觀察缺失、評估器故障是不同狀態。未知不得顯示 PASS；保留原 rubric 的 null／bounds／分母。
政策不足可阻擋下一步，但不得偷偷改 rubric，把 unverifiable 填成 0 或已通過。

子代理只收到指定視圖不代表已有正式物理隔離。第一版標成 diagnostic；
正式 A/B 沿用另外的凍結、獨立、audit、runtime 與驗收契約。
原生子代理沒有獨立 spawn RPC 或通用 no-tools 參數；會繼承 parent 的 runtime permissions。
無工具整理可先重用已有 source-bound deterministic extractor，作為只轉換已保存內容的獨立步驟。
需要語意整理時，必須另證明受限執行方式或明確保留 blocked；只有 prompt「不要用工具」不算驗收。

### 低分與重跑

問題連到具體節點，例如缺來源、claim 過強、比較不足、交付缺漏或 evaluator 故障。
使用者選擇補查、修訂、重跑研究節點或修復後重新評分；diagnostic 不自動啟動正式 A/B。
新工作建立新 attempt，舊 attempt、failed generation、原始 judge output 和 retry budgets 保留。
上游內容改變後，依現有 workflow 的保守失效規則使下游評估 stale，不能沿用舊 PASS。
Stage 2 現有 source 更新會使所有候選查核 pending；選擇性失效需另做有據的 dependency 分析與測試。
控制可重跑的節點及 next_allowed_action，不能讓 UI 一個按鈕略過研究者決定或既有 gate。

## 4. 系統性處理既有 PR 與組員任務

主 issue：[**#79 — Proposal: LLM Wiki＋local HTML research workspace、native-subagent evaluation 與節點重跑**](https://github.com/WenyuChiou/AutoResearchAgent/issues/79)。
實作組員先交可點擊小樣與節點流程，核心組確認替代範圍後，再按四個切片開 PR。
組員負責實作、測試及回覆 review；核心組負責審查、原則決定與 fork-only merge。

| 現有 PR | 處理方向與仍需關閉的 finding |
|---|---|
| #73 | 核心組按 existing review／current-head CI 處理回退；後續統一基底，不直接重寫 main |
| #74 | 保留執行紀錄與監督，改接專案原生 session；Python 3.11 可讀未綁定的舊 `__pycache__` 問題須以真實 fixture 證明修復 |
| #75 | 保留 artifact/action API，收斂 localhost；token 必須 URL-safe，decoded JSON／escaped-content 不能重建或外洩憑證 |
| #76 | 以 Wiki＋主 HTML 重做互動；離線小樣不得假稱已接上執行器或真研究結果 |
| #77 | 保留研究範圍與使用者決定；用 project/run/attempt/version 定位歷史，操作不依賴 topic 輸入框再比對 |

既有 findings：[74 review](https://github.com/WenyuChiou/AutoResearchAgent/pull/74#pullrequestreview-5397415467)、
[75 review](https://github.com/WenyuChiou/AutoResearchAgent/pull/75#pullrequestreview-5397416037)、
[77 review](https://github.com/WenyuChiou/AutoResearchAgent/pull/77#pullrequestreview-5397416592)。
主提案承接 [76 的 wiki-first comment](https://github.com/WenyuChiou/AutoResearchAgent/pull/76#issuecomment-5962830700)。
舊 Draft PR 只有替代範圍、commit 與 findings 的接收位置確認後才由核心組取代／關閉，現在不批量關閉。

四個交付切片，按此順序記錄；可並行不代表能跳過相依驗收：

1. [**#80 — Workspace／Wiki 資料投影與 Stage 登錄。**](https://github.com/WenyuChiou/AutoResearchAgent/issues/80) WorkspaceIndex v1、canonical refs、可重建 Wiki；
   Stage 1、2 adapter 登錄，Stage 3–6 reserved。不得修改 strict StageRun 或歷史 registry。
2. [**#81 — 本機 session、原生互動與操作介面。**](https://github.com/WenyuChiou/AutoResearchAgent/issues/81) 專案 thread 綁定、原生 request、停止、duplicate/stale/interrupted；
   localhost、token、cache/runtime bytes 與檔案邊界。
3. [**#82 — 主 HTML、檔案定位及歷史檢視。**](https://github.com/WenyuChiou/AutoResearchAgent/issues/82) 六 Stage、節點詳情、Wiki、artifact/source、評估與歷史；
   離線閱讀、連線狀態、pending native 問題、明確 attempt 定位與可及性。
4. [**#83 — Subagent 評分、缺口診斷與重跑整合。**](https://github.com/WenyuChiou/AutoResearchAgent/issues/83) Stage 交付事件 → native R1/R2／必要 ADJ →
   無工具擷取／validator → diagnostic 分數；診斷連回節點、new attempt、下游 stale。

共用相依：1→2／3；1+2+3→4；完整 native／Stage 1→2 acceptance 後才宣布第一版接通。
每個切片交可重現測試、示意資料與已知限制，開 `codex/` branch 的 Draft PR，不自行 merge。
每個新 capability 登錄相應 versioned metric map，frozen v1 bytes 不变。

[Issue #78](https://github.com/WenyuChiou/AutoResearchAgent/issues/78) 是 Stage 1 證據完成與可信探索性交接的獨立修復。
工作空間只呈現該驗收結果；UI 不會把現有 partial package 改成官方 stop-sufficient 匯入。
未解 claims 保持未解，探索性 handoff 與正式 eligible import 必須有不同狀態與明確信任紀錄。

## 5. 驗收條件

- [ ] HTML 可定位目前 Stage、阻塞節點、交付及來源；Stage 3–6 與擴充登錄完整。
- [ ] Windows 實際證明完整 harness skill bytes 載入、原生 base session 續用及評分子代理呼叫；文字自稱不算。
- [ ] R1/R2、必要 ADJ、rubric、input/view versions 與 native 紀錄可重建；缺證據、低分與故障分流。
- [ ] 具體 native 請求可回答／核准／拒絕／中斷；不自動繞過 sandbox、approval 或預算。
- [ ] 重跑只執行允許節點；duplicate click、refresh、reconnect、crash／interrupt 不造成盲重送或假完成。
- [ ] 檔案 hash／安全路徑／manifest 可核對；Stage 1→2 importer 實際通過，未解 claims 不升级。
- [ ] 修訂候選或上游來源後不沿用舊 PASS；Stage 3 仍要求有效研究者選擇。
- [ ] HTML injection、unsafe file links、private data、token escaped-content、stale cache、history view 各有負面測試。
- [ ] Shipping PR 通過 repository contract、必要獨立 general／drift review 及 latest current-head CI。
- [ ] Stage 1 freeze 和歷史結果 bytes 不變；本次 diagnostic 不宣稱正式 A/B 或品質改善。

### 完成報告

每個切片回覆：PR／exact head、改動檔案、實際測試、證據位置、完成／部分／阻塞、剩餘項目。
第一版整合報告連到一次 Windows 全流程的實際 transcript、檔案及 validators；
不能用 screenshot、合成分數、offline 小樣或單獨 green CI 代替這份證據。
