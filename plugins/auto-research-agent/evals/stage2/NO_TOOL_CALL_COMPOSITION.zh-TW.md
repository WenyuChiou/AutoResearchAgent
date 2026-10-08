# 原生呼叫的無工具組合契約

狀態：implementation-only。採用 `wrap`：組合既有 v3.1 模型呼叫、原生 trace
擷取與重播驗證，不新增模型執行器或重試。

## 兩種明示政策

- 預設 `no-offered-tools-v1` 是嚴格模式。每次 inference 的工具清單必須為空；即使工具
  從未被呼叫，只要曾提供給模型就拒絕。
- `no-executed-tools-v1` 只證明觀察到零工具呼叫與零子執行緒。它保留並雜湊實際提供的
  工具清單，不能解讀為工具不可用。此模式必須由呼叫端明示；嚴格模式失敗時不會自動
  降級。

## 封存、失敗與重播

每個已驗證的模型呼叫 archive 對應新產生的原生 trace。擷取器複製原始 trace bytes、
建立 seal，並回傳原始 seal SHA。若後續單元驗證失敗，錯誤仍保留已建立的 seal receipts
與已完成單元，讓呼叫端保存失敗證據；內部 capture token 不會序列化。

重播不執行 callback、模型或工具。它重新驗證 v3.1 archive、原始 seal 與所選政策。
嚴格模式保留舊版 1.0 controller metadata；明示零執行模式使用 1.1 metadata 與
policy-bound seal receipt。切換政策、缺少 receipt 或竄改 receipt 都在重播前拒絕。

## 證據邊界

這些 artifacts 只支持有界的 trace 與零行動判讀。它們不證明 sandbox 隔離、工具在
runtime 中不可用、正式執行 readiness、科學品質改善或研究結果有效。外層 workflow
仍須驗證 metadata 與 receipt 的原始 bytes；正式聲明另需既定 review、audit 與配對證據。
