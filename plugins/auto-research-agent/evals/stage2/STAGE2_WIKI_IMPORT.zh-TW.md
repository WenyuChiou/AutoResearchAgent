# Stage 2 Wiki 匯入的證據接口

本批建立 `stage2_import`，讓後續 Wiki 閱讀版能接收已驗證的 Stage 2
交付物。尚未修改 HTML 或 CLI；顯示功能在下一批整合。

1. 以原有 Stage 1 projector 產生 WorkspaceIndex，保留其 v1 格式。
2. `prepare_stage2_bridge` 核對 Stage 2 evaluated delivery v3.0.0，
   操作者指定要放在一起閱讀的版本，保存 canonical receipt 及其 SHA-256。
3. `import_evaluated_delivery` 要求外部保留的 receipt hash，並重新核對
   project、index、delivery、brief、resources、source snapshot 與 event head。
4. 回傳 attachment 與 hash 核對過的原檔 bytes；不改原 index，不呼叫模型。

這是**明確指定的閱讀關聯**，不是歷史 Stage 1 lineage 證明；
`original_stage1_lineage_attested=false`。相同主題不自動建立關聯。

原來源層級、unknown、failed、audit-required、九项評語與候選版本原樣保留。
目前只接受 human selection pending，Stage 3、formal readiness、improvement
三種授權均為 false 的交付物；不相容版本或執行授權拒絕匯入。

私人原文與交付物保持在 Git 以外；輸入 inventory、hash、project／版本或
receipt 不符時拒絕。內容 hash 正確也不代表科學結論正確。

測試涵蓋原 bytes、九項評語、待覆核及評估故障、跨 project／index、
重算 hash 的假 receipt 和原報告篡改。本批只證明接口行為，
不宣稱完成 live 預演、A/B 或研究品質改善。
