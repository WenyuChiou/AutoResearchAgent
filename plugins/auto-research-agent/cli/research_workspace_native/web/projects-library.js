/* Saved screening companion. GET only; no intents, approvals or execution. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const words = {
    en: {title: "Complete screening library", help: "All saved candidates stay here, including excluded and unread works. Discovery order is not a relevance ranking. This list does not establish Stage1 completion.", more: "Read more papers", loading: "Reading saved screening records…", unavailable: "Saved screening records are unavailable for this project version.", empty: "No candidates have been recorded yet.", select: "Select a paper to read its saved evidence and decision history.", total: "Candidates", include: "Included", exclude: "Excluded", pending: "Pending", "not-screened": "Not screened", "not-acquired": "Source not acquired", "no-reading-evidence-recorded": "No reading evidence recorded", "claim-evidence-recorded": "Claim evidence recorded", "saved-import-intent-recorded": "Saved import intent", "saved-import-bytes-recorded": "Saved import bytes", available: "Source available", work: "Work / version", first: "First candidate discovery in this run", discoveries: "Discoveries", queries: "Distinct queries", attempts: "Backend attempts", rounds: "Recorded search rounds", relevance: "Relevance", decision: "Current decision", history: "Decision history", discovery: "Search and discovery trail", source: "Source observations", claims: "Saved claims", access: "Recorded access links", sourceLevel: "Evidence level", reading: "Reading evidence", close: "Close details", loaded: "Loaded", of: "of", unavailableDetail: "Details are unavailable. Refresh the project to read its current saved version.", status: "Status", orderHelp: "Candidate order and backend result position are saved observations; neither is a scientific ranking.", noDecision: "No screening decision has been recorded.", sourceNotRead: "Source availability does not prove complete reading or verified claims.", noHistory: "No recorded history", reason: "Reason", outcome: "Outcome"},
    "zh-Hans": {title: "完整筛选文献库", help: "保留全部已记录候选，包括排除和未阅读文献。发现顺序不是相关度排名；此列表不代表 Stage1 完成。", more: "读取更多文献", loading: "正在读取已保存的筛选记录…", unavailable: "当前项目版本暂无可读取的筛选记录。", empty: "尚未记录候选文献。", select: "点击论文查看已保存证据与决定历史。", total: "候选", include: "纳入", exclude: "排除", pending: "待定", "not-screened": "未筛选", "not-acquired": "尚未取得来源", "no-reading-evidence-recorded": "尚无阅读证据记录", "claim-evidence-recorded": "已记录论述证据", "saved-import-intent-recorded": "已保存导入意图", "saved-import-bytes-recorded": "已保存导入文件", available: "来源可用", work: "作品／版本", first: "本轮运行首次发现次序", discoveries: "发现次数", queries: "不同查询数", attempts: "后端尝试数", rounds: "已记录搜索轮数", relevance: "相关度", decision: "当前决定", history: "决定历史", discovery: "搜索与发现路径", source: "来源观察记录", claims: "已保存论述", access: "已记录访问链接", sourceLevel: "证据层级", reading: "阅读证据", close: "关闭详情", loaded: "已载入", of: "／", unavailableDetail: "详情暂不可读取。请刷新项目，查看当前已保存版本。", status: "状态", orderHelp: "候选发现次序和后端结果位置都是保存的观察记录，不是科学排名。", noDecision: "尚未记录筛选决定。", sourceNotRead: "来源可用不代表已完整阅读或论述已核实。", noHistory: "暂无记录", reason: "理由", outcome: "结果"},
    "zh-Hant": {title: "完整篩選文獻庫", help: "保留全部已記錄候選，包括排除及未閱讀文獻。發現順序不是相關度排名；此列表不代表 Stage1 完成。", more: "讀取更多文獻", loading: "正在讀取已保存的篩選紀錄…", unavailable: "目前專案版本暫無可讀取的篩選紀錄。", empty: "尚未記錄候選文獻。", select: "點選論文查看已保存證據與決定歷史。", total: "候選", include: "納入", exclude: "排除", pending: "待定", "not-screened": "未篩選", "not-acquired": "尚未取得來源", "no-reading-evidence-recorded": "尚無閱讀證據紀錄", "claim-evidence-recorded": "已記錄論述證據", "saved-import-intent-recorded": "已保存匯入意圖", "saved-import-bytes-recorded": "已保存匯入檔案", available: "來源可用", work: "作品／版本", first: "本次執行首次發現次序", discoveries: "發現次數", queries: "不同查詢數", attempts: "後端嘗試數", rounds: "已記錄搜尋輪數", relevance: "相關度", decision: "目前決定", history: "決定歷史", discovery: "搜尋與發現路徑", source: "來源觀察紀錄", claims: "已保存論述", access: "已記錄存取連結", sourceLevel: "證據層級", reading: "閱讀證據", close: "關閉詳情", loaded: "已載入", of: "／", unavailableDetail: "詳情暫不可讀取。請重新整理專案，查看目前已保存版本。", status: "狀態", orderHelp: "候選發現次序及後端結果位置都是保存的觀察紀錄，不是科學排名。", noDecision: "尚未記錄篩選決定。", sourceNotRead: "來源可用不代表已完整閱讀或論述已核實。", noHistory: "暫無紀錄", reason: "理由", outcome: "結果"}
  };
  let language = "en", basis = null, generation = 0, page = null, entries = [], selected = null;
  let loading = false, detailGeneration = 0;
  const t = key => (words[language] || words.en)[key] || words.en[key] || key;
  const sourceLabels = {
    en: {pending: "Source read unfinished", unavailable: "Source unavailable", not_found: "Source not found", rate_limited: "Source rate limited", http_error: "Source HTTP error", network_error: "Source network error", parse_error: "Source parse error", interrupted: "Source read interrupted"},
    "zh-Hans": {pending: "来源读取未完成", unavailable: "来源不可用", not_found: "未找到来源", rate_limited: "来源访问限流", http_error: "来源 HTTP 错误", network_error: "来源网络错误", parse_error: "来源解析错误", interrupted: "来源读取中断"},
    "zh-Hant": {pending: "來源讀取未完成", unavailable: "來源不可用", not_found: "未找到來源", rate_limited: "來源存取限流", http_error: "來源 HTTP 錯誤", network_error: "來源網路錯誤", parse_error: "來源解析錯誤", interrupted: "來源讀取中斷"}
  };
  const artifactLabel = () => ({en: "saved files", "zh-Hans": "已保存文件", "zh-Hant": "已保存檔案"})[language];
  const sourceLabel = code => (sourceLabels[language] || sourceLabels.en)[code] || t(code);
  const value = v => v === null || v === undefined ? "Unknown" : String(v);
  function append(parent, tag, content, className) {
    const el = document.createElement(tag); el.textContent = value(content);
    if (className) el.className = className; parent.append(el); return el;
  }
  function clear() {
    ++generation; ++detailGeneration; basis = null; page = null; entries = []; selected = null; loading = false;
    $("screening-list").replaceChildren(); $("screening-summary").replaceChildren();
    $("screening-detail").replaceChildren(); $("screening-detail").hidden = true; $("screening-more").hidden = true;
    $("screening-status").textContent = t("unavailable");
  }
  function labels() {
    $("screening-title").textContent = t("title"); $("screening-help").textContent = t("help");
    $("screening-more").textContent = t("more");
  }
  async function get(path) {
    const result = await fetch(path, {method: "GET", cache: "no-store", headers: {Authorization: "Bearer " + window.RESEARCH_PROJECTS.credential}});
    const reply = await result.json(); if (!result.ok) throw Error(reply.error || result.status); return reply;
  }
  function matches(reply, expected) {
    const bound = reply && reply.binding;
    return basis && expected === generation && reply.project_ref === basis.ref && reply.input_version === basis.version
      && bound && bound.project_ref === basis.ref && bound.input_version === basis.version
      && bound.ledger_state_sha256 === basis.state && bound.brief_sha256 === basis.brief
      && /^[a-f0-9]{64}$/.test(reply.projection_sha256)
      && (!page || reply.projection_sha256 === page.projection_sha256);
  }
  function route(kind) { return "/api/projects/" + encodeURIComponent(basis.ref) + "/stage1/" + kind + "/" + basis.version + "/" + basis.state; }
  async function readPage(offset = 0) {
    if (!basis || loading) return;
    const current = generation, expected = page && page.projection_sha256;
    loading = true; $("screening-more").disabled = true; $("screening-status").textContent = t("loading");
    try {
      const reply = await get(route("screening") + "/" + offset + (expected ? "/" + expected : ""));
      if (current !== generation) return;
      if (!matches(reply, current) || reply.kind !== "Stage1ScreeningPage" || reply.offset !== offset || !Array.isArray(reply.rows)
          || reply.rows.some((row, i) => row.index !== offset + i) || offset !== entries.length)
        throw Error("stage1-library-page-binding-differs");
      page = reply; entries.push(...reply.rows); render();
    } catch (error) {
      if (current !== generation) return;
      clear(); labels(); $("screening-status").textContent = t("unavailable") + " (" + error.message + ")";
    } finally { if (current === generation) { loading = false; $("screening-more").disabled = false; } }
  }
  function field(dl, label, content) { append(dl, "dt", t(label)); append(dl, "dd", content); }
  function link(parent, url) {
    if (typeof url !== "string") return;
    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) return;
      const el = append(parent, "a", url); el.href = parsed.href; el.target = "_blank"; el.rel = "noopener noreferrer";
    } catch { /* Missing/invalid access metadata remains an unlinked record. */ }
  }
  function history(parent, key, list, describe) {
    const box = document.createElement("details"); parent.append(box); append(box, "summary", t(key));
    if (!list.length) { append(box, "p", t("noHistory"), "subtle"); return; }
    const ul = document.createElement("ul"); box.append(ul);
    for (const row of list) append(ul, "li", describe(row));
  }
  function renderDetail() {
    const area = $("screening-detail"); area.replaceChildren(); area.hidden = !selected;
    if (!selected) return;
    const row = selected.row, meta = row.metadata, counts = row.counts;
    const close = append(area, "button", t("close")); close.type = "button";
    close.onclick = () => { ++detailGeneration; selected = null; render(); };
    append(area, "h3", meta.title);
    append(area, "p", (Array.isArray(meta.authors) ? meta.authors.join(" · ") : value(meta.authors)) + " · " + value(meta.year), "subtle");
    const dl = document.createElement("dl"); area.append(dl);
    field(dl, "work", row.work_id + " / " + row.selected_version_id);
    field(dl, "status", t(row.screening_status)); field(dl, "sourceLevel", row.metadata_evidence_level);
    field(dl, "first", row.first_candidate_discovery_order_in_run);
    for (const [label, name] of [["discoveries", "discoveries"], ["queries", "distinct_queries"], ["attempts", "query_backend_attempts"], ["rounds", "recorded_rounds"]]) field(dl, label, counts[name]);
    field(dl, "relevance", row.relevance.score); field(dl, "reading", t(row.reading.status));
    append(area, "p", t("orderHelp"), "subtle");
    append(area, "h4", t("decision"));
    append(area, "p", row.current_decision ? row.current_decision.rationale : t("noDecision"));
    if (row.current_decision) append(area, "p", row.current_decision.reason_code, "subtle");
    append(area, "h4", t("access"));
    const currentSources = (row.source_attempts || []).filter(item => item.started.version_id === row.selected_version_id);
    const currentImports = (row.source_imports || []).filter(item => item.started.version_id === row.selected_version_id);
    const urls = new Set([meta.url, meta.URL, ...currentSources.flatMap(s => [s.started.source_uri, s.finished && s.finished.resolved_uri]), ...currentImports.map(s => s.started.source_uri)]);
    for (const url of urls) link(area, url);
    if (!area.querySelector("a")) append(area, "p", "Unknown", "subtle");
    append(area, "p", t("sourceNotRead"), "subtle");
    history(area, "history", row.decision_history, item => item.event_id + " · " + t(item.new_decision) + " · " + value(item.reason_code) + " · " + value(item.rationale));
    history(area, "discovery", row.query_history, item => item.started.event_id + " · " + value(item.started.arguments.input && item.started.arguments.input.query || item.started.arguments.query) + " · " + item.backend_attempts.map(attempt => value(attempt.started.backend) + ": " + value(attempt.finished ? attempt.finished.outcome : "pending")).join(" · "));
    history(area, "discoveries", row.discoveries, item => value(item.candidate_discovery_order_in_run) + " · " + value(item.query_id) + " · " + value(item.attempt_id) + " · " + value(item.version_id) + " · " + value(item.result_position) + " · " + value(item.source_ref && item.source_ref.sha256));
    history(area, "source", [...row.source_attempts, ...(row.source_imports || [])], item => item.started.event_id + " · " + value(item.started.version_id) + " · " + value(item.started.source_uri) + " · " + (item.finished ? item.finished.outcome : item.artifacts ? item.artifacts.length + " " + artifactLabel() : t("pending")) + " · " + (item.finished && item.finished.raw_ref ? item.finished.raw_ref.sha256 : item.artifacts ? item.artifacts.map(ref => ref.sha256).join(" · ") : "Unknown"));
    history(area, "claims", row.claims, item => value(item.claim_id || item.event_id) + " · " + value(item.version_id) + " · " + value(item.claim_text) + " · " + value(item.relation) + " · " + value(item.evidence_level));
    const hashes = document.createElement("details"); area.append(hashes); append(hashes, "summary", "SHA-256");
    append(hashes, "p", selected.projection_sha256, "subtle"); append(hashes, "p", selected.binding.ledger_state_sha256, "subtle");
  }
  function render() {
    labels(); const summary = $("screening-summary"), list = $("screening-list"); summary.replaceChildren(); list.replaceChildren();
    if (!page) { $("screening-status").textContent = t("unavailable"); return; }
    for (const [label, name] of [["total", "total_candidates"], ["include", "include"], ["exclude", "exclude"], ["pending", "pending"], ["not-screened", "not_screened"]]) append(summary, "span", t(label) + " " + value(page.counts[name]));
    $("screening-status").textContent = entries.length ? t("loaded") + " " + entries.length + " " + t("of") + " " + page.total : t("empty");
    for (const row of entries) {
      const button = document.createElement("button"); button.type = "button"; button.dataset.index = row.index;
      button.setAttribute("aria-current", String(Boolean(selected && selected.index === row.index)));
      append(button, "strong", row.title); append(button, "small", value(row.year) + " · " + t(row.screening_status) + " · " + sourceLabel(row.source_status));
      append(button, "small", t("discoveries") + " " + row.counts.discoveries + " · " + t("relevance") + " " + value(row.relevance.score));
      button.onclick = () => readDetail(row).catch(() => {}); list.append(button);
    }
    $("screening-more").hidden = page.next_offset === null; renderDetail();
  }
  async function readDetail(row) {
    if (!basis || !page) return;
    const current = generation, task = ++detailGeneration, expected = page.projection_sha256;
    selected = null; render(); $("screening-detail").hidden = false; append($("screening-detail"), "p", t("loading"));
    try {
      const reply = await get(route("screening-detail") + "/" + expected + "/" + row.index);
      if (current !== generation || task !== detailGeneration) return;
      if (!matches(reply, current) || reply.kind !== "Stage1ScreeningDetail" || reply.index !== row.index || reply.row.work_id !== row.work_id || reply.row.selected_version_id !== row.selected_version_id) throw Error("stage1-library-detail-binding-differs");
      selected = reply; render();
    } catch (error) {
      if (current !== generation || task !== detailGeneration) return;
      selected = null; $("screening-detail").replaceChildren(); append($("screening-detail"), "p", t("unavailableDetail") + " (" + error.message + ")");
    }
  }
  document.addEventListener("project-screening-clear", clear);
  document.addEventListener("project-screening-state", event => {
    const detail = event.detail; language = words[detail.language] ? detail.language : "en"; labels();
    const descriptor = detail.stage1 && detail.stage1.screening_library, project = detail.project;
    if (!project || !descriptor || !descriptor.available || descriptor.project_ref !== project.project_ref || descriptor.input_version !== project.input_version) { clear(); labels(); return; }
    const next = {ref: project.project_ref, version: project.input_version, state: descriptor.ledger_state_sha256, brief: project.brief_sha256};
    if (basis && Object.keys(next).every(key => next[key] === basis[key])) { if (page) render(); return; }
    clear(); basis = next; readPage();
  });
  $("screening-more").onclick = () => { if (page && page.next_offset !== null) readPage(page.next_offset); };
  labels(); clear();
})();
