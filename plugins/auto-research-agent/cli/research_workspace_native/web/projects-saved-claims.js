/* Saved-source review. All credentials, intents and dispatch stay in the broker. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const words = {
    en: ["Review evidence in saved source text", "Select the exact passage, then state one claim. Source text stays verbatim. This saves evidence only; it does not verify identity, accept coverage or run Codex.", "Saved source", "Previous page", "Next page", "Use selected passage", "Exact quotation", "Your claim", "Source section / location", "Relation", "Evidence level", "I reviewed the source and this claim.", "Save reviewed claim", "Select a passage and complete the review. Each text field must be valid Unicode within 4096 UTF-8 bytes.", "Saved. Read history and refresh before the next claim.", "Close", "supports", "partial", "contradicts", "unclear", "unverifiable", "pending", "context", "full-text", "abstract"],
    "zh-Hans": ["审阅已保存原文的证据", "选取精确原文，再填写一条主张。来源文字保持原文。这只保存证据，不代表身份核实、接受覆盖或运行 Codex。", "已保存来源", "上一页", "下一页", "使用选中原文", "精确引文", "你的主张", "来源章节／位置", "关系", "证据层级", "我已审阅来源及此条主张。", "保存已审阅主张", "请选取原文并填写审阅内容。每项文字须为完整 Unicode，不超过 4096 个 UTF-8 字节。", "已保存。请查看历史并刷新，再登记下一条主张。", "关闭", "支持", "部分支持", "反驳", "不明确", "无法核实", "待评估", "仅作为背景", "全文", "摘要"],
    "zh-Hant": ["審閱已保存原文的證據", "選取精確原文，再填寫一條主張。來源文字保持原文。這只保存證據，不代表身分核實、接受覆蓋或執行 Codex。", "已保存來源", "上一頁", "下一頁", "使用選取原文", "精確引文", "你的主張", "來源章節／位置", "關係", "證據層級", "我已審閱來源及此條主張。", "保存已審閱主張", "請選取原文並填寫審閱內容。每項文字須為完整 Unicode，不超過 4096 個 UTF-8 位元組。", "已保存。請查看歷史並重新整理，再登記下一條主張。", "關閉", "支持", "部分支持", "反駁", "不明確", "無法核實", "待評估", "僅作為背景", "全文", "摘要"]
  };
  let state, signature, view, pages = [], busy = false;
  const t = i => (words[state && state.language] || words.en)[i];
  const blocked = () => !state || state.busy || state.held || busy;
  function node(parent, tag, text) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; parent.append(n); return n; }
  function field(parent, label, tag) { const row = node(parent, "label"); node(row, "span", label); return node(row, tag); }
  function button(parent, caption, action, unavailable = false) { const n = node(parent, "button", caption); n.type = "button"; n.dataset.unavailable = String(unavailable); n.onclick = action; return n; }
  function bounded(value) {
    if (!value.trim() || new TextEncoder().encode(value).length > 4096) return false;
    for (let i = 0; i < value.length; i++) {
      const c = value.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF) { const d = value.charCodeAt(++i); if (!(d >= 0xDC00 && d <= 0xDFFF)) return false; }
      else if (c >= 0xDC00 && c <= 0xDFFF) return false;
    }
    return true;
  }
  function disable() { const panel = $("source-claim-panel"); if (panel) panel.querySelectorAll("button,input,select,textarea").forEach(n => { n.disabled = blocked() || n.dataset.unavailable === "true"; }); }
  function clear() { view = null; pages = []; $("source-claim-panel").replaceChildren(); $("source-claim-card").hidden = true; }
  function update(next) {
    state = next;
    const p = next.project, ledger = next.stage1 && next.stage1.ledger;
    const current = JSON.stringify([p && p.project_ref, p && p.input_version, p && p.brief_sha256, p && p.revision, ledger && ledger.state_sha256, next.language]);
    if (current !== signature) { signature = current; clear(); }
    disable();
  }
  function render(reply, readPage, save, readNotes) {
    const p = state && state.project;
    if (!p || reply.project_ref !== p.project_ref || reply.input_version !== p.input_version
        || reply.brief_sha256 !== p.brief_sha256 || reply.revision !== p.revision) return;
    const prior = view; view = reply;
    if (!prior || prior.selected_source.source_ref !== reply.selected_source.source_ref || prior.work_ref !== reply.work_ref) pages = [];
    const panel = $("source-claim-panel"), basis = signature;
    panel.replaceChildren(); $("source-claim-card").hidden = false;
    node(panel, "h2", t(0)); node(panel, "p", t(1));
    button(panel, t(15), () => { clear(); document.dispatchEvent(new Event("project-close-source-review")); });
    if (typeof readNotes === "function") {
      const titles = {en: "Review and register reading notes", "zh-Hans": "审阅并登记阅读笔记", "zh-Hant": "審閱並登記閱讀筆記"};
      button(panel, titles[state.language] || titles.en, () => { if (!blocked() && view === reply && signature === basis) return readNotes(reply); });
    }
    const choice = field(panel, t(2), "select");
    for (const source of reply.sources) { const n = node(choice, "option", source.source_id + " · " + source.scope); n.value = source.source_ref; }
    choice.value = reply.selected_source.source_ref;
    async function load(source, offset, direction) {
      if (blocked()) return;
      const previous = pages.slice();
      if (direction === "previous") pages.pop();
      if (direction === "next") pages.push(reply.page.start_byte);
      busy = true; disable();
      try { if (await readPage(source, offset) !== true) pages = previous; }
      catch (error) { pages = previous; throw error; }
      finally { busy = false; disable(); }
    }
    choice.onchange = () => load(choice.value, 0);
    const controls = node(panel, "div");
    button(controls, t(3), () => load(choice.value, pages[pages.length - 1], "previous"), pages.length === 0);
    button(controls, t(4), () => load(choice.value, reply.page.next_byte, "next"), reply.page.next_byte === null);
    node(panel, "p", reply.work_ref + " · " + reply.version_id + " · SHA-256 " + reply.selected_source.text_sha256);
    const source = node(panel, "textarea"); source.id = "saved-claim-source-text"; source.readOnly = true; source.rows = 12; source.value = reply.page.text;
    // Textareas normalize CRLF/CR to LF. Preserve a map back to original UTF16
    // positions so quotes and UTF8 byte offsets always use the saved raw text.
    const positions = [0];
    for (let i = 0; i < reply.page.text.length;) {
      if (reply.page.text[i] === "\r" && reply.page.text[i + 1] === "\n") i += 2;
      else i++;
      positions.push(i);
    }
    source.setAttribute("aria-label", t(2));
    const quote = node(panel, "blockquote"), status = node(panel, "p"); status.setAttribute("role", "status");
    let span;
    button(panel, t(5), () => {
      const a = positions[source.selectionStart], b = positions[source.selectionEnd], text = reply.page.text.slice(a, b);
      if (!bounded(text)) { status.textContent = t(13); return; }
      span = {start_byte: reply.page.start_byte + new TextEncoder().encode(reply.page.text.slice(0, a)).length,
        end_byte: reply.page.start_byte + new TextEncoder().encode(reply.page.text.slice(0, b)).length, quote: text};
      quote.textContent = t(6) + ": " + text; quote.style.whiteSpace = "pre-wrap";
    });
    const form = node(panel, "form"); form.id = "saved-claim-form";
    const claim = field(form, t(7), "textarea"), section = field(form, t(8), "input");
    claim.rows = 3; claim.required = section.required = true; claim.maxLength = section.maxLength = 4096;
    const relation = field(form, t(9), "select"), level = field(form, t(10), "select");
    for (const [i, value] of ["supports", "partial", "contradicts", "unclear", "unverifiable", "pending", "context"].entries()) { const n = node(relation, "option", t(16 + i)); n.value = value; }
    relation.value = "pending";
    for (const [i, value] of ["full-text", "abstract"].entries()) { const n = node(level, "option", t(23 + i)); n.value = value; }
    const confirmRow = node(form, "label"), confirm = node(confirmRow, "input"); confirm.type = "checkbox"; confirm.required = true; node(confirmRow, "span", t(11));
    const submit = node(form, "button", t(12)); submit.type = "submit";
    form.onsubmit = async event => {
      event.preventDefault();
      if (blocked() || view !== reply || signature !== basis) return;
      if (!span || !confirm.checked || !bounded(claim.value) || !bounded(section.value)) { status.textContent = t(13); return; }
      busy = true; disable();
      try {
        const result = await save(Object.assign({}, span, {project_ref: reply.project_ref, revision: reply.revision,
          input_version: reply.input_version, brief_sha256: reply.brief_sha256, ledger_state_sha256: reply.ledger_state_sha256,
          work_ref: reply.work_ref, source_ref: reply.selected_source.source_ref, offer_sha256: reply.selected_source.offer_sha256,
          review: {claim_text: claim.value, section: section.value, relation: relation.value, evidence_level: level.value}}));
        if (result && view === reply) status.textContent = t(14);
      } finally { busy = false; disable(); }
    };
    disable(); $("source-claim-card").scrollIntoView({behavior: "smooth", block: "start"});
  }
  window.ResearchSavedClaims = {update, render};
}());
