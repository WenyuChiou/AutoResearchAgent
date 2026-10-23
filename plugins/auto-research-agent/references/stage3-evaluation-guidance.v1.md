# Stage 3 通用評審指引 v1

Guidance ID：`stage3-evaluation-guidance-v1`。來源核對日期：2026-10-22。
用途：在 Stage 2 的候選、版本與 SQ 已明確後，審查研究計畫是否能回答原問題。
此指引是文獻支持的本地改編；尚未完成領域專家校準或效度驗證。
`execution_authorized=false`；離線接線本身不授權評審模型呼叫。

## 評什麼，以及如何使用

沿著「背景重要性 → 現況與既有應用 → 有證據的 gap／挑戰 → SQ →
資料／材料或形式假設 → 方法與設計 → 分析 → 結果判讀 → 有界貢獻」審查。
每個 SQ 必須保留原候選與版本；共用資料或實驗可以服務多題，但不能把同一證據重複當成獨立結果。
合法替代方法同樣可接受，不以參考論文的方法當唯一答案。[S01–S05]

1. 先核對輸入、候選、SQ、計畫及來源版本。Stage 2 建議不等於真人選案；synthetic／manual 來源保持原標記。
2. 按每題的意圖主張確定必要證據、適用研究型態及可接受替代；缺領域知識時明示不可判定。
3. 逐題使用下列九項診斷，寫出必要性、證據位置、簡短理由與未知條件。
4. 再對整份計畫的既有 P7、P8、P9 各給一個判斷，交代每題證據與尚存的重要缺口。
5. 保留原始評語、評審來源與作者關係、raw judgment、rubric／guidance／輸入 hashes；交由既有 review／選案／確認機制處置。

只要欄位齊全或 JSON pointer 存在，不能證明方法適當。評審要說明該證據為何能回答 SQ。
若核心問題或意圖主張改變，沿用版本化選案／修訂路徑；評分不替使用者改選題目。
不索取評審的私有推理鏈；提供可核對的理由即可。[S01、S02、S09]

## 九項診斷與既有評分的關係

| 診斷 | 面向／既有語義軸 | 審查問題與證據 | 已知缺陷例／合法替代例 | 來源 |
|---|---|---|---|---|
| D01 SQ、gap、主張對齊 | P7／answerability | 原 SQ、gap、主張及所需辨別／估計／證明／理解之對象，是否對準主要產物？ | 圖連結齊全卻回答另一問題；描述研究可只估計分布，不必強改成因果問題 | S01、S02、S05 |
| D02 材料與方法適配 | P7／resource-fit | 單位、粒度、涵蓋、測量、材料／來源版本或形式假設，是否支持原問題？ | 材料可取得但分析單位矛盾；理論研究可用明確假設與定義代替資料集 | S01、S02、S04 |
| D03 比較與設計邏輯 | P7／answerability、inference-boundary | 對照、baseline、識別、可信度檢查、證明義務或替代詮釋是否適合排除關鍵解釋？ | 因果主張缺必要識別；有效反例／證明或質性負例分析可代替不適用的隨機試驗 | S02–S05 |
| D04 分析與不確定性 | P8／inference-boundary | 主要／次要分析、判準、誤差與不確定性，是否對準 SQ 及推論單位？ | 把相依重複當獨立樣本；可按型態採取抽樣分析、數值檢查、證明或可追溯詮釋 | S04、S05；ML 適用時 S07 |
| D05 結果判讀與邊界 | P8／result-interpretation | 支持、反駁及無法判定的結果各能說明什麼？主張有何邊界？ | 預填未執行的成功結果，或把相關說成因果；負面結果仍可回答 SQ，不要求勝過 baseline | S02、S05；ML 適用時 S07 |
| D06 可重建規格 | P8／resource-fit、result-interpretation | 版本、材料處理、設定、程序、分析及合法保存／取得方案，是否足以重建？ | 缺關鍵處理或設定；受限資料可有合法取得與替代驗證方案，不強制公開敏感材料 | S06；ML 適用時 S07 |
| D07 規模與資源 | P9／feasibility | 最小／標準設計的規模、工時、計算、成本與估算算式是否相稱？ | 說明的規模超出資源卻無處置；相稱的簡單方法與縮減方案可以充分 | S02、S04；ML 適用時 S07 |
| D08 unknown 與依賴 | P9／resource-fit、feasibility | 必要條件在哪一步前，以何證據釐清？責任、trigger、fallback 是否有效？ | 將 unknown 寫成 available；誠實列出條件、時點與 fallback 的草案仍有規劃價值 | S02、S04；精確時點沿用本地 1.1 |
| D09 最小交付與停止 | P9／feasibility | 最小產物能回答哪個核心 SQ？里程碑、critical path、縮減／停止／回 Stage 2 的理由是否合理？ | DAG 合法卻沒有有用最小產物；有限範圍的否定或不可識別結論也可有貢獻 | S02、S04、S05 |

