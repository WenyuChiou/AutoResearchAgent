# Stage 1 評估器 v3.1：原生能力、來源與重播

**Rubric 仍是已凍結的 v3，P1–P3 共十項，沒有新增論文答案表。**
v3.1 修的是如何取得、傳遞、核對及重播證據。它不是較寬鬆的評分標準。
本次改動屬 implementation-only；正式美國 A/B 尚未完成，不宣稱改善。

### 共用被動觀察器與完整已存歷史

新建 v3.1 lock 綁定 `passive_observer` 的政策和實作 hash。A、B 都在原生程序
啟動前、收到每個 `item.completed` 後及程序退出後觀察工作區，保存原始 stdout、
stderr、檔案 bytes 和觀察事件。觀察器不向 subject 發指令，也不替它搜尋或查證。
`observed_at` 是觀察時刻；原生未提供的 backend、result count、HTTP status、
duration 仍為 null。讀取檔案有成本，也可能遇到並行寫入；遇到偵測到的競爭或
I/O 失敗就保留錯誤並拒絕完整擷取，不替 subject 扣分。此採樣不能保證每次檔案
寫入都被捕捉，兩次觀察之間已消失的版本仍不可重建。

`evaluate --evaluator-version 3.1` 現在透過 `capture_history` 讀取所有已存 attempts
與新 observer snapshots，匯出 `workspace-history.json` 和
`native-field-availability.json`。早期或未交付版本只進 process evidence，不能
冒充最後交付內容。歷史擷取不补造 observer 紀錄，診斷仍標為修復後診斷。
完整 content/source/major-error 語意整合與非計分 pilot 尚待完成。

### 評估器啟動與片段選擇修正

已觀察到評估環境只裝了 `pdfminer.six`、漏裝 `pdfplumber`，使已取得的公開 PDF
無法解析。這是 evaluator 的環境失敗，不能當成文獻本來不可取得或 subject 做不好。
現在先用真正的 PDF parser 解析一頁固定文字，核對文字與頁數，記錄 parser 版本和
Python source hash。測試環境依賴固定於 `requirements-test.txt`；實際 evaluator
也必須安裝這些依賴。可用 `python -m stage1_eval.source_runtime` 單獨預檢。
預檢在 extraction 與 judge 模型呼叫前完成；新鎖保存相同結果，恢復時重新核對。
這個小測試不證明 OCR、網路可用或科學內容正確；執行環境仍需另綁定完整 image／依賴。

Judge 曾在一次修正後仍抄錯長片段 hash。現在模型只選 `s1`、`s2` 等短代號，
每個判讀單元的 schema enum 限制它只能選當前可見的代號。獨立保存代號到原始
hash、檔案、版本和位置的對應，重播時重建並比較；不以近似字串自動修正錯誤。
不存在的代號、被修改的對應與不支持同一作品的引文仍拒絕。沒有增加語意修正次數。

擷取清單仍可能保留簡稱、出版版本或待核對的重複紀錄。其筆數不是已核實的獨立
論文數；不能只因擷取器數出 19 筆、subject 說 18 篇，就判 subject 身分錯誤。
需要來源證明的作者、題名、版本等衝突；未解身分填未知，不能替模型猜測合併。
先前受缺 parser 或片段選擇失敗影響的結果保留為診斷。修復後重新凍結 evaluator
環境與 bundle，對六份原始輸出採同一設定；不重跑 subject、不改 v3 rubric，
亦不把修復後的結果冒充原先凍結的正式比較。

### 文獻清單修復（作品擷取 schema 3.2）

搜尋字串只是「想找什麼」，不是「已納入哪篇文章」。搜尋紀錄裡的 query 和僅被
排除的候選另存為 `search-query`／`excluded-candidate` mentions；同一來源若在其他
段落真的被引用或比較，該段仍可形成作品紀錄。這是模型依上下文作的分類，schema
只能檢查紀錄結構，不能保證分類永遠正確；需保留片段供查核，不能靠檔名刪除內容。

只缺識別碼的完整題名，若與清單中唯一一筆具識別碼的題名相同（忽略大小寫、空白和
句尾句點），合併為同一作品並保留每次出現的位置。簡稱、題名衝突或多個識別碼仍不
猜測合併。Judge 明確收到已判定 supported 的 closest work IDs；空清單不能給此項
2 分，來源不足填未知。程式不代改 judge 分數，也不增加重試次數。

