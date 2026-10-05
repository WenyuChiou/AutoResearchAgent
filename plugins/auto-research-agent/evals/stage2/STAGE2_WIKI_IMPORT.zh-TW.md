# Stage 2 如何出現在 Research Workspace／Wiki

Stage 2 的交付物現在可以附到既有唯讀 Wiki：不用重新呼叫研究模型，
也不用重新評分。它是已驗證交付物的閱讀版，不會替使用者選方向。

## 使用者會看到什麼

- **方向**：研究問題、候選 ID／版本、推薦／修正／暫存／淘汰及理由。
- **材料**：內部材料查核的分數、阻塞、限制、下一步及已記錄的資源。
  `assessed` 只代表已判斷；分數低或有阻塞時，不能解讀為材料可用。
- **外部評估**：P4、P5、P6 各自的分數，九項 criterion 的 R1、R2、
  ADJ、最後記錄的判斷、理由、信心、未知原因、證據位置及覆核狀態。
- **完整依據**：原本的 HTML／可編輯 Markdown proposal、來源檔案、
  結構化資料與私人 Wiki 筆記。proposal 裡的比較及修訂歷史原樣保留。

三個面向各以六分為固定分母，不加成總分。必要項目未知時，面向分數
仍為 unknown；評估故障與待具名覆核也保留。待覆核分數標為 provisional，
不改寫或隱藏原始評語。高分不等於方向可行，也不等於研究已開始。

## 匯入順序

1. 使用既有 `project_package`，以外部保留的 Stage 1 manifest SHA-256
   產生 `WorkspaceIndex`。既有 v1 index 與 UI 參考資產不用改版。
2. 對指定的 Stage 2 evaluated delivery，保留並核對 manifest SHA-256。
   原有 delivery validator 核對完整 inventory、內容、來源與評估綁定。
3. 呼叫 `prepare_stage2_bridge(index, delivery_dir,
   expected_manifest_sha256=...)`。操作者確認要把這兩個版本放在一起閱讀，
   保存回傳 receipt 的 canonical bytes 與 SHA-256。
4. 呼叫 `write_workspace`，同時提供 `stage2_delivery`、`stage2_bridge`
   與 `expected_stage2_bridge_sha256`。只提供部分參數會被拒絕。
5. 寫入 Git 以外的新私人資料夾。`index.html` 顯示 Stage 2，
   `stage2/selection.html`／`.md` 保留原報告 bytes；
   `stage2/README.md`、`workspace-attachment.json` 與 `view-manifest.json`
   提供筆記、完整資料及檔案 hash。重新排版不呼叫 judge。

CLI `python -m research_workspace` 的原有 Stage 1 參數不變，新增可選的
`--stage2-delivery`、`--stage2-bridge`、`--expected-stage2-bridge-sha256`。
三個必須一起提供。bridge 檔案也放在私人資料夾，不放 Git。

## 綁定證明到哪裡

receipt 綁定 project、Stage 1 index／manifest、Stage 2 manifest、selection、
brief、resources、source snapshot 與 workflow event head。相同主題不會
自動建立關聯；更換 project、index 或交付物版本，必須重新確認並建立 receipt。

這是**操作者明確指定的閱讀關聯**。目前輸入格式沒有可核對的原始 Stage 1
lineage，因此 `original_stage1_lineage_attested=false`：它不能證明歷史 Stage 2
確實使用了這份 Stage 1 封包。內容的 hash 核對也不能證明科學結論正確。

此匯入只支援 Stage 2 evaluated delivery v3.0.0。使用者選擇仍為 pending；
`stage3_authorized`、`formal_ready`、`improvement_demonstrated` 維持 false。
不支援的版本或已授權的執行狀態拒絕匯入，不偷偷降級其意思。

## 驗收及限制

測試核對來源／proposal bytes、九項原評語、unknown、待覆核、評估失敗、
錯 manifest、跨 project、重算 hash 後的假 receipt、部分參數與安全文字轉義。
新 Wiki 的 manifest 記錄 adapter bytes 和每個輸出檔案 hash。

匯入沒有模型呼叫，來源內容不具有指令權限，HTML 文字經轉義。
一般閱讀連結經 `stage2/report-reader.html`，在不開放 scripts、popups 或
同源權限的 sandboxed iframe 中顯示原報告及其來源。原始 bytes 仍供私人
重現使用，不應把 raw source HTML 當成可信網頁直接發布或執行。
下載論文、評語及私人資料不因此獲准公開；需要分享時另產生去識別版本。
這次接的是私人唯讀 Workspace；Research Studio 的執行 UI 仍由其工作分支負責。
工程測試及閱讀版重播不代表完整 live 預演或正式 A/B 已完成。
