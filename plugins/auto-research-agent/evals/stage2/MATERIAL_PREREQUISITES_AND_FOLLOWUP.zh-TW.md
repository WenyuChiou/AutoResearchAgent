# Stage 2：必要材料、前提與定向補查

這份文件解釋新增的工程接口。它仍為 `implementation-only`：通過格式和
來源測試，不代表 AI 已能正確判斷所有研究方向，也不代表正式 A/B 已完成。

## 為何需要

「資料下載成功」不等於「裡面有研究需要的欄位」。兩個方向各需要
7 和 8 人週，雖然各自都小於 10 人週，一起做仍需要 15 人週。
我們要把這些條件、來源和未知留下來，避免報告只寫一句「可行」。

## 檢查什麼

每個目前版本的候選，明確記錄七類條件：

| 類別 | 白話問題 |
|---|---|
| data | 必要資料、變數、粒度和連結條件真的存在嗎？ |
| tool | 工具能處理需要的操作嗎？ |
| model | 若需要模型，能取得且適合這個任務嗎？ |
| license | 授權允許研究需要的使用方式嗎？ |
| cost | 時間、算力與 API 的估計有什麼依據？ |
| premise | 關鍵前提有沒有依據或反證？ |
| validation-path | 什麼證據能回答問題、排除替代解釋？ |

四種狀態分開保存：`supported`、`contradicted`、`unknown`、
`not-applicable`。前兩者需要已綁定的 evidence ID；unknown 要寫下一步；
不適用要寫原因。理論研究可說明資料、模型等不適用，不強迫使用 LLM。

## 工程接口與邊界

`stage2_workflow.prerequisites.prepare_prerequisite_review` 接收目前 packet、
source root、候選 ID、七類 checks、demands 和 capacities。
`inspect_prerequisite_review` 以外部保存的紀錄 hash 重建並核對結果。
紀錄綁定 packet hash、候選版本與來源；換版本後不能冒充仍有效。

每個 check 包含 check_id、candidate_id、candidate_version、kind、statement、
status、evidence_ids、reason、next_check。重複類別、錯版本和錯 evidence 拒絕。
這些檢查是結構與來源驗證；`semantic_verification` 仍是 `not-established`。
獨立 reviewer 要判斷引文是否真正支持前提，不能靠格式驗證器宣告 PASS。

資源需求按明確 component ID 加總。只有明確由多候選共用的同一 component
可只計一次；名字相近不能自動省掉工作。未知需求或未知上限的結果是
unknown；不自行填零。容量來源保留實際 decision_ref，不替 Eric 做預算決定。

## 哪些情況會補查

controller 的新行為採明確 opt-in，保留舊版預設。新的 `followup_policy`
必須是 kind=`Stage2FollowupPolicy`、schema_version=`2.0.0`，且
investigate_material_partial=`true`。

除了原本 blocking unknown，修正或暫存候選中，有 next_check 的
0／1 分判斷與 revision next_step 也會轉成 `follow-up-needed`。
已經有據淘汰、沒有可行修復的候選不強制反覆搜尋；新方法成效尚未知，
但這正是研究問題時，也不要求先證明成功。

這個接口產生有界的補查需求，並非自動下載來源的引擎。既有來源快照、
補查與重新查核接口負責後續工作；沒有新證據或可行下一步時保存未解事項。
實際 E2E 行為還需要通過 native 能力與隔離門檻後的完整預演。

## 對應測試與評估

- `test_stage2_prerequisites.py`：七類、來源／版本、未知、共享成本、超支、純理論。
- `test_stage2_material_followup.py`：舊行為、新 opt-in、反證、未量測成效、缺席 reviewer。
- P5V2.REVISION：遇到新證據是否修正並保留歷史。
- P6V2.FEASIBILITY：材料、可回答性與資源判斷有沒有依据。

正式品質由獨立 P4–P6 評估與配對測試決定。這些單元測試不提供科學品質分數。
