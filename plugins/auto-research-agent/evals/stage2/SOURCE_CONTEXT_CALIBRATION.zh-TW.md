# Stage 2 來源語境校準：先驗證怎麼算，再驗證 judge 會不會讀

## Why

引用位置正確，仍可能把前人的研究當成本研究、說原文沒有其實已有的
數字，或漏掉會改變可行性的政策例外。原本 72 份九項校準不能代替
這些新的來源語境案例。

## What / How

新增 12 份：研究歸屬、原文存在性、政策例外各四份，各含兩個正例與
兩個反例。資料與參考答案分開，R1/R2 每份各評一次，共 24 個指定
主要判斷。與原 72 份／144 判斷合計 84 份／168 判斷。案例數、判斷
數與真正模型呼叫數分別記錄。

`prepare_context_quality_input` 只傳研究內容、criterion 與來源事實；
分數、critical、family、polarity 與原始識別碼不傳給 judge。私有 ID
對照留在評估端。來源或候選文字本身仍須查核，不是答案提示的清除器；
context 分離也不是檔案隔離證明。R1/R2 不得看到對方輸出或參考答案。

驗證器以原始 dataset/reference/R1/R2 重算報告，不接受單独手填 passed。
原始評語、證據 ID、分歧、重大錯誤與 evaluator failure 都保留。
必要狀態未知用 null，不算成零；缺案例直接拒絕，不縮分母。

## 門檻

- 原有九項：整體與每項參考符合率至少 90%、R1/R2 一致率至少 85%、
  等義變體至少 90%；原規則不改。
- 新來源語境：整體與每群至少 90%、R1/R2 一致率至少 85%；每群固定
  八個判斷，90% 要求實際上是 8/8，不能用其他群抵銷錯誤。
- 明確重大錯誤不能誤判；重大分歧要釐清；evaluator failure 阻擋驗收。
- 須另綁真實模型呼叫、版本、輸入、輸出與隔離證據，才可作 live 校準。

## Example

原文寫「先前 Android 研究是 X；本研究則分析 Python」。候選誤稱
本研究是 Android，judge 要依兩段原文指出歸屬問題，不能因有 X 的
正確引文位置就通過。原文只查了一段，也不能說整份文章沒有某資訊。

目前的 combined acceptance 明確標成 deterministic-mechanics-only。
合成測試通過不代表真實 judge 品質已通過，不建立 formal-ready 或
改善聲明。舊 QA03、原始失敗與 rubric v3 不覆寫。

## 原生呼叫入口

`python -m stage2_live calibrate-context-v3` 接受私有 dataset/reference、
`codex`、分開的 `r1-home`／`r2-home`、model、reasoning、policy、output
及外部 `replay-receipt-output`。參考答案只留在 host；模型收到匿名內容與
來源事實，不收到 family、polarity、critical 或參考分數。每個實際
prompt 最多 12,000 字元；按 criterion 分組，案例數不是呼叫數。

保存 request、schema、每次 attempt、完成單元及原始評語。缺席 reviewer
保持 incomplete。使用 `--resume --resume-receipt` 只重用外部回執核對過的
完成單元；來源、runtime、設定、prompt 或共用執行程式改變時拒絕重用。
失敗原生 archive 不會被盲目重跑，須先保存失敗並釐清後另建執行。
CLI 在呼叫前拒絕已存在或放在結果／profile 內的回執輸出位置。

`native_qa_pass` 只表示這 12 個案例的真實 no-tool judge 判斷通過。
注入 adapter 的測試永遠不是 native；完整 84 份驗收仍須另外重算
72 份與 12 份的證據，且正式 readiness、隔離及 A/B 尚有各自門檻。