九項是診斷提示，不新增九個 criterion、分母、gate 或正式總分。
五軸語義 review 仍為 `stage3-semantic-v1`，狀態為 adequate／needs-revision／unknown；
不能將 adequate 自動換成 2，或將 unknown 換成 0。
新的 guidance hash 另行綁定，不冒稱舊 semantic rubric hash 已涵蓋此文件。

## 研究型態的適用性

以下是開放的示例，可混用；不構成研究型態白名單。評審先說明必要性，再判斷設計。

| 型態 | 可接受的證據／設計與可信度規格 | 避免錯誤要求 |
|---|---|---|
| 受控實證／實驗 | 測量、合適比較、取樣、誤差與相應分析；必要時估樣本與功效 | 不強制 LLM、GPU 或特定 benchmark |
| 觀察／描述／關聯 | 研究人口與分析單位、涵蓋、測量、偏誤；因果主張才需要相應識別 | 不因沒有因果估計而否定合法描述問題 |
| 模擬／機制／數值 | 假設、參數／邊界、數值與靈敏度檢查；隨機或確定性程序的重建規格 | 不把模擬內部支持當成外部世界已驗證因果 |
| 理論／數學／形式 | 定義、假設、證明義務、一致性、反例與適用範圍 | 不要求資料集、RCT、p-value 或實測效果 |
| 質性／詮釋 | 選樣、脈絡、反思性、編碼／材料與詮釋證據鏈、替代詮釋 | 不強制統計 power、量化效果量或固定編碼程序 |
| 方法／設計／工程 | 目的與條件、合適驗證／比較、失效情境與資源 | ML／LLM 僅在候選需要時啟用相應模組 |

通用核心不要求固定問題數、假說配額、16 週、正向效果、統計顯著或新方法勝出。
對未執行計畫，實際結果保持 not-run／null；評的是能否產生可判讀證據的設計。[S04–S07]

## P7–P9 錨點與狀態

正式 criterion 來源為 `evals/rubrics/stage23-general.v1.json` 的 `stage23-general-v1`。
每個面向一個 0／1／2 或 null，不加總、不平均，不重算 P1–P6 或既有研究。

| 面向／criterion | 0：有證據的必要缺陷 | 1：部分充分 | 2：充分的規劃依據 |
|---|---|---|---|
| P7／P7V1.QUESTION_DESIGN | 設計缺失、偏題或不能回答必要問題 | 關鍵問題、材料／測量或設計論證尚不完整 | 原問題、證據與適合該主張的設計有可核對論證 |
| P8／P8V1.EVIDENCE_INTERPRETATION | 把取得當適配、推論超界或捏造未執行結果 | 材料適配、分析／不確定性或判讀規格不完整 | 證據條件、分析與支持／反駁／不確定判讀均有合理規格 |
| P9／P9V1.FEASIBILITY | 隱瞞依賴、捏造許可或最小產物不能回答核心問題 | 規模、相依或停止條件尚未處理充分 | 有設計依據的估算、替代、blocker、停止與有用最小交付；權限分開 |

本表幫助解讀，原 catalog 的完整錨點及身份保持不變。

- `scored`：以已知證據評 0、1 或 2；每個面向交代全部原 SQ 的適用性、理由與計畫位置。存在可觀察的必要缺漏可評低分，不能用 unknown 掩蓋。
- `unverifiable`：必要證據不可得或缺適當專業，score=null，列 missing evidence、原因及受影響範圍。誠實 unknown 本身不等於已證實缺陷。
- `grader_error`：timeout、429、格式／技術或其他評審失敗，score=null，保留原失敗及原因。它不等於研究 0 分，也不冒稱已完成科學審查。
- `not-applicable`：只用於有理由的診斷／方法條件，不把整個 P7、P8 或 P9 免評。必要但不可得仍是 unknown。

2 分代表符合規劃判準，不代表資料已可用、研究已完成或文章必定有貢獻。
結構完整率、評審一致性與科學有效性分開；尚無本地校準、可靠性或 A/B 改善數值。[S01、S02、S08–S10]

## Unknown 的處置時點與既有權限

沿用 opt-in plan schema 1.1 的 condition ID、disposition、deadline、evidence、owner、trigger、fallback。
不要在 evaluator 另建一套條件解決 gate。1.0 計畫仍按原契約處理，不回填成 1.1。

| 條件意義 | 既有最遲處置步驟 |
|---|---|
| 問題含義／範圍 | question-definition |
| 材料適配 | material-design |
| 方法假設 | method-design |
| 驗證參考 | validation-design |
| 規模與可行性 | resource-planning |
| 其他必要條件 | plan-review |
| 資料／工具使用條件 | before-access-use |

評審查的是「處置證據與 fallback 是否能解決問題」；僅填了文字不算解決。
將條件留待必要步驟前確認，可以形成有用草案；相關 ready 狀態仍由既有邏輯決定。
評分輸出不解除 blocker、不認證真人、不確認計畫，也不授予資料使用或實驗許可。

## 離線接線與失敗保存

