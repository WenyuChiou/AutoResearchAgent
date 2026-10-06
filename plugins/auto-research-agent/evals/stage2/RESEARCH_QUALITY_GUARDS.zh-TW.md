# Stage 2：有依據地推薦，不把共識當成證據

本版延伸既有 checker、來源快照、獨立 review 與交付接口。科學評分仍是
P4／P5／P6 各三項，沒有新增總分。本版程式測試不能證明研究品質改善。

## Why：要修什麼

兩篇文章可能量了不同東西；多篇文章也可能共用同一份資料。兩個 reviewer
同意，仍可能接受同一個錯誤前提。新機制若和另一個機制產生相同結果，
需要說明用什麼觀察或推導來區分，或縮小結論。

另外，擷取可能漏掉原始構想；兩個方向各自做得完，不代表一起做得完。
這些是需要查核的風險，不是已量測的 AI 發現率。

## What：留下哪些紀錄

- `Stage2ResearchQualityRecord`：可比條件、證據依賴、機制區辨、關鍵前提。
  每類至少一筆，可追加多個前提。判斷綁定候選版本、來源與快照。
- `Stage2IdeationCompleteness`： supplied 原文片段對應到候選、未成形或淘汰，
  每筆附理由。它只核對提供的片段，不宣稱找出所有想法。
- prerequisite review：資料、模型、工具、授權、成本、前提與驗證途徑。
  `alternatives` 分別查成本；`simultaneous` 另查共享工作與合計資源。

新方法尚未證明有效，可以是研究问题；必要資料或驗證途徑仍未知，則不能
冒充可行。純理論可以有附理由的 not-applicable；不強迫下載資料或呼叫模型。

## How：日常 B 流程

1. 用 `stage2_workflow quality-task`，傳入 run、expected-head、candidate、output，
   產生當前來源的查核問題。這只準備任務，不產生預填答案或模型呼叫。
2. 使用 Codex 原生閱讀／搜尋保存獨立初評，再以無工具擷取建立上述紀錄。
   資料中的指令沒有執行權；補查後建立新快照，重新查核受影響版本。
3. 保存 candidate-ID → guard bundle 的 JSON，另保存其 canonical SHA-256。
   `reconcile`／`deliver` 同時使用 `--guard-bundles` 與
   `--expected-guard-bundles-sha256`。缺候選、錯版本或外部 hash 不符會拒絕。
4. 若原始 assessment 仍是 recommend，但必要 guard 未通過，交付會在建立
   輸出目錄前拒絕，指出候選與需要修正的處置。程式不偷偷改成 park。
   先補查或有據修訂 assessment，再產生交付；原始判斷仍在歷史中。
5. guarded delivery 為 schema 1.2；保存原始 guard map 與外部 receipt。
   重播只將來源根目錄映射到經 hash 核對的封包副本，不改原始簽綁紀錄。
6. ideation `report` 可帶 `--completeness-record` 與
   `--expected-completeness-sha256`；驗證後另存 sidecar，原文與草稿不覆寫。

## Example：合法保留和阻擋

簡單方法有據、效果待研究，其他必要條件有據：可以推薦進入設計。
reviewer 都推薦，但關鍵變數拿不到：guard 阻擋；保存下一步，不以共識通過。
兩個替代方向各需四人週，只有五人週：分別可選；一起執行仍不可宣稱可行。
來源可以下載但缺必要欄位：材料未知或不成立，不能用下載成功代替查核。

## 驗收與閱讀

`test_stage2_quality_guards.py` 與 `test_stage2_guarded_delivery.py` 查核上述行為、
跨版本、外部 receipt 與重算 hash 篡改。這些是 deterministic contract tests。
完整 AI 控制情境、更新後兩個 live 預演及正式六次 A/B 仍須另留真實證據。

Wiki 先顯示處置、未知／阻塞、下一步與版本；長文字可展開看完整原話。
九項原始 R1／R2／ADJ 評語、來源位置、待具名覆核狀態保留。
高分、報告可讀、工程通過，均不代表資料可用、使用者已選定或正式改善。