六次美國受測執行已完成，但原凍結評估發現清單污染與判分矛盾。原失敗保留，原正式
比較仍不完整。修復後使用新 evaluator bundle hash，對同六份輸出重評須明示為
**修復後重分析**，不能寫成原先凍結評估已通過，也不能選擇性重跑受測答案。
Rubric v3、兩組原生工具與受測 harness bytes 不隨評估器修復改動。

來源文字先以檔案原始 bytes 核對 hash，再直接解碼 UTF-8，保留 LF、CRLF 或 CR。
不可讓一般文字讀取自動改換行，否則正確的原文可能被誤判為遭修改，片段位置也會偏移。
實際 bytes 被修改時仍拒絕；錯誤訊息會指出對應的 work ID。

## 先讓使用者決定研究範圍

自然語言方向 → ResearchBrief → 必要澄清或有限初探 → 使用者決定 →
需求、概念與搜尋式 → 蒐集、閱讀與比較。

已指定的地域沿用；沒指定且會影響研究時，詢問要指定、看建議或暫不限制。
推薦地區不等於選定地區。使用者選「不限制」也可以繼續工作。方法文獻可以
來自其他地區，但要說明可轉移性。每組搜尋式連回研究需要，範圍修改保留歷史。
目前 Eric 已從建議中選擇**美國**，方向仍是人口老化、消費行為的雙向 LLM
agent 模擬，16 週、探索性研究。舊南韓案例只用於修復診斷，不混入新配對。

入口另報三個量測：未授權的已宣告範圍縮小次數、範圍決定來源可追溯率、
必要澄清是否完成。它們不併入 P1–P3，也不聲稱程式能辨認所有自然語言暗示。

## 保留 Codex 原生能力

A 是原生 Codex；B 是同一 Codex 加 Stage 1 plugin。兩邊保留相同原生搜尋、
閱讀及推理能力。B 可選擇 research-hub 做特定資料庫查詢、DOI 查核、引用追蹤
或來源取得；有 runtime pin 不代表必須使用它，也不需要重複搜尋來湊 ledger。

原生 JSONL 能證明實際動作與暴露的 query。若沒有完整結果、HTTP 狀態或原文，
這些欄位保持未知；「搜尋動作結束」不是「已查證全文」。新鎖明示
`search_observation_policy=native-or-cli`。有 CLI ledger 時仍嚴格驗證，不能因為
它損壞就跳過。原生 receipt 是執行觀察，不授予 `stop-sufficient` 或科學品質認證。
評分不獎勵檔案格式或篇數；A 的原生日誌同樣能支持 P3。

## 如何修正以前的評估失敗

1. **引用不用模型重打。** 保存原文片段索引；模型選 `span_id`，程式還原原句。
   每個片段連回原檔、hash、作品、版本、文字位置。跨檔錯引、改字或換版本仍拒絕。
2. **文獻和 claim 分開擷取。** 每塊連相鄰上下文最多 12,000 字元，涵蓋所有交付
   文字，保留尾段及片段來源。作者簡稱、討論中的縮寫和群組描述另存為 mentions，
   不把它們算成新論文。相同 DOI 且題名只差大小寫、空白或句尾句點時合併；
   題名衝突仍分開查核。原始引文和每次出現的位置全部保留。
3. **修正有界而且留痕。** 每個語意失敗單元最多一次修正；模型呼叫預設 600 秒，
   暫時性傳輸錯誤最多一次同設定重試。逾時、登入失敗、工具越界不盲目重試。
   初次失敗、修正 prompt、stdout、stderr、輸出和驗證結果全部保存。
   API 不支援的數值、篇數或字數限制，仍以欄位說明傳給模型並由本地嚴格檢查。
   已完整產生但違反本地 schema 的 JSON，也只能進入這一次修正；它不能直接
   當作合格結果或完成單元。第二次仍錯就停止，原始失敗與修正都保留。
4. **恢復必須重驗。** 輸入、schema、模型設定、程式及輸出符合原紀錄才可重用。
   `--resume-verified` 不等於重新抽到喜歡的答案。未完整捕捉的失敗不冒充完成。
5. **完整執行歷史。** 空工作目錄合法；多次 attempt 全部保留。結果檔不能被覆寫；
   每次評估的成功或失敗另存一筆。評估失敗沒有 subject 零分。

