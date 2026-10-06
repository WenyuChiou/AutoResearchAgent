/* Read-only adapter for WorkspaceIndex. Research values are never translated. */
(() => {
  "use strict";
  const i18n = window.WorkspaceI18n, payload = window.WORKSPACE_VIEW, index = payload.index;
  i18n.extend([
    ["BOUND SOURCE RECORDS · READ-ONLY · EXECUTOR NOT CONNECTED", "已绑定来源记录 · 只读 · 未连接执行器", "已綁定來源紀錄 · 唯讀 · 未連線執行器"],
    ["Read the original package without changing its evidence, judgments or execution state.", "浏览原包，保留其证据、判断和执行状态。", "瀏覽原套件，保留其證據、判斷和執行狀態。"],
    ["Read-only package view", "原包只读视图", "原套件唯讀檢視"],
    ["Read-only projection of the original package. Source access and claim judgments remain unchanged.", "原包的只读投影，来源访问状态与主张判断保持不变。", "原套件的唯讀投影，來源存取狀態與主張判斷保持不變。"],
    ["Stage 1 / Bound literature records", "Stage 1 / 已绑定文献记录", "Stage 1 / 已綁定文獻紀錄"],
    ["Graph & list", "图谱与列表", "圖譜與清單"], ["Catalog", "文献目录", "文獻目錄"], ["Notes", "笔记", "筆記"],
    ["Save Markdown note", "保存 Markdown 笔记", "儲存 Markdown 筆記"],
    ["Sources & provenance", "来源与溯源", "來源與溯源"], ["Coverage & screening", "覆盖与筛选", "涵蓋與篩選"],
    ["Index binding", "索引绑定", "索引綁定"], ["Source records", "来源记录", "來源紀錄"], ["Claim records", "主张记录", "主張紀錄"],
    ["Original audit documents", "原始核查文档", "原始核查文件"],
    ["Saved findings", "已保存研究内容", "已儲存研究內容"], ["Top-3 supplement is pending.", "Top-3 补充材料待提供。", "Top-3 補充材料待提供。"],
    ["Question", "问题", "問題"], ["Data", "数据", "資料"], ["Method", "方法", "方法"], ["Main findings", "主要发现", "主要發現"], ["Limitations", "限制", "限制"], ["Relevance", "相关性", "相關性"], ["Transferability", "可迁移性", "可遷移性"], ["Unresolved claim records", "尚未解决的主张记录", "尚未解決的主張紀錄"],
    ["Export canonical .bib", "导出 canonical .bib", "匯出 canonical .bib"], ["Bibliography scope", "参考文献范围", "參考文獻範圍"],
    ["All indexed records", "索引全部文献", "索引全部文獻"], ["Filtered records", "当前筛选文献", "目前篩選文獻"],
    ["Classification", "分类", "分類"], ["Classifications", "分类", "分類"], ["All classifications", "全部分类", "全部分類"],
    ["No records match these filters.", "没有匹配记录。", "沒有符合紀錄。"],
    ["Browse a small Obsidian-like graph and complete bibliographic list. Edges show recorded assignments only; this view does not assert similarity, citation, evidence support, coverage, or quality.", "浏览全部文献及完整书目。连线只表示原包记录的分类和角色，不代表相似度、引用或科学质量。", "瀏覽全部文獻及完整書目。連線僅表示原套件記錄的分類和角色，不代表相似度、引用或科學品質。"],
    ["Lines mean an explicit keyword or role assignment. No paper-to-paper citation edges are recorded.", "连线仅表示原记录的分类或角色，不是文献间的引用关系。", "連線僅表示原紀錄的分類或角色，並非文獻間的引用關係。"],
    ["Inputs", "输入", "輸入"], ["Expected outputs", "预期输出", "預期輸出"], ["Blocked · execution disconnected", "阻塞 · 未连接执行器", "阻塞 · 未連線執行器"],
    ["A reviewed handoff from the preceding stage is required.", "需要上一阶段已审阅的交接包。", "需要前一階段已審閱的交接套件。"],
    ["No new research deliverable is created by this view.", "此视图不生成新的科研交付。", "此檢視不產生新的研究交付。"],
    ["Comparison & direction records", "比较与研究方向记录", "比較與研究方向紀錄"], ["Design & feasibility records", "设计与可行性记录", "設計與可行性紀錄"],
    ["Execution records", "实验执行记录", "實驗執行紀錄"], ["Analysis & figures", "分析与图表", "分析與圖表"], ["Manuscript & citations", "论文与引用", "論文與引用"],
    ["Literature and Evidence", "文献与证据", "文獻與證據"], ["Comparison and Gap", "比较与缺口", "比較與缺口"], ["Design and Feasibility", "设计与可行性", "設計與可行性"], ["Experiment Execution", "实验执行", "實驗執行"], ["Analysis and Figures", "分析与图表", "分析與圖表"], ["Writing and Submission", "写作与投稿", "寫作與投稿"],
    ["Find and preserve source-bound literature.", "查找并保存绑定来源的文献。", "查找並保存綁定來源的文獻。"], ["Compare evidence and retain unresolved research opportunities.", "比较证据并保留未解决的研究机会。", "比較證據並保留未解決的研究機會。"], ["Turn a reviewed direction into a bounded research design.", "将已审阅方向转为有界研究设计。", "將已審閱方向轉為有界研究設計。"],
    ["Execute the approved design and retain raw outcomes and failures.", "执行已批准设计并保留原始结果与失败。", "執行已核准設計並保留原始結果與失敗。"], ["Analyze validated outcomes with uncertainty and provenance.", "分析已验证结果，保留不确定性和来源。", "分析已驗證結果，保留不確定性和來源。"], ["Write from reviewed evidence and preserve publication decisions.", "依据已审阅证据写作并保留发表决定。", "依據已審閱證據寫作並保留發表決定。"],
    ["Confirmed research brief", "已确认研究简报", "已確認研究簡報"], ["Search intake", "检索输入", "檢索輸入"], ["Resources", "资源", "資源"], ["Literature package", "文献包", "文獻套件"], ["Claims", "主张", "主張"], ["Search and coverage records", "检索与覆盖记录", "檢索與涵蓋紀錄"],
    ["Accepted Stage 1 input route", "已接受的 Stage 1 输入路径", "已接受的 Stage 1 輸入路徑"], ["Confirmed brief", "已确认简报", "已確認簡報"], ["Comparison", "比较", "比較"], ["Candidates", "候选方向", "候選方向"], ["Independent assessment", "独立评估", "獨立評估"], ["User direction decision", "用户方向决定", "使用者方向決定"],
    ["Reviewed comparison", "已审阅比较", "已審閱比較"], ["Explicit direction choice", "明确方向选择", "明確方向選擇"], ["Design", "设计", "設計"], ["Feasibility checks", "可行性检查", "可行性檢查"], ["Experiment plan", "实验计划", "實驗計畫"], ["Approved design", "已批准设计", "已核准設計"], ["Execution authority", "执行授权", "執行授權"],
    ["Raw results", "原始结果", "原始結果"], ["Failures", "失败记录", "失敗紀錄"], ["Validated execution records", "已验证执行记录", "已驗證執行紀錄"], ["Figures", "图表", "圖表"], ["Uncertainty records", "不确定性记录", "不確定性紀錄"], ["Reviewed evidence", "已审阅证据", "已審閱證據"], ["Manuscript", "论文稿件", "論文稿件"], ["Submission artifacts", "投稿材料", "投稿材料"],
  ]);
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  const source = (tag, value, cls) => { const el = make(tag, value === null || value === undefined ? "unknown" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value), cls); el.translate = false; return el; };
  const displayMetadata = value => value === null || value === undefined || value === "" ? "Not recorded" : value;
  const updateTitle = () => { document.title = `${i18n.t("Research Workspace")} | ${i18n.t("Read-only package view")}`; };
  const identity = paper => encodeURIComponent(paper.work_id) + "~" + encodeURIComponent(paper.version_id);
  const safeArtifactId = value => typeof value === "string" && value.length > 0 && !/[\\:%?#\u0000-\u001f]/.test(value) && !value.startsWith("/") && value.split("/").every(part => part && part !== "." && part !== "..");
  const rawSection = (root, title, value) => { const section = make("details"); section.append(make("summary", title), source("pre", value)); root.append(section); };
  const stages = index.stages;
  const views = [["graph", "Graph & list"], ["catalog", "Catalog"], ["notes", "Notes"], ["sources", "Sources & provenance"], ["coverage", "Coverage & screening"]];
  if (window.WorkspaceRepair) views.push(["repairs", "Accepted repairs & core findings"]);
  const records = index.papers.map(p => ({workId: identity(p), identity: `${p.work_id} / ${p.version_id}`, shortTitle: p.work_id, title: displayMetadata(p.title), authors: p.authors.length ? p.authors.map(displayMetadata) : ["Not recorded"], year: displayMetadata(p.year), journal: displayMetadata(p.venue), volume: p.volume ?? null, issue: p.issue ?? null, pages: p.pages ?? null, doi: p.doi, sourceStatus: `${p.evidence_level} · ${p.source_ids.map(id => index.sources.find(s => s.source_id === id)?.receipt?.status ?? "unknown").join(", ") || "unknown"}`, classifications: p.classification?.topic_cluster ? [p.classification.topic_cluster] : [], roles: (p.roles || []).map(r => ({name: r.role, basis: r.reason})), original: p}));
  const state = {stage: 1, view: "graph", selected: records[0]?.workId || null, filters: {text:"",keyword:"",role:""}, scope:"filtered"};
  function bibliography(visible, scope) {
    if (scope === "all") return index.bibliography.all_bibtex;
    const chosen = new Set(visible.map(p => p.workId));
    return index.bibliography.entries.filter(entry => chosen.has(identity(entry))).map(entry => entry.bibtex.trimEnd()).join("\n\n") + "\n";
  }
  function download(visible) {
    const url = URL.createObjectURL(new Blob([bibliography(visible, state.scope)], {type:"application/x-bibtex;charset=utf-8"}));
    const link = make("a"); link.href = url; link.download = `references-${state.scope}.bib`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  function details(root, record) {
    const paper = record.original, matching = row => row.work_id === paper.work_id && (!row.version_id || row.version_id === paper.version_id);
    root.dataset.selectedWork = paper.work_id; root.dataset.selectedVersion = paper.version_id;
    rawSection(root, "Complete metadata", paper);
    rawSection(root, "Source records", index.sources.filter(row => paper.source_ids.includes(row.source_id)));
    rawSection(root, "Claim records", index.claims.filter(matching));
    note(root, paper);
    rawSection(root, "Unresolved claim records", index.claims.filter(matching).filter(row => row.relation !== "supports"));
    rawSection(root, "Sources & provenance", index.edges.filter(matching));
  }
  function note(root, paper) {
    if (window.WorkspaceRepair) root.append(make("p", "Original package findings (historical). Accepted repairs appear below where available.", "original-findings-label"));
    const fields = make("dl"); fields.dataset.workId = paper.work_id; fields.dataset.versionId = paper.version_id;
    for (const [key, label] of [["question","Question"],["data","Data"],["method","Method"],["main_findings","Main findings"],["limitations","Limitations"],["relevance","Relevance"],["transferability","Transferability"]]) fields.append(make("dt", label), source("dd", paper.findings?.[key]));
    root.append(fields);
    window.WorkspaceRepair?.note(root, paper);
    const saved = payload.note_paths?.find(row => row.work_id === paper.work_id && row.version_id === paper.version_id);
    if (saved && /^wiki\/[a-f0-9]{64}\.md$/.test(saved.path)) {
      const link = make("a", "Save Markdown note"); link.href = "./" + saved.path; link.download = saved.path.split("/")[1];
      link.dataset.noteWork = paper.work_id; link.dataset.noteVersion = paper.version_id; root.append(link);
      if (typeof saved.text === "string") link.onclick = event => { event.preventDefault(); const url = URL.createObjectURL(new Blob([saved.text], {type:"text/markdown;charset=utf-8"})); const copy = make("a"); copy.href = url; copy.download = link.download; copy.click(); setTimeout(() => URL.revokeObjectURL(url), 0); };
    }
  }
  function library(root) {
    window.LiteratureReference.render(root, records, {selectedId:state.selected, filters:state.filters, select:id => {state.selected = id;}, detail:details, export:download});
    const scope = make("select"); scope.id = "bibliographyScope"; scope.setAttribute("aria-label", "Bibliography scope");
    for (const [value, label] of [["filtered", "Filtered records"], ["all", "All indexed records"]]) { const option = make("option", label); option.value = value; scope.append(option); }
    scope.value = state.scope; scope.onchange = () => {state.scope = scope.value;}; root.querySelector(".lit-actions").prepend(scope);
    root.querySelectorAll("[data-literature-filter]").forEach(control => { const save = () => {state.filters[control.dataset.literatureFilter] = control.value;}; control.addEventListener("input", save); control.addEventListener("change", save); });
    if (state.view === "catalog") { root.querySelectorAll(".graph-actions,.graph-frame,.graph-legend,.paper-list").forEach(el => {el.hidden = true;}); root.querySelectorAll(":scope > .section-title").forEach(el => {el.hidden = !el.nextElementSibling?.matches(".paper-detail,.metadata-scroll");}); }
    if (state.view === "graph") window.WorkspaceRepair?.graph(root);
  }
  function render() {
    const stage2 = $("stage2-delivery");
    const showDelivery = state.stage === 2 && Boolean(stage2 && payload.stage2);
    if (stage2) stage2.hidden = !showDelivery;
    const main = document.querySelector("main");
    if (main) main.hidden = showDelivery;
    $("stageRail").replaceChildren();
    stages.forEach(stage => { const button = make("button", undefined, `stage ${state.stage === stage.stage ? "active" : "locked"}`); button.append(make("b", `STAGE ${stage.stage}`), make("span", stage.label)); button.setAttribute("aria-pressed", String(state.stage === stage.stage)); button.onclick = () => {state.stage = stage.stage; render();}; $("stageRail").append(button); });
    const tabs = document.querySelector(".view-tabs"); tabs.hidden = showDelivery; tabs.replaceChildren(); $("nodeList").replaceChildren();
    for (const [value, label] of views) { const button = make("button", label, `view-tab${state.view === value ? " active" : ""}`); button.dataset.workspaceView = value; button.disabled = state.stage !== 1; button.onclick = () => {state.view = value; render();}; tabs.append(button); }
    $("outlineTitle").textContent = "Index binding";
    if (window.WorkspaceRepair) {
      const binding = make("details", undefined, "project-binding"), summary = make("summary");
      summary.append(make("span", "Project & version"), source("small", index.status, "binding-status"));
      binding.append(summary, source("p", index.project_id), source("p", index.topic));
      $("nodeList").append(binding, make("p", "Blocked · execution disconnected", "binding-execution"));
    } else $("nodeList").append(source("p", index.project_id), source("p", index.topic), source("small", index.status), make("p", "Blocked · execution disconnected"));
    const root = $("article"); root.replaceChildren(); root.classList.remove("literature-shell");
    if (state.stage !== 1) { const stage = stages.find(s => s.stage === state.stage); root.append(make("h2", stage.label), make("p", stage.purpose), make("p", "Blocked · execution disconnected", "status blocked"), source("p", stage.support_status), make("h3", "Inputs"), ...stage.required_inputs.map(value => make("p", value)), make("h3", "Expected outputs"), ...stage.expected_deliverables.map(value => make("p", value)), make("p", "No new research deliverable is created by this view.")); }
    else if (["graph", "catalog"].includes(state.view)) library(root);
    else if (state.view === "repairs" && window.WorkspaceRepair) window.WorkspaceRepair.render(root);
    else if (state.view === "notes") { root.append(make("h2", "Notes"), make("p", window.WorkspaceRepair ? "Accepted repairs & core findings" : "Top-3 supplement is pending.")); for (const record of records) { const section = make("section", undefined, "note-card"); section.append(source("h3", record.title), source("p", record.identity)); note(section, record.original); rawSection(section, "Complete metadata", record.original); root.append(section); } }
    else if (state.view === "sources") { root.append(make("h2", "Sources & provenance")); rawSection(root, "Index binding", {index_sha256:payload.index_sha256, ...index.provenance}); for (const row of index.sources) { root.append(source("h3", row.source_id)); rawSection(root, "Source records", row); } rawSection(root, "Sources & provenance", index.edges); }
    else { root.append(make("h2", "Coverage & screening")); rawSection(root, "Coverage & Stop Decision", index.coverage); rawSection(root, "Coverage & screening", index.screening); rawSection(root, "Search & Reading", index.search); rawSection(root, "Original audit documents", index.audit_documents); rawSection(root, "Coverage & Stop Decision", index.coverage_documents); rawSection(root, "Unknown", index.missing_fields); rawSection(root, "Import Stage 1", index.readiness); }
    if (window.WorkspaceRepair) {
      const binding = make("details", undefined, "view-binding");
      binding.append(make("summary", "View & rebuild binding"), make("p", "Read-only projection of the original package. Source access and claim judgments remain unchanged."), source("p", payload.index_sha256), make("p", "No new research deliverable is created by this view."));
      $("detail").replaceChildren(binding);
    } else $("detail").replaceChildren(make("p", "Read-only projection of the original package. Source access and claim judgments remain unchanged."), source("p", payload.index_sha256), make("p", "No new research deliverable is created by this view."));
    $("workspaceLanguage").value = i18n.locale; i18n.apply(); updateTitle();
  }
  $("workspaceLanguage").onchange = event => { i18n.set(event.target.value); updateTitle(); };
  window.WorkspaceRecords = Object.freeze({safeArtifactId, bibliography, render});
  render();
})();
