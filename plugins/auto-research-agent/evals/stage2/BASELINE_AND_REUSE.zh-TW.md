# Stage 2 baseline 診斷與重用決策

這是歷史診斷與靜態程式盤點，不是正式 A/B，也不是所有原文 claims 已查完的結論。
run01 第一份回答 SHA-256：
`5fb5ff21fe73981504071b07f119ec5c62c25963ae541a7a45c7bef03db8a333`。
原 ZIP SHA-256：`7455a44afbf4183c315eaabab4442a6fe045380a15d4a377e0640714216f896e`。
原件保留在組織者的 run01 bundle，不提交私人 transcript 或完整文章。

| 觀察 | 原始回答定位／程式依據 | 待驗證問題 | 功能與指標 |
|---|---|---|---|
| 已有共同尺度比較，是優點 | research_response.md 行 52–58 | 新流程是否保留比較能力 | P4，不退步 |
| 方向 A/B/C 有問題、貢獻與難點，推薦有理由 | 行 65–113 | 查核是否能補足證據而保留有用取捨 | P6 |
| 窄範圍「證據少」主張與最近工作定位仍待核實 | 行 41、79、103 | 來自 Stage 1 漏搜，還是 Stage 2 推論不足？ | 固定輸入測 P5，不直接歸因 |
| 推薦限於 composition-only，回答也承認限制 | 行 77、121–123 | 範圍變更是否明示並獲使用者選擇 | ResearchBrief、P5/P6 邊界 |
| 舊 validator 要求至少兩個方向，並以最低方向分數限制推薦 | rubric_judge_result.py 的 Stage 2 分支，base 56bb49e2 | 正確淘汰低可行性候選是否被錯誤扣分 | 新版分開候選性質與判斷品質 |

run01 的題目、地域、單向設定、人工介入與目前美國雙向探索案例不同。不能用今日
需求回頭當成當時答錯，也不能將舊 run01 當作新正式 A/B 的 A 組。

## Reuse first

| 能力 | 決定 | 重用來源與必要差異 |
|---|---|---|
| 範圍與使用者決定 | reuse | stage1_brief 的 ResearchBrief；不自行換國家 |
| 起始來源、claims、未解事項 | wrap | Stage 1 handoff；共同中立封包同時接原生輸出 |
| 多文獻比較 | wrap | literature-triage-matrix；需真實來源，不能凭模型記憶填 findings |
| 研究機會、反例、初步可行性 | wrap | gap-to-topic 三個 gate；其內部量表不直接作外部 P4–P6 |
| 來源綁定 | extend | 既有來源版本／hash／逐字片段原則；新增候選版本引用 |
| 修訂與處置歷史 | extend | DecisionEvent／StageResult；保留版本、scope 問題與 Stage 3 未啟動 |
| 獨立 Stage 2 評分與配對 | build-new | 搜過既有 rubric_judge_result、judge_bundle、paired_evaluation 與 Stage1 v3；舊最低分聚合與人類選擇 endpoint 不適用。沿用驗證原則，新增版本不覆寫舊結果 |

可重用 skills 位於 WenyuChiou/ai-research-skills；工具來源為
https://github.com/WenyuChiou/research-hub 。本輪無需修改這兩個外部 repo。
安裝 skills 不是完整科學驗證；不複製其所有限制或把現有提示包裝成已證明有效的能力。

## 分工與接續

核心組負責契約、rubric、baseline 診斷、獨立評估、review 與 fork merge。
工程模型負責限定程式模組與 regression tests；組員可接續完整方向生成、補查與預演。
第一個 PR 放契約、共同證據接口、離線評估與 CI admission；第二個 PR 放固定候選
checker 與 skill。先處理 PR1，再以其合併版本更新 PR2。
每個 PR 記 Why／What／How／Example、實際測試與 AI contribution。
改善聲明為 not yet demonstrated，不能把 synthetic 通過寫成 P5/P6 已改善。

接續工作：第 1 週契約與控制情境；第 2 週最小切片；第 3 週診斷後擴充生成與預演。
這是排程目標，不是本輪已經經過三週或完成 formal A/B 的聲明。
