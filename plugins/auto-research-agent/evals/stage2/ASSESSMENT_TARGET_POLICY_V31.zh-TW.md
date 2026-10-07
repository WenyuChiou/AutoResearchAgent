# Stage 2：評分要看提交內容實際完成了什麼

## Why

judge 能指出缺漏，不代表被評的提案已完成那些工作。例如提案只說
「A 用訪談、B 用實驗」，judge 再指出沒有比較結果，不能因此給提案
完整比較的分數。另一个問題是前例定位、貢獻邊界等子項互相混用要求。

## What

新增 opt-in `assessment_target_policy` 3.1.0。P4／P5／P6 九項 rubric
仍為原來 v3，沒有改分數、門檻或 unknown 定義。

新提示固定五件事：提交內容是評分對象；外部事實只能查核；不能把
judge 自己的批評算成提案成果；各子項使用自己的 anchors；後來版本
的完成檢查不能補成早期版本已完成。

正確發現不可行、提出條件式替代路線、或有據地零推薦，仍能得高分。
判斷品質與方向是否可立即執行，是兩件事。

## How

`prepare_targeted_quality_batch` 重用既有 blinded batch 擷取與 schema。
只加固定提示及 policy binding；alias、原始内容與科學標準保持原樣。
binding 保存提示與实际模組 bytes 的 SHA-256，呼叫前由 host 凍結。
不支援的版本、角色、空 prompt 或不同 binding 明確拒絕。

binding 留在 host 的評估設定；送給 judge 的 prompt 不含參考分數、
variant 標籤、其他 reviewer 分數或 A／B 身分。

此接口不默默修改 `run_quality_v3`、`daily_v3` 或舊版 replay。
新 runner 要明確使用新 preparer、保存 policy／prompt／rubric bytes，
並經對應的 native archive 驗證。準備好 prompt 不等於 native admission。

## Example

提交內容只比較兩篇研究的方法，沒有交代結果與限制：依原 anchors
給部分充分的分數。judge 的詳盡補充不能把提交內容升成完整。
若新內容真的補上查核過的結果與限制，建立新版本後才重新評分。

## 已量測與尚未完成

獨立審查後、看回覆前凍結的 84 份控制案例，使用兩個獨立
GPT-5.6 Sol／High judge，共 22 個實際呼叫與 168 個指定判斷。
核心符合率 144／144、一致率 72／72、等義變體 72／72，來源語境
24／24；九個子項各 16／16。這是本組控制案例的校準結果。

舊版失敗保留；因新控制案例與提示不同，不能把兩次結果當成 A／B。
參考答案由 AI 整理並經另一個模型獨立審查，不冒稱 Eric 人工核准。
公開 Git 不放私有控制答案、研究原文或憑證。

完整 daily 評分、正式隔離／用量 admission、兩個研究預演及三組
正式 A／B，仍須各自驗證。這個接口不宣稱 formal-ready 或研究改善。

## 日常 CLI 如何使用與查回原紀錄

`daily-v3` 與 `verify-daily-v3` 都提供選用的
`--assessment-target-policy`，其值是 policy binding JSON 檔案路徑。
由實際安裝的 `stage2_live.assessment_target_policy.target_policy_binding`
產生 binding；它包含政策種類、版本、提示 hash 與模組 hash。
只寫「3.1.0」不足以確認用了哪一份政策，不能自行補 hash。

新評分明確選用此政策時，評分與 replay 使用同一份 binding。
replay 只核對原本的設定、提示、來源語境、呼叫與輸出，不重跑模型。
省略參數保留原來的呼叫方式與驗證規則，舊 archive 不改写。
明確提供 null、陣列、文字、缺檔、錯誤 JSON 或不符實際 bytes 的
binding 時，必須拒絕，不能退回舊政策繼續評分。

評分提示修正與研究品質改善不同。完成 replay 也不代表完成真人覆核、
正式隔離、兩個預演或三組 A／B。科學內容不變時，不為了新增這個
CLI 參數而重跑已驗證的模型呼叫。
