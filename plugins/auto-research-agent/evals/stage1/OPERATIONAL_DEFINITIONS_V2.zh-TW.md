# Stage 1 雙向耦合案例：六群指標 v2

本文件只適用於 `aging-sk-bidirectional-development-v2`。舊四群 benchmark、
`metric-spec.v1.json` 與 run01 保持原義，不回頭改分。正式判斷仍以凍結的
`aging-bidirectional-rubric-v1`、criterion catalog 和 private holdout 為準。

## 我們到底量什麼

| 指標 | 白話問題 | 可重算的數字 | 0–2 判斷 |
|---|---|---|---|
| P1 Evidence Reliability | 引用的文章與它支持的話是否真的對得上？ | 書目正確／已查、連結正確／已查、central claim 的 supported／partial／contradicted／unverifiable 數、原文 locator 數、重大錯配數。分母為實際提出的項目；零分母記 `NA`。 | 依 frozen rubric 逐篇、逐 central claim 評分；stage summary 有重大錯誤為 0，中央證據未查全最多 1。 |
| P2 Relevant Coverage | 六塊必要拼圖是否真的找到證據？ | 有已核實支援的群數／**6**；core 命中／凍結 core 總數；must-have 命中／凍結 must-have 總數；近期來源數及最新確認年份；closest-work 搜尋是否完成。 | 整組去重文獻評一次；不能以篇數多或關鍵字命中代替六群與 closest-work 證據。 |
| P3 Auditability | 另一人能否照紀錄重建研究過程？ | 有 discovery path 的作品／列出作品、有 locator 的 central claim／central claim、有理由與來源的決定／全部決定、有版本與存取日期的 included work／included work；搜尋動作和失敗狀態另列。 | 整個 run 評一次；關鍵搜尋或決定不可重建，或把 429 當零結果，為 0。 |

`unverifiable` 既不是正確也不是錯誤。T 提出的 claim 比 B 多時，分母也跟著增加；
不能以較少主張換取看似較高的正確率。每項皆保留 evidence ID、原文位置與核對狀態。
P1、P2、P3 分開報，不相加；時間、工具、tokens、費用與人類介入另列。

## 私有答案包如何建立

兩位具名人類各自先評候選的 identity、來源版本、證據位置、六群角色、classic 和
decision-critical 資格。只有兩人都給 `include` 的候選可進 `anchors`；一人不同意的
候選放入 `disagreements`，保留雙方初評與排除理由，不交由同一人假扮第三人裁決。
另存完整 candidate screening log。凍結前若六群或六種研究角色缺一，繼續尋找候選，
不能降低標準。兩人分別核准最終 manifest；實際 core／must-have 分母由它計算。

Classic 至少早於 cutoff 五年，field recognition、foundational role、durability
均非零且合計至少 5／6，並有兩項獨立權威證據。Must-have 需兩人均確認 directness=2、
decision impact=2、evidence quality≥1、沒有 equally direct substitute。
新近 closest work 可是 must-have；不能為了讓它變成 core 而假稱已是經典。

`holdout-manifest.v2` 是兩人一致納入契約。v1 的第三位獨立裁決者契約仍供舊資料使用，
兩種 manifest 不能互換或默默升版。私有答案、候選標題、全文與評定紀錄不進 Git，
被測 agent 的環境不得有答案檔讀取路徑。公開程式只保存 schema、規則、版本與 hash。

## 主 A/B 判斷

以相同 prompt、模型、Default mode 和搜尋工具做三對 B／T：B→T、T→B、B→T。
P2、P3 各至少兩對改善且零對退步；P1 零退步；T 不新增 major error；必要的
human audit 全部完成。任何條件不明或資料不完整為 `inconclusive`。這三對只描述
此南韓開發案例的方向和波動，不宣稱統計顯著或跨題目泛化。
