# 原生 trace：先核對檔案，再解讀執行紀錄

這一批只建立檔案讀取接口，不執行模型，也不宣告 formal-ready。
目標是避免「紀錄被換過，卻仍拿來算 A/B」以及讀入不受控的大檔案。

## 輸入與輸出

`stage2_live.trace_files._load_inventory` 接收原生 trace 目錄、逐檔 SHA-256
清單，以及由呼叫端另外保存的清單 hash。它回傳核對過的原始 bytes。
目前沒有新增 CLI；後續原生 inventory／用量 observer 重用這個接口。

清單包含 `manifest.json`、`trace.jsonl` 與 `payloads/` 的檔案；目錄中
多出、少掉、重算 hash 或換內容，均拒絕。不能從當前檔案自行建立一份
新清單，就說它是原執行留下的證據。外部 receipt 的保管仍由 runner 負責。

最多 4,096 檔、每檔 4 MiB、合計 32 MiB。先檢查大小，再有限量讀取；
讀取前核對開啟檔案的身分，讀取後再次檢查，防止檔案變大或被替換。
POSIX 以 directory descriptors 逐層開啟，禁止跟隨連結；Windows 保留
不允許刪除／替換的 directory handles，並原子開啟及拒絕 reparse 檔案。
讀取只接受一般檔案；FIFO 不會阻塞開啟，也不會被當成 trace 內容。
拒絕路徑跳脫、symlink、Windows reparse point，以及未知的目錄。
JSON 重複欄位、非有限數字及不可解析內容另有明確錯誤，不當成空結果。

## Example

原本：來源 bytes 被改過，作者重新計算清單，可能誤用為原始紀錄。
現在：另存的 receipt 不符，立即拒絕，不讀取或採用該份結果。

原文 payload 可能包含研究輸入及工具回覆，留在私有證據目錄；公開 Git
只放本接口及合成測試。此接口不能證明模型真的執行、sandbox 隔離、
用量完整或 P4–P6 改善。後續 observer 與正式 admission 必須分別驗收。
