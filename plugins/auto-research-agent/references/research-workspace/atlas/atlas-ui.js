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
  const state = {language: "en", stage: 1, scope: "working", sort: "recorded", mode: "library", topic: "", method: "", pair: [], paper: null, page: 0, graphPage: 0, groupPage: 0, neighborsPage: 0, text: "", status: "", tab: "sets", selected: new Set(), comparePage: 0, candidatePage: 0, libraryOpen: false};
  const locale = () => ["en", "zh-Hans", "zh-Hant"].indexOf(state.language);
  const t = name => words[name]?.[locale()] ?? name;
  const caption = name => fieldLabels[name]?.[locale()] ?? name;
  const text = value => value == null || value === "" ? t("unknown") : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
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
    state.paper = key; state.mode = "paper"; state.neighborsPage = 0; render();
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
    control.append(source("span", `${t("relevance")}: ${text(paper.findings?.relevance)}`, "atlas-small"));
    row.append(control); parent.append(row); return row;
  }
  function contextRows() {
    let rows = state.mode === "topic" ? papers.filter(p => p.topics.includes(state.topic)) : state.mode === "shared" ? model.intersection(papers, state.pair) : state.mode === "unknown" ? papers.filter(p => !p.topics.length) : papers;
    return state.method ? rows.filter(p => p.methods.includes(state.method)) : rows;
  }
  function graph(parent, nodes, edges) {
    const box = el("div", undefined, "atlas-graph"), svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 600 470"); svg.setAttribute("aria-hidden", "true");
    edges.forEach(([a, b]) => {
      const line = document.createElementNS(svg.namespaceURI, "line");
      Object.entries({x1: a.x, y1: a.y, x2: b.x, y2: b.y}).forEach(([name, value]) => line.setAttribute(name, value)); svg.append(line);
    });
    box.append(svg);
    nodes.forEach(node => {
      const control = button("", node.action); control.className = `atlas-node ${node.type || ""}`;
      control.style.left = `${node.x / 6}%`; control.style.top = `${node.y / 4.7}%`; control.style.setProperty("--category", node.color || colors[0]);
      control.append(source("span", node.label)); if (node.count !== undefined) control.append(el("strong", node.count));
      control.title = text(node.label);
      control.setAttribute("aria-label", `${text(node.label)} ${node.count ?? ""}`); box.append(control);
    }); parent.append(box);
  }
  function groupGraph(parent) {
    const topicMode = state.mode === "topic", rows = topicMode ? papers.filter(p => p.topics.includes(state.topic)) : papers;
    const groups = model.groups(rows, topicMode ? "methods" : "topics"), page = pagination(parent, groups.length, 6, "groupPage"), shown = groups.slice(page * 6, page * 6 + 6);
    const center = {x: 300, y: 235, label: topicMode ? state.topic : t("library"), count: rows.length, type: "atlas-center", action: () => changeContext("library")};
    const nodes = [center], edges = [];
    shown.forEach((group, i) => {
      const angle = i * Math.PI * 2 / Math.max(shown.length, 1) - Math.PI / 2;
      const node = {x: 300 + Math.cos(angle) * 205, y: 235 + Math.sin(angle) * 165, label: group.label, count: group.ids.length, color: colors[(page * 6 + i) % 6], type: topicMode ? "atlas-method" : "", action: () => { if (topicMode) { state.method = group.key; state.graphPage = 0; render(); } else changeContext("topic", group.key); }};
      nodes.push(node); edges.push([center, node]);
    });
    graph(parent, nodes, edges); parent.append(el("p", t("graphNote"), "atlas-small"));
    const all = el("details"), buttons = el("div", undefined, "atlas-actions"); all.append(el("summary", `${t("allGroups")} · ${groups.length}`));
    groups.forEach(group => buttons.append(button(`${group.label} · ${group.ids.length}`, () => { if (topicMode) { state.method = group.key; state.graphPage = 0; render(); } else changeContext("topic", group.key); })));
    all.append(buttons); parent.append(all);
    if (!topicMode) {
      parent.append(button(`${t("unclassified")} · ${papers.filter(p => !p.topics.length).length}`, () => changeContext("unknown")));
      const shared = el("details"), pairs = el("div", undefined, "atlas-actions"); shared.append(el("summary", t("shared")));
      shown.forEach((a, i) => shown.slice(i + 1).forEach(b => {
        const count = model.intersection(papers, [a.key, b.key]).length;
        if (count) pairs.append(button(`${a.label} × ${b.label} · ${count}`, () => { state.pair = [a.key, b.key]; changeContext("shared"); }));
      })); shared.append(pairs); parent.append(shared);
    }
  }
  function paperGraph(parent, paper) {
    const neighbors = model.local(papers, paper.key).filter(row => row.similarity > 0), n = neighbors.length;
    let indices = n <= 6 ? neighbors.map((_, i) => i) : [0, 1, Math.floor(n / 2) - 1, Math.floor(n / 2), n - 2, n - 1];
    if (window.innerWidth < 700 && indices.length > 3) indices = [indices[0], indices[Math.floor(indices.length / 2)], indices.at(-1)];
    const center = {x: 300, y: 220, label: paper.work_id, type: "atlas-center atlas-paper-node", action: () => choosePaper(paper.key)};
    const nodes = [center], edges = [];
    indices.forEach((index, i) => {
      const related = neighbors[index], angle = i * Math.PI * 2 / Math.max(indices.length, 1) - Math.PI / 2, distance = 95 + 90 * (1 - related.similarity);
      const node = {x: 300 + Math.cos(angle) * distance, y: 220 + Math.sin(angle) * distance, label: related.paper.work_id, type: "atlas-paper-node", color: colors[i % 6], action: () => choosePaper(related.paper.key)};
      nodes.push(node); edges.push([center, node]);
    });
    graph(parent, nodes, edges); parent.append(el("p", t("localNote"), "atlas-small"));
    if (!n) parent.append(el("p", t("noRelations"), "atlas-note"));
    const list = el("details"); list.append(el("summary", `${t("related")} · ${n}`));
    const page = pagination(list, n, 6, "neighborsPage");
    neighbors.slice(page * 6, page * 6 + 6).forEach(row => {
      paperRow(list, row.paper); list.append(el("p", `Jaccard ${(row.similarity * 100).toFixed(1)}%`, "atlas-small"));
    }); parent.append(list);
  }
  function paperDetail(parent, paper) {
    parent.append(source("h3", paper.title));
    kv(parent, [["Work / version", [paper.work_id, paper.version_id]], ["Authors", paper.authors], ["Year / venue", [paper.year, paper.venue]], [t("status"), `${paper.selection?.status ?? t("unknown")} · ${(paper.selection?.reasons || []).join(" / ")}`], ["Evidence level", paper.evidence_level]]);
    disclosure(parent, t("status"), paper.selection);
    parent.append(el("h3", t("findings")));
    kv(parent, ["question", "data", "method", "main_findings", "limitations", "relevance", "transferability"].map((name, i) => [t("fields")[i], paper.findings?.[name]]));
    const access = el("details"); access.append(el("summary", t("access")));
    const url = safeUrl(paper.url); if (url) access.append(link(t("publicLink"), url));
    kv(access, [["Recorded URL", paper.url], ["Recorded DOI", paper.doi], ["Source IDs", paper.source_ids]]);
    const rerun = index.source_rerun;
    (rerun?.data?.rows || []).filter(row => row.work_id === paper.work_id && row.version_id === paper.version_id && paper.source_ids?.includes(row.source_id)).forEach(row => {
      const path = row.raw_path, accepted = typeof path === "string" && /^sources\/[A-Za-z0-9_-]+\/raw\.(pdf|html)$/.test(path);
      if (accepted && rerun.artifact_hashes?.[path]?.sha256 === row.raw_sha256) access.append(link(`${t("savedSource")} · ${row.source_id}`, `./source-rerun/${path}`));
    });
    if (typeof paper.notePath === "string" && /^wiki\/[a-f0-9]{64}\.md$/.test(paper.notePath)) access.append(link(t("note"), `./${paper.notePath}`, true));
    disclosure(access, t("sources"), paper.sources); parent.append(access);
    const ledger = el("details"); ledger.append(el("summary", t("ledger")));
    kv(ledger, [[t("discovery"), null]]); ledger.append(el("p", t("discoveryNote"), "atlas-small"));
    (paper.screening || []).forEach(row => { const item = el("section", undefined, "atlas-note"); kv(item, [["Decision", row.decision_id], ["Status", row.status], ["Reason", row.reason], ["Query", row.query], ["Discovery path", row.discovery_path], ["Observed at", row.observed_at]]); disclosure(item, t("raw"), row); ledger.append(item); });
    disclosure(ledger, t("searchRecords"), paper.rawSearch); parent.append(ledger);
    disclosure(parent, t("claims"), {claims: paper.claims, relations: paper.relations});
    disclosure(parent, t("provenance"), {project_id: index.project_id, index_sha256: payload.index_sha256, provenance: index.provenance, work_id: paper.work_id, version_id: paper.version_id, source_ids: paper.source_ids});
    disclosure(parent, t("raw"), index.papers.find(row => model.key(row) === paper.key));
  }
  function choice(label, value, options, action) {
    const field = el("label", label), select = el("select");
    options.forEach(([key, caption]) => { const option = source("option", caption); option.value = key; select.append(option); });
    select.value = value; select.onchange = () => action(select.value); field.append(select); return field;
  }
  function stage1() {
    const scope = el("div", undefined, "atlas-actions atlas-tabs"), included = archive.filter(p => p.selection?.status === "included"), pending = archive.filter(p => p.selection?.status === "pending");
    scope.append(button(`${t("working")} · ${(included.length ? included : pending.length ? pending : archive).length}`, () => { state.scope = "working"; changeContext("library"); }, state.scope === "working"), button(`${t("archive")} · ${archive.length}`, () => { state.scope = "archive"; changeContext("library"); }, state.scope === "archive")); content.append(scope);
    if (state.scope === "working" && !included.length) content.append(el("p", t(pending.length ? "noIncluded" : "archiveFallback"), "atlas-note"));
    const actions = el("div", undefined, "atlas-actions"); actions.append(button(t("library"), () => changeContext("library")));
    if (state.topic) actions.append(source("span", state.topic, "atlas-small")); if (state.method) actions.append(source("span", state.method, "atlas-small")); content.append(actions);
    const split = el("div", undefined, "atlas-split"), graphPanel = panel(state.mode === "paper" ? t("related") : t("topics")), detailPanel = panel(state.mode === "paper" ? t("detail") : t("library"));
    const selected = papers.find(p => p.key === state.paper);
    if (state.mode === "paper" && selected) { paperGraph(graphPanel, selected); paperDetail(detailPanel, selected); }
    else {
      groupGraph(graphPanel); const rows = contextRows(), page = pagination(detailPanel, rows.length, 6, "graphPage");
      ordered(rows).slice(page * 6, page * 6 + 6).forEach(p => paperRow(detailPanel, p));
    }
    split.append(graphPanel, detailPanel); content.append(split);
    const library = el("details"); library.id = "atlas-library"; library.open = state.libraryOpen; library.ontoggle = () => { state.libraryOpen = library.open; }; library.append(el("summary", `${t("library")} · ${papers.length}`));
    const filters = el("div", undefined, "atlas-filters"), search = el("label", t("search")), input = el("input"); input.value = state.text; input.type = "search"; input.onchange = () => { state.text = input.value; state.page = 0; render(); }; search.append(input); filters.append(search);
    filters.append(choice(t("topics"), state.topic, [["", t("all")], ...model.groups(papers, "topics").map(g => [g.key, g.label])], value => { state.topic = value; state.mode = value ? "topic" : "library"; state.page = 0; render(); }));
    filters.append(choice(t("methods"), state.method, [["", t("all")], ...model.groups(papers, "methods").map(g => [g.key, g.label])], value => { state.method = value; state.page = 0; render(); }));
    filters.append(choice(t("status"), state.status, ["", "included", "pending", "excluded", "unbound"].map(key => [key, t(key || "all")]), value => { state.status = value; state.page = 0; render(); })); library.append(filters);
    const sorting = choice(t("sorting"), state.sort, [["recorded", t("originalOrder")], ["title", t("titleOrder")], ["year", t("yearOrder")], ["relevance", t("relevanceOrder")]], value => { state.sort = value; render(); }); sorting.querySelector('option[value="relevance"]').disabled = true; library.append(sorting);
    const rows = model.filter(papers, {text: state.text, topic: state.topic, method: state.method, status: state.status}), page = pagination(library, rows.length, 12, "page");
    ordered(rows).slice(page * 12, page * 12 + 12).forEach(p => paperRow(library, p)); content.append(library);
    if (state.scope === "archive") { content.append(el("p", t("archiveNote"), "atlas-small")); disclosure(content, t("searchRecords"), index.search || []); }
    const downloads = panel(t("exports")), links = el("div", undefined, "atlas-actions");
    links.append(link(t("bib"), "./references.bib", true), link(t("screeningBib"), "./literature/screening.bib", true), link(t("includedBib"), "./literature/included.bib", true), link(t("original"), "./index.html")); downloads.append(links); content.append(downloads);
  }
  function directionSets() {
    const rows = model.stage2Papers(payload), groups = model.groups(rows, "topics"), cards = el("div", undefined, "atlas-cards"), page = pagination(content, groups.length, 6, "groupPage");
    const maximum = Math.max(1, ...groups.map(g => g.ids.length));
    groups.slice(page * 6, page * 6 + 6).forEach((group, i) => {
      const card = el("article", undefined, "atlas-card"); card.style.setProperty("--category", colors[i % 6]);
      card.append(button(group.label, () => { state.selected = new Set(group.ids); state.tab = "comparison"; state.comparePage = 0; render(); }), el("p", `${group.ids.length} ${t("records")}`, "atlas-tally"));
      const track = el("div", undefined, "atlas-track"), fill = el("span"); fill.style.width = `${group.ids.length / maximum * 100}%`; track.append(fill); card.append(track); cards.append(card);
    }); content.append(el("p", t("setNote"), "atlas-note"), cards);
    const shared = panel(t("shared"));
    groups.slice(page * 6, page * 6 + 6).forEach((a, i, shown) => shown.slice(i + 1).forEach(b => {
      const matched = model.intersection(rows, [a.key, b.key]);
      if (matched.length) shared.append(button(`${a.label} × ${b.label} · ${matched.length}`, () => { state.selected = new Set(matched.map(p => p.key)); state.tab = "comparison"; state.comparePage = 0; render(); }));
    })); content.append(shared);
  }
  function comparisons(view) {
    const literature = view.literature || [], library = panel(t("comparison")), page = pagination(library, literature.length, 8, "page");
    content.append(el("p", t("compareNote"), "atlas-note"));
    literature.slice(page * 8, page * 8 + 8).forEach(row => {
      const field = el("label", undefined, "atlas-check"), input = el("input"); input.type = "checkbox"; input.checked = state.selected.has(row.key);
      input.onchange = () => { if (input.checked) state.selected.add(row.key); else state.selected.delete(row.key); state.comparePage = 0; render(); };
      field.append(input, source("span", row.title)); library.append(field);
    }); library.append(button(t("clear"), () => { state.selected.clear(); render(); })); content.append(library);
    const selected = literature.filter(row => state.selected.has(row.key)), selectedPanel = panel(`${t("selected")} · ${selected.length}`), focusPage = pagination(selectedPanel, selected.length, 4, "comparePage"), cards = el("div", undefined, "atlas-cards atlas-comparison");
    selected.slice(focusPage * 4, focusPage * 4 + 4).forEach(row => {
      const card = el("article", undefined, "atlas-card"); card.append(source("h3", row.title));
      kv(card, [["Work / version", [row.work_id, row.version_id]], ["Evidence level", row.evidence_level]]);
      Object.entries(row.cells || {}).forEach(([name, cell]) => { const field = el("details"); field.append(el("summary", caption(name)), source("p", cell?.text), source("small", cell?.field)); card.append(field); });
      disclosure(card, t("evidence"), (view.evidence || []).filter(e => (row.evidence_ids || []).includes(e.evidence_id)));
      disclosure(card, t("raw"), row); cards.append(card);
    }); selectedPanel.append(cards); content.append(selectedPanel);
    const focused = selected.slice(focusPage * 4, focusPage * 4 + 4), relationships = panel(t("related"));
    focused.forEach((a, i) => focused.slice(i + 1).forEach(b => {
      const own = model.stage2Papers(payload), pa = own.find(p => p.key === a.key), pb = own.find(p => p.key === b.key), methods = pa && pb ? pa.methods.filter(method => pb.methods.includes(method)) : [];
      const association = !pa?.methods.length || !pb?.methods.length ? t("unknown") : methods.length ? methods.join(" / ") : t("noRelations");
      relationships.append(source("p", `${text(a.title)} ↔ ${text(b.title)} · ${association}`, "atlas-small"));
    })); content.append(relationships);
  }
  function candidates(view) {
    const rows = view.directions || [], page = pagination(content, rows.length, 3, "candidatePage"), cards = el("div", undefined, "atlas-cards");
    rows.slice(page * 3, page * 3 + 3).forEach((row, i) => {
      const card = el("article", undefined, "atlas-card"); card.style.setProperty("--category", colors[i % 6]);
      card.append(source("p", `${row.candidate_id} · v${row.version}`, "atlas-small"), source("h3", row.question));
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
    if (payload.stage2) {
      const evaluation = payload.stage2.evaluation, summary = panel(t("assessment")); summary.id = "atlas-assessment";
      kv(summary, [[t("evaluationStatus"), evaluation?.evaluation_status]]);
      const scores = el("div", undefined, "atlas-actions");
      for (const metric of ["P4", "P5", "P6"]) {
        const dimension = evaluation?.dimensions?.[metric];
        scores.append(el("span", `${metric}: ${text(dimension?.score)} · ${text(dimension?.assessed)}/${text(dimension?.required)} ${t("assessed")}`, "atlas-chip"));
      }
      summary.append(el("p", t("recordedScores"), "atlas-small"), scores);
      const audits = (evaluation?.rows || []).map(row => `${text(row.criterion_id)}: ${text(row.final?.audit_status)}`);
      kv(summary, [[t("auditStatus"), audits.length ? audits.join(" · ") : null]]);
      if (evaluation?.evaluation_status === "audit-required") summary.append(el("p", t("auditPending"), "atlas-note"));
      if (evaluation?.evaluation_status === "failed" || !evaluation) summary.append(el("p", t("assessmentFailed"), "atlas-note"));
      summary.append(el("p", t("importNote"), "atlas-small"));
      disclosure(summary, t("assessmentRecords"), payload.stage2); content.append(summary);
    }
    const actions = el("div", undefined, "atlas-actions atlas-tabs");
    for (const [key, label] of [["sets", "directionSets"], ["comparison", "comparison"], ["candidates", "candidates"]]) actions.append(button(t(label), () => { state.tab = key; state.page = 0; state.groupPage = 0; render(); }, state.tab === key)); content.append(actions);
    if (payload.stage2) content.append(link(t("report"), "./stage2/report-reader.html"));
    else content.append(el("p", t("missingStage2"), "atlas-note"));
    const view = payload.stage2_comparison;
    if (view && !(view.literature || []).length) content.append(el("p", t("missingLiterature"), "atlas-note"));
    if (view && state.tab === "sets") directionSets();
    else if (view && state.tab === "comparison") comparisons(view);
    else if (view) candidates(view);
  }
  function later() {
    const stage = (index.stages || []).find(row => row.stage === state.stage), card = panel(t("reserved"));
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
    const included = archive.filter(p => p.selection?.status === "included"), pending = archive.filter(p => p.selection?.status === "pending");
    papers = state.scope === "archive" ? archive : included.length ? included : pending.length ? pending : archive;
    document.documentElement.lang = state.language; content.replaceChildren();
    const nav = document.getElementById("atlas-stages"); nav.replaceChildren();
    t("stages").forEach((label, i) => nav.append(button(`${i + 1}  ${label}`, () => { state.stage = i + 1; state.groupPage = 0; state.page = 0; render(); }, state.stage === i + 1)));
    document.getElementById("atlas-language-label").textContent = t("language");
    document.getElementById("atlas-original").textContent = t("original");
    document.getElementById("atlas-project").textContent = text(index.topic); document.getElementById("atlas-project").translate = false;
    document.getElementById("atlas-status").textContent = `${index.project_id} · ${index.status}`;
    document.getElementById("atlas-footer").textContent = `${t("readOnly")} · SHA-256 ${payload.index_sha256}`;
    const heading = el("div", undefined, "atlas-heading"); heading.append(el("p", `STAGE 0${state.stage} / 06`, "atlas-eyebrow"), el("h1", t("stages")[state.stage - 1])); content.append(heading);
    if (state.stage === 1) stage1(); else if (state.stage === 2) stage2(); else later();
    if (state.stage <= 2) contract();
  }
  document.getElementById("atlas-language").onchange = event => { state.language = event.target.value; render(); };
  render();
})();
