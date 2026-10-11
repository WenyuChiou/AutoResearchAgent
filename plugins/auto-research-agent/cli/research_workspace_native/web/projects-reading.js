/* Saved reading review. The project broker owns GET, durable intent and POST. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const words = {
    en: {
      open: "Review quotes and save a claim", title: "Review a saved reading draft", help: "Select an exact saved quote and write the claim you want to record. A draft is untrusted model content. Unknown remains Unknown; saving a claim does not accept coverage or deliver Stage1.", preview: "Read the full draft", summary: "Summary", classification: "Classification", findings: "Findings", limitations: "Limitations", open_questions: "Open questions", evidence: "Quoted evidence", choose: "Choose one quote to review", quote: "Exact source quote", source: "Saved source", textHash: "Saved text SHA-256", byteSpan: "UTF-8 byte span", existing: "Existing claim", noExisting: "No existing claim recorded", claim: "Your claim, saved verbatim", section: "Source section / location, entered by you", relation: "How the source relates to your claim", level: "Your evidence-level assessment", pending: "Pending assessment", supports: "Supports", partial: "Partial support", contradicts: "Contradicts", unclear: "Unclear", unverifiable: "Unverifiable", context: "Context only", "full-text": "Full text", abstract: "Abstract", submit: "Save this explicitly reviewed claim", held: "Submission is held. Inspect saved history and refresh state; refresh never resends.", empty: "No quote review is currently offered.", unknown: "Unknown", incomplete: "Stage1 has not been delivered by this action.", invalid: "Enter both a claim and a source location using valid Unicode, each within 4096 UTF-8 bytes.", saved: "Claim action saved. Read the shared history for its result.", topic_cluster: "Topic cluster", method: "Method", geography: "Geography", population: "Population", data_type: "Data type", domain: "Domain", question: "Research question", data: "Data", main_findings: "Main findings", relevance: "Relevance", transferability: "Transferability"
    },
    "zh-Hans": {
      open: "审阅引用并保存主张", title: "审阅已保存阅读草稿", help: "选择已保存的精确原文，并填写你要记录的主张。草稿是未经信任的模型内容。Unknown 保持未知；保存主张不代表接受覆盖或完成 Stage1 交付。", preview: "查看完整草稿", summary: "摘要", classification: "分类", findings: "研究发现", limitations: "局限", open_questions: "待解问题", evidence: "引用证据", choose: "选择一段原文进行审阅", quote: "来源精确原文", source: "已保存来源", textHash: "已保存文本 SHA-256", byteSpan: "UTF-8 字节范围", existing: "既有主张", noExisting: "尚无既有主张记录", claim: "你的主张，保留原文", section: "来源章节／位置，请亲自填写", relation: "来源与主张的关系", level: "你判断的证据层级", pending: "待评估", supports: "支持", partial: "部分支持", contradicts: "反驳", unclear: "不明确", unverifiable: "无法核实", context: "仅作为背景", "full-text": "全文", abstract: "摘要", submit: "保存这条明确审阅的主张", held: "提交暂不可用。请查看已保存历史并刷新状态；刷新不会重发。", empty: "当前没有可审阅的引用选项。", unknown: "Unknown（未知）", incomplete: "此操作尚未完成 Stage1 交付。", invalid: "请填写主张与来源位置，使用完整 Unicode 字符，每项不超过 4096 个 UTF-8 字节。", saved: "已保存主张操作。请在全局历史中查看结果。", topic_cluster: "研究主题", method: "方法", geography: "地理范围", population: "研究对象", data_type: "数据类型", domain: "研究领域", question: "研究问题", data: "数据", main_findings: "主要发现", relevance: "相关性", transferability: "可迁移性"
    },
    "zh-Hant": {
      open: "審閱引用並保存主張", title: "審閱已保存閱讀草稿", help: "選擇已保存的精確原文，並填寫你要記錄的主張。草稿是未經信任的模型內容。Unknown 保持未知；保存主張不代表接受覆蓋或完成 Stage1 交付。", preview: "查看完整草稿", summary: "摘要", classification: "分類", findings: "研究發現", limitations: "局限", open_questions: "待解問題", evidence: "引用證據", choose: "選擇一段原文進行審閱", quote: "來源精確原文", source: "已保存來源", textHash: "已保存文字 SHA-256", byteSpan: "UTF-8 位元組範圍", existing: "既有主張", noExisting: "尚無既有主張紀錄", claim: "你的主張，保留原文", section: "來源章節／位置，請親自填寫", relation: "來源與主張的關係", level: "你判斷的證據層級", pending: "待評估", supports: "支持", partial: "部分支持", contradicts: "反駁", unclear: "不明確", unverifiable: "無法核實", context: "僅作為背景", "full-text": "全文", abstract: "摘要", submit: "保存這條明確審閱的主張", held: "提交暫不可用。請查看已保存歷史並重新整理狀態；重新整理不會重送。", empty: "目前沒有可審閱的引用選項。", unknown: "Unknown（未知）", incomplete: "此操作尚未完成 Stage1 交付。", invalid: "請填寫主張與來源位置，使用完整 Unicode 字元，每項不超過 4096 個 UTF-8 位元組。", saved: "已保存主張操作。請在全域歷史中查看結果。", topic_cluster: "研究主題", method: "方法", geography: "地理範圍", population: "研究對象", data_type: "資料類型", domain: "研究領域", question: "研究問題", data: "資料", main_findings: "主要發現", relevance: "相關性", transferability: "可遷移性"
    }
  };
  Object.assign(words.en, {notesTitle: "Review and save reading notes", notesHelp: "Edit the draft's annotations before confirming. Draft wording, including Unknown, is kept verbatim. Saving notes neither authorizes a model call nor completes Stage1.", roles: "Literature roles: none selected; no roles are inferred.", notesConfirm: "I reviewed these annotations; saving them does not mean Stage1 is complete.", notesSubmit: "Save these reviewed reading notes", notesUnavailable: "Saving reading notes is not currently offered.", notesInvalid: "Confirm your review and enter valid Unicode in every field, each within 4096 UTF-8 bytes.", notesSaved: "Reading notes action saved. Read the shared history for its result."});
  Object.assign(words["zh-Hans"], {notesTitle: "审阅并保存阅读笔记", notesHelp: "确认前请编辑草稿注释。草稿原文（包括 Unknown）保持不变。保存笔记不会授权模型调用，也不代表 Stage1 完成。", roles: "文献角色：尚未选择，不推断任何角色。", notesConfirm: "我已审阅这些注释；保存不代表 Stage1 完成。", notesSubmit: "保存这些已审阅的阅读笔记", notesUnavailable: "当前没有可保存阅读笔记的许可选项。", notesInvalid: "请明确确认审阅，并在每个字段填写完整 Unicode，每项不超过 4096 个 UTF-8 字节。", notesSaved: "已保存阅读笔记操作。请在全局历史中查看结果。"});
  Object.assign(words["zh-Hant"], {notesTitle: "審閱並保存閱讀筆記", notesHelp: "確認前請編輯草稿註釋。草稿原文（包括 Unknown）保持不變。保存筆記不會授權模型呼叫，也不代表 Stage1 完成。", roles: "文獻角色：尚未選擇，不推斷任何角色。", notesConfirm: "我已審閱這些註釋；保存不代表 Stage1 完成。", notesSubmit: "保存這些已審閱的閱讀筆記", notesUnavailable: "目前沒有可保存閱讀筆記的許可選項。", notesInvalid: "請明確確認審閱，並在每個欄位填寫完整 Unicode，每項不超過 4096 個 UTF-8 位元組。", notesSaved: "已保存閱讀筆記操作。請在全域歷史中查看結果。"});
  const noteFields = {classification: ["topic_cluster", "method", "geography", "population", "data_type", "domain"], findings: ["question", "data", "method", "main_findings", "limitations", "relevance", "transferability"]};
  Object.assign(words.en, {sourceTitle: "Review saved-source reading notes", sourceHelp: "Review the saved sources and claims below, then edit these annotations. Unknown stays Unknown. This is your source review, not a model-generated draft or stage acceptance.", sourceEvidence: "Bound sources and recorded claims", roleHelp: "Optional literature roles need an explicit reason and same-work claim evidence.", roleReason: "Reason for this role", roleClaims: "Evidence claims for this role", classic: "Classic", "topic-core": "Topic core", "closest-work": "Closest work", comparator: "Comparator"});
  Object.assign(words["zh-Hans"], {sourceTitle: "审阅已保存来源的阅读笔记", sourceHelp: "先审阅下方已保存来源与主张，再编辑这些注释。Unknown 保持未知。这是你的来源审阅，不是模型生成草稿，也不代表阶段通过。", sourceEvidence: "绑定的来源与已记录主张", roleHelp: "可选文献角色须明确填写理由，并选择同一论文的主张证据。", roleReason: "此角色的理由", roleClaims: "此角色的主张证据", classic: "经典文献", "topic-core": "主题核心文献", "closest-work": "最接近的工作", comparator: "比较文献"});
  Object.assign(words["zh-Hant"], {sourceTitle: "審閱已保存來源的閱讀筆記", sourceHelp: "先審閱下方已保存來源與主張，再編輯這些註釋。Unknown 保持未知。這是你的來源審閱，不是模型生成草稿，也不代表階段通過。", sourceEvidence: "綁定的來源與已記錄主張", roleHelp: "可選文獻角色須明確填寫理由，並選擇同一論文的主張證據。", roleReason: "此角色的理由", roleClaims: "此角色的主張證據", classic: "經典文獻", "topic-core": "主題核心文獻", "closest-work": "最接近的工作", comparator: "比較文獻"});
  let state = null, basis = null, view = null, selected = null, submitting = false;
  const hash = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  const t = key => (words[state && state.language] || words.en)[key] || words.en[key] || key;
  function append(parent, tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value == null ? t("unknown") : value);
    if (className) node.className = className;
    if (tag === "blockquote") node.style.whiteSpace = "pre-wrap";
    parent.append(node); return node;
  }
  function field(parent, label, tag) { const row = append(parent, "label"); append(row, "span", t(label)); return append(row, tag); }
  function option(select, value, label) { const node = append(select, "option", label); node.value = value; }
  function bounded(value) {
    if (!value.trim()) return false;
    for (let i = 0; i < value.length; ++i) {
      const code = value.charCodeAt(i);
      if (code >= 0xD800 && code <= 0xDBFF) { const next = value.charCodeAt(++i); if (!(next >= 0xDC00 && next <= 0xDFFF)) return false; }
      else if (code >= 0xDC00 && code <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= 4096;
  }
  function blocked() { return !state || state.busy || state.held || submitting; }
  function disable() {
    const panel = $("reading-panel"); if (!panel) return;
    panel.querySelectorAll("button,input,select,textarea").forEach(node => { node.disabled = blocked() || node.dataset.readingUnavailable === "true"; });
    const held = $("reading-held"); if (held) held.hidden = !(state && state.held);
  }
  function clear() { view = selected = null; $("reading-panel").replaceChildren(); $("reading-card").hidden = true; }
  function update(next) {
    if (!$("reading-panel")) return;
    const project = next.project, ledger = next.stage1 && next.stage1.ledger;
    const signature = JSON.stringify([project && project.project_ref, project && project.input_version, project && project.brief_sha256, project && project.revision, ledger && ledger.state_sha256, next.language]);
    state = next;
    if (basis !== signature) { basis = signature; clear(); }
    $("reading-title").textContent = t(view && view.source_mode === "saved-source-review" ? "sourceTitle" : "title"); disable();
  }
  function preview(parent, draft) {
    const details = append(parent, "details"); append(details, "summary", t("preview"));
    append(details, "h4", t("summary")); append(details, "p", draft.summary);
    for (const name of ["classification", "findings"]) {
      append(details, "h4", t(name)); const fields = append(details, "dl");
      for (const [key, value] of Object.entries(draft[name])) { append(fields, "dt", t(key)); append(fields, "dd", value); }
    }
    for (const name of ["limitations", "open_questions"]) {
      append(details, "h4", t(name)); const items = append(details, "ul");
      if (!draft[name].length) append(items, "li", t("unknown"));
      for (const value of draft[name]) append(items, "li", value);
    }
    append(details, "h4", t("evidence"));
    for (const span of draft.evidence) {
      const row = append(details, "div", undefined, "history-row"); append(row, "blockquote", span.quote);
      append(row, "p", t("source") + ": " + span.source_id, "subtle");
      append(row, "p", t("textHash") + ": " + span.text_sha256, "subtle");
      append(row, "p", t("byteSpan") + ": " + span.start_byte + "–" + span.end_byte, "subtle");
      append(row, "p", t("existing") + ": " + (span.claim_id || t("noExisting")), "subtle");
    }
  }
  function readingNotes(parent, reply, onSaveReading, originalBasis) {
    const sourceMode = reply.source_mode === "saved-source-review", notes = sourceMode ? reply : reply.draft;
    const details = append(parent, "details"); append(details, "summary", t("notesTitle"));
    append(details, "p", t(sourceMode ? "sourceHelp" : "notesHelp"), "subtle");
    const form = append(details, "form"); form.id = "reading-notes-form";
    const offer = reply.reading_review_offer;
    const available = Boolean(offer && typeof offer.offer_ref === "string" && offer.offer_ref && hash(offer.offer_sha256)
      && typeof onSaveReading === "function" && Object.entries(noteFields).every(([name, keys]) => keys.every(key => typeof notes[name][key] === "string")));
    const inputs = {classification: {}, findings: {}};
    for (const [name, keys] of Object.entries(noteFields)) {
      append(form, "h4", t(name));
      for (const key of keys) {
        const input = field(form, key, "textarea"); input.rows = 2; input.required = true; input.maxLength = 4096;
        input.value = typeof notes[name][key] === "string" ? notes[name][key] : "";
        input.dataset.readingNote = name + "." + key; inputs[name][key] = input;
      }
    }
    const roleInputs = [];
    append(form, "p", t(sourceMode ? "roleHelp" : "roles"), "subtle");
    if (sourceMode) for (const role of ["classic", "topic-core", "closest-work", "comparator"]) {
      const prior = reply.roles.find(row => row.role === role), group = append(form, "details");
      append(group, "summary", t(role));
      const label = append(group, "label", undefined, "check"), selected = append(label, "input");
      selected.type = "checkbox"; selected.checked = Boolean(prior); append(label, "span", t(role));
      const reason = field(group, "roleReason", "textarea"); reason.rows = 2; reason.maxLength = 4096; reason.value = prior ? prior.reason : "";
      append(group, "p", t("roleClaims")); const claims = [];
      for (const id of reply.claim_ids) {
        const row = append(group, "label", undefined, "check"), input = append(row, "input");
        input.type = "checkbox"; input.checked = Boolean(prior && prior.claim_ids.includes(id)); append(row, "span", id); claims.push({id, input});
      }
      roleInputs.push({role, selected, reason, claims});
    }
    const label = append(form, "label", undefined, "check"), confirm = append(label, "input");
    confirm.type = "checkbox"; confirm.checked = false; confirm.required = true; append(label, "span", t("notesConfirm"));
    const button = append(form, "button", t("notesSubmit"), "primary"); button.type = "submit";
    const message = append(form, "p", available ? "" : t("notesUnavailable"), "subtle"); message.setAttribute("role", "status");
    form.querySelectorAll("button,input,textarea").forEach(node => { node.dataset.readingUnavailable = String(!available); });
    form.onsubmit = async event => {
      event.preventDefault(); if (!available || blocked() || view !== reply || basis !== originalBasis) return;
      if (confirm.checked !== true || !form.reportValidity() || Object.values(inputs).some(group => Object.values(group).some(input => !bounded(input.value)))) { message.textContent = t("notesInvalid"); return; }
      const review = {classification: {}, findings: {}, roles: []};
      for (const [name, group] of Object.entries(inputs)) for (const [key, input] of Object.entries(group)) review[name][key] = input.value;
      for (const row of roleInputs.filter(row => row.selected.checked)) {
        const ids = row.claims.filter(claim => claim.input.checked).map(claim => claim.id);
        if (!bounded(row.reason.value) || !ids.length) { message.textContent = t("notesInvalid"); return; }
        review.roles.push({role: row.role, reason: row.reason.value, claim_ids: ids});
      }
      submitting = true; disable();
      try {
        const content = sourceMode ? {revision: reply.revision, work_ref: reply.work_ref, source_snapshot_sha256: reply.source_snapshot_sha256} : {output_ref: reply.output_ref, draft_sha256: reply.draft_sha256};
        const saved = await onSaveReading(Object.assign({project_ref: reply.project_ref, input_version: reply.input_version, brief_sha256: reply.brief_sha256, ledger_state_sha256: reply.ledger_state_sha256, offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, review, confirmed: true}, content));
        if (basis === originalBasis && view === reply && saved) { form.replaceChildren(); append(form, "p", t("notesSaved"), "subtle"); }
      } catch (error) { if (basis === originalBasis && view === reply) message.textContent = error.message; }
      finally { submitting = false; disable(); }
    };
  }
  function renderSource(reply, onSaveReading) {
    const project = state && state.project, ledger = state && state.stage1 && state.stage1.ledger;
    if (!reply || !project || !ledger || reply.source_mode !== "saved-source-review"
        || reply.project_ref !== project.project_ref || reply.revision !== project.revision
        || reply.input_version !== project.input_version || reply.brief_sha256 !== project.brief_sha256
        || reply.ledger_state_sha256 !== ledger.state_sha256 || !hash(reply.source_snapshot_sha256)
        || typeof reply.work_ref !== "string" || !reply.work_ref || typeof reply.version_id !== "string"
        || !Array.isArray(reply.sources) || !Array.isArray(reply.claims) || !Array.isArray(reply.claim_ids) || !Array.isArray(reply.roles)
        || reply.sources.some(row => !row || typeof row.source_id !== "string" || !hash(row.text_sha256))
        || new Set(reply.claim_ids).size !== reply.claim_ids.length || reply.claim_ids.some(id => typeof id !== "string" || !id)
        || reply.roles.some(row => !row || !["classic", "topic-core", "closest-work", "comparator"].includes(row.role)
          || typeof row.reason !== "string" || !Array.isArray(row.claim_ids) || !row.claim_ids.length || row.claim_ids.some(id => !reply.claim_ids.includes(id)))
        || reply.claims.length !== reply.claim_ids.length || new Set(reply.claims.map(row => row && row.claim_id)).size !== reply.claim_ids.length
        || reply.claims.some(row => !row || !reply.claim_ids.includes(row.claim_id) || (row.quote !== null && typeof row.quote !== "string"))
        || !Object.entries(noteFields).every(([name, keys]) => reply[name] && keys.every(key => typeof reply[name][key] === "string"))
        || typeof onSaveReading !== "function" || new TextEncoder().encode(JSON.stringify(reply)).length > 262144) return false;
    clear(); view = reply; const panel = $("reading-panel"); $("reading-card").hidden = false;
    $("reading-title").textContent = t("sourceTitle"); append(panel, "p", t("sourceHelp"), "subtle");
    append(panel, "p", reply.work_ref + " · " + reply.version_id);
    const evidence = append(panel, "details"); append(evidence, "summary", t("sourceEvidence"));
    for (const source of reply.sources) append(evidence, "p", source.source_id + " · " + source.text_sha256);
    for (const claim of reply.claims) { append(evidence, "p", claim.claim_id); append(evidence, "blockquote", claim.quote === null ? t("unknown") : claim.quote); }
    readingNotes(panel, reply, onSaveReading, basis); disable();
    $("reading-card").scrollIntoView({block: "nearest"}); return true;
  }
  function render(reply, onSave, onSaveReading) {
    const project = state && state.project, ledger = state && state.stage1 && state.stage1.ledger;
    const draft = reply && reply.draft;
    if (!reply || !$("reading-panel") || !project || !ledger || reply.project_ref !== project.project_ref || reply.revision !== project.revision
        || reply.input_version !== project.input_version || reply.brief_sha256 !== project.brief_sha256
        || reply.ledger_state_sha256 !== ledger.state_sha256 || !hash(reply.output_ref) || !hash(reply.draft_sha256)
        || !draft || typeof draft.summary !== "string" || !draft.classification || !draft.findings
        || typeof draft.classification !== "object" || Array.isArray(draft.classification)
        || typeof draft.findings !== "object" || Array.isArray(draft.findings)
        || !Array.isArray(draft.limitations) || !Array.isArray(draft.open_questions) || !Array.isArray(draft.evidence)
        || !Array.isArray(reply.offers) || typeof onSave !== "function"
        || new TextEncoder().encode(JSON.stringify(reply)).length > 262144) return false;
    const offers = reply.offers;
    if (draft.evidence.some(span => !span || typeof span.source_id !== "string" || typeof span.quote !== "string"
        || !hash(span.text_sha256) || !Number.isInteger(span.start_byte) || !Number.isInteger(span.end_byte)
        || span.start_byte < 0 || span.end_byte <= span.start_byte)
        || [...Object.values(draft.classification), ...Object.values(draft.findings), ...draft.limitations, ...draft.open_questions].some(value => typeof value !== "string")) return false;
    if (offers.some(offer => !offer || !Number.isInteger(offer.evidence_index) || offer.evidence_index < 0
        || offer.evidence_index >= draft.evidence.length || typeof offer.offer_ref !== "string" || !hash(offer.offer_sha256)
        || typeof offer.source_id !== "string" || typeof offer.quote !== "string"
        || offer.source_id !== draft.evidence[offer.evidence_index].source_id || offer.quote !== draft.evidence[offer.evidence_index].quote)) return false;
    clear(); view = reply; const originalBasis = basis;
    const panel = $("reading-panel"); $("reading-card").hidden = false;
    append(panel, "p", t("help"), "subtle"); append(panel, "p", t("incomplete"), "subtle");
    append(panel, "p", draft.summary); preview(panel, draft);
    const held = append(panel, "p", t("held"), "subtle"); held.id = "reading-held";
    readingNotes(panel, reply, onSaveReading, originalBasis);
    if (!offers.length) { append(panel, "p", t("empty"), "subtle"); disable(); return true; }
    const select = field(panel, "choose", "select"); option(select, "", t("choose"));
    offers.forEach((offer, index) => option(select, String(index), (offer.evidence_index + 1) + ". " + (offer.quote.length > 120 ? offer.quote.slice(0, 120) + "…" : offer.quote)));
    const formArea = append(panel, "div");
    select.onchange = () => {
      formArea.replaceChildren(); selected = select.value === "" ? null : offers[Number(select.value)]; if (!selected) return;
      const offer = selected, span = draft.evidence[offer.evidence_index];
      const form = append(formArea, "form"); form.id = "reading-claim-form"; append(form, "h4", t("quote")); append(form, "blockquote", offer.quote);
      append(form, "p", t("source") + ": " + offer.source_id, "subtle");
      append(form, "p", t("textHash") + ": " + span.text_sha256, "subtle");
      append(form, "p", t("byteSpan") + ": " + span.start_byte + "–" + span.end_byte, "subtle");
      append(form, "p", t("existing") + ": " + (offer.existing_claim_id || t("noExisting")), "subtle");
      const claim = field(form, "claim", "textarea"), section = field(form, "section", "input");
      claim.rows = 3; claim.required = section.required = true; claim.maxLength = section.maxLength = 4096;
      const relation = field(form, "relation", "select"); for (const value of ["pending", "supports", "partial", "contradicts", "unclear", "unverifiable", "context"]) option(relation, value, t(value));
      const level = field(form, "level", "select"); for (const value of ["full-text", "abstract"]) option(level, value, t(value));
      const button = append(form, "button", t("submit"), "primary"); button.type = "submit";
      const message = append(form, "p", "", "subtle"); message.setAttribute("role", "status");
      form.onsubmit = async event => {
        event.preventDefault(); if (blocked() || view !== reply || selected !== offer || basis !== originalBasis || !form.reportValidity()) return;
        if (!bounded(claim.value) || !bounded(section.value)) { message.textContent = t("invalid"); return; }
        submitting = true; disable();
        try {
          const saved = await onSave({project_ref: reply.project_ref, input_version: reply.input_version, brief_sha256: reply.brief_sha256, ledger_state_sha256: reply.ledger_state_sha256, output_ref: reply.output_ref, draft_sha256: reply.draft_sha256, evidence_index: offer.evidence_index, offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, review: {claim_text: claim.value, relation: relation.value, evidence_level: level.value, section: section.value}});
          if (basis === originalBasis && view === reply && saved) { selected = null; select.value = ""; formArea.replaceChildren(); append(formArea, "p", t("saved"), "subtle"); }
        } catch (error) { if (basis === originalBasis && view === reply) message.textContent = error.message; }
        finally { submitting = false; disable(); }
      };
      disable();
    };
    disable(); $("reading-card").scrollIntoView({block: "nearest"}); return true;
  }
  window.ResearchProjectReading = Object.freeze({update, render, renderSource, text: t});
})();
