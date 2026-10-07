# Stage 2：依研究主題比較，並列出每個方向需要的資源

本接口延伸現有 ideation、來源綁定、workflow 與 Wiki；不另建研究引擎。
一般使用者執行 Codex＋研究 harness，不必先做 A/B。研究工作仍可使用
Codex 原生搜尋、閱讀和子 agent；只有整理紀錄的擷取步驟不使用工具。

## 流程與三種表

**確認需求 → 閱讀代表文獻 → 整理概念／機制 → 定義比較欄位 → 查核矩陣 → 提出方向 → 查資源與限制
→ 獨立查核／補查／修訂 → proposal＋Wiki → 使用者選擇。**

1. **文獻總覽**：研究問題、地區／對象、資料、方法、發現與限制。
2. **主題矩陣**：每篇研究是一列；欄位根據目前研究需求產生。
   每欄說明「對應什麼需要、為何重要、如何判斷、比較條件」。
   例如 agent 設計可以比較 reflection、memory 或工具使用；人口老化研究
   可以比較人口映射、家庭決策、跨期回饋與驗證。這些是例子，不是固定欄位。
   只談關鍵字不足以建立欄位：同名機制可能不同，不同名稱也可能是同一設計。
3. **方向資源表**：依候選 ID 和版本列出 dataset、report、reference、model、tool。
   每筆包含名稱／網址／版本、用來回答哪個問題、是否必要、取得條件、授權、
   成本依據、限制、替代方案、來源證據與查核時間。不需要的類型不硬湊。

## 每格如何判斷

| 狀態 | 意思與規則 |
|---|---|
| Present ✓ | 來源支持這項 feature 存在；綁定原文位置與檢查範圍。 |
| Absent ✕ | 來源明說不存在，或已記錄全文設計檢查與限定範圍；沒看到不等於沒有。 |
| Partial | 只符合一部分；說明條件與理由。 |
| Described | 文字或數值欄位的已記錄內容；不是 ✓／✕。 |
| Unknown | 尚缺必要證據；保持 null，說明欠缺或下一個查核。 |
| Not applicable | 這個比較對該研究不適用；必須說明原因。 |

列出完整格子可以揭露未知，不能證明研究解讀正確。程式只核對原文、hash、
作品／版本／來源、候選版本與紀錄完整性；獨立 reviewer 判斷理由是否成立。
資料能下載不代表有必要變數、可連結或獲准供模型使用；模型名稱存在也不代表
權重、授權或算力可用。未核對的授權、費用和版本繼續顯示 Unknown。

## 版本與操作入口

舊 packet 2.0／2.1、舊結果與分數保持原樣。新 packet **2.2.0** 同時支援
原完整 Stage 1 匯入與 exploratory acceptance；後者的 unknown、review-only
與限制不因啟用表格而升級。`research_tables: null` 表示尚未準備。

在既有 CLI 環境執行 `python -m stage2_ideation enable-tables --packet <input.json>
--source-root <sources> --output <new-private-packet.json>`，得到新的種子檔。
輸出必須位於 Git 外的私有目錄，已有檔案不覆寫。從這個種子建立**新 workflow run**，
不可把舊 run 的 packet 版本原地更換。這個命令不搜尋、不呼叫模型、不給研究通過。

研究 agent 保存原始提案後，packet 2.2 自動使用 extraction 1.1。
無工具擷取器選擇原提案的 span IDs；host 還原引文及候選 ID／版本。
表格綁定確認的 brief、輸入 packet、snapshot、原始提案與來源證據。
新表格進入下一個不可變 snapshot；新版候選需重新查核，舊版資源不可冒充新版。
沿用既有 daily-v3／evaluated-deliver-v3，科學內容改變才重新評分。

## 交付與驗收界線

同一份已驗證紀錄產生可編輯 Markdown、proposal HTML 與 Wiki 的
Topic comparison／Data, models & tools 頁籤。可展開每格理由、原文引文、
作品版本與位置；資源依候選版本分組，舊版另外呈現。
舊資料沒表格時明示未準備，不從既有評語猜出 ✓ 或資源可用性。

閱讀介面以滿版比較表為主：主要文字至少 16px，次要標籤至少 14px。
預設只呈現比較、方向與重要資源狀態；欄位定義、限制、原文及評語按需展開。
不能為了清爽而隱藏 Unknown、取得限制或把未知畫成零分。

P4 比較忠實性、可比條件、綜合；P6 可行性與選擇包是預期改善面向。
九項 v3 rubric、unknown 規則、人工選擇與 Stage 3 權限保持不變。
本功能先驗收契約、擷取、snapshot 與報告投影；**研究品質改善尚未證明**。
正式 A/B 另凍結版本、共同輸入與投入政策，不能把表格數量或填滿率當成改善。

新的 packet 2.2 研究任務綁定 `comparison_preparation_policy`，因此不重用舊
任務的模型成果。交付 presentation 1.3 會重建紀錄完整性門檻；閱讀
[內容先行交付規則](stage2-content-first-delivery.zh-TW.md)了解草稿、完整紀錄、
科學查核與正式改善之間的界線。
