/* Inert evidence browsing. All research text retains its original language. */
(() => {
  "use strict";
  const payload = window.WORKSPACE_VIEW, model = window.AtlasModel;
  const content = document.getElementById("atlas-content");
  if (!content || !payload?.index || !model) return;
  const index = payload.index, archive = model.papers(payload);
  let papers = archive;
  const colors = ["#397d7c", "#567fa2", "#a48644", "#87729b", "#ad7d77", "#72927d"];
  const words = {
    computedLinks: ["Content similarity (computed)", "内容相近（自动计算）", "內容相近（自動計算）"],
    showAllNames: ["Show all names", "显示全部名称", "顯示全部名稱"],
    sharedTopics: ["Shared research directions", "共同研究方向", "共同研究方向"],
    paperShape: ["Paper", "论文", "論文"],
    topicShape: ["Research direction", "研究方向", "研究方向"],
    methodShape: ["Method", "方法", "方法"],
    sharedMethods: ["Same recorded method labels", "相同方法标签", "相同方法標籤"],
    computedBasis: ["Saved findings and topic labels · computed text cosine", "已保存概要及方向标签 · 计算出的文本余弦相似度", "已保存概要及方向標籤 · 計算出的文字餘弦相似度"],
    sharedTerms: ["Shared normalized terms", "共有词（规范化后）", "共有詞（正規化後）"],
    moreRelated: ["More related papers", "更多相关论文", "更多相關論文"],
    noRelated: ["No recorded or qualifying computed paper links in this collection.", "此文献集中暂无已记录或达到显示条件的计算关联。", "此文獻集中暫無已記錄或達到顯示條件的計算關聯。"],
    overlapLink: ["Shared recorded classification", "已记录分类交集", "已記錄分類交集"],
    spatialHelp: ["Hover or select to reveal related names · drag to rotate · scroll to zoom · select the same node to clear focus", "悬停或点击显示相关名称 · 拖动旋转 · 滚轮缩放 · 再次点击同一节点取消选中", "懸停或點選顯示相關名稱 · 拖曳旋轉 · 滾輪縮放 · 再次點選同一節點取消選取"],
    spatialBasis: ["Solid lines show recorded memberships or intersections. Dashed method links and dotted computed content links have separate meanings. Distance serves layout; content cosine is not scientific evidence strength.", "实线表示已记录的归属或交集；虚线表示方法归属，点线表示自动计算的内容相近。距离用于排版；内容余弦相似度不代表科学证据强弱。", "實線表示已記錄的歸屬或交集；虛線表示方法歸屬，點線表示自動計算的內容相近。距離用於排版；內容餘弦相似度不代表科學證據強弱。"],
    spatialUnavailable: ["This browser could not initialize the 3D view. Paper details and the library remain available.", "此浏览器未能初始化 3D 视图。论文详情和文献库仍可使用。", "此瀏覽器未能初始化 3D 檢視。論文詳情及文獻庫仍可使用。"],
    planarFallback: ["Use the planar fallback", "使用平面备用视图", "使用平面備用檢視"],
    dimension: ["Comparison field", "比较维度", "比較維度"],
    stages: [["Literature & evidence", "Comparison & directions", "Design & feasibility", "Experiment execution", "Analysis & figures", "Writing & submission"], ["文献与证据", "比较与研究方向", "设计与可行性", "实验执行", "分析与图表", "写作与投稿"], ["文獻與證據", "比較與研究方向", "設計與可行性", "實驗執行", "分析與圖表", "寫作與投稿"]],
    language: ["Language", "界面语言", "介面語言"],
    original: ["Original workspace · session, scope & review", "原工作台 · 会话、范围与审阅", "原工作臺 · 會話、範圍與審閱"],
    readOnly: ["Read-only companion · execution state unchanged", "只读图谱 · 执行状态保持不变", "唯讀圖譜 · 執行狀態保持不變"],
    library: ["Whole library", "完整文献库", "完整文獻庫"],
    working: ["Working collection", "工作文献集", "工作文獻集"],
    archive: ["Screening archive · all recorded versions", "筛选档案 · 全部已记录版本", "篩選檔案 · 全部已記錄版本"],
    archiveNote: ["Counts refer to canonical paper versions. Broader search hits remain in the original search documents below, without invented identities or rankings.", "篇数对应规范论文版本。更广的检索命中保留在下方原始检索文档中，不补造身份或排名。", "篇數對應規範論文版本。更廣的搜尋命中保留在下方原始搜尋文件中，不補造身分或排名。"],
    noIncluded: ["No formally included records yet. The working view shows pending records; historical screening decisions remain separate.", "目前没有正式纳入记录。工作视图显示待审记录；历史筛选决定单独保留。", "目前沒有正式納入紀錄。工作檢視顯示待審紀錄；歷史篩選決定分開保留。"],
    archiveFallback: ["No included or pending collection is recorded. Showing the complete screening archive.", "没有已纳入或待审文献集记录。显示完整筛选档案。", "沒有已納入或待審文獻集紀錄。顯示完整篩選檔案。"],
    sorting: ["Order", "排序", "排序"],
    originalOrder: ["Recorded order", "原记录顺序", "原紀錄順序"],
    titleOrder: ["Title", "按标题", "依標題"],
    yearOrder: ["Year (newest first)", "年份（由新到旧）", "年份（由新到舊）"],
    relevanceOrder: ["Relevance rank: not recorded", "相关性排名：未记录", "相關性排名：未記錄"],
    relevance: ["Recorded relevance", "已记录相关性", "已記錄相關性"],
    topics: ["Recorded directions", "已记录研究分类", "已記錄研究分類"],
    methods: ["Recorded methods", "已记录方法", "已記錄方法"],
    unknown: ["Unknown", "未知", "未知"],
    unclassified: ["Unclassified", "未分类", "未分類"],
    graphNote: ["Links show recorded label membership or exact set intersections, not citations, coverage or evidence quality. Counts may overlap.", "连线表示已记录标签的归属或集合交集，不代表引用关系、覆盖程度或证据质量。分类篇数可重叠。", "連線表示已記錄標籤的歸屬或集合交集，不代表引用關係、涵蓋程度或證據品質。分類篇數可重疊。"],
    localNote: ["Distance = 95 + 90 × (1 − method-label Jaccard). Label overlap only; evidence strength remains separate. At most 6 representative neighbors are drawn; every neighbor stays in the paginated list.", "距离 = 95 + 90 ×（1 − 方法标签 Jaccard）。仅表示标签交集；证据强弱单独保留。图中最多显示 6 个代表邻居，全部关联论文保留在分页列表。", "距離 = 95 + 90 ×（1 − 方法標籤 Jaccard）。僅表示標籤交集；證據強弱分開保留。圖中最多顯示 6 個代表鄰居，全部關聯論文保留在分頁清單。"],
    noRelations: ["No shared recorded method labels. No similarity is inferred from prose.", "没有共用的已记录方法标签；不从描述文字推断相似度。", "沒有共用的已記錄方法標籤；不從描述文字推斷相似度。"],
    related: ["Related papers", "关联论文", "關聯論文"],
    detail: ["Paper detail", "论文详情", "論文詳情"],
    records: ["records", "篇记录", "篇紀錄"],
    shared: ["Shared membership", "共同归属", "共同歸屬"],
    allGroups: ["All groups", "全部分类", "全部分類"],
    previous: ["Previous", "上一页", "上一頁"],
    next: ["Next", "下一页", "下一頁"],
    of: ["of", "/", "/"],
    search: ["Search recorded text", "检索已记录文字", "搜尋已記錄文字"],
    status: ["Selection status", "文献筛选状态", "文獻篩選狀態"],
    all: ["All", "全部", "全部"],
    included: ["Included", "已纳入", "已納入"],
    pending: ["Pending", "待审", "待審"],
    excluded: ["Excluded", "已排除", "已排除"],
    unbound: ["Unbound", "未绑定", "未綁定"],
    findings: ["Recorded findings", "已记录论文概要", "已記錄論文概要"],
    fields: [["Question", "Data", "Method", "Main findings", "Limitations", "Relevance", "Transferability"], ["研究问题", "数据", "方法", "主要发现", "限制", "相关性", "可迁移性"], ["研究問題", "資料", "方法", "主要發現", "限制", "相關性", "可遷移性"]],
    access: ["Access & source versions", "访问路径与来源版本", "存取路徑與來源版本"],
    publicLink: ["Recorded public URL", "已记录公开网址", "已記錄公開網址"],
    note: ["Open complete Markdown note", "打开完整 Markdown 笔记", "開啟完整 Markdown 筆記"],
    savedSource: ["Open bound saved source", "打开已绑定的保存来源", "開啟已綁定的儲存來源"],
    ledger: ["Screening decisions & history", "筛选决定与历史", "篩選決定與歷史"],
    discovery: ["Discovery count / first result / repeat searches", "发现次数／首次结果位置／重复检索", "發現次數／首次結果位置／重複檢索"],
    discoveryNote: ["Decision rows are not search attempts. Missing discovery receipts remain Unknown.", "筛选决定不等于检索尝试。缺失的发现回执保持未知。", "篩選決定不等於檢索嘗試。缺少的發現回執保持未知。"],
    sources: ["Sources & reading attempts", "来源与阅读尝试", "來源與閱讀嘗試"],
    claims: ["Claims & evidence relations", "主张与证据关系", "主張與證據關係"],
    provenance: ["Identity & provenance", "身份与溯源", "身分與溯源"],
    raw: ["Complete original record", "完整原始记录", "完整原始紀錄"],
    searchRecords: ["Original search documents", "原始检索文档", "原始檢索文件"],
    exports: ["Canonical files", "规范输出文件", "規範輸出檔案"],
    bib: ["Complete bibliography", "完整参考文献", "完整參考文獻"],
    screeningBib: ["Screening bibliography", "完整筛选参考文献", "完整篩選參考文獻"],
    includedBib: ["Included bibliography", "纳入文献参考文献", "納入文獻參考文獻"],
    directionSets: ["Direction sets", "方向集合", "方向集合"],
    comparison: ["Paper comparison", "论文比较", "論文比較"],
    candidates: ["Candidate routes & review", "候选路线与审阅", "候選路線與審閱"],
    setNote: ["Sets browse recorded classifications. They do not create candidate directions or establish comparable scientific results.", "集合用于浏览已记录分类，不生成候选研究方向，也不证明科研结果可比较。", "集合用於瀏覽已記錄分類，不產生候選研究方向，也不證明研究結果可比較。"],
    compareNote: ["Selection and pagination only change this view. Compare recorded conditions and missing fields before comparing outcomes; no performance ranking is inferred.", "选择和分页仅改变显示。比较结果前，先核对已记录条件与缺失字段；不推断性能排名。", "選擇與分頁僅改變顯示。比較結果前，先核對已記錄條件與缺少欄位；不推斷效能排名。"],
    selected: ["Selected", "已选", "已選"],
    clear: ["Clear selection", "清空选择", "清空選擇"],
    report: ["Original verified Stage 2 report & evaluation", "原始已验证 Stage 2 报告与评估", "原始已驗證 Stage 2 報告與評估"],
    assessment: ["Bound assessment status", "已绑定评估状态", "已綁定評估狀態"],
    evaluationStatus: ["Evaluation status", "评估状态", "評估狀態"],
    recordedScores: ["Recorded scores", "已记录分数", "已記錄分數"],
    provisional: ["provisional", "暂定", "暫定"],
    assessed: ["criteria assessed", "已评估判据", "已評估判準"],
    auditStatus: ["Recorded audit status", "已记录覆核状态", "已記錄覆核狀態"],
    assessmentRecords: ["Complete original assessment, comments & attachment", "完整原始评估、评语与附件", "完整原始評估、評語與附件"],
    importNote: ["Import byte verification preserves the records; it is separate from scientific approval, completed audit and execution authority.", "导入字节验证用于保留记录；科研认可、覆核完成和执行授权分别判断。", "匯入位元組驗證用於保留紀錄；研究認可、覆核完成及執行授權分別判斷。"],
    auditPending: ["Required audit is pending. Recorded scores are provisional.", "必要覆核待完成。已记录分数为暂定结果。", "必要覆核待完成。已記錄分數為暫定結果。"],
    assessmentFailed: ["Technical assessment failed or is incomplete. Missing scores remain Unknown; this does not make the research score zero.", "技术评估失败或未完成。缺失分数保持未知，不将研究记为零分。", "技術評估失敗或未完成。缺少分數保持未知，不將研究記為零分。"],
    missingStage2: ["No verified Stage 2 attachment is present. Stage 1 browsing cannot authorize its import or execution.", "没有已验证的 Stage 2 附件。浏览 Stage 1 不会授权导入或执行。", "沒有已驗證的 Stage 2 附件。瀏覽 Stage 1 不會授權匯入或執行。"],
    missingLiterature: ["This packet has no structured literature rows. Candidate routes and the original assessment remain available.", "此版本未记录结构化文献行。候选路线和原始评估仍可查看。", "此版本未記錄結構化文獻列。候選路線及原始評估仍可檢視。"],
    evidence: ["Recorded evidence references", "已记录证据引用", "已記錄證據引用"],
    checks: ["Checks, disposition & unresolved items", "查核、处置与未解事项", "查核、處置與未解事項"],
    inputs: ["Required inputs", "所需输入", "所需輸入"],
    outputs: ["Expected outputs", "预期输出", "預期輸出"],
    flow: ["Recorded stage workflow", "已记录阶段工作流", "已記錄階段工作流"],
    workbench: ["Workspace", "工作台", "工作臺"], files: ["Project files", "项目文件", "專案檔案"],
    history: ["Activity", "操作历史", "操作歷史"], settings: ["Settings", "设置", "設定"],
    networkTitle: ["Literature knowledge network", "文献知识网络", "文獻知識網絡"],
    networkSubtitle: ["Papers, methods and directions in one view. Select a node to read its bound record.", "论文、方法与方向在同一张图上；点击节点，查看已绑定的记录。", "論文、方法與方向在同一張圖上；點選節點，檢視已綁定的紀錄。"],
    stage2Title: ["Compare evidence, explore directions", "比较文献，探索研究方向", "比較文獻，探索研究方向"],
    globalNetwork: ["Global network", "全局网络", "全域網絡"], localNetwork: ["Local network", "局部网络", "局部網絡"],
    fit: ["Fit view", "适合画面", "符合畫面"],
    similarity: ["Method-label similarity", "方法标签相似度", "方法標籤相似度"],
    workflow: ["Within-stage workflow", "阶段内工作流", "階段內工作流程"],
    viewOnly: ["Artifact browsing · no research is started", "产物浏览 · 不启动研究", "產物瀏覽 · 不啟動研究"],
    workflow1: [["Confirm scope", "Search & read", "Check evidence", "Coverage & stop", "Package & review"], ["确定范围", "搜索与阅读", "核对证据", "覆盖与停止", "整理与审阅"], ["確認範圍", "搜尋與閱讀", "核對證據", "涵蓋與停止", "整理與審閱"]],
    products1: [["Research brief", "Literature catalog", "Claims & sources", "Coverage record", "Versioned literature package"], ["研究范围", "文献目录", "主张与来源", "覆盖记录", "版本化文献包"], ["研究範圍", "文獻目錄", "主張與來源", "涵蓋紀錄", "版本化文獻套件"]],
    workflow2: [["Bind literature", "Compare topics", "Explore routes", "Independent review", "Choose & hand off"], ["绑定文献", "比较主题", "探索路线", "独立审阅", "选择与交接"], ["綁定文獻", "比較主題", "探索路線", "獨立審閱", "選擇與交接"]],
    products2: [["Source-bound input", "Comparison record", "Candidate routes", "Assessment & comments", "Selection package"], ["来源绑定输入", "比较记录", "候选路线", "评估与评语", "选择包"], ["來源綁定輸入", "比較紀錄", "候選路線", "評估與評語", "選擇套件"]],
    loop1: ["When evidence is missing: coverage review → search & reading; previous attempts are retained.", "需要补充证据时：覆盖检查 → 搜索与阅读；原尝试保留。", "需要補充證據時：涵蓋檢查 → 搜尋與閱讀；原嘗試保留。"],
    loop2: ["When comparison needs revision: review → source checks → revised comparison; previous versions are retained.", "需要修订比较时：审阅 → 核对来源 → 新版比较；旧版本保留。", "需要修訂比較時：審閱 → 核對來源 → 新版比較；舊版本保留。"],
    artifactPreview: ["Artifact preview", "产物预览", "產物預覽"], nextConsumer: ["Next consumer", "下一个流程", "下一個流程"],
    process: ["Process & decisions", "过程与决策", "過程與決策"],
    discoveryLedger: ["Discovery & screening record", "发现与筛选记录", "發現與篩選紀錄"],
    discoveryCount: ["Discovery count / distinct queries / backend attempts", "发现次数／涉及查询数／后端尝试数", "發現次數／涉及查詢數／後端嘗試數"],
    firstFound: ["First discovery: query / attempt / result position", "首次记录：查询／尝试／结果位置", "首次紀錄：查詢／嘗試／結果位置"],
    rounds: ["Coverage round", "覆盖轮次", "涵蓋輪次"], decisionHistory: ["Decision versions & reversal history", "决定版本与撤回历史", "決定版本與撤回歷史"],
    sourceBinding: ["Project / snapshot hash", "项目／快照哈希", "專案／快照雜湊"],
    paperBinding: ["Project / paper version / snapshot hash", "项目／论文版本／快照哈希", "專案／論文版本／快照雜湊"],
    noRank: ["Result position is not quality rank. Search attempts, screening decisions and source reads are separate records; missing receipts stay Unknown.", "结果位置不等于质量排名。检索尝试、筛选决定与来源阅读分别记录；缺失回执保持未知。", "結果位置不等於品質排名。搜尋嘗試、篩選決定及來源閱讀分別記錄；缺少回執保持未知。"],
    topicCounts: ["Literature by direction", "各方向文献", "各方向文獻"],
    countsNote: ["Counts show recorded label membership, not research coverage. A paper may belong to several directions.", "篇数表示已记录标签的归属，不等于研究覆盖率；同一论文可属于多个方向。", "篇數表示已記錄標籤的歸屬，不等於研究涵蓋率；同一論文可屬於多個方向。"],
    compactCollection: ["Use the accepted working collection for reading; every screened version and exclusion reason stays in the archive. No fixed paper limit is imposed.", "日常阅读使用已纳入的工作文献集；全部筛选版本与排除原因留在档案中，不设固定篇数上限。", "日常閱讀使用已納入的工作文獻集；全部篩選版本及排除原因留在檔案中，不設固定篇數上限。"],
    formalWorks: ["Formally included distinct works", "正式纳入的不同作品", "正式納入的不同作品"],
    unboundTarget: ["Confirmed formal target: Unknown — ResearchBrief is not bound to this view. This count does not establish coverage or permission to start Stage 2.", "已确认正式目标：未知——此视图尚未绑定 ResearchBrief。数量不代表覆盖充分，也不授予 Stage 2 执行权限。", "已確認正式目標：未知——此檢視尚未綁定 ResearchBrief。數量不代表涵蓋充分，也不授予 Stage 2 執行權限。"],
    auditRecords: ["review records", "条审阅记录", "筆審閱紀錄"],
    relatedRoutes: ["Routes using these papers", "引用这些论文的路线", "引用這些論文的路線"],
    compareChosen: ["Compare these papers", "比较这些论文", "比較這些論文"],
    relevanceRank: ["Recorded relevance rank", "已记录相关度排名", "已記錄相關度排名"],
    noRouteBinding: ["No exact work/version evidence link is recorded for these papers.", "这些论文尚未记录精确的作品／版本证据关联。", "這些論文尚未記錄精確的作品／版本證據關聯。"],
    routeGraphNote: ["Lines identify the candidate's recorded evidence links to exact paper versions. They do not certify support or feasibility.", "连线表示候选路线与精确论文版本之间已记录的证据引用，不证明证据支持或可行性。", "連線表示候選路線與精確論文版本之間已記錄的證據引用，不證明證據支持或可行性。"],
    resetNetwork: ["Reset network", "返回全图", "返回全圖"],
    selectNode: ["Select a paper, direction or method to read its content. Select the same node again to clear focus.", "点击论文、方向或方法查看内容；再次点击同一节点即可取消选中。", "點選論文、方向或方法以檢視內容；再次點選同一節點即可取消選取。"],
    directionLink: ["Direction membership", "方向归属", "方向歸屬"],
    evidenceLink: ["Bound evidence link", "绑定的证据关系", "綁定的證據關係"],
    methodLink: ["Recorded method", "已记录方法", "已記錄方法"],
    similarityLink: ["Method-label similarity", "方法标签相似度", "方法標籤相似度"],
    sourceLinkMissing: ["Paper-to-paper source links: not recorded in this package", "论文间原文关系：此包尚未记录", "論文間原文關係：此套件尚未記錄"],
    viewAliases: ["P/M numbers are display labels, not discovery order. Hover or select to read the complete record.", "P／M 编号仅用于图上显示，不是发现顺序。悬停或点击查看完整记录。", "P／M 編號僅用於圖上顯示，不是發現順序。懸停或點選以檢視完整紀錄。"],
    globalSimilarity: ["Similarity is overlaid on this layout; distance is not a score. Percentages use exact recorded method-label Jaccard.", "相似度叠加在当前布局上，距离不代表评分。百分比按已记录方法标签的 Jaccard 交集计算。", "相似度疊加於目前佈局，距離不代表評分。百分比依已記錄方法標籤的 Jaccard 交集計算。"],
    layoutNote: ["Solid: direction membership · Dashed: recorded methods · Dotted: label similarity. Distance is layout only.", "实线：方向归属 · 虚线：已记录方法 · 点线：标签相似度。距离仅用于排版。", "實線：方向歸屬 · 虛線：已記錄方法 · 點線：標籤相似度。距離僅用於排版。"],
    graphBasis: ["Classification & relationship basis", "分类与关系依据", "分類與關係依據"],
    backToLibrary: ["Back to whole library", "返回完整文献库", "返回完整文獻庫"],
    fixtureNotice: ["Simulated interface example · paper records are retained; routes, comparisons and scores are examples. Real Stage 2 has not run.", "界面模拟示例 · 论文记录保留原内容，路线、比较与分数仅供展示；真实 Stage 2 尚未执行。", "介面模擬範例 · 論文紀錄保留原內容，路線、比較與分數僅供展示；真實 Stage 2 尚未執行。"],
    simulatedReport: ["Open simulated Stage 2 report", "查看模拟 Stage 2 报告", "檢視模擬 Stage 2 報告"],
    reserved: ["Stage contract preview · this companion performs no execution", "阶段契约预览 · 此图谱不执行研究", "階段契約預覽 · 此圖譜不執行研究"]
  };
  const fieldLabels = {
    "Work / version": ["Work / version", "作品／版本", "作品／版本"],
    "Authors": ["Authors", "作者", "作者"], "Year / venue": ["Year / venue", "年份／出版信息", "年份／出版資訊"],
    "Evidence level": ["Evidence level", "证据层级", "證據層級"], "Recorded URL": ["Recorded URL", "已记录网址", "已記錄網址"],
    "Recorded DOI": ["Recorded DOI", "已记录 DOI", "已記錄 DOI"], "Source IDs": ["Source IDs", "来源标识", "來源識別"],
    "Decision": ["Decision", "决定标识", "決定識別"], "Status": ["Status", "状态", "狀態"], "Reason": ["Reason", "原因", "原因"],
    "Query": ["Query", "检索式", "檢索式"], "Discovery path": ["Discovery path", "发现路径", "發現路徑"],
    "Observed at": ["Observed at", "记录时间", "紀錄時間"], "Opportunity": ["Opportunity", "研究机会", "研究機會"],
    "Value": ["Value", "研究价值", "研究價值"], "Approach": ["Approach", "研究途径", "研究途徑"],
    "Disposition": ["Disposition", "处置", "處置"], "Next step": ["Next step", "下一步", "下一步"],
    "Support status": ["Support status", "支持状态", "支援狀態"], "Execution enabled": ["Execution enabled", "执行已启用", "執行已啟用"],
    question: ["Question", "问题", "問題"], data: ["Data", "数据", "資料"], method: ["Method", "方法", "方法"],
    findings: ["Findings", "发现", "發現"], validation: ["Validation", "验证", "驗證"], limitations: ["Limitations", "限制", "限制"],
    relevance: ["Relevance", "相关性", "相關性"], geography: ["Geography", "地区", "地區"], population: ["Population", "研究对象", "研究對象"],
    concepts: ["Concepts", "概念", "概念"], plan: ["Plan", "规划", "規劃"], execute: ["Execute", "执行", "執行"],
    extract: ["Extract", "提取", "擷取"], validate: ["Validate", "验证", "驗證"], gate: ["Gate", "审查门槛", "審查門檻"], checkpoint: ["Checkpoint", "保存记录", "儲存紀錄"]
  };
  const languageControl = document.getElementById("atlas-language");
  const interfaceLanguage = value => ["en", "zh-Hans", "zh-Hant"].includes(value) ? value : "en";
  const state = {language: interfaceLanguage(languageControl?.value), stage: 1, scope: "working", sort: "recorded", mode: "library", topic: "", method: "", pair: [], paper: null, page: 0, graphPage: 0, groupPage: 0, neighborsPage: 0, ledgerPage: 0, text: "", status: "", tab: "sets", selected: new Set(), comparePage: 0, candidatePage: 0, libraryOpen: false, network: "global", similarity: false, zoom: 1, workflow: {1: 1, 2: 1}, productOpen: false, stage2Paper: null, networkFocus: null, graphCleared: false, processOpen: false};
  state.summaryTopic = null; state.summaryPaper = null; state.summaryPage = 0; state.summaryGraphPage = 0;
  state.summaryGraphFocus = null;
  const graphFocus = () => state.summaryGraphFocus || state.networkFocus;
  state.libraryReturn = null;
  state.graphSettings = {mode: 3, computed: true, showLabels: false}; state.graphPose = {}; state.planarFallback = false; state.fitNext = false;
  state.stage2Focus = null;
  let activeNetwork = null, activeNetworkStage = 1;
  function sharedNetwork(parent, rows, onSelect, focus) {
    if (!window.AtlasNetwork) return;
    const complete = state.stage === 1 ? archive : model.stage2Papers(payload);
    const lightColors = ["#77c9c4", "#94b8df", "#d8ba7b", "#bd9dce", "#dcaaa4", "#a8c6ae"];
    const topicColors = new Map(model.networkLayout(complete).groups.map(group => [group.key, lightColors[group.colorIndex] || "#aab8c8"]));
    const paperAliases = new Map(complete.map((paper, i) => [paper.key, `P${String(i + 1).padStart(2, "0")}`]));
    activeNetworkStage = state.stage;
    activeNetwork = window.AtlasNetwork.mount(parent, {papers: rows, model, language: state.language, t,
      focus, onSelect, topicColors, paperAliases, settings: state.graphSettings, pose: state.graphPose[state.stage],
      onSettings: render, onFallback: () => {state.planarFallback = true; render();}});
  }
  if (languageControl) languageControl.value = state.language;
  const locale = () => ["en", "zh-Hans", "zh-Hant"].indexOf(state.language);
  const t = name => words[name]?.[locale()] ?? name;
  const caption = name => fieldLabels[name]?.[locale()] ?? name;
  const text = value => value == null || value === "" ? t("unknown") : Array.isArray(value) && value.every(item => item === null || typeof item !== "object") ? value.map(item => item == null ? t("unknown") : String(item)).join(" · ") : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  function el(tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = text(value);
    if (className) node.className = className;
    return node;
  }
  function source(tag, value, className) {
    const node = el(tag, text(value), className); node.translate = false; return node;
  }
  function button(label, action, pressed) {
    const node = el("button", label === "" ? undefined : label); node.type = "button"; node.onclick = action;
    if (pressed !== undefined) node.setAttribute("aria-pressed", String(pressed));
    return node;
  }
  function disclosure(parent, label, value) {
    const box = el("details"); box.append(el("summary", label), source("pre", value)); parent.append(box);
  }
  function safeUrl(value) {
    try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch (_) { return null; }
  }
  function link(label, href, download = false) {
    const node = el("a", label); node.href = href;
    if (download) node.download = href.split("/").pop();
    return node;
  }
  function panel(title) { const node = el("section", undefined, "atlas-panel"); node.append(el("h2", title)); return node; }
  function kv(parent, rows) {
    const list = el("dl"); rows.forEach(([label, value]) => list.append(el("dt", caption(label)), source("dd", value))); parent.append(list);
  }
  function pagination(parent, total, size, field) {
    const pages = Math.max(1, Math.ceil(total / size)); state[field] = Math.min(state[field], pages - 1);
    const bar = el("div", undefined, "atlas-pagination"), page = state[field];
    bar.append(el("span", `${total ? page * size + 1 : 0}–${Math.min((page + 1) * size, total)} ${t("of")} ${total}`, "atlas-small"));
    const actions = el("div", undefined, "atlas-actions");
    for (const [label, step] of [[t("previous"), -1], [t("next"), 1]]) {
      const control = button(label, () => { state[field] += step; render(); });
      control.disabled = page + step < 0 || page + step >= pages; actions.append(control);
    }
    bar.append(actions); parent.append(bar);
    return page;
  }
  function changeContext(mode, key = "") {
    state.mode = mode; state.topic = mode === "topic" ? key : ""; state.method = "";
    state.paper = null; state.graphPage = 0; state.groupPage = 0; state.neighborsPage = 0; render();
  }
  function choosePaper(key) {
    if (!papers.some(p => p.key === key)) state.scope = "archive";
    state.paper = key; state.graphCleared = false; state.networkFocus = {kind: "paper", key}; state.neighborsPage = 0; render();
  }
  function openLibraryPaper(key) {
    state.libraryReturn = {top: Number(window.scrollY) || 0};
    state.fitNext = true;
    state.libraryOpen = true; state.network = "global"; state.summaryGraphFocus = null;
    choosePaper(key);
    document.getElementById("atlas-network")?.scrollIntoView?.({behavior: "smooth", block: "start"});
  }
  function backToLibrary() {
    const top = state.libraryReturn?.top;
    state.libraryReturn = null; state.libraryOpen = true; render();
    if (typeof window.scrollTo === "function" && Number.isFinite(top)) window.scrollTo({top, behavior: "auto"});
    else document.getElementById("atlas-library")?.scrollIntoView?.({block: "start"});
  }
  function ordered(rows) {
    if (state.sort === "title") return [...rows].sort((a, b) => String(a.title).localeCompare(String(b.title)) || a.key.localeCompare(b.key));
    if (state.sort === "year") return [...rows].sort((a, b) => (b.year ?? -Infinity) - (a.year ?? -Infinity) || a.key.localeCompare(b.key));
    return rows;
  }
  function paperRow(parent, paper, action = () => choosePaper(paper.key)) {
    const row = el("div", undefined, "atlas-row"), control = button("", action);
    control.className = "atlas-paper"; control.dataset.paperKey = paper.key;
    control.append(source("span", `${paper.work_id} · ${paper.year ?? t("unknown")} · ${paper.selection?.status ?? t("unknown")}`, "atlas-small"), source("strong", paper.title));
    control.append(source("span", `${t("relevance")}: ${text(paper.findings?.relevance ?? paper.cells?.relevance?.text)}`, "atlas-small"));
    row.append(control); parent.append(row); return row;
  }
  function contextRows() {
    let rows = state.mode === "topic" ? papers.filter(p => p.topics.includes(state.topic)) : state.mode === "shared" ? model.intersection(papers, state.pair) : state.mode === "unknown" ? papers.filter(p => !p.topics.length) : papers;
    return state.method ? rows.filter(p => p.methods.includes(state.method)) : rows;
  }
  function resetNetwork() {
    state.fitNext = true;
    state.summaryGraphFocus = null;
    state.networkFocus = null; state.paper = null; state.graphCleared = true;
    state.mode = "library"; state.topic = ""; state.method = "";
    state.network = "global"; state.similarity = false; state.zoom = 1; state.graphPage = 0; render();
  }
  function focusGroup(kind, key) {
    state.summaryGraphFocus = null;
    state.networkFocus = state.networkFocus?.kind === kind && state.networkFocus.key === key ? null : {kind, key};
    state.network = "global"; render();
  }
  function focusPaper(key) {
    state.summaryGraphFocus = null;
    if (state.networkFocus?.kind === "paper" && state.paper === key) {
      state.networkFocus = null; state.paper = null; state.graphCleared = true; render();
    } else choosePaper(key);
  }
  function focusSummary(kind, key) {
    const rows = ordered(papers);
    const index = rows.findIndex(paper => kind === "paper" ? paper.key === key : key ? paper.topics.includes(key) : !paper.topics.length);
    state.summaryGraphPage = Math.max(0, Math.floor(index / 48));
    state.summaryGraphFocus = {kind, key}; state.networkFocus = {kind, key};
    state.paper = kind === "paper" ? key : null; state.graphCleared = kind !== "paper"; state.network = "global";
  }
  function graph(parent, nodes, edges, clusters = [], height = 470) {
    const box = el("div", undefined, "atlas-graph"), layer = el("div", undefined, "atlas-graph-layer"), svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    layer.style.transform = `scale(${state.zoom})`;
    box.style.aspectRatio = `600 / ${height}`;
    if (height >= 540) {box.style.height = `${height}px`; box.style.aspectRatio = "auto"; box.classList.add("atlas-stage1-network");}
    svg.setAttribute("viewBox", `0 0 600 ${height}`); svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("preserveAspectRatio", "none");
    clusters.forEach(group => {
      const ellipse = document.createElementNS(svg.namespaceURI, "ellipse");
      Object.entries({cx: group.x, cy: group.y, rx: group.rx || 85, ry: group.ry || 67, fill: group.color}).forEach(([name, value]) => ellipse.setAttribute(name, value));
      ellipse.setAttribute("class", "atlas-cluster-background"); svg.append(ellipse);
    });
    const lines = edges.map(([a, b, meta = {}]) => {
      const line = document.createElementNS(svg.namespaceURI, "line");
      Object.entries({x1: a.x, y1: a.y, x2: b.x, y2: b.y}).forEach(([name, value]) => line.setAttribute(name, value));
      line.dataset.kind = meta.kind || "direction"; line.style.setProperty("--edge", meta.color || b.color || colors[0]);
      const title = document.createElementNS(svg.namespaceURI, "title"); title.textContent = t((meta.kind || "direction") + "Link") + (meta.label ? ` · ${meta.label}` : ""); line.append(title);
      svg.append(line);
      let label = null;
      if (meta.label) {
        label = document.createElementNS(svg.namespaceURI, "text"); label.textContent = meta.label;
        label.setAttribute("x", (a.x + b.x) / 2); label.setAttribute("y", (a.y + b.y) / 2 - 5);
        label.setAttribute("class", "atlas-edge-label"); svg.append(label);
      }
      return {line, label, a, b};
    });
    layer.append(svg);
    const controls = [];
    const highlight = requested => {
      const key = nodes.some(node => node.key === requested) ? requested : null;
      const related = new Set(key ? [key] : []);
      lines.forEach(({line, label, a, b}) => {
        const active = !key || a.key === key || b.key === key;
        if (active) {related.add(a.key); related.add(b.key);}
        line.dataset.related = String(Boolean(key && active)); line.dataset.muted = String(Boolean(key && !active));
        if (label) label.dataset.muted = String(Boolean(key && !active));
      });
      controls.forEach(({control, node}) => {control.dataset.muted = String(Boolean(key && !related.has(node.key)));});
    };
    nodes.forEach(node => {
      const control = button("", node.action); control.className = `atlas-node ${node.type || ""}`;
      control.style.left = `${node.x / 6}%`; control.style.top = `${node.y / (height / 100)}%`; control.style.setProperty("--category", node.color || colors[0]);
      if (node.fill) control.style.setProperty("--node-fill", node.fill);
      control.append(source("span", node.label)); if (node.sub) control.append(source("small", node.sub)); if (node.count !== undefined) control.append(el("strong", node.count));
      control.title = text(node.title || node.label); control.dataset.nodeKey = node.key || "";
      if (node.selected) control.setAttribute("aria-pressed", "true");
      control.onpointerenter = control.onfocus = () => highlight(node.key);
      control.onpointerleave = control.onblur = () => highlight(graphFocus() ? `${graphFocus().kind}:${graphFocus().key}` : null);
      control.setAttribute("aria-label", `${text(node.title || node.label)} ${node.count ?? ""}`); layer.append(control); controls.push({control, node});
    });
    highlight(graphFocus() ? `${graphFocus().kind}:${graphFocus().key}` : null);
    box.append(layer); parent.append(box);
  }
  function legend(parent, similarity = false) {
    const box = el("div", undefined, "atlas-graph-legend");
    ["direction", "method", ...(similarity ? ["similarity"] : [])].forEach(kind => {
      const item = el("span"), sample = el("i"); sample.dataset.kind = kind;
      item.append(sample, el("span", t(kind + "Link"))); box.append(item);
    }); parent.append(box);
  }
  function groupGraph(parent) {
    const summaryFocus = Boolean(state.summaryGraphFocus), rows = summaryFocus ? papers : contextRows();
    const page = rows.length > 48 ? pagination(parent, rows.length, 48, summaryFocus ? "summaryGraphPage" : "graphPage") : 0, shown = ordered(rows).slice(page * 48, page * 48 + 48);
    if (rows.length <= 48) parent.append(el("p", `${rows.length} ${t("records")}`, "atlas-small"));
    if (window.AtlasNetwork && !state.planarFallback) {
      sharedNetwork(parent, shown, node => node.kind === "paper" ? focusPaper(node.key) : focusGroup(node.kind, node.key), graphFocus());
      return;
    }
    const layout = model.networkLayout(shown, {singleMethods: true}), nodes = [], edges = [], groupNodes = new Map();
    const palette = new Map(model.networkLayout(archive).groups.map(group => [group.key, group.colorIndex < 0 ? "#8b949a" : colors[group.colorIndex]]));
    layout.groups.forEach(group => {
      const x = group.labelX, y = group.labelY;
      const label = group.key || t("unclassified");
      const node = {x, y, key: "topic:" + group.key, label, title: label, count: group.ids.length, color: palette.get(group.key), selected: graphFocus()?.kind === "topic" && graphFocus().key === group.key, type: "atlas-topic-node", action: () => focusGroup("topic", group.key)};
      groupNodes.set(group.key, node); nodes.push(node);
    });
    const paperNodes = new Map();
    layout.papers.forEach(position => {
      const paper = shown.find(p => p.key === position.key), categories = position.groupKeys.map(key => palette.get(key));
      const alias = `P${String(archive.findIndex(p => p.key === paper.key) + 1).padStart(2, "0")}`;
      const author = String(paper.work_id).replace(/-(?:19|20)\d\d.*$/, "").replace(/-et-al\b/g, " et al.").replace(/-/g, " ");
      const short = `${author.length > 18 ? author.slice(0, 16) + "…" : author}${paper.year ? " · " + paper.year : ""}`;
      const fill = categories.length > 1 ? `conic-gradient(${categories.map((color, i) => `${color} ${i / categories.length * 100}% ${(i + 1) / categories.length * 100}%`).join(",")})` : null;
      const node = {...position, key: "paper:" + paper.key, label: alias, sub: short, title: `${alias} · ${paper.title} · ${paper.work_id} / ${paper.version_id}`, color: palette.get(position.primaryGroupKey), fill, selected: graphFocus()?.kind === "paper" && paper.key === graphFocus().key, type: "atlas-paper-node", action: () => focusPaper(paper.key)};
      nodes.push(node); paperNodes.set(paper.key, node);
      paper.topics.forEach(topic => {if (groupNodes.has(topic)) edges.push([node, groupNodes.get(topic), {kind: "direction", color: groupNodes.get(topic).color}]);});
    });
    const literalMethods = model.groups(shown, "methods").sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    /* Unique literal methods remain unique. Small packets can show each method
       diamond; larger packets show shared hubs plus the explicitly focused method. */
    const hasShared = literalMethods.some(m => m.ids.length > 1);
    const drawn = layout.methods.filter(m => m.ids.length > 1 || !hasShared && literalMethods.length <= 16 || m.ids.includes(state.paper) || state.networkFocus?.kind === "method" && state.networkFocus.key === m.key);
    const allMethods = model.groups(archive, "methods").sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    drawn.forEach((method, i, list) => {
      const {x, y} = method;
      const methodIndex = allMethods.findIndex(m => m.key === method.key), alias = `M${String(methodIndex + 1).padStart(2, "0")}`;
      const node = {x, y, key: "method:" + method.key, label: alias, title: method.label, color: colors[methodIndex % 6], type: "atlas-method atlas-method-compact", selected: state.networkFocus?.kind === "method" && state.networkFocus.key === method.key, action: () => focusGroup("method", method.key)};
      nodes.push(node); method.ids.forEach(key => {if (paperNodes.has(key)) edges.push([node, paperNodes.get(key), {kind: "method", color: node.color}]);});
    });
    const similarityKey = graphFocus()?.kind === "paper" ? graphFocus().key : state.paper;
    const neighbors = state.similarity && paperNodes.has(similarityKey) ? model.local(shown, similarityKey) : [];
    neighbors.forEach(row => {
      edges.push([paperNodes.get(similarityKey), paperNodes.get(row.paper.key), {kind: "similarity", color: "#567fa2", label: `${(row.similarity * 100).toFixed(1)}%`}]);
    });
    graph(parent, nodes, edges, layout.groups.map(group => ({...group, color: palette.get(group.key)})), layout.height);
    legend(parent, state.similarity); parent.append(el("p", t("layoutNote"), "atlas-small"));
    if (state.similarity && !neighbors.length) parent.append(el("p", t("noRelations"), "atlas-small"));
    const basis = el("details", undefined, "atlas-small"); basis.append(el("summary", t("graphBasis")), el("p", t("graphNote")), el("p", t("viewAliases")), el("p", t("sourceLinkMissing")));
    if (state.similarity) basis.append(el("p", t("globalSimilarity"))); parent.append(basis);
    const all = el("details"), buttons = el("div", undefined, "atlas-actions"); all.append(el("summary", `${t("allGroups")} · ${layout.groups.length}`));
    model.groups(rows).forEach(group => buttons.append(button(`${group.label} · ${group.ids.length}`, () => focusGroup("topic", group.key))));
    model.groups(rows, "methods").forEach(group => buttons.append(button(`${group.label} · ${group.ids.length}`, () => focusGroup("method", group.key))));
    all.append(buttons); parent.append(all);
  }
  function paperGraph(parent, paper) {
    if (window.AtlasNetwork && !state.planarFallback) {
      const associations = window.AtlasAssociations.build(papers, {neighbors: 2, threshold: .09});
      const keys = new Set([paper.key]);
      [...associations.recorded, ...(state.graphSettings.computed ? associations.lexical : [])].forEach(edge => {
        if (edge.from.type === "paper" && edge.to.type === "paper" && [edge.from.key, edge.to.key].includes(paper.key)) {
          keys.add(edge.from.key); keys.add(edge.to.key);
        }
      });
      sharedNetwork(parent, papers.filter(row => keys.has(row.key)), node => node.kind === "paper" ? focusPaper(node.key) : focusGroup(node.kind, node.key), graphFocus());
      return;
    }
    const neighbors = model.local(papers, paper.key).filter(row => row.similarity > 0), n = neighbors.length;
    let indices = n <= 6 ? neighbors.map((_, i) => i) : [0, 1, Math.floor(n / 2) - 1, Math.floor(n / 2), n - 2, n - 1];
    if (window.innerWidth < 700 && indices.length > 3) indices = [indices[0], indices[Math.floor(indices.length / 2)], indices.at(-1)];
    const center = {x: 300, y: 220, key: "paper:" + paper.key, label: paper.work_id, title: paper.title, selected: state.networkFocus?.kind === "paper" && state.paper === paper.key, type: "atlas-center atlas-paper-node", action: () => focusPaper(paper.key)};
    const nodes = [center], edges = [];
    indices.forEach((index, i) => {
      const related = neighbors[index], angle = i * Math.PI * 2 / Math.max(indices.length, 1) - Math.PI / 2, distance = 95 + 90 * (1 - related.similarity);
      const node = {x: 300 + Math.cos(angle) * distance, y: 220 + Math.sin(angle) * distance, key: "paper:" + related.paper.key, label: related.paper.work_id, title: related.paper.title, selected: state.networkFocus?.kind === "paper" && state.paper === related.paper.key, type: "atlas-paper-node", color: colors[i % 6], action: () => focusPaper(related.paper.key)};
      nodes.push(node); edges.push([center, node, {kind: "similarity", color: "#567fa2"}]);
    });
    graph(parent, nodes, edges); legend(parent, true); parent.append(el("p", t("localNote"), "atlas-small"));
    if (!n) parent.append(el("p", t("noRelations"), "atlas-note"));
    const list = el("details"); list.append(el("summary", `${t("related")} · ${n}`));
    const page = pagination(list, n, 6, "neighborsPage");
    neighbors.slice(page * 6, page * 6 + 6).forEach(row => {
      paperRow(list, row.paper); list.append(el("p", `Jaccard ${(row.similarity * 100).toFixed(1)}%`, "atlas-small"));
    }); parent.append(list);
  }
  function sourceAccess(parent, paper) {
    const access = el("section", undefined, "atlas-access"); access.append(el("h4", t("access")));
    const url = safeUrl(paper.url); if (url) access.append(link(t("publicLink"), url));
    kv(access, [["Recorded URL", paper.url], ["Recorded DOI", paper.doi], ["Source IDs", paper.source_ids]]);
    const rerun = index.source_rerun;
    (rerun?.data?.rows || []).filter(row => row.work_id === paper.work_id && row.version_id === paper.version_id && paper.source_ids?.includes(row.source_id)).forEach(row => {
      const path = row.raw_path, accepted = typeof path === "string" && /^sources\/[A-Za-z0-9_-]+\/raw\.(pdf|html)$/.test(path);
      if (accepted && rerun.artifact_hashes?.[path]?.sha256 === row.raw_sha256) access.append(link(`${t("savedSource")} · ${row.source_id}`, `./source-rerun/${path}`));
    });
    if (typeof paper.notePath === "string" && /^wiki\/[a-f0-9]{64}\.md$/.test(paper.notePath)) access.append(link(t("note"), `./${paper.notePath}`, true));
    parent.append(access);
  }
  function paperDetail(parent, paper) {
    parent.append(source("h3", paper.title));
    kv(parent, [["Work / version", [paper.work_id, paper.version_id]], ["Authors", paper.authors], ["Year / venue", [paper.year, paper.venue]], [t("status"), `${paper.selection?.status ?? t("unknown")} · ${(paper.selection?.reasons || []).join(" / ")}`], ["Evidence level", paper.evidence_level]]);
    sourceAccess(parent, paper);
    parent.append(el("h3", t("findings")));
    kv(parent, ["question", "data", "method", "main_findings", "limitations", "relevance", "transferability"].map((name, i) => [t("fields")[i], paper.findings?.[name]]));
    relatedPapers(parent, paper);
    disclosure(parent, t("status"), paper.selection);
    disclosure(parent, t("sources"), paper.sources);
    const ledger = el("details"); ledger.append(el("summary", t("ledger"))); ledgerContent(ledger, paper); parent.append(ledger);
    disclosure(parent, t("claims"), {claims: paper.claims, relations: paper.relations});
    disclosure(parent, t("provenance"), {project_id: index.project_id, index_sha256: payload.index_sha256, provenance: index.provenance, work_id: paper.work_id, version_id: paper.version_id, source_ids: paper.source_ids});
    disclosure(parent, t("raw"), index.papers.find(row => model.key(row) === paper.key));
  }
  function relatedPapers(parent, paper) {
    const rows = window.AtlasAssociations?.related(papers, paper.key, {neighbors: 2, threshold: .09, computed: state.graphSettings.computed}) || [];
    const section = el("section", undefined, "atlas-related"); section.append(el("h3", `${t("related")} · ${rows.length}`));
    const append = (container, row) => {
      const card = el("div", undefined, "atlas-related-paper");
      const open = button(row.paper.title, () => {
        focusSummary("paper", row.paper.key); state.fitNext = true; render();
        document.getElementById("atlas-paper-detail")?.scrollIntoView({behavior: "smooth", block: "start"});
      }); open.dataset.relatedPaper = row.paper.key; card.append(open);
      card.append(source("p", `${row.paper.work_id} · ${row.paper.version_id} · ${text(row.paper.year)}`, "atlas-small"));
      for (const [label, values] of [["sharedTopics", row.shared_topics], ["sharedMethods", row.shared_methods]]) {
        if (values.length) {const line = el("p", undefined, "atlas-small"); line.append(el("strong", `${t(label)}: `), source("span", values.join(" / "))); card.append(line);}
      }
      if (row.lexical) {
        card.append(el("p", `${t("computedBasis")} ${(100 * row.lexical.score).toFixed(1)}%`, "atlas-small"));
        const terms = el("p", undefined, "atlas-small"); terms.append(el("span", `${t("sharedTerms")}: `), source("span", row.lexical.shared_terms.join(" / "))); card.append(terms);
      }
      container.append(card);
    };
    if (!rows.length) section.append(el("p", t("noRelated"), "atlas-small"));
    rows.slice(0, 5).forEach(row => append(section, row));
    if (rows.length > 5) {const more = el("details"); more.append(el("summary", `${t("moreRelated")} · ${rows.length - 5}`)); rows.slice(5).forEach(row => append(more, row)); section.append(more);}
    parent.append(section);
  }
  function choice(label, value, options, action) {
    const field = el("label", label), select = el("select");
    options.forEach(([key, caption]) => { const option = source("option", caption); option.value = key; select.append(option); });
    select.value = value; select.onchange = () => action(select.value); field.append(select); return field;
  }
  function workflow() {
    const number = state.stage, names = t(`workflow${number}`), products = t(`products${number}`), selected = state.workflow[number], box = panel(t("workflow"));
    box.classList.add("atlas-workflow"); box.append(el("p", t("viewOnly"), "atlas-small"));
    const strip = el("div", undefined, "atlas-workflow-strip");
    names.forEach((name, i) => {
      const step = button("", () => { state.workflow[number] = i; state.productOpen = !state.productOpen || selected !== i; render(); }, selected === i);
      step.className = "atlas-workflow-step"; step.dataset.workflowStep = i;
      const title = el("span"); title.append(el("strong", name), el("small", products[i]));
      const miniature = el("span", undefined, `atlas-workflow-mini atlas-workflow-mini-${i}`);
      for (let j = 0; j < 3; j++) miniature.append(el("i"));
      title.append(miniature); step.append(el("b", i + 1), title); strip.append(step);
    }); box.append(strip, el("p", t(`loop${number}`), "atlas-small"));
    if (state.productOpen) {
      const product = el("div", undefined, "atlas-workflow-product"); product.append(el("h3", `${t("artifactPreview")} · ${products[selected]}`));
      const stage = (index.stages || []).find(row => row.stage === number);
      const data = number === 1 ? [
        {topic: index.topic, input: stage?.required_inputs, provenance: index.provenance},
        {paper_versions: archive.length, source_records: (index.sources || []).length},
        {claims: index.claims, source_records: index.sources},
        {coverage: index.coverage, original_documents: index.coverage_documents},
        {selection: payload.literature_selection, provenance: index.provenance}
      ][selected] : [
        payload.stage2?.bridge_receipt, payload.stage2_comparison?.comparison,
        payload.stage2_comparison?.directions, payload.stage2?.evaluation, payload.stage2?.selection
      ][selected];
      if (number === 1 && selected === 1) product.append(button(`${t("library")} · ${archive.length}`, () => document.getElementById("atlas-network")?.scrollIntoView({behavior: "smooth"})));
      if (number === 1 && selected === 4) product.append(link(t("screeningBib"), "./literature/screening.bib", true), link(t("includedBib"), "./literature/included.bib", true));
      if (number === 2 && payload.stage2) product.append(link(t("report"), "./stage2/report-reader.html"));
      disclosure(product, t("raw"), data);
      const chain = el("div", undefined, "atlas-product-chain");
      for (const [label, value] of [[t("inputs"), stage?.required_inputs], [t("outputs"), products[selected]], [t("nextConsumer"), selected < 4 ? names[selected + 1] : `Stage ${number + 1}`]]) {
        const item = el("div"); item.append(el("small", label), source("p", value)); chain.append(item);
      } product.append(chain); box.append(product);
    } content.append(box);
  }
  function ledgerContent(parent, paper) {
    parent.append(source("h3", `${t("discoveryLedger")} · ${paper.work_id}`));
    const fields = el("div", undefined, "atlas-ledger-grid");
    const rows = [[t("paperBinding"), `${index.project_id} · ${paper.work_id} / ${paper.version_id} · ${text(payload.index_sha256)}`],
      [t("discoveryCount"), paper.discovery?.count], [t("firstFound"), paper.discovery?.first_result_position], [t("rounds"), paper.discovery?.round],
      [t("status"), paper.selection?.status], [t("relevance"), paper.findings?.relevance], [t("relevanceRank"), null],
      ["Reason", paper.selection?.reasons?.length ? paper.selection.reasons : null], [t("decisionHistory"), (paper.screening || []).length ? paper.screening.map(row => ({decision_id: row.decision_id, status: row.status, reason: row.reason, observed_at: row.observed_at})) : null]];
    rows.forEach(([label, value]) => { const field = el("div"); field.append(el("dt", caption(label)), source("dd", value)); fields.append(field); });
    parent.append(fields, el("p", t("noRank"), "atlas-small"));
    disclosure(parent, t("paperBinding"), {project_id: index.project_id, work_id: paper.work_id, version_id: paper.version_id, index_sha256: payload.index_sha256});
    (paper.screening || []).forEach(row => { const item = el("details"); item.append(el("summary", `${text(row.decision_id)} · ${text(row.status)} · ${text(row.reason)}`)); kv(item, [["Query", row.query], ["Discovery path", row.discovery_path], ["Observed at", row.observed_at]]); disclosure(item, t("raw"), row); parent.append(item); });
    disclosure(parent, t("searchRecords"), paper.rawSearch);
  }
  function processPanel() {
    const box = el("details", undefined, "atlas-panel atlas-process"); box.id = "atlas-process";
    box.open = state.processOpen; box.ontoggle = () => {state.processOpen = box.open;};
    box.append(el("summary", t("process")));
    const chips = el("div", undefined, "atlas-actions atlas-paper-chips"), page = pagination(box, archive.length, 12, "ledgerPage");
    archive.slice(page * 12, page * 12 + 12).forEach(paper => chips.append(button(paper.work_id, () => choosePaper(paper.key), paper.key === state.paper)));
    box.append(chips); const chosen = archive.find(p => p.key === state.paper) || papers[0];
    if (chosen) { const ledger = el("div", undefined, "atlas-process-ledger"); ledgerContent(ledger, chosen); box.append(ledger); }
    else box.append(el("p", t("unknown")));
    content.append(box);
  }
  function topicCounts() {
    const box = panel(t("topicCounts")), split = el("div", undefined, "atlas-summary-split"), cards = el("div", undefined, "atlas-topic-cards"), list = el("div", undefined, "atlas-summary-list"), groups = model.groups(papers);
    box.id = "atlas-direction-summary";
    const unclassified = papers.filter(p => !p.topics.length);
    if (unclassified.length) groups.push({key: "", label: t("unclassified"), ids: unclassified.map(p => p.key)});
    const palette = new Map(model.networkLayout(archive).groups.map(group => [group.key, colors[group.colorIndex]]));
    const selected = groups.find(group => group.key === state.summaryTopic) || groups[0];
    const unit = Math.min(28, 72 / Math.sqrt(Math.max(1, ...groups.map(group => group.ids.length))));
    groups.forEach(group => {
      const card = button("", () => {
        state.summaryTopic = group.key; state.summaryPaper = null; state.summaryPage = 0;
        if (state.summaryGraphFocus?.kind === "topic" && state.summaryGraphFocus.key === group.key) {
          state.summaryGraphFocus = null; state.networkFocus = null; state.paper = null; state.graphCleared = true;
        }
        else focusSummary("topic", group.key);
        state.network = "global"; render();
      }, selected?.key === group.key); card.className = "atlas-topic-card"; card.style.setProperty("--category", palette.get(group.key) || "#8b949a");
      const bubble = el("b", group.ids.length); bubble.style.width = bubble.style.height = `${unit * Math.sqrt(group.ids.length)}px`;
      card.append(bubble, source("strong", group.label)); cards.append(card);
    });
    if (selected) {
      list.append(source("h3", selected.label), el("p", `${selected.ids.length} ${t("related")}`, "atlas-small"));
      const rows = papers.filter(p => selected.ids.includes(p.key)), page = rows.length > 5 ? pagination(list, rows.length, 5, "summaryPage") : 0;
      rows.slice(page * 5, page * 5 + 5).forEach(paper => {
        const control = button("", () => {
          state.summaryPaper = paper.key; focusSummary("paper", paper.key); state.fitNext = true; render();
          document.getElementById("atlas-paper-detail")?.scrollIntoView?.({behavior: "smooth", block: "start"});
        }, state.summaryPaper === paper.key); control.className = "atlas-summary-paper";
        control.dataset.summaryPaper = paper.key; control.append(source("strong", paper.title), source("small", `${paper.work_id} · ${paper.year ?? t("unknown")}`)); list.append(control);
        if (state.summaryPaper === paper.key) {
          const preview = el("div", undefined, "atlas-summary-preview"); preview.append(source("p", paper.findings?.main_findings ?? paper.findings?.relevance));
          const url = safeUrl(paper.url); if (url) preview.append(link(t("publicLink"), url));
          list.append(preview);
        }
      });
    } else list.append(el("p", t("unclassified")));
    split.append(cards, list); box.append(split, el("p", t("countsNote"), "atlas-small"));
    content.append(box);
  }
  function stage1() {
    const scope = el("div", undefined, "atlas-actions atlas-tabs"), included = archive.filter(p => p.selection?.status === "included"), pending = archive.filter(p => p.selection?.status === "pending");
    scope.append(button(`${t("working")} · ${(included.length ? included : pending.length ? pending : archive).length}`, () => { state.scope = "working"; changeContext("library"); }, state.scope === "working"), button(`${t("archive")} · ${archive.length}`, () => { state.scope = "archive"; changeContext("library"); }, state.scope === "archive")); content.append(scope);
    const collectionStatus = el("details", undefined, "atlas-small atlas-collection-status");
    collectionStatus.append(el("summary", `${t("formalWorks")}: ${new Set(included.map(p => p.work_id)).size}`), el("p", t("unboundTarget")));
    if (state.scope === "working" && !included.length) collectionStatus.append(el("p", t(pending.length ? "noIncluded" : "archiveFallback")));
    content.append(collectionStatus);
    const split = el("div", undefined, "atlas-split atlas-network-split"), graphPanel = panel(t("networkTitle")), detailPanel = panel(t("detail")); split.id = "atlas-network"; detailPanel.id = "atlas-paper-detail"; detailPanel.classList.add("atlas-detail-panel");
    if (state.libraryReturn) detailPanel.append(button(t("backToLibrary"), backToLibrary));
    const selected = papers.find(p => p.key === state.paper);
    const networkActions = el("div", undefined, "atlas-actions atlas-network-actions");
    for (const [mode, label] of [["global", "globalNetwork"], ["local", "localNetwork"]]) networkActions.append(button(t(label), () => { state.network = mode; state.similarity = mode === "local"; render(); }, state.network === mode));
    if (!window.AtlasNetwork || state.planarFallback) {
      const label = el("label", undefined, "atlas-check"), checkbox = el("input"); checkbox.type = "checkbox"; checkbox.checked = state.similarity;
      checkbox.onchange = () => {state.similarity = checkbox.checked; render();}; label.append(checkbox, el("span", t("similarity"))); networkActions.append(label);
    }
    networkActions.append(button(t("resetNetwork"), resetNetwork)); graphPanel.append(networkActions);
    if (state.network === "local" && selected) paperGraph(graphPanel, selected); else groupGraph(graphPanel);
    if (state.networkFocus && ["topic", "method"].includes(state.networkFocus.kind)) {
      const focus = state.networkFocus, field = focus.kind === "topic" ? "topics" : "methods";
      const rows = papers.filter(p => focus.kind === "topic" && !focus.key ? !p.topics.length : p[field].includes(focus.key));
      detailPanel.append(source("h3", focus.key || t("unclassified")), el("p", `${rows.length} ${t("related")}`, "atlas-small"));
      rows.forEach(p => paperRow(detailPanel, p));
    } else if (selected) paperDetail(detailPanel, selected);
    else detailPanel.append(el("p", t("selectNode"), "atlas-note"));
    split.append(graphPanel, detailPanel); content.append(split);
    topicCounts(); workflow(); processPanel(); content.append(el("p", t("compactCollection"), "atlas-small"));
    const library = el("details"); library.id = "atlas-library"; library.open = state.libraryOpen; library.ontoggle = () => { state.libraryOpen = library.open; }; library.append(el("summary", `${t("library")} · ${papers.length}`));
    const filters = el("div", undefined, "atlas-filters"), search = el("label", t("search")), input = el("input"); input.value = state.text; input.type = "search"; input.onchange = () => { state.text = input.value; state.page = 0; render(); }; search.append(input); filters.append(search);
    filters.append(choice(t("topics"), state.topic, [["", t("all")], ...model.groups(papers, "topics").map(g => [g.key, g.label])], value => { state.topic = value; state.mode = value ? "topic" : "library"; state.page = 0; render(); }));
    filters.append(choice(t("methods"), state.method, [["", t("all")], ...model.groups(papers, "methods").map(g => [g.key, g.label])], value => { state.method = value; state.page = 0; render(); }));
    filters.append(choice(t("status"), state.status, ["", "included", "pending", "excluded", "unbound"].map(key => [key, t(key || "all")]), value => { state.status = value; state.page = 0; render(); })); library.append(filters);
    const sorting = choice(t("sorting"), state.sort, [["recorded", t("originalOrder")], ["title", t("titleOrder")], ["year", t("yearOrder")], ["relevance", t("relevanceOrder")]], value => { state.sort = value; render(); }); sorting.querySelector('option[value="relevance"]').disabled = true; library.append(sorting);
    const rows = model.filter(papers, {text: state.text, topic: state.topic, method: state.method, status: state.status}), page = pagination(library, rows.length, 12, "page");
    ordered(rows).slice(page * 12, page * 12 + 12).forEach(p => paperRow(library, p, () => openLibraryPaper(p.key))); content.append(library);
    if (state.scope === "archive") { content.append(el("p", t("archiveNote"), "atlas-small")); disclosure(content, t("searchRecords"), index.search || []); }
    const downloads = panel(t("exports")), links = el("div", undefined, "atlas-actions"); downloads.id = "atlas-exports";
    links.append(link(t("bib"), "./references.bib", true), link(t("screeningBib"), "./literature/screening.bib", true), link(t("includedBib"), "./literature/included.bib", true), link(t("original"), "./index.html")); downloads.append(links); content.append(downloads);
  }
  function directionSets() {
    const rows = model.stage2Papers(payload), groups = model.groups(rows, "topics"), layout = el("div", undefined, "atlas-split"), catalog = panel(t("directionSets")), detail = panel(t("related")), cards = el("div", undefined, "atlas-topic-cards"), page = pagination(catalog, groups.length, 6, "groupPage");
    sharedNetwork(catalog, rows, node => {
      const repeated = state.stage2Focus?.kind === node.kind && state.stage2Focus.key === node.key;
      state.stage2Focus = repeated ? null : node;
      if (node.kind === "paper") state.stage2Paper = repeated ? null : node.key;
      else {
        const field = node.kind === "method" ? "methods" : "topics";
        state.selected = new Set(repeated ? [] : rows.filter(row => row[field].includes(node.key)).map(row => row.key));
        state.stage2Paper = null;
      }
      state.comparePage = 0; render();
    }, state.stage2Focus);
    const maximum = Math.max(1, ...groups.map(g => g.ids.length));
    const palette = new Map(model.networkLayout(rows).groups.map(group => [group.key, colors[group.colorIndex]]));
    groups.slice(page * 6, page * 6 + 6).forEach((group, i) => {
      const card = el("article", undefined, "atlas-card"); card.style.setProperty("--category", palette.get(group.key));
      card.append(button(group.label, () => { state.selected = new Set(group.ids); state.stage2Focus = {kind: "topic", key: group.key}; state.stage2Paper = null; state.comparePage = 0; render(); }), el("p", `${group.ids.length} ${t("records")}`, "atlas-tally"));
      const track = el("div", undefined, "atlas-track"), fill = el("span"); fill.style.width = `${group.ids.length / maximum * 100}%`; track.append(fill); card.append(track); cards.append(card);
    }); catalog.append(el("p", t("setNote"), "atlas-small"), cards);
    const unclassified = rows.filter(row => !row.topics.length);
    const unclassifiedControl = button(`${t("unclassified")} · ${unclassified.length}`, () => { state.selected = new Set(unclassified.map(row => row.key)); state.comparePage = 0; render(); }); unclassifiedControl.disabled = !unclassified.length; catalog.append(unclassifiedControl);
    const related = state.selected.size ? rows.filter(row => state.selected.has(row.key)) : rows, relatedPage = pagination(detail, related.length, 6, "comparePage"), shown = related.slice(relatedPage * 6, relatedPage * 6 + 6);
    shown.forEach(row => paperRow(detail, row, () => { state.stage2Paper = row.key; state.stage2Focus = {kind: "paper", key: row.key}; render(); }));
    if (related.length) detail.append(button(t("compareChosen"), () => { state.selected = new Set(related.map(row => row.key)); state.tab = "comparison"; state.comparePage = 0; render(); }));
    const selected = rows.find(row => row.key === state.stage2Paper);
    if (selected) {
      const note = el("div", undefined, "atlas-stage2-detail"); stage2Detail(note, selected);
      detail.append(note);
    } layout.append(catalog, detail); content.append(layout);
    const shared = panel(t("shared"));
    groups.slice(page * 6, page * 6 + 6).forEach((a, i, shown) => shown.slice(i + 1).forEach(b => {
      const matched = model.intersection(rows, [a.key, b.key]);
      if (matched.length) shared.append(button(`${a.label} × ${b.label} · ${matched.length}`, () => { state.selected = new Set(matched.map(p => p.key)); state.tab = "comparison"; state.comparePage = 0; render(); }));
    })); content.append(shared);
  }
  function evidenceFor(view, paper) {
    return (view?.evidence || []).filter(item => (paper.evidence_ids || []).includes(item.evidence_id) && item.work_id === paper.work_id && item.version_id === paper.version_id && (paper.source_ids || []).includes(item.source_id));
  }
  function stage2Detail(parent, row) {
    parent.append(source("h3", row.title));
    kv(parent, [["Work / version", [row.work_id, row.version_id]], ["Source IDs", row.source_ids], ["Evidence level", row.evidence_level]]);
    const packet = payload.stage2?.selection?.evaluation_packet, original = (packet?.literature || []).find(paper => paper.work_id === row.work_id && paper.version_id === row.version_id);
    const retained = archive.find(paper => paper.key === row.key && (row.source_ids || []).every(id => paper.source_ids?.includes(id)));
    sourceAccess(parent, {...row, url: original?.url, doi: original?.doi, notePath: retained?.notePath});
    Object.entries(row.cells || {}).forEach(([name, cell]) => { const field = el("section", undefined, "atlas-compare-field"); field.append(el("h4", caption(name)), source("p", cell?.text)); disclosure(field, t("provenance"), cell?.field); parent.append(field); });
    disclosure(parent, t("sources"), (packet?.sources || []).filter(item => (row.source_ids || []).includes(item.source_id)));
    disclosure(parent, t("evidence"), evidenceFor(payload.stage2_comparison, row));
    disclosure(parent, t("raw"), row);
  }
  function relatedRoutes(parent, view, selected) {
    const ids = new Set(selected.flatMap(row => evidenceFor(view, row).map(item => item.evidence_id))), evidence = (view.evidence || []).filter(row => ids.has(row.evidence_id));
    const routes = (view.directions || []).filter(row => evidence.some(item => (row.evidence_ids || []).includes(item.evidence_id)));
    const box = panel(t("relatedRoutes"));
    routes.forEach(row => box.append(button(`${row.candidate_id} · v${row.version} · ${text(row.question)}`, () => { state.candidatePage = Math.floor((view.directions || []).indexOf(row) / 3); state.tab = "candidates"; render(); })));
    if (!routes.length) box.append(el("p", t("noRouteBinding"), "atlas-small")); parent.append(box);
  }
  function comparisons(view) {
    const literature = view.literature || [], library = panel(t("comparison")), page = pagination(library, literature.length, 8, "page");
    content.append(el("p", t("compareNote"), "atlas-note"));
    literature.slice(page * 8, page * 8 + 8).forEach(row => {
      const field = el("label", undefined, "atlas-check"), input = el("input"); input.type = "checkbox"; input.checked = state.selected.has(row.key);
      input.onchange = () => { if (input.checked) state.selected.add(row.key); else state.selected.delete(row.key); state.comparePage = 0; render(); };
      field.append(input, source("span", row.title)); library.append(field);
    }); library.append(button(t("clear"), () => { state.selected.clear(); render(); })); content.append(library);
    const selected = literature.filter(row => state.selected.has(row.key)), selectedPanel = panel(`${t("selected")} · ${selected.length}`), focusPage = pagination(selectedPanel, selected.length, 4, "comparePage");
    const rows = selected.slice(focusPage * 4, focusPage * 4 + 4), scroll = el("div", undefined, "atlas-matrix-scroll"), table = el("table", undefined, "atlas-table atlas-comparison-matrix"), head = el("thead"), header = el("tr");
    header.append(el("th", t("dimension")));
    rows.forEach(row => {const cell = el("th"); cell.append(button(row.title, () => {state.stage2Paper = state.stage2Paper === row.key ? null : row.key; render();})); header.append(cell);});
    head.append(header); table.append(head);
    const body = el("tbody"), fields = [...new Set(rows.flatMap(row => Object.keys(row.cells || {})))];
    fields.forEach(name => {
      const line = el("tr"); line.append(el("th", caption(name)));
      rows.forEach(row => {
        const cell = el("td"), field = row.cells?.[name]; cell.append(source("p", field?.text));
        if (field?.field) disclosure(cell, t("provenance"), field.field);
        line.append(cell);
      }); body.append(line);
    });
    table.append(body); scroll.append(table); selectedPanel.append(scroll);
    const inspected = rows.find(row => row.key === state.stage2Paper);
    if (inspected) {const detail = el("div", undefined, "atlas-stage2-detail"); stage2Detail(detail, inspected); selectedPanel.append(detail);}
    content.append(selectedPanel);
    const focused = selected.slice(focusPage * 4, focusPage * 4 + 4), relationships = panel(t("related"));
    focused.forEach((a, i) => focused.slice(i + 1).forEach(b => {
      const own = model.stage2Papers(payload), pa = own.find(p => p.key === a.key), pb = own.find(p => p.key === b.key), methods = pa && pb ? pa.methods.filter(method => pb.methods.includes(method)) : [];
      const association = !pa?.methods.length || !pb?.methods.length ? t("unknown") : methods.length ? methods.join(" / ") : t("noRelations");
      relationships.append(source("p", `${text(a.title)} ↔ ${text(b.title)} · ${association}`, "atlas-small"));
    })); content.append(relationships);
    relatedRoutes(content, view, selected);
  }
  function candidates(view) {
    const rows = view.directions || [], page = pagination(content, rows.length, 3, "candidatePage"), cards = el("div", undefined, "atlas-cards");
    rows.slice(page * 3, page * 3 + 3).forEach((row, i) => {
      const card = el("article", undefined, "atlas-card"); card.style.setProperty("--category", colors[i % 6]);
      card.append(source("p", `${row.candidate_id} · v${row.version}`, "atlas-small"), source("h3", row.question));
      const bound = (view.evidence || []).filter(item => (row.evidence_ids || []).includes(item.evidence_id));
      const linked = (view.literature || []).filter(paper => evidenceFor(view, paper).some(item => bound.includes(item)));
      if (linked.length) {
        const center = {x: 300, y: 230, label: row.candidate_id, type: "atlas-center", action: () => card.querySelector("details")?.setAttribute("open", "")}, nodes = [center], edges = [];
        linked.slice(0, 6).forEach((paper, i, drawn) => {
          const angle = i * Math.PI * 2 / drawn.length - Math.PI / 2;
          const node = {x: 300 + Math.cos(angle) * 185, y: 230 + Math.sin(angle) * 150, label: paper.work_id, title: paper.title, type: "atlas-paper-node", color: colors[i % 6], action: () => { state.selected = new Set([paper.key]); state.tab = "comparison"; state.comparePage = 0; render(); }};
          nodes.push(node); edges.push([node, center, {kind: "evidence"}]);
        }); graph(card, nodes, edges); card.append(el("p", t("routeGraphNote"), "atlas-small"));
        const all = el("details"); all.append(el("summary", `${t("related")} · ${linked.length}`)); linked.forEach(paper => paperRow(all, paper, () => { state.selected = new Set([paper.key]); state.tab = "comparison"; state.comparePage = 0; render(); })); card.append(all);
      }
      kv(card, [["Opportunity", row.opportunity], ["Value", row.value], ["Approach", row.approach], ["Disposition", row.disposition], ["Reason", row.reason], ["Next step", row.next_step]]);
      disclosure(card, t("checks"), {checks: row.checks, limitations: row.limitations, requirements: row.requirements, prior_work_review: row.prior_work_review});
      const evidence = el("details"); evidence.append(el("summary", `${t("evidence")} · ${(row.evidence_ids || []).length}`));
      (row.evidence_ids || []).forEach(id => {
        const bound = (view.evidence || []).find(e => e.evidence_id === id); disclosure(evidence, id, bound ?? {evidence_id: id, status: "Unknown"});
      }); card.append(evidence); disclosure(card, t("raw"), row); cards.append(card);
    }); content.append(cards);
    disclosure(content, t("checks"), {bridge: payload.stage2?.bridge_receipt, evaluation: payload.stage2?.evaluation, comparison: view.comparison, resources: view.resources, research_tables: view.research_tables});
  }
  function stage2() {
    const process = el("details", undefined, "atlas-panel atlas-process"); process.id = "atlas-process";
    process.open = state.processOpen; process.ontoggle = () => {state.processOpen = process.open;};
    process.append(el("summary", t("process")));
    const bridge = payload.stage2?.bridge_receipt;
    kv(process, [[t("sourceBinding"), bridge ? `${bridge.project_id} · ${bridge.selection_sha256?.slice(0, 16) || t("unknown")}` : null], [t("checks"), payload.stage2_comparison?.comparison]]);
    disclosure(process, t("sourceBinding"), bridge);
    disclosure(process, t("decisionHistory"), {selection: payload.stage2?.selection, prior_work_reviews: payload.stage2_comparison?.prior_work_reviews});
    if (payload.stage2) {
      const evaluation = payload.stage2.evaluation, summary = panel(t("assessment")); summary.id = "atlas-assessment";
      kv(summary, [[t("evaluationStatus"), evaluation?.evaluation_status]]);
      const scores = el("div", undefined, "atlas-actions");
      for (const metric of ["P4", "P5", "P6"]) {
        const dimension = evaluation?.dimensions?.[metric];
        const score = dimension?.score == null ? t("unknown") : `${typeof dimension.score === "number" && Number.isFinite(dimension.score) ? Number(dimension.score.toFixed(1)) : text(dimension.score)}%`;
        const points = `${text(dimension?.sum)}/${text(dimension?.max)}`;
        const pending = evaluation?.evaluation_status === "audit-required" ? ` · ${t("provisional")}` : "";
        scores.append(el("span", `${metric}: ${score} (${points}) · ${text(dimension?.assessed)}/${text(dimension?.required)} ${t("assessed")}${pending}`, "atlas-chip"));
      }
      summary.append(el("p", t("recordedScores"), "atlas-small"), scores);
      const audits = (evaluation?.rows || []).map(row => `${text(row.criterion_id)}: ${text(row.final?.audit_status)}`);
      kv(summary, [[t("auditStatus"), audits.length ? `${audits.length} ${t("auditRecords")}` : null]]);
      disclosure(summary, t("auditStatus"), audits);
      if (evaluation?.evaluation_status === "audit-required") summary.append(el("p", t("auditPending"), "atlas-note"));
      if (evaluation?.evaluation_status === "failed" || !evaluation) summary.append(el("p", t("assessmentFailed"), "atlas-note"));
      summary.append(el("p", t("importNote"), "atlas-small"));
      disclosure(summary, t("assessmentRecords"), payload.stage2); content.append(summary);
    }
    const actions = el("div", undefined, "atlas-actions atlas-tabs");
    for (const [key, label] of [["sets", "directionSets"], ["comparison", "comparison"], ["candidates", "candidates"]]) actions.append(button(t(label), () => { state.tab = key; state.page = 0; state.groupPage = 0; render(); }, state.tab === key)); content.append(actions);
    if (payload.stage2) content.append(link(t(payload.fixture === true ? "simulatedReport" : "report"), "./stage2/report-reader.html"));
    else content.append(el("p", t("missingStage2"), "atlas-note"));
    const view = payload.stage2_comparison;
    if (view && !(view.literature || []).length) content.append(el("p", t("missingLiterature"), "atlas-note"));
    if (view && state.tab === "sets") directionSets();
    else if (view && state.tab === "comparison") comparisons(view);
    else if (view) candidates(view);
    workflow(); content.append(process);
  }
  function later() {
    const stage = (index.stages || []).find(row => row.stage === state.stage), card = panel(t("reserved"));
    card.id = "atlas-process";
    if (!stage) { card.append(el("p", t("unknown"))); content.append(card); return; }
    card.append(source("p", stage.purpose));
    kv(card, [[t("inputs"), stage.required_inputs], [t("outputs"), stage.expected_deliverables], ["Support status", stage.support_status], ["Execution enabled", stage.execution_enabled]]);
    const flow = el("div", undefined, "atlas-flow"); (stage.node_flow || []).forEach(value => flow.append(el("span", caption(value)))); card.append(el("h3", t("flow")), flow, link(t("original"), "./index.html")); content.append(card);
  }
  function contract() {
    const stage = (index.stages || []).find(row => row.stage === state.stage);
    if (!stage) return;
    const box = el("details"); box.append(el("summary", t("flow")));
    const flow = el("div", undefined, "atlas-flow"); (stage.node_flow || []).forEach(name => flow.append(el("span", caption(name)))); box.append(flow);
    kv(box, [[t("inputs"), stage.required_inputs], [t("outputs"), stage.expected_deliverables], ["Support status", stage.support_status], ["Execution enabled", stage.execution_enabled]]); content.append(box);
  }
  function render() {
    if (activeNetwork) {
      state.graphPose[activeNetworkStage] = state.fitNext ? null : activeNetwork.snapshot(); activeNetwork.destroy(); activeNetwork = null;
    }
    state.fitNext = false;
    const included = archive.filter(p => p.selection?.status === "included"), pending = archive.filter(p => p.selection?.status === "pending");
    papers = state.scope === "archive" ? archive : included.length ? included : pending.length ? pending : archive;
    if (!state.paper && !state.graphCleared && papers.length) state.paper = papers[0].key;
    document.documentElement.dataset.atlasStage = String(state.stage);
    document.documentElement.lang = state.language; content.replaceChildren();
    const nav = document.getElementById("atlas-stages"); nav.replaceChildren();
    t("stages").forEach((label, i) => { const control = button("", () => { state.stage = i + 1; state.groupPage = 0; state.page = 0; render(); }, state.stage === i + 1); control.append(el("span", i + 1, "atlas-stage-number"), el("span", label)); nav.append(control); });
    document.getElementById("atlas-language-label").textContent = t("language");
    document.getElementById("atlas-original").textContent = t("original");
    document.getElementById("atlas-project").textContent = text(index.topic); document.getElementById("atlas-project").translate = false;
    document.getElementById("atlas-status").textContent = `${index.project_id} · ${index.status}`;
    document.getElementById("atlas-footer").textContent = `${t("readOnly")} · SHA-256 ${payload.index_sha256}`;
    const heading = el("div", undefined, "atlas-heading"); heading.append(el("p", `STAGE 0${state.stage} / 06 · ${t("stages")[state.stage - 1]}`, "atlas-eyebrow"), el("h1", state.stage === 1 ? t("networkTitle") : state.stage === 2 ? t("stage2Title") : t("stages")[state.stage - 1]));
    if (state.stage === 1) heading.append(el("p", t("networkSubtitle"), "atlas-subtitle")); content.append(heading);
    if (payload.fixture === true) content.append(el("p", t("fixtureNotice"), "atlas-note atlas-fixture-notice"));
    if (state.stage === 1) stage1(); else if (state.stage === 2) stage2(); else later();
    if (state.stage <= 2) contract();
  }
  for (const [id, label] of [["atlas-view-workbench", "workbench"], ["atlas-view-files", "files"], ["atlas-view-history", "history"], ["atlas-view-settings", "settings"]]) {
    const control = document.getElementById(id); if (!control) continue;
    if (id === "atlas-view-files") control.onclick = event => { event.preventDefault(); state.stage = 1; render(); document.getElementById("atlas-exports")?.scrollIntoView({behavior: "smooth"}); };
    if (id === "atlas-view-history") control.onclick = event => { event.preventDefault(); if (state.stage > 2) state.stage = 1; state.processOpen = true; render(); document.getElementById("atlas-process")?.scrollIntoView({behavior: "smooth"}); };
    control.dataset.atlasLabel = label;
  }
  const originalRender = render;
  function refresh() { originalRender(); document.querySelectorAll("[data-atlas-label]").forEach(control => { const label = control.querySelector("span"); if (label) label.textContent = t(control.dataset.atlasLabel); }); }
  languageControl.onchange = event => { state.language = interfaceLanguage(event.target.value); languageControl.value = state.language; refresh(); };
  refresh();
})();