`evaluation-prepare` 由既有計畫 package 與外部 manifest hash 準備可審查 view，
另綁定 catalog、guidance、計畫、intake 與問題身份。
`evaluation-record` 驗證外部 request／judgment hashes，保存原始 judgment 及逐面向結果。
這是記錄外部評審的工程接線，沒有 provider、native judge、自動重試或校準／A/B runner。

輸出必須在 Git checkout 外，寫入新路徑並受既有大小限制。
遇到已存在輸出先核對已保存 bytes／hash；不得覆寫成功或失敗。輸入改變時用新版本路徑。
hash 不符、格式錯誤或中斷時保留原輸入／錯誤，明示未完成；不能把不完整檔案當成功恢復。
429／timeout 保留為 grader_error；本接線不呼叫服務，因此不藉改模型、等待或迴圈偷偷重跑。
未來若要呼叫評審，須另有明確授權、界限與凍結設定；本輪不執行。

## 來源與簡報引用

下列資料沿用保存的定點 primary methods／official framework 查核；不是窮盡搜尋，
也沒有將原文全部全文下載。來源支持構念或程序，九項分組與本地錨點仍是改編。

| ID／來源 | 版本、方法位置與本地用途 | 限制 |
|---|---|---|
| S01 Huang et al., *Idea2Plan: Exploring AI-Powered Research Planning* | [2025 arXiv v1](https://arxiv.org/html/2510.24891v1)，§3.2、3.5–3.6、4.3、6、App. B/C；逐題 rubric、專家核對與校準 | preprint；回溯 ICML 案例，覆蓋／長度不能代表普遍科學有效性 |
| S02 Goel et al., *Training AI Co-Scientists Using Rubric Rewards* | [ICML 2026／PMLR 306 metadata](https://proceedings.mlr.press/v306/goel26b.html)；實際方法查核用 [2025 arXiv v1](https://arxiv.org/html/2512.23707v1) §2.2、App. A.1 Table 4、C.6–C.7、§6；要求、soundness、清楚度與可行性 | 出版 PDF 與 preprint 文字同一性 unknown；計畫評判不是實作成功；自評可能偏好複雜度 |
| S03 Wang et al., *PaperGym: Rubric-Centered Evolution for Research-Plan Generation* | [2026 arXiv v1](https://arxiv.org/html/2608.31119v1)，§3.1.2；通用與 instance-specific 判準及洩漏注意事項 | preprint；通用 rubric 沿用 S02，不是獨立效度驗證；不照抄參考答案 |
| S04 NIH, *Simplified Peer Review Framework* | [官方框架](https://www.grants.nih.gov/policy-and-compliance/policy-topics/peer-review/simplifying-review/framework)，Factors 1–3，適用 due dates 自 2025-01-25；rigor／feasibility／resources | 生醫補助背景；不搬用 NIH 1–9 分數或強制臨床設計 |
| S05 Center for Open Science, *Registered Reports* | [官方說明](https://www.cos.io/initiatives/registered-reports)，Details & Workflow、Design and Analysis；結果未知前審查設計與結果中立條件 | 期刊程序的 Stage 1／2 與本系統編號不同；不是自動通過尺度 |
| S06 COS／TOP Advisory Board, *TOP 2025 Guidelines* | [現行官方表](https://www.cos.io/initiatives/top-guidelines)，七項 Research Practices 與 Verification Practices；protocol／analysis／材料及重現規格 | 透明度不等於已重現；不混入 2015 八項舊表；連結解說文章未全文核對 |
| S07 NeurIPS, *Paper Checklist Guidelines* | [官方指南](https://neurips.cc/public/guides/PaperChecklist)，Claims、Limitations、Reproducibility、Settings、Significance、Compute；僅 ML 適用模組 | 完成後論文清單作事前改編；其 NA 可混不可得與不適用，本地分開 |
| S08 Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* | [2023／arXiv v4](https://arxiv.org/html/2306.05685v4)，§3.3–3.4、4、App. D；次序、篇幅、自我偏好及盲化注意事項 | 聊天偏好相符不能外推科學正確性；不同模型家族不保證獨立 |
| S09 Liu et al., *G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment* | [EMNLP 2023](https://aclanthology.org/2023.emnlp-main.153/)，§2–4、Limitations；criterion-specific 表單與人類對照 | 摘要／對話相關性不是科學計畫效度；不要求隱藏推理鏈 |
| S10 Artstein & Poesio, *Inter-Coder Agreement for Computational Linguistics* | [Computational Linguistics 34(4), 2008](https://aclanthology.org/J08-4004/)，§2.6；尺度、權重、缺值及 rater 假設 | agreement 不等於正確性；未選用通用 alpha／kappa 通過門檻 |

S11 Nosek 2018、S12 Koo & Li 2016（含 2017 erratum）、S13 Testing Standards 2014、
S14 Kane 2013 保留在原 source ledger 作延伸閱讀，全文存取／核對受限；不作本版具體分數規則依據。
未來簡報應並列「文獻支持的改編」「工程測試」「尚待專家校準與跨案例效度證據」，不將它們混稱已驗證 rubric。
