# Judge 與擷取：沒有使用工具，不等於沒有工具

原生 Codex 可能依模型設定提供 `functions.exec` 等工具。CLI 的停用旗標不能保證模型請求中的工具清單為空。因此保留兩種不同證據，不暗中放寬舊版：

- `Stage2NoToolTraceEvidence`：工具清單必須為空，且實際零工具、零子 agent。舊契約不變。
- `Stage2NoExecutionTraceEvidence`／`no-executed-tools-v1`：實際零工具、零子 agent，但保存每次請求的工具清單 hash、數量、位置及 tool choice；明示不證明工具不可用。

兩種驗證都核對所有 attempt、原始 seal、模型、read-only／never 設定、完成狀態及用量；未知仍是 null。發現工具使用、子 agent、缺漏或篡改時拒絕。原始失敗和評語不覆寫。

日常擷取或 judge 可以明確採用第二種政策。它只證明「這次沒有外部動作」，不授權執行、不證明 context／檔案隔離，也不能單獨宣告 formal-ready。

正式 A/B 必須在看到結果前凍結實際政策與 judge 工具清單；R1／R2／ADJ 各有物理隔離證據。任何工具使用均保留並拒絕該 judge 單元，不以有無成功結果掩蓋。受測 A／B 的原生研究工具不因此被削弱。

舊校準仍可用原始輸出重算科學判斷，但不能冒稱通過「沒有提供工具」門檻。新版 verifier 成功也不替代兩個真實預演、正式六次執行或 Eric 必要覆核。九項 v3 rubric 不改。
