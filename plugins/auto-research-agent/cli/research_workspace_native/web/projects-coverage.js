/* Explicit saved-evidence reviews. Submission belongs to the shared project intent broker. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const words = {
    en: {
      title: "Review coverage and saved evidence", help: "Review saved evidence only. These actions grant no new search or model permission. Accepting a stop decision cannot override blockers; saved actions appear in the shared history.",
      unavailable: "Coverage actions are unavailable for this project version.", empty: "No coverage action is currently offered.", choose: "Choose an action", action: "Saved evidence action", round: "Active round", blockers: "Current blockers", none: "None recorded", unknown: "Unknown", held: "Submission is held. Refresh saved state to inspect pending work; refresh never resends.",
      "review-work": "Review a paper's coverage evidence", receipt: "Record query result limits", "open-round": "Open the next coverage round", "close-round": "Close the current coverage round", "human-action": "Record a coverage decision",
      version: "Source version", current: "Recorded review", currentReceipt: "Recorded result-limit observation", claims: "Saved claims and source spans", quote: "Source quote", source: "Source SHA-256", identity: "Citation identity", identityHelp: "Choose evidence for each identity field. The initial assessment remains unverifiable; missing evidence stays Unknown.", identityStatus: "Identity assessment", verified: "Verified", unverifiable: "Unverifiable", conflict: "Conflict", titleField: "Title", authors: "Authors", year: "Year", identifier: "Identifier", versionField: "Version", noClaim: "No supporting claim / Unknown", clusters: "Evidence for each research cluster", closest: "Mark as verified closest work", rationale: "Review rationale, saved verbatim", truncated: "Were these query results truncated?", yes: "Yes — truncated", no: "No — not truncated", note: "Observation note, saved verbatim", results: "Returned results", outcome: "Recorded outcome", decision: "Your coverage decision", "accept-stop": "Accept stop, subject to the evidence gate", "request-cluster": "Request coverage for a cluster", cluster: "Research cluster", input: "Your instruction, saved verbatim", submit: "Save this explicit review", required: "Complete the required choices and explanation.", tooLarge: "The explanation exceeds the saved text limit.", saved: "Saved. Read the shared action history for the result.", roundHelp: "Save this round change against the current evidence. Opening a round does not run a query or grant search permission."
    },
    "zh-Hans": {
      title: "审阅覆盖与已保存证据", help: "仅审阅已保存证据。这些操作不授予新的搜索或模型许可。接受停止不能覆盖阻塞项；已保存操作可在全局历史中查看。",
      unavailable: "当前项目版本暂无可用的覆盖操作。", empty: "当前没有可提交的覆盖操作。", choose: "选择一项操作", action: "已保存证据操作", round: "当前轮次", blockers: "当前阻塞项", none: "尚无记录", unknown: "Unknown（未知）", held: "提交暂不可用。请刷新已保存状态查看待定操作；刷新不会重发。",
      "review-work": "审阅论文的覆盖证据", receipt: "记录查询结果限制", "open-round": "开启下一覆盖轮次", "close-round": "关闭当前覆盖轮次", "human-action": "记录覆盖决定",
      version: "来源版本", current: "已记录审阅", currentReceipt: "已记录结果限制", claims: "已保存论述与来源片段", quote: "来源原文", source: "来源 SHA-256", identity: "引用身份", identityHelp: "为每项身份信息选择证据。初始判断为无法核实；缺失证据保留 Unknown。", identityStatus: "身份核实结果", verified: "已核实", unverifiable: "无法核实", conflict: "存在冲突", titleField: "标题", authors: "作者", year: "年份", identifier: "标识符", versionField: "版本", noClaim: "无支持论述／Unknown", clusters: "各研究主题的证据", closest: "标记为已核实的最接近研究", rationale: "审阅理由，保留原文", truncated: "这次查询结果是否被截断？", yes: "是，已截断", no: "否，未截断", note: "观察说明，保留原文", results: "返回结果数", outcome: "已记录结果", decision: "你的覆盖决定", "accept-stop": "接受停止，仍需通过证据门槛", "request-cluster": "请求补充某个主题的覆盖", cluster: "研究主题", input: "你的指示，保留原文", submit: "保存这次明确审阅", required: "请完成必要选择与说明。", tooLarge: "说明超过可保存的文字上限。", saved: "已保存。请在全局操作历史中查看结果。", roundHelp: "依据当前证据保存轮次变更。开启轮次不会执行查询或授予搜索许可。"
    },
    "zh-Hant": {
      title: "審閱覆蓋與已保存證據", help: "僅審閱已保存證據。這些操作不授予新的搜尋或模型許可。接受停止不能覆蓋阻塞項；已保存操作可在全域歷史中查看。",
      unavailable: "目前專案版本暫無可用的覆蓋操作。", empty: "目前沒有可提交的覆蓋操作。", choose: "選擇一項操作", action: "已保存證據操作", round: "目前輪次", blockers: "目前阻塞項", none: "尚無紀錄", unknown: "Unknown（未知）", held: "提交暫不可用。請重新整理已保存狀態查看待定操作；重新整理不會重送。",
      "review-work": "審閱論文的覆蓋證據", receipt: "記錄查詢結果限制", "open-round": "開啟下一覆蓋輪次", "close-round": "關閉目前覆蓋輪次", "human-action": "記錄覆蓋決定",
      version: "來源版本", current: "已記錄審閱", currentReceipt: "已記錄結果限制", claims: "已保存論述與來源片段", quote: "來源原文", source: "來源 SHA-256", identity: "引用身分", identityHelp: "為每項身分資訊選擇證據。初始判斷為無法核實；缺失證據保留 Unknown。", identityStatus: "身分核實結果", verified: "已核實", unverifiable: "無法核實", conflict: "存在衝突", titleField: "標題", authors: "作者", year: "年份", identifier: "識別碼", versionField: "版本", noClaim: "無支持論述／Unknown", clusters: "各研究主題的證據", closest: "標記為已核實的最接近研究", rationale: "審閱理由，保留原文", truncated: "這次查詢結果是否被截斷？", yes: "是，已截斷", no: "否，未截斷", note: "觀察說明，保留原文", results: "回傳結果數", outcome: "已記錄結果", decision: "你的覆蓋決定", "accept-stop": "接受停止，仍需通過證據門檻", "request-cluster": "請求補充某個主題的覆蓋", cluster: "研究主題", input: "你的指示，保留原文", submit: "保存這次明確審閱", required: "請完成必要選擇與說明。", tooLarge: "說明超過可保存的文字上限。", saved: "已保存。請在全域操作歷史中查看結果。", roundHelp: "依據目前證據保存輪次變更。開啟輪次不會執行查詢或授予搜尋許可。"
    }
  };
  const operations = new Set(["review-work", "receipt", "open-round", "close-round", "human-action"]);
  Object.assign(words.en, {clusterHelp: "Choose a saved claim for at least one research cluster. This review creates no new claims.", supports: "Supports", partial: "Partial support", abstract: "Abstract", "full-text": "Full text", full_text: "Full text", primary_data_or_table: "Primary data or table"});
  Object.assign(words["zh-Hans"], {clusterHelp: "请为至少一个研究主题选择已保存论述。这次审阅不会创建新论述。", supports: "支持", partial: "部分支持", abstract: "摘要", "full-text": "全文", full_text: "全文", primary_data_or_table: "原始数据或表格"});
  Object.assign(words["zh-Hant"], {clusterHelp: "請為至少一個研究主題選擇已保存論述。這次審閱不會建立新論述。", supports: "支持", partial: "部分支持", abstract: "摘要", "full-text": "全文", full_text: "全文", primary_data_or_table: "原始資料或表格"});
  Object.assign(words.en, {omitted: "The response limit omits some offers. This action list is partial.", omittedActions: "Omitted actions", omittedWorks: "Omitted paper reviews", invalidText: "Use valid Unicode text within 4096 UTF-8 bytes."});
  Object.assign(words["zh-Hans"], {omitted: "响应数量上限省略了部分选项；当前操作列表并不完整。", omittedActions: "省略的操作数", omittedWorks: "省略的论文审阅数", invalidText: "请使用完整的 Unicode 字符，且不超过 4096 个 UTF-8 字节。"});
  Object.assign(words["zh-Hant"], {omitted: "回應數量上限省略了部分選項；目前操作列表並不完整。", omittedActions: "省略的操作數", omittedWorks: "省略的論文審閱數", invalidText: "請使用完整的 Unicode 字元，且不超過 4096 個 UTF-8 位元組。"});
  Object.assign(words.en, {
    noActiveRound: "No active round", targetRound: "Target round", maxRounds: "Maximum rounds", sourceRules: "Original Core rule codes", references: "Reference list", "cited-by": "Citing papers",
    "development-dependency-unmerged": "A research dependency is still on an unmerged development version.",
    "cluster-incomplete": "This research cluster still needs qualifying evidence",
    "recent-sweep-incomplete": "The planned search for recent work is incomplete.",
    "closest-work-unverified": "The required closest works have not all been verified.",
    "closest-expansion-incomplete": "The closest-work citation check is incomplete",
    "human-request-outstanding": "Requested additional coverage is still pending.",
    "screening-or-evidence-review-incomplete": "Some papers still need a screening decision or evidence review.",
    "extraction-incomplete": "Saved query results are not fully extracted.",
    "round-still-open": "The current coverage round is still open.",
    "latest-round-incomplete": "The latest closed round is missing or incomplete.",
    "marginal-yield-not-saturated": "The required consecutive rounds with no new qualifying work have not been recorded.",
    "coverage-changed-since-round-close": "Evidence reviews changed after the round closed; coverage needs another check."
  });
  Object.assign(words["zh-Hans"], {
    noActiveRound: "当前无活动轮次", targetRound: "目标轮次", maxRounds: "轮次上限", sourceRules: "Core 原始规则代码", references: "参考文献列表", "cited-by": "引用该文的论文",
    "development-dependency-unmerged": "研究依赖仍使用尚未合并的开发版本。",
    "cluster-incomplete": "该研究主题仍缺少符合要求的证据",
    "recent-sweep-incomplete": "近期研究的计划检索尚未完成。",
    "closest-work-unverified": "尚未核实全部必需的最接近研究。",
    "closest-expansion-incomplete": "最接近研究的引用追踪尚未完成",
    "human-request-outstanding": "用户要求补充的覆盖仍待完成。",
    "screening-or-evidence-review-incomplete": "部分论文仍缺少筛选决定或证据审阅。",
    "extraction-incomplete": "已保存查询结果尚未完整提取。",
    "round-still-open": "当前覆盖轮次尚未关闭。",
    "latest-round-incomplete": "尚无已关闭轮次，或最近关闭的轮次不完整。",
    "marginal-yield-not-saturated": "尚未记录达到要求的连续轮次：每轮均无新增合格文献。",
    "coverage-changed-since-round-close": "轮次关闭后证据审阅发生变化，需要再次检查覆盖。"
  });
  Object.assign(words["zh-Hant"], {
    noActiveRound: "目前無活動輪次", targetRound: "目標輪次", maxRounds: "輪次上限", sourceRules: "Core 原始規則代碼", references: "參考文獻列表", "cited-by": "引用該文的論文",
    "development-dependency-unmerged": "研究依賴仍使用尚未合併的開發版本。",
    "cluster-incomplete": "該研究主題仍缺少符合要求的證據",
    "recent-sweep-incomplete": "近期研究的計畫檢索尚未完成。",
    "closest-work-unverified": "尚未核實全部必需的最接近研究。",
    "closest-expansion-incomplete": "最接近研究的引用追蹤尚未完成",
    "human-request-outstanding": "使用者要求補充的覆蓋仍待完成。",
    "screening-or-evidence-review-incomplete": "部分論文仍缺少篩選決定或證據審閱。",
    "extraction-incomplete": "已保存查詢結果尚未完整擷取。",
    "round-still-open": "目前覆蓋輪次尚未關閉。",
    "latest-round-incomplete": "尚無已關閉輪次，或最近關閉的輪次不完整。",
    "marginal-yield-not-saturated": "尚未記錄達到要求的連續輪次：每輪均無新增合格文獻。",
    "coverage-changed-since-round-close": "輪次關閉後證據審閱發生變化，需要再次檢查覆蓋。"
  });
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  let state = null, basis = null, selected = null, language = "en", submitting = false;
  const t = key => words[language][key] || words.en[key] || key;
  const list = value => Array.isArray(value) ? value : [];
  function append(parent, tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value === null ? t("unknown") : value);
    if (className) node.className = className;
    parent.append(node); return node;
  }
  function blockerText(code, offers) {
    if (code.startsWith("cluster-incomplete:")) {
      const id = code.slice("cluster-incomplete:".length);
      const action = offers.find(offer => offer.operation === "human-action");
      const cluster = list(action && action.document.clusters).find(row => row.cluster_id === id);
      return t("cluster-incomplete") + ": " + (cluster && cluster.title || id);
    }
    if (code.startsWith("closest-expansion-incomplete:")) {
      const suffix = code.slice("closest-expansion-incomplete:".length), divider = suffix.lastIndexOf(":");
      const work = suffix.slice(0, divider), operation = suffix.slice(divider + 1);
      if (divider < 0 || !["references", "cited-by"].includes(operation)) return code;
      const offer = offers.find(row => row.operation === "review-work" && row.document.work_ref === work);
      return t("closest-expansion-incomplete") + ": " + t(operation) + (offer && offer.document.title ? " · " + offer.document.title : "");
    }
    const known = ["development-dependency-unmerged", "recent-sweep-incomplete", "closest-work-unverified", "human-request-outstanding", "screening-or-evidence-review-incomplete", "extraction-incomplete", "round-still-open", "latest-round-incomplete", "marginal-yield-not-saturated", "coverage-changed-since-round-close"];
    return known.includes(code) ? t(code) : code;
  }
  function field(parent, label, tag = "select") {
    const wrapper = append(parent, "label"); append(wrapper, "span", label);
    return append(wrapper, tag);
  }
  function option(select, value, label) { const node = append(select, "option", label); node.value = value; }
  function claimSelect(parent, label, claims) {
    const select = field(parent, label); option(select, "", t("noClaim"));
    for (const claim of claims) { const label = String(claim.text); option(select, claim.claim_ref, label.length > 160 ? label.slice(0, 160) + "…" : label); }
    return select;
  }
  function explanation(parent, key) {
    const input = field(parent, t(key), "textarea"); input.rows = 2; input.maxLength = 4096; input.required = true;
    return input;
  }
  function bounded(value) {
    for (let i = 0; i < value.length; ++i) {
      const code = value.charCodeAt(i);
      if (code >= 0xD800 && code <= 0xDBFF) {
        const next = value.charCodeAt(++i);
        if (!(next >= 0xDC00 && next <= 0xDFFF)) return false;
      } else if (code >= 0xDC00 && code <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= 4096;
  }
  function blocked() { return !state || state.busy || state.held || Boolean(state.stage1 && state.stage1.coverage_actions && state.stage1.coverage_actions.held) || submitting; }
  function disable() {
    const area = $("coverage-panel"); if (!area) return;
    area.querySelectorAll("input,select,textarea,button").forEach(node => { node.disabled = blocked(); });
    const message = $("coverage-held"); if (message) message.hidden = !(state && (state.held || state.stage1 && state.stage1.coverage_actions && state.stage1.coverage_actions.held));
  }
  function renderForm() {
    const area = $("coverage-form"); area.replaceChildren();
    if (!selected) return;
    const offer = selected, document = offer.document;
    const form = append(area, "form"), message = append(form, "p", "", "subtle");
    message.setAttribute("role", "status");
    let review;
    if (offer.operation === "review-work") {
      append(form, "h3", document.title); append(form, "p", t("version") + ": " + (document.version_id || t("unknown")), "subtle");
      if (document.current_review) append(form, "p", t("current") + ": " + t(document.current_review.identity_status || "unknown") + (document.current_review.rationale ? " · " + document.current_review.rationale : ""), "subtle");
      const claims = list(document.claims), clusters = list(document.clusters);
      append(form, "h4", t("clusters")); append(form, "p", t("clusterHelp"), "subtle");
      const clusterClaims = clusters.map(cluster => [cluster.cluster_id, claimSelect(form, cluster.title || cluster.cluster_id, claims)]);
      append(form, "h4", t("identity")); append(form, "p", t("identityHelp"), "subtle");
      const status = field(form, t("identityStatus"));
      for (const value of ["unverifiable", "verified", "conflict"]) option(status, value, t(value));
      const identityClaims = ["title", "authors", "year", "identifier", "version"].map(name => [name, claimSelect(form, t(name === "title" ? "titleField" : name === "version" ? "versionField" : name), claims)]);
      const wrapper = append(form, "label", undefined, "check"), closest = append(wrapper, "input"); closest.type = "checkbox"; closest.checked = false; append(wrapper, "span", t("closest"));
      const rationale = explanation(form, "rationale");
      const evidence = append(form, "details"); append(evidence, "summary", t("claims"));
      if (!claims.length) append(evidence, "p", t("none"), "subtle");
      for (const claim of claims) {
        const row = append(evidence, "div", undefined, "history-row");
        append(row, "p", claim.text); append(row, "p", t(claim.relation || "unknown") + " · " + t(claim.evidence_level || "unknown"), "subtle");
        append(row, "p", t("quote") + ": " + (claim.quote == null ? t("unknown") : claim.quote));
        append(row, "p", t("source") + ": " + (claim.source_sha256 || t("unknown")), "subtle");
      }
      review = () => ({cluster_claims: Object.fromEntries(clusterClaims.filter(([, select]) => select.value).map(([id, select]) => [id, select.value])), identity_status: status.value, identity_claims: Object.fromEntries(identityClaims.map(([id, select]) => [id, select.value || null])), closest: closest.checked, rationale: rationale.value});
    } else if (offer.operation === "receipt") {
      append(form, "p", document.query);
      append(form, "p", t("results") + ": " + (document.result_count == null ? t("unknown") : document.result_count) + " · " + t("outcome") + ": " + (document.outcome || t("unknown")), "subtle");
      if (document.current_receipt) append(form, "p", t("currentReceipt") + ": " + t(document.current_receipt.truncated === true ? "yes" : document.current_receipt.truncated === false ? "no" : "unknown") + (document.current_receipt.note ? " · " + document.current_receipt.note : ""), "subtle");
      const truncated = field(form, t("truncated"));
      option(truncated, "", t("unknown")); option(truncated, "true", t("yes")); option(truncated, "false", t("no"));
      const note = explanation(form, "note");
      review = () => ({truncated: truncated.value === "" ? null : truncated.value === "true", note: note.value});
    } else if (offer.operation === "human-action") {
      const action = field(form, t("decision")); option(action, "", t("choose"));
      option(action, "accept-stop", t("accept-stop")); option(action, "request-cluster", t("request-cluster")); action.required = true;
      const cluster = field(form, t("cluster")); option(cluster, "", t("choose"));
      for (const row of list(document.clusters)) option(cluster, row.cluster_id, row.title || row.cluster_id);
      cluster.parentElement.hidden = true;
      action.onchange = () => { const request = action.value === "request-cluster"; cluster.parentElement.hidden = !request; cluster.required = request; if (!request) cluster.value = ""; };
      const input = explanation(form, "input");
      review = () => ({action: action.value, cluster_id: action.value === "request-cluster" ? cluster.value : null, user_input: input.value});
    } else {
      append(form, "p", t("targetRound") + ": " + (document.round_number == null ? t("unknown") : document.round_number), "subtle");
      if (document.max_rounds !== undefined) append(form, "p", t("maxRounds") + ": " + (document.max_rounds === null ? t("unknown") : document.max_rounds), "subtle");
      append(form, "p", t("roundHelp"), "subtle"); review = () => ({});
    }
    const button = append(form, "button", t("submit"), "primary"); button.type = "submit";
    form.onsubmit = async event => {
      event.preventDefault(); if (blocked() || selected !== offer || !form.reportValidity()) return;
      const value = review(), originalBasis = basis;
      if (offer.operation === "review-work" && !Object.keys(value.cluster_claims).length) { message.textContent = t("clusterHelp"); return; }
      const texts = [value.rationale, value.note, value.user_input].filter(text => typeof text === "string");
      if (texts.some(text => !text.trim())) { message.textContent = t("required"); return; }
      if (texts.some(text => !bounded(text))) { message.textContent = t("invalidText"); return; }
      const submit = state.submit;
      submitting = true; disable();
      try {
        const saved = await submit({project_ref: state.project.project_ref, input_version: state.project.input_version, brief_sha256: state.project.brief_sha256, ledger_state_sha256: state.stage1.coverage_actions.ledger_state_sha256, operation: offer.operation, offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, review: value});
        if (basis === originalBasis && selected === offer && saved) { selected = null; $("coverage-select").value = ""; area.replaceChildren(); append(area, "p", t("saved"), "subtle"); }
      } catch (error) { if (basis === originalBasis && selected === offer) message.textContent = error.message; }
      finally { submitting = false; disable(); }
    };
    disable();
  }
  function update(next) {
    const panel = $("coverage-panel"), details = $("coverage-controls"); if (!panel || !details) return;
    state = next; language = words[next.language] ? next.language : "en";
    $("coverage-title").textContent = t("title");
    const project = next.project, stage1 = next.stage1, actions = stage1 && stage1.coverage_actions;
    const available = Boolean(project && project.brief && stage1 && stage1.ledger && actions && actions.schema_version === "1.0.0" && hash(actions.ledger_state_sha256) && actions.ledger_state_sha256 === stage1.ledger.state_sha256 && Array.isArray(actions.offers) && typeof next.submit === "function");
    const offers = available ? actions.offers.filter(offer => offer && operations.has(offer.operation) && typeof offer.offer_ref === "string" && hash(offer.offer_sha256) && offer.document && typeof offer.document === "object" && !Array.isArray(offer.document)) : [];
    const signature = available ? JSON.stringify([project.project_ref, project.input_version, project.brief_sha256, actions.ledger_state_sha256, language, actions.omitted_action_count, actions.omitted_work_count, offers.map(offer => [offer.operation, offer.offer_ref, offer.offer_sha256])]) : JSON.stringify([project && project.project_ref, language, null]);
    if (basis === signature) { disable(); return; }
    basis = signature; selected = null; details.open = false; panel.replaceChildren();
    append(panel, "p", t("help"), "subtle");
    if (!available) { append(panel, "p", t("unavailable"), "subtle"); return; }
    const omitted = [["omitted_action_count", "omittedActions"], ["omitted_work_count", "omittedWorks"]]
      .filter(([name]) => Number.isSafeInteger(actions[name]) && actions[name] > 0)
      .map(([name, label]) => t(label) + ": " + actions[name]);
    if (omitted.length) append(panel, "p", t("omitted") + " " + omitted.join(" · "), "notice");
    append(panel, "p", t("round") + ": " + (actions.active_round === null ? t("noActiveRound") : actions.active_round === undefined ? t("unknown") : actions.active_round), "subtle");
    append(panel, "h4", t("blockers"));
    const blockers = list(actions.blockers);
    if (blockers.length) {
      const items = append(panel, "ul"), codes = [];
      for (const blocker of blockers) {
        const code = typeof blocker === "string" ? blocker : blocker && blocker.code;
        const label = code ? blockerText(code, offers) : blocker && (blocker.message || blocker.reason) || t("unknown");
        append(items, "li", label); if (code && label !== code) codes.push(code);
      }
      if (codes.length) { const rules = append(panel, "details", undefined, "subtle"); append(rules, "summary", t("sourceRules")); const raw = append(rules, "ul"); for (const code of codes) append(append(raw, "li"), "code", code); }
    }
    else append(panel, "p", Array.isArray(actions.blockers) ? t("none") : t("unknown"), "subtle");
    if (!offers.length) { append(panel, "p", t("empty"), "subtle"); return; }
    const selector = field(panel, t("action")); selector.id = "coverage-select"; option(selector, "", t("choose"));
    offers.forEach((offer, index) => option(selector, String(index), t(offer.operation) + (offer.document.title || offer.document.query ? " · " + (offer.document.title || offer.document.query) : "")));
    const held = append(panel, "p", t("held"), "subtle"); held.id = "coverage-held";
    const area = append(panel, "div"); area.id = "coverage-form";
    selector.onchange = () => { selected = selector.value === "" ? null : offers[Number(selector.value)]; renderForm(); };
    disable();
  }
  window.ResearchProjectCoverage = Object.freeze({update});
})();
