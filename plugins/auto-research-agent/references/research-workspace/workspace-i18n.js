/* Presentation only. Never translate or mutate canonical research records. */
(() => {
  "use strict";
  const rows = `
Research Workspace|研究工作台|研究工作臺
Language|界面语言|介面語言
Research stages|研究阶段|研究階段
Content views|内容视图|內容檢視
Research pipeline|研究流程|研究流程
Offline interaction reference|离线交互参考|離線互動參考
Workspace|工作台|工作臺
Stage Nodes|阶段节点|階段節點
Selected Node|当前节点|目前節點
SYNTHETIC DATA · OFFLINE WORKFLOW PROTOTYPE · EXECUTOR NOT CONNECTED|示例数据 · 离线交互原型 · 未连接执行器|示例資料 · 離線互動原型 · 未連線執行器
A readable, traceable editorial desk for research workflows. This page demonstrates information architecture only; every record is synthetic.|按阶段阅读、审阅和追溯研究内容。此页面展示信息结构，所有记录均为示例。|依階段閱讀、審閱與追溯研究內容。此頁面展示資訊結構，所有紀錄均為示例。
Start Research|开始研究|開始研究
Continue Run|继续运行|繼續執行
Local executor is not connected|尚未连接本地执行器|尚未連線本機執行器
Research controls are disabled while the local executor is pending.|连接执行器后才能开始或继续真实研究。|連線執行器後才能開始或繼續實際研究。
Deliverables & Sources|交付与来源|交付與來源
Evaluation & History|评估与历史|評估與歷史
Literature|文献图谱|文獻圖譜
Discussion & Review|对话与审阅|對話與審閱
Your answers and decisions|你的回答与决定|你的回答與決定
This is the place to answer Codex, confirm scope, and review an exact output version. The native session is not connected; text entered here is a page-only draft and disappears on refresh.|在这里回答 Codex、确认范围并审阅具体产物版本。尚未连接原生会话；输入仅为当前页面草稿，刷新即清除。|在這裡回答 Codex、確認範圍並審閱具體產出版本。尚未連線原生工作階段；輸入僅為目前頁面草稿，重新整理即清除。
Question from Codex (synthetic)|Codex 的问题（示例）|Codex 的問題（示例）
Which geography and time range should this research cover? What should be excluded?|本次研究覆盖哪些地区与时间范围？需要排除哪些内容？|本次研究涵蓋哪些地區與時間範圍？需要排除哪些內容？
Reply to Codex|在这里回答或提问|在這裡回答或提問
Scope to confirm|待确认的研究范围|待確認的研究範圍
Review notes|审阅意见|審閱意見
Review target: no run, attempt, request ID, or output hash is bound.|审阅对象：尚未绑定运行、尝试、请求 ID 或产物哈希。|審閱對象：尚未綁定執行、嘗試、請求 ID 或產出雜湊。
Send answer|提交回答|提交回答
Confirm scope|确认范围|確認範圍
Accept reviewed version|通过当前版本|通過目前版本
Request changes|退回修改|退回修改
Connecting the native adapter must bind each answer or approval to the displayed request and version. Confirming scope must never silently start a run or the next stage.|接入原生执行器后，回答和审批必须绑定当前显示的请求与版本；确认范围不会自动运行或进入下一阶段。|整合原生執行器後，回答與核准必須綁定目前顯示的請求與版本；確認範圍不會自動執行或進入下一階段。
Evidence|文献与证据|文獻與證據
Comparison & Directions|比较与方向|比較與方向
Study Design|设计与可行性|設計與可行性
Execution|实验执行|實驗執行
Analysis|分析与图表|分析與圖表
Writing & Submission|写作与投稿|寫作與投稿
Scope & Geography|范围与地区|範圍與地區
Keywords & Concepts|关键词与概念|關鍵字與概念
Search & Reading|检索与阅读|檢索與閱讀
Core, Classic & Closest-Work Roles|核心、经典与最接近研究|核心、經典與最接近研究
Claim Checks|主张核验|主張核驗
Coverage & Stop Decision|覆盖与停止判断|涵蓋與停止判斷
Deliverable Package|交付包|交付套件
P1–P3 Evaluation|P1–P3 评估|P1–P3 評估
Import Stage 1|导入 Stage 1|匯入 Stage 1
Common Comparison|统一比较|統一比較
Open Ideation|开放构思|開放構思
Capture Candidate Records|保存候选方向|儲存候選方向
Independent Challenge & Feasibility|独立质疑与可行性|獨立質疑與可行性
Revise, Recheck, Park or Reject|修改、复核、搁置或拒绝|修改、複核、擱置或拒絕
Selection Package|方向选择包|方向選擇套件
P4–P6 Evaluation|P4–P6 评估|P4–P6 評估
User Decision & Stage 3 Handoff|人工选择与 Stage 3 交接|人工選擇與 Stage 3 交接
Direction Input|方向输入|方向輸入
Question & Method Design|问题与方法设计|問題與方法設計
Validation & Delivery Spec|验证与交付要求|驗證與交付要求
Design Package Input|设计包输入|設計套件輸入
Run & Observe|执行与观察|執行與觀察
Reproducible Output|可复现产物|可重現產出
Results & Quality Input|结果与质量输入|結果與品質輸入
Analysis & Robustness|分析与稳健性|分析與穩健性
Findings & Limits|发现与限制|發現與限制
Approved Materials|已审阅材料|已審閱材料
Argument & Citation Writing|论证与引用写作|論證與引用寫作
Manuscript & Submission Deliverables|论文与投稿材料|論文與投稿材料
Build a traceable foundation of literature and claims.|建立可追溯的文献与主张基础。|建立可追溯的文獻與主張基礎。
Compare research through a shared evidence view and form viable directions.|基于共同的证据视图比较研究，形成可行方向。|依據共同的證據檢視比較研究，形成可行方向。
Turn the selected direction into a testable question, design, and validation plan.|将选定方向转为可验证的问题、设计和验证计划。|將選定方向轉為可驗證的問題、設計與驗證計畫。
Run the approved plan while preserving versions, failures, and resource records.|执行已批准计划，保留版本、失败和资源记录。|執行已核准計畫，保留版本、失敗與資源紀錄。
Turn execution results into bounded, reviewable analysis.|将执行结果整理为边界明确、可审阅的分析。|將執行結果整理為邊界明確、可審閱的分析。
Shape the evidence, methods, results, and limits into an editable manuscript.|将证据、方法、结果与限制整理为可编辑论文。|將證據、方法、結果與限制整理為可編輯論文。
What this node must complete|此节点需要完成什么|此節點需要完成什麼
Input|输入|輸入
Output|输出|輸出
Evidence boundary|证据边界|證據邊界
Status|状态|狀態
Current selection|当前选择|目前選擇
Why blocked|受阻原因|受阻原因
Next action|下一步|下一步
Source reading|查看来源|查看來源
Open plugin README|打开插件说明|開啟外掛說明
Execution is not connected: this stage shows expected inputs, purpose, and outputs only. It does not imply a run or results.|尚未连接执行器：本阶段仅展示预期输入、目的和输出，不代表已执行或有研究结果。|尚未連線執行器：本階段僅展示預期輸入、目的與輸出，不代表已執行或有研究結果。
Every example record is synthetic. No private papers were read, and search results are never promoted automatically into research findings.|所有记录均为示例；未读取私有论文，检索结果不会自动成为研究结论。|所有紀錄均為示例；未讀取私人論文，檢索結果不會自動成為研究結論。
Read-only specification · Execution not connected|只读要求 · 未连接执行器|唯讀要求 · 未連線執行器
Interaction reference · No dispatch or storage|交互参考 · 不派发任务、不保存研究数据|互動參考 · 不派發任務、不儲存研究資料
The plugin status is available through a safe, known relative path. Other source controls stay disabled to prevent links to unverified locations.|插件说明链接指向已知仓库路径。尚未绑定来源的按钮保持禁用。|外掛說明連結指向已知儲存庫路徑。尚未綁定來源的按鈕保持停用。
Deliverables & Sources / Synthetic Example|交付与来源 / 示例|交付與來源 / 示例
This view shows expected deliverables and source bindings. It contains no paper files and cannot download sources or export canonical deliverables.|此视图展示预期交付和来源绑定，不含论文文件，不能下载来源或导出正式交付。|此檢視展示預期交付與來源綁定，不含論文檔案，不能下載來源或匯出正式交付。
Node output|节点输出|節點輸出
Source status|来源状态|來源狀態
Version binding|版本绑定|版本綁定
Private boundary|私有数据边界|私人資料邊界
Synthetic source S-A · metadata-only · never presented as full text|示例来源 S-A · 仅元数据 · 不代表全文|示例來源 S-A · 僅中繼資料 · 不代表全文
work-demo / version-demo · synthetic labels|work-demo / version-demo · 示例标识|work-demo / version-demo · 示例標識
Private sources stay outside Git; this page embeds no full text or credentials|私有来源保存在 Git 之外；页面不含全文或凭证|私人來源儲存在 Git 之外；頁面不含全文或憑證
Source control disabled: no verified local deliverable package is bound.|来源操作已禁用：尚未绑定经验证的本地交付包。|來源操作已停用：尚未綁定經驗證的本機交付套件。
View Source File|查看来源文件|查看來源檔案
No local source is bound|尚未绑定本地来源|尚未綁定本機來源
Evaluation & History / Synthetic Example|评估与历史 / 示例|評估與歷史 / 示例
The history selector binds an explicit attempt and version independently of the topic name. Switching it never reruns research.|历史选择器绑定具体尝试和版本，不依赖主题名称；切换不会重新运行研究。|歷史選擇器綁定具體嘗試與版本，不依賴主題名稱；切換不會重新執行研究。
Select an explicit attempt and version|选择具体尝试与版本|選擇具體嘗試與版本
Unknown|未知|未知
Required evidence is unavailable, so no score is assigned.|所需证据不可用，因此不评分。|所需證據不可用，因此不評分。
Evaluator failure|评估器失败|評估器失敗
The evaluation process or parser failed. This is not a low score for the research under review.|评估过程或解析器失败，不代表被审研究获得低分。|評估過程或剖析器失敗，不代表被審研究獲得低分。
Observed low score|有证据的低分|有證據的低分
Evidence is sufficient, and a rubric-defined deficiency was observed.|证据充分，发现了量规中定义的缺陷。|證據充分，發現了量規中定義的缺陷。
P-metric status|P 指标状态|P 指標狀態
No approved handoff exists from the prior stage, and the local executor is not connected.|尚无上一阶段批准的交接，且未连接本地执行器。|尚無上一階段核准的交接，且未連線本機執行器。
This is an offline prototype with no research executor or real sources bound.|当前为离线原型，未绑定研究执行器或真实来源。|目前為離線原型，未綁定研究執行器或真實來源。
Complete and explicitly approve the versioned handoff from the prior stage.|完成并明确批准上一阶段的版本化交接。|完成並明確核准上一階段的版本化交接。
Connect the local executor, then let the user start the real workflow.|连接本地执行器，再由用户启动真实工作流。|連線本機執行器，再由使用者啟動實際工作流程。
Preserve the original research direction, geographic choice, and open decisions without treating a suggestion as an accepted scope.|保留原始研究方向、地区选择和待定事项；建议不等于已确认范围。|保留原始研究方向、地區選擇與待定事項；建議不等於已確認範圍。
Keep the three roles and their source-based reasons separate; age, prominence, or a similar title establishes none of them automatically.|分别记录三种角色及来源依据；年代、名气或相似标题都不能自动确定角色。|分別記錄三種角色及來源依據；年代、名氣或相似標題都不能自動確定角色。
Classify each claim as supported, partial, contradicted, or unverifiable.|将每项主张标记为支持、部分支持、矛盾或无法验证。|將每項主張標記為支持、部分支持、矛盾或無法驗證。
Check the recent sweep, closest work, unresolved needs, and stopping rationale without substituting paper counts for sufficiency.|核查近期检索、最接近研究、未解决需求和停止依据，不以论文数量替代充分性。|核查近期檢索、最接近研究、未解決需求與停止依據，不以論文數量替代充分性。
Independently check closest work, materials, answerability, validation paths, and resource dependencies.|独立核查最接近研究、材料、可回答性、验证路径和资源依赖。|獨立核查最接近研究、材料、可回答性、驗證路徑與資源依賴。
Preserve evidence-based reasons and release conditions for revision, rechecking, parking, or rejection.|保留修改、复核、搁置或拒绝的证据依据与恢复条件。|保留修改、複核、擱置或拒絕的證據依據與恢復條件。
Record the human choice and hand the selected direction and unresolved items to the next stage.|记录人工选择，将选定方向与待解决事项交接到下一阶段。|記錄人工選擇，將選定方向與待解決事項交接到下一階段。
Complete this node with clear inputs, decision reasons, and versioned outputs while preserving unknowns and failures.|以明确输入、决策理由和版本化输出完成本节点，保留未知与失败。|以明確輸入、決策理由與版本化輸出完成本節點，保留未知與失敗。
Approved Stage 1 deliverable with an external hash|已批准且绑定外部哈希的 Stage 1 交付|已核准且綁定外部雜湊的 Stage 1 交付
Versioned evidence view and frozen rubric|版本化证据视图与冻结量规|版本化證據檢視與凍結量規
Approved, reproducible handoff package from the prior stage|上一阶段已批准、可复现的交接包|上一階段已核准、可重現的交接套件
Synthetic research brief, example source records, and open questions|示例研究简报、来源记录与待回答问题|示例研究簡報、來源紀錄與待回答問題
Separate P-metric states: all currently unscored|分开记录 P 指标状态：当前均未评分|分開記錄 P 指標狀態：目前均未評分
Read-only output specification; no execution result exists|只读输出要求；尚无执行结果|唯讀輸出要求；尚無執行結果
Versioned choice or delivery package with source mapping|含来源映射的版本化选择或交付包|含來源對應的版本化選擇或交付套件
Synthetic node record, rationale, source status, and next action|示例节点记录、理由、来源状态与下一步|示例節點紀錄、理由、來源狀態與下一步
Offline interaction reference · Refreshing resets this prototype only. It cannot execute research or modify canonical records; only synthetic bibliography export is available.|离线交互参考 · 刷新重置原型。无法执行研究或修改正式记录；仅支持示例参考文献导出。|離線互動參考 · 重新整理重設原型。無法執行研究或修改正式紀錄；僅支援示例參考文獻匯出。
Stage 1 / Synthetic Literature Reference|Stage 1 / 示例文献|Stage 1 / 示例文獻
Local Literature Graph|本地文献图谱|本機文獻圖譜
Browse a small Obsidian-like graph and complete bibliographic list. Edges show recorded assignments only; this view does not assert similarity, citation, evidence support, coverage, or quality.|浏览文献图谱与完整书目信息。连线仅表示记录的关键词或角色分配，不表示相似度、引用、证据支持、覆盖或质量。|瀏覽文獻圖譜與完整書目資訊。連線僅表示記錄的關鍵字或角色分配，不表示相似度、引用、證據支持、涵蓋或品質。
Title, author, journal, ID|标题、作者、期刊、ID|標題、作者、期刊、ID
All keywords|全部关键词|全部關鍵字
All roles|全部角色|全部角色
Filter literature|筛选文献|篩選文獻
Keyword|关键词|關鍵字
Recorded role|已记录角色|已記錄角色
Export visible .bib (synthetic)|导出可见文献 .bib（示例）|匯出可見文獻 .bib（示例）
Graph view|图谱视图|圖譜檢視
Zoom −|缩小 −|縮小 −
Zoom +|放大 +|放大 +
Reset|重置|重設
Scrollable literature graph|可滚动文献图谱|可捲動文獻圖譜
Synthetic literature graph of papers, keywords, and recorded roles|论文、关键词及角色的示例图谱|論文、關鍵字與角色的示例圖譜
Select a paper to inspect its record. On narrow screens, scroll the graph horizontally.|选择文献查看记录。窄屏可以横向滚动图谱。|選擇文獻查看紀錄。窄螢幕可以橫向捲動圖譜。
Paper|文献|文獻
Lines mean an explicit keyword or role assignment. No paper-to-paper citation edges are recorded.|连线表示明确的关键词或角色分配；未记录文献之间的引用关系。|連線表示明確的關鍵字或角色分配；未記錄文獻之間的引用關係。
Bibliographic list|文献列表|文獻清單
Selected paper|当前文献|目前文獻
Complete metadata|完整元数据|完整中繼資料
Scrollable complete bibliographic metadata|可滚动完整书目元数据|可捲動完整書目中繼資料
Synthetic UI demo only. Every source is metadata-only; no record represents full-text access. BibTeX export is separate from the canonical research deliverable exporter.|仅用于界面演示。所有来源仅含元数据，不代表已获取全文；示例 BibTeX 导出与正式研究交付导出分开。|僅用於介面示範。所有來源僅含中繼資料，不代表已取得全文；示例 BibTeX 匯出與正式研究交付匯出分開。
No synthetic records match these filters.|没有匹配的示例记录。|沒有符合的示例紀錄。
Select a visible paper to inspect its metadata and recorded role basis.|选择可见文献以检查元数据及角色依据。|選擇可見文獻以檢查中繼資料與角色依據。
Work ID|研究条目 ID|研究條目 ID
Authors|作者|作者
Year|年份|年份
Journal|期刊|期刊
Volume|卷|卷
Issue|期|期
Pages|页码|頁碼
Source|来源|來源
Keywords|关键词|關鍵字
Title|标题|標題
Recorded role basis|角色分配依据|角色分配依據
Not recorded|未记录|未記錄
Recorded paper-to-keyword and paper-to-role assignments|已记录的文献与关键词、角色关系|已記錄的文獻與關鍵字、角色關係
`;
  const catalog = new Map(rows.trim().split("\n").map(row => { const [key, ...values] = row.split("|"); return [key, values]; }));
  let locale = "zh-Hans";
  try { const saved = localStorage.getItem("research-workspace-language"); if (["en", "zh-Hans", "zh-Hant"].includes(saved)) locale = saved; } catch { /* Storage is optional for offline files. */ }
  const originals = new WeakMap();
  const attributes = new WeakMap();
  function t(raw) {
    const text = String(raw).trim().replace(/\s+/g, " ");
    if (locale === "en") return raw;
    const index = locale === "zh-Hant" ? 1 : 0;
    if (catalog.has(text)) return catalog.get(text)[index];
    // These templates contain presentation identifiers, never editable research text.
    if (/^Stage [1-6] [\/·] /.test(text)) return text.replace(/^(Stage [1-6] [\/·] )(.*)$/, (_, a, b) => a + t(b));
    if (/^Stage [1-6] Delivery Interface$/.test(text)) return text.slice(0, 7) + (index ? " 交付介面" : " 交付界面");
    if (/^Stage [1-6] Explicit Version View$/.test(text)) return text.slice(0, 7) + (index ? " 版本檢視" : " 版本视图");
    if (/^Attempt [ABC] · Version v[012] \(synthetic\)$/.test(text)) return text.replace("Attempt", "尝试").replace("Version", "版本").replace("(synthetic)", "（示例）").replace("尝试", index ? "嘗試" : "尝试");
    if (text.startsWith("Currently bound: ")) return text.replace(/^Currently bound: (.+)\. Switching changes this display only\.$/, (_, attempt) => (index ? "目前綁定：" : "当前绑定：") + t(attempt) + (index ? "。切換僅改變顯示。" : "。切换仅改变显示。"));
    if (/^\d of \d synthetic records visible$/.test(text)) return text.replace(/^(\d) of (\d).*$/, index ? "顯示 $1 / $2 筆示例紀錄" : "显示 $1 / $2 条示例记录");
    if (text.includes(": unscored. This prototype")) return text.split(":")[0].replace("Reserved evaluation", index ? "預留評估" : "预留评估") + (index ? "：未評分。原型不產生研究分數，介面完整度不代表研究品質改善。" : "：未评分。原型不产生研究分数，界面完整度不代表研究质量改善。");
    return raw;
  }
  function apply(root = document.body) {
    document.documentElement.lang = locale;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement.closest("script, style, textarea, [translate='no']")) continue;
      if (!originals.has(node)) originals.set(node, node.nodeValue);
      const translated = t(originals.get(node));
      if (node.nodeValue !== translated) node.nodeValue = translated;
    }
    root.querySelectorAll("[title], [aria-label], [placeholder]").forEach(el => {
      if (!attributes.has(el)) attributes.set(el, Object.fromEntries(["title", "aria-label", "placeholder"].filter(key => el.hasAttribute(key)).map(key => [key, el.getAttribute(key)])));
      for (const [key, value] of Object.entries(attributes.get(el))) el.setAttribute(key, t(value));
    });
  }
  window.WorkspaceI18n = { apply, t, get locale() { return locale; }, set(value) { if (!["en", "zh-Hans", "zh-Hant"].includes(value)) return; locale = value; try { localStorage.setItem("research-workspace-language", value); } catch {} apply(); } };
})();
