# Stage 2 比較工作台

## Why：為什麼需要這個畫面

Stage 1 找到文章並核對來源。Stage 2 要讓人看得出：不同研究用什麼
資料、怎麼做、得到什麼，以及哪些方向值得繼續查核。只有長篇文字，
很難比較。這個工作台把既有紀錄排在一起，方便閱讀與追查。

## What：你會看到什麼

- **Literature comparison**：逐篇比較問題或研究理由、資料、方法、結果、
  驗證、限制及與本題的關係。勾選文章可以並排看相同欄位。
  可切換研究總覽、概念／方法及詳細證據；總覽也呈現研究地域與對象。
  概念使用既有主題分類，不把名稱相似當成方法相同或歷史演進。
- **Research directions**：比較候選的問題、增量、價值、方法、材料、
  限制、處置及下一步。不把整份選擇包的評分貼到單一候選。
- **Data, models & tools**：呈現已記錄的資源及取得限制；沒有記錄的
  費用、授權或可用狀態不會自動變成零元或可用。
- **Recorded synthesis**：保留跨文獻的原始綜合文字。群體推論不會
  被塞進每一篇文章的結果欄。
- **Full candidate checks** 與 **Original criterion comments**：保留內部
  五面向查核，以及外部九項 R1、R2、ADJ 的原始評語、未知和覆核狀態。

## How：資料從哪裡來

先核對 Stage 2 delivery 與 bridge receipt 的 hash，再讀取同一份
`core_selection.json`。`build_comparison_view` 只投影已存在的資料，
不呼叫研究模型、不重新查文獻，也不改評分或執行權限。

表格原話來自 `evaluation_packet.literature[].findings`；缺少時，
資料類型或方法可以顯示既有 `classification`，並保留原欄位路徑。
分類標籤不能當成已核對的完整方法。舊 `question` 欄有時記錄的是
研究理由，所以畫面明確寫 **Recorded question / rationale**。

未記錄的格子顯示 Unknown。原有 partial、限制或未知前綴完整保留。
**full-text 代表保存的來源層級，不代表每個格子的敘述都已驗證。**
來源欄位路徑用來追查紀錄，不是論文原文位置。

相關原文必須同時符合文章、版本及該文章記錄的來源 ID。原文旁
保留位置和證據層級；「相關」不代表它支持這一列的每一句話。
詳細報告與原始材料沿用已核對的閱讀版。

真正的主題維度由研究 agent 根據 brief 與原文提出，並經比較與
前例查核。這個 UI 不會自動發明關鍵字、研究方向或資源。
若要從 CoT、ReAct、reflection 等設計提出縱向演進解釋，仍須保存
各研究的設計差異與證據，不能僅按發表年份連成因果或承襲關係。

每次匯出保存 `stage2/comparison-view.json`。manifest 綁定投影、
HTML、CSS、JavaScript 及產生器 bytes，方便重建；不覆寫原封包。
搜尋、勾選和切換頁籤只改目前畫面，重新整理後不代表人工選題。

## Example：怎麼使用

想比較兩篇方法：在 Literature comparison 勾選兩篇，按
Compare selected，逐欄看資料、方法和限制。若 Validation 是
Unknown，就表示紀錄缺少這項資料，不能解讀成驗證失敗。

想決定方向：先看 Research directions 的價值、材料和下一步，
再展開完整查核。即使 P4–P6 分數很高，資料取得仍可能未知；
推薦也不代表 Eric 已選定，更不授權 Stage 3。

## 測試與改善界線

驗收包含跨文章／版本來源排除、原話保留、null 不轉零分、
HTML 安全轉義、選取比較、篩選、證據顯示及桌面／手機布局。
新版畫面改善資料呈現與可追查性；研究品質是否改善仍須正式 A/B。
內部五面向 checker 和外部 P4–P6 rubric 都沒有在本次改版中改標準。
