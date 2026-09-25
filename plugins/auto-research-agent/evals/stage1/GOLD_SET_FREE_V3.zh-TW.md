# Stage 1 通用、無論文答案表的評估（v3，experimental）

這是 Stage 1 新增的獨立評估路徑；歷史 v1、南韓雙向耦合 v2／v2.1 的 frozen 分數、分母與人工策展規則不變。v3 目前可做開發預演，**尚未證明**加入 harness 比 stock Codex 好，也不能把不同題目的 80 分直接視為同等難度。

## 評估的是什麼

同一份 Stage 1 rubric 固定 P1 證據可靠、P2 文獻骨架是否足以支撐題目、P3 過程能否重建。每個面向有可見的 0／1／2 判準；零表示有觀察到的缺失，未知是 `unverifiable`，不適用須由看過**原始題目**的獨立需求規格預先說明。程式報每個面向的已評比例、已評平均、未知項目取 0 或 2 的算術上下界、重大問題，**不產生總分，也不計算「核心論文召回率」**。

「topic-core」是來源證實它對本題的知識或研究決策有實質作用；「classic」是另有獨立歷史採用證據；「closest work」是與本題在問題、對象／系統、方法或機制、結果與驗證設定上的實質接近。三者分開記錄。舊論文不因年齡得分，新論文不因未累積引用而失格；高引用與 DOI 可解析都不能代替原文證據。

## 從題目到報告

1. **先定題目與截止日。** `stage1_eval prepare-spec` 只看原始題目，產生 needs、適用的 literature roles、近期時窗與至少兩條不同的 foundation／closest 搜尋路徑。此時不能看 B 或 T 的回答。規格中禁止 gold titles、expected DOI 或 holdout 命中欄位。規格、rubric 和原始題目都有 SHA-256。
2. **再執行受測 agent。** B 是 stock Codex；T 是同設定加 AutoResearchAgent Stage 1。兩方用同一 prompt、日期、模型與原生工具。T 額外 plugin／research-hub 的影響屬整個 treatment package。subject 的原生 transcript、最後回答及實際交付檔案分別保存。
3. **中立擷取與來源查核。** Adapter 不要求 B 擁有 T 的 ledger。獨立 extraction 擷取每個被引用作品及中央 claim，原句必須在實際交付內容中。Evaluator 用 research-hub 查核被引作品，保存命令、原始 stdout／stderr、時間、狀態與 hash；metadata／abstract 不冒稱全文。
4. **可選的有限挑戰搜尋。** `packet-only` 只能判眼前內容，不可給完整 coverage／closest 滿分，也不可聲稱找不到遺漏。`evidence-audited` 在 frozen spec 下做有限搜尋，找到的作品是 potential omission，需要再判來源、直接性、決策影響與替代性。搜尋失敗不是零結果；固定 top-K 不是全領域 recall。
5. **盲化與分開判讀。** 同一封閉 evidence packet 交給禁用工具的 Auto-R1／Auto-R2。P1/P2 只見內容和外部來源，沒有 T 的格式獎勵；P3 看實際 native trace 與交付物，不替 B 補造紀錄。每個 criterion／core／omission 的實質 verdict 不同才叫 Auto-ADJ。引文必須逐字存在於已綁定 evidence。
6. **程式計分。** `StageEvaluationResult v3` 保存 criterion vector、assessed fraction、unknown、P1/P2/P3 分數與界線、重大錯誤及 evaluator／subject／source failure。評估器本身失敗產生 `EvaluationFailure`，不能當受測模型零分；科學證據不足則可正常輸出 `inconclusive`。

## 執行與來源限制

`python -m stage1_eval --help` 列出 `prepare-spec`、`collect-background` 與 `evaluate`；詳見各子命令 `--help`。安裝測試依賴後需指定實際可用的 Codex CLI、登入的 evaluator CODEX_HOME，以及 research-hub 命令。Windows 上若安裝的 `research-hub.exe` 是失效啟動器，可用 `--hub-command-json '["@python","-m","research_hub"]'` 並在**同一隔離 Python 環境**安裝固定 commit 的 research-hub；`@python` 會換成目前 Python 路徑。每次 backend failure 的原始 stderr 都要保留。

正式配對前，規格、執行位元組與版本必須在 subject 開始前凍結，並與原生 capture 綁定。現有 v3 CLI 的 `formal` 模式**明確拒絕執行**，直到前述 pre-subject lock 和 native capture 驗證完成；不能用評估時才輸入的 hash 或開始時間代替。因本地 schema 修正而重用已完成模型輸出的 `finalize-saved-spec` 和 `--resume-pilot` 僅供**探索預演**；缺原始 prompt 位元組時明示 `prompt_sha256=null`，不得拿來冒充正式配對紀錄。

來源查核目前主要依 research-hub 可取得的 metadata 和摘要；全文、同年出版日期及付費來源可能仍不可核實。未知須維持未知。Judge agreement 是一致性，不證明專家正確；可靠的改善聲明仍需 frozen topic、配置、同一 evaluator 版本、配對 B/T 與另外的審查。

目前 PR validator 對 v3 只接受 `implementation-only`。現有 Level 2 readiness manifest 綁的是舊版南韓 Stage 1 live smoke，不能拿來替 v3 宣告 `stage-executable`。未來須另以 v3 專用 manifest 綁住 topic spec、rubric hash、evaluation result 和實際執行 artifacts，經驗證後才提升層級。

## 已做的探索預演與邊界

- 舊 v2 執行器曾以加拿大人口老化與家戶消費做**不計分預演**。最新保存的 `pilot19` 記錄為 B 完成、T 未完成，`scored: false`；這不是第二個正式研究案例，也不能納入南韓的三對 A/B 或改善主張。南韓仍是既定開發案例。
- 本地操作員曾用兩個簡短的人工撰寫 smoke 輸出試跑早期 v3 路徑：一個理論題與一個人口老化題。其 P1／P2／P3 已評項目各為 100／37.5／33.33。這些是**operator-reported** 的探索紀錄，raw bundle 保留在工作機器、沒有放入 Git，無法單憑此 PR 獨立重播；後續證據完整性修正後須重新預演。它們**不是** stock Codex 與 harness 的比較，也不代表文獻綜述品質。理論題缺原始 prompt hash，只能用於診斷。
- 上述人口老化 smoke 的本地紀錄顯示評估器完成 7 個模型回合、使用 270,509 個輸入 tokens（其中 72,192 為 cached）和 11,445 個輸出 tokens，來源查核 9 次，約 250 秒。這顯示評估成本需要納入正式實驗設計；有限搜尋的 top-K 結果相關性仍不足，不能據此宣稱未找到重要文獻。受測模型的 token 與貨幣成本未知，不填零。
- v3 的新增能力另列於 `capability-metric-map.v3.json`；`capability-metric-map.v1.json` 保持原位元組不變，避免破壞舊版南韓計畫的 registry hash 與可重播性。

## 誰決定什麼

日常 v3 評分不要求真人列核心論文名單、標來源或簽核才可產生報告。核心組仍決定 rubric 版本、正式 A/B 設計、外部改善主張、投稿與 PR review／merge。組員可開 Draft PR 並回報實測，不能自行把 `experimental` 說成 `improvement-demonstrated`。
