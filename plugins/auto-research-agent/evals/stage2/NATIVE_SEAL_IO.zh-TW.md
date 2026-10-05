# 封存目錄 handle

`SealDirectory` 開啟並保留目錄 handle，再透過它讀取來源及建立新檔案。像是先確定使用哪個抽屜，再把東西放入；不能只看抽屜上容易被換掉的標籤。

Linux/macOS 使用逐層 no-follow 與 descriptor-relative I/O。Windows 保留不允許 SHARE_DELETE 的祖先目錄 handle，建立檔案用 CREATE_NEW。符號連結、reparse point、覆寫既有檔案及跨目錄 leaf 都被拒絕。

本接口只建立檔案 I/O 的安全性，不能證明研究品質、runtime 隔離或正式 A/B readiness。實際來源封存仍由獨立接口綁定 receipt、版本與完整內容。
