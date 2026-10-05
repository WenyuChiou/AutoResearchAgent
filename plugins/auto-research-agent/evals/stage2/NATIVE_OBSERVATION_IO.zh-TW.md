# 工具清單的安全寫入

問題：工具清單查詢完成前，已檢查的輸出路徑可能被替換，讓紀錄寫到別處。

Producer 保留輸出目錄及子目錄的 handle，交給 observation collector；正常結果與失敗紀錄都透過同一個 handle 寫入，已存在的檔案不能被覆寫。Windows 阻止目錄改名；POSIX 使用原目錄的 descriptor，路徑被換掉也不會轉向新位置。

這是供 producer 使用的內部接口；舊的獨立呼叫維持相容。清單只記錄設定、skills、plugins 與 MCP 狀態，不能單獨证明實際提供的工具、角色隔離或研究品質，也不會啟動模型回合。

驗收包含成功與失敗保存、錯誤 handle、寫入途中替換目錄及同名檔案碰撞。P4–P6 的研究品質改善仍需正式 A/B；本修復為 implementation-only。
