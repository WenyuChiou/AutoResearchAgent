# Stage 1 / T1：執行來源審計單元

`source_audit_units.audit_sources(packet, source_records, extraction, directory,
model_options, replay_only=False)` 是可呼叫的執行介面。呼叫者先用既有公開
來源重播核對取得紀錄，再傳入完整 catalogue 與抽取結果。尚未接入正式
`evaluate_v31` 路徑；不能以這個介面宣稱 T1 或整個新 evaluator 完成。

每個作品保留 title、authors、year、identifier、version 五個原始欄位，
並保留原始引用文字。舊抽取器沒有提供的欄位保持 missing-original-field，
不從外部資料補成「受測答案已寫對」。新的 `original_fields.audit_subject_sources`
可先從有 provenance 的受測原文提取這些值，再呼叫本介面；詳見
[原值提取](ORIGINAL_FIELDS.zh-TW.md)。每個中央主張保持原 ID 和原文；
未引用作品的主張保持 unlinked-claim。未取得來源、只有 metadata、證據
不足和相互衝突分別記錄原因。完整欄位抽取與最終判準彙整仍待整合。

來源文字依有位置的 400 字元 span 全部切分，按序放進最多 5,500 UTF-8
bytes 的一般視窗；超長目標不截斷，超過執行上限則失敗。原始與一次修正
提示都不得超過 9,000 bytes。新增提示可能超過 1,000 tokens，須核心團隊
額外人工審查。這個 bytes 上限不聲稱是精確的 token 計量。

模型只回傳來源別名。程式檢查所有別名被列入 addressed，並從保存資料
恢復原文、位置、作品、來源版本與 raw source hash。addressed 是機械路由
紀錄，不能證明模型心理上讀懂了全文。Metadata 不會進入 claim 的證據視窗。

`plan.json` 保存預期單元及完整窗口，原生 model-call 目錄保存輸入、schema、
輸出和執行紀錄；成功產生 `result.json`。失敗保留 coverage-error，區分
completed、pending、error，不發出成功結果、不盲目重試。重播重新驗證
原生輸出及正規化結果，不能靠修改結果並重新計算雜湊來偽造完成。

結果保留全部 leaf，包括反證。支持與反證並存時只作保守的 unverifiable
暫定彙整，等待語意彙整；從不給 rubric 分數。R1、R2 應在獨立目錄分別
執行，不把別人的判斷塞入提示。自動 R1/R2/ADJ 調度與正式模型實驗尚未整合。
後續真實调用遵照使用者選擇 gpt-6-astra/high；測試用 test-model 合成原生回覆。