Judge 的單元採有界證據視窗，保存完整索引、實際入選片段及截斷清單。
每個作品最多 12,000 字元、每個單元最多 60,000 字元的來源文字；檔案先輪流取得
片段，再依 claim、開頭、結尾與分散位置補入。若連各檔基本片段都放不下，回報
評估限制。Process 檔案很多時，片段長度以「60,000／檔案數」和 900 的較小值切分，
讓每個檔案都有可定位片段；完整索引仍不漏字。遺漏片段可能影響判斷時填未知；
不因紀錄較長就自動降分或設定隱藏上限。
完整 artifact 仍保留，便於後續查核。這是 evaluator 的限制，不是受測者的錯誤。

## 原文取得與文獻角色

評估器使用固定版本 `research-hub source fetch --json` 取得公開摘要、HTML、
arXiv 或開放 PDF，儲存每次原始回應、HTTP 狀態、時間、版本、身分比對和文字位置。
無法取得、rate limit、解析錯誤與身分不符分開記。登入頁不能冒充全文，metadata
不能支持中央 findings。付費或其他不可取得的證據保持未知。

`source validate` 可從原始 bytes 離線重做擷取；單純重算 hash 不能讓假引文成立。
驗證成功表示紀錄完整，來源本身仍可能不可取得。Evaluator 查到的資料不能算成
subject 做過的搜尋；兩種來源分開標記。

- **Topic-core**：原文支持它在這個題目的作用，說明漏掉後少了什麼及有沒有替代。
- **Classic**：除原始貢獻外，還有獨立歷史採用或認可證據。年紀與引用數不是捷徑。
- **Closest work**：比較問題、研究對象、機制、方法與驗證的實質接近程度。

三者可以重疊但不互相替代。不要求命中某幾篇私有標準文章。

## 從預演到正式結果

先用舊六份輸出做明示的修復診斷，再完成一組不計分的 live 預演。
新正式研究另開六次乾淨執行，GPT-5.6 Sol、High、任務模式，相同英文題目與截止日，
順序 A→B、B→A、A→B。受測 harness 與 evaluator 的 research-hub 版本分開固定；
修復 evaluator 不能悄悄更換受測 B 的工具版本。

操作入口：`prepare-spec --evaluator-version 3.1`；`freeze-v3` 額外提供
`--research-brief`、`--evaluator-dependency-repo`、`--evaluator-dependency-sha`；
`evaluate --evaluator-version 3.1` 搭配 lock、capture 與 `--execution-class formal`。
完整參數以各 CLI 的 `--help` 為準。`repair-diagnostic` 和跨主機 portable replay
不能進入正式配對；它們也不證明原 runtime 可在新機器執行。

R1、R2 各自只看同一封閉證據包；實質判斷不同才用 ADJ。程式從 native model
transcript、原始來源、擷取單元和判分單元重建結果，然後套用原配對規則：
**P2、P3 各至少兩對改善且零退步；P1 零退步；B 沒有確認的重大錯誤。**
缺必要證據則 `inconclusive`。不合成總分，不從三對推論統計顯著或跨題目泛化。

報告逐項分數、可判比例、未知、各對差值、中位數與範圍，另列來源失敗、模型
失敗、耗時、工具呼叫、可得 tokens、成本與人工介入。部分 attempt 缺用量時，
已觀察的小計和完整總量分開，未知總量不填零。完整報告保留未改善與證據不足結果。

配對入口完成 capture 與 evaluator 的離線重播後，輸出 decision JSON，並在旁邊
寫入同名 `.criteria.csv`、`.report.json` 與可編輯英文 `.html`。CSV 保留十個
criterion 的每對 A/B 分數、可判比例、未知原因、evidence IDs 與 delta eligibility。
維度差值必須具有完全相同的適用 criterion 集合、全部可判，且 rubric、spec、
evaluator identity 與 evidence mode 一致；相同可判比例不代表相同分母。
不合格差值保留 null 與機器可讀原因。觀察到的部分平均仍可列出，但不能當作完整差值。

報告另保留 subject 每次 attempt 的實際 wall time、可得 usage、evaluator 模型成本
及重大錯誤。Wall time 包含 observer 額外時間，不冒充 native tool duration；
無法取得的金額與人工介入保持 null。此輸出不授予 freeze approval，目前驗證仍是
合成資料工程測試；非美國預演與正式科學比較需各自完成其前置 gate。
