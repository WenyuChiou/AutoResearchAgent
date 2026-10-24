# 本機 Stage1 工作台與明確授權接續

本入口使用同一份已確認的研究需求、計畫、資源與專案紀錄。預設開啟只顯示工作台；輸入主題、GET、重新整理、預算數字或載入舊交付物都不會自行呼叫模型或取得來源。

## 在本機開啟主 Wiki

使用原 examples/run-project-workspace.py，以自己的 Python、完整 checkout、位於 Git 之外的短私人 projects root，以及從可信版本取得的 atlas_local_source.py SHA256 啟動。指定 --open 會開啟回傳的 loopback 工作台 URL；也可以在瀏覽器開啟該 URL。保留終端輸出的 URL 和登入資料；不要公開它們。

--views-config 和 --views-sha256 接入已核驗的 saved-view 設定。主 Wiki 在左側 Stages 內顯示兩個 inline iframe；外鏈不能取代這個驗收。載入 saved view 只是讀取既有交付物，不會把舊資料或舊的 Core 決定變成新主題結果。BibTeX、Markdown 下載必須實際取得檔案並核對內容和 SHA256。

以下 PowerShell 形式只開啟原工作台；範例路徑和可信 helper pin 必須換成自己的實際版本：

```powershell
$stage1Repo = 'C:/AutoResearchAgent'
$stage1Python = 'C:/Stage1Runtime/Scripts/python.exe'
$stage1HelperPin = '<可信版本提供的64字元SHA256>'
& $stage1Python -B -X utf8 "$stage1Repo/plugins/auto-research-agent/references/research-workspace/examples/run-project-workspace.py" --repo $stage1Repo --source-helper-sha256 $stage1HelperPin --projects-root 'C:/S1/p' --open
```

先以 --check-only 做檔案及 raw-loader 核對；此模式不建立專案 store、啟動服務或模型。--prepare-only 只建立實際服務，仍不執行研究。完整來源 worker 目前是 Windows containment profile；三平台測試通過不等於 macOS/Linux 原生來源 worker 已可執行。

## 開啟整段接續能力

--enable-stage1-run 只註冊共用的 typed run issuer，必須同時明確啟用 --enable-content-model 與 --enable-public-sources。還需要既有 --stage1-query-runtime、其外部 SHA256、私人 --stage1-materials-root、自己的 --model、原生 --codex 與 --codex-home。這些旗標只做註冊，不新增研究授權。

在原工作台確認主題需求與計畫後，才準備一份私人 ProjectStage1RunRequest 1.0.0 JSON。其 project_ref 指向同一專案，run_id 用於這次接續；authorization 必須是原 ProjectStage1RunGrantService 接受的完整 body，包含真實版本、revision、brief、明確使用者同意、允許操作與原上限。入口不替使用者產生 consent，也不把計畫確認改成 AI 自批。

以 --stage1-run-request 和 --stage1-run-request-sha256 同時指定該檔案與外部 byte pin。只有這個明確動作會走原 ProjectHost.continue_stage1。使用相同私人專案 root 前，先在原終端正常關閉自己擁有的工作台，避免兩個程序同時持有來源或模型 owner；不可強制終止不明程序。CLI 輸出 ProjectStage1RunReceipt，保存完整 stdout/stderr、exit 和實際 runtime。

預設 intake history 容量是256筆。30篇可能需要更多持久意圖和回執；如確有需要，在原 authorization 中明確指定 max_history_actions（256至2048），保存為版本化1.1 grant。這只調整紀錄容量，不增加模型、查詢、來源、輪次或時間額度，不能在額度用完後另開 grant。

恢復時使用同一份 grant_ref/grant_sha256 的 resume body；不得重設期限或額度。slice_max_actions 只能縮小原 grant 的動作上限。過期、撤銷、輸入或 runtime 改變時會拒絕；已耗用或失敗的模型／查詢／取得嘗試仍保留。

## 停止條件與交付

流程只等待本程序持有的既有 worker 一次，之後重讀持久回執。遺失 owner、執行 Unknown、來源取得已知失敗、無法判斷的模型內容、未支援版本或需要 Core／Wiki 審查時，保留 partial 並停止，不能另換 key 重送或捏造30篇。

CLI exit 0 僅表示遇到原 saved-delivery barrier；其他 partial/held 結果為 exit 2。產生套件不等於科學驗收。檢查回執 reason、30 works／30 fullnotes、逐來源與 claim 綁定、Unknown 和歷史資源，再做同版主 Wiki 七項測試、內容與 Core 驗收。

最後使用原 import-stage1 正式接收，核對 Stage2 readback、init、inspect 和 expected-head inspect。只有套件、來源與接收 runtime 的正式版本證據齊備，才算交付到 Stage2；初始化不表示 Stage2 pipeline 或研究已執行。每個新主題都要有自己的 package 和正式接收回執，不能借用既有30篇。
