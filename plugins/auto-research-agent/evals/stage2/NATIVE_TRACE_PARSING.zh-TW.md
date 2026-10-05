# 原生 trace：工具與用量不能靠猜測

這一批提供推論 request／response 的解析函式，供後續 observer 使用。
不新增 CLI、不呼叫模型，也不宣告完整執行或 formal-ready。

`trace_parsing.summarize_inferences` 接收已驗證且已整理的事件；它不取代
原始檔案、事件順序、thread 身分或執行版本的核對。

## 工具清單

工具可位於 request 的 `tools` 或 developer `additional_tools`。
兩處都有清單時必須一致；已知的空清單與沒有提供清單不同。
delta request 只能沿用同一 thread、在本次 request 前已完成的前次
response 所解析的工具。不能借用別的 agent 或尚未完成的推論。

## 用量

token 欄位必須是非負整數；布林值不是數字。快取與 reasoning token
不能超過所屬輸入／輸出，total 必須等於 input 加 output。
彙總包含每次推論及已知的 compaction 用量；不重加快取子集。
未完成推論、缺少用量或無法確認 compaction 計量時，總量為 unknown，
不把缺少的部分填成零。費用仍須另外取得，不能由 token 數猜金額。

## Example

父 agent 有工具清單，子 agent 的 request 沒有清單：不能直接說它們
擁有相同工具；留下 `offered-tools-unknown`，供執行驗證處理。

六項 regression tests 檢查工具別名、巢狀上限、錯誤用量、delta 歸屬
及不完整計量。解析正確不代表 sandbox 隔離或研究品質已改善。
