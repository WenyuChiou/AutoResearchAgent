/* ResearchBrief overlay: explicit saved versions; never starts or activates a turn. */
(() => {
  "use strict";
  window.NativePanel.extend(({root, available, read, write}) => {
    const rows = {
      title: ["Scope & version review", "范围与版本审阅", "範圍與版本審閱"],
      boundary: ["Saving scope or a review records your decision. It does not activate this input, approve execution or start research.", "保存范围和审阅仅记录你的决定，不会激活输入、批准执行或开始研究。", "儲存範圍與審閱僅記錄你的決定，不會啟用輸入、核准執行或開始研究。"],
      version: ["Saved brief version", "已保存范围版本", "已儲存範圍版本"],
      field: ["Scope field", "范围字段", "範圍欄位"],
      choice: ["Your choice", "你的选择", "你的選擇"],
      specified: ["Specify a value", "指定范围", "指定範圍"],
      unrestricted: ["Leave unrestricted", "不限制范围", "不限制範圍"],
      "not-applicable": ["Not applicable", "不适用", "不適用"],
      value: ["Value", "具体范围", "具體範圍"],
      reason: ["Reason", "原因", "原因"],
      original: ["Your original instruction", "你的原始说明", "你的原始說明"],
      confirm: ["I confirm this decision for the displayed version", "我确认对当前显示版本作此决定", "我確認對目前顯示版本作此決定"],
      save: ["Save new scope version", "保存新的范围版本", "儲存新的範圍版本"],
      review: ["Record version review", "记录版本审阅", "記錄版本審閱"],
      reviewed: ["Reviewed", "已审阅", "已審閱"],
      changes: ["Changes requested", "需要修改", "需要修改"],
      note: ["Review note", "审阅意见", "審閱意見"],
      held: ["Local intent retained. Read history to recover; do not resubmit.", "本地意图已保留，请读取历史恢复，不要重新提交。", "本機意圖已保留，請讀取歷史恢復，不要重新提交。"],
      unavailable: ["Scope overlay unavailable for this session", "本会话的范围覆盖层不可用", "本工作階段的範圍覆蓋層不可用"],
      large: ["Decision is too large or local intent storage is unavailable", "决定过长或本地意图存储不可用", "決定過長或本機意圖儲存不可用"],
    };
    const el = (tag, parent, text) => {
      const e = document.createElement(tag); if (text !== undefined) e.textContent = text;
      e.setAttribute("translate", "no"); parent?.append(e); return e;
    };
    const translated = (tag, parent, key) => {const e = el(tag, parent); e.dataset.scopeLabel = key; return e;};
    const box = el("section", root); box.id = "native-scope-panel";
    translated("h3", box, "title"); translated("p", box, "boundary");
    const notice = el("p", box); notice.setAttribute("role", "status");
    const content = el("div", box);
    let view = null, history = null, selected = null, snapshot = null, sequence = 0, busy = false, loading = false;
    let noticeKey = null; const index = () => ({en: 0, "zh-Hans": 1, "zh-Hant": 2}[document.documentElement.lang] ?? 0);
    const t = key => rows[key][index()];
    const showNotice = key => {noticeKey = key; notice.textContent = key ? t(key) : "";}; const translate = () => {box.querySelectorAll("[data-scope-label]").forEach(e => e.textContent = t(e.dataset.scopeLabel)); box.querySelectorAll("[data-scope-aria]").forEach(e => e.setAttribute("aria-label", t(e.dataset.scopeAria))); if (noticeKey) notice.textContent = t(noticeKey);};
    new MutationObserver(translate).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
    const ledgerName = () => `native-scope-intents:${view.project_ref}:${view.index_sha256}:${view.input_version}`;
    const intents = () => {
      const records = JSON.parse(sessionStorage.getItem(ledgerName()) || "[]");
      if (!Array.isArray(records) || records.length > 128 || records.some(r => !r ||
        Object.keys(r).sort().join() !== "key,kind,target" || !/^[a-z0-9-]{36}$/.test(r.key) ||
        !/^[0-9a-f]{64}$/.test(r.target) || !["versions", "reviews"].includes(r.kind))) throw Error("local-intents-invalid");
      return records;
    };
    const held = kind => intents().some(r => r.kind === kind && r.target === selected &&
      !history.actions.some(a => a.client_key === r.key && ["version-saved", "review-recorded"].includes(a.status)));
    const field = (parent, key, tag = "textarea") => {
      const label = el("label", parent); translated("span", label, key);
      const control = el(tag, label); control.required = true;
      control.dataset.scopeAria = key; control.setAttribute("aria-label", t(key)); return control;
    };
    const confirmation = parent => {
      const label = el("label", parent), checkbox = el("input", label);
      checkbox.type = "checkbox"; checkbox.required = true;
      translated("span", label, "confirm"); return checkbox;
    };
    const render = () => {
      content.replaceChildren(); if (!history || !snapshot) return;
      const version = field(content, "version", "select");
      for (const row of history.versions) {
        const option = el("option", version, row.sha256); option.value = row.version_ref;
      }
      version.value = selected;
      version.onchange = async () => {selected = version.value; await load(view);};
      el("pre", content, JSON.stringify(snapshot, null, 2));
      const form = el("form", content); form.id = "native-scope-form";
      const choiceField = field(form, "field", "select");
      for (const row of snapshot.scope_fields) el("option", choiceField, row.field).value = row.field;
      const choice = field(form, "choice", "select");
      for (const key of ["specified", "unrestricted", "not-applicable"]) translated("option", choice, key).value = key;
      const value = field(form, "value"); value.maxLength = 8000;
      const reason = field(form, "reason"); reason.maxLength = 8000;
      const original = field(form, "original"); original.maxLength = 8000;
      const confirmed = confirmation(form);
      choice.onchange = () => {value.required = choice.value === "specified"; value.disabled = choice.value !== "specified";};
      const save = translated("button", form, "save"); save.type = "submit";
      save.disabled = busy || loading || !available() || selected !== history.latest_version_ref || held("versions");
      form.onsubmit = event => {event.preventDefault(); if (confirmed.checked) submit("versions", {
        parent_ref: snapshot.version_ref, parent_sha256: snapshot.sha256,
        choices: [{field: choiceField.value, status: choice.value,
          value: choice.value === "specified" ? value.value : null, reason: reason.value, user_input: original.value}],
      });};
      const reviewForm = el("form", content); reviewForm.id = "native-review-form";
      const decision = field(reviewForm, "review", "select");
      translated("option", decision, "reviewed").value = "reviewed";
      translated("option", decision, "changes").value = "changes-requested";
      const note = field(reviewForm, "note"); note.maxLength = 8000;
      const reviewed = confirmation(reviewForm);
      const review = translated("button", reviewForm, "review"); review.type = "submit";
      review.disabled = busy || loading || !available() || held("reviews");
      reviewForm.onsubmit = event => {event.preventDefault(); if (reviewed.checked) submit("reviews", {
        version_ref: snapshot.version_ref, version_sha256: snapshot.sha256, decision: decision.value, note: note.value,
      });};
      for (const action of history.actions) el("pre", content, JSON.stringify(action, null, 2));
      for (const local of intents()) if (!history.actions.some(a => a.client_key === local.key)) {
        translated("p", content, "held"); el("code", content, local.key + " · " + local.target);
      }
      translate();
    };
    const load = async nextView => {
      const current = ++sequence;
      loading = true; content.querySelectorAll("input, textarea, select, button").forEach(e => e.disabled = true);
      if (!view || nextView.project_ref !== view.project_ref || nextView.input_version !== view.input_version ||
        nextView.index_sha256 !== view.index_sha256) {selected = null; history = null; snapshot = null; content.replaceChildren();}
      view = nextView;
      try {
        const saved = await read("/scope");
        if (current !== sequence) return;
        if (saved.project_ref !== view.project_ref || saved.index_sha256 !== view.index_sha256 || saved.input_version !== view.input_version) throw Error("scope-binding-differs");
        const ref = selected && saved.versions.some(v => v.version_ref === selected) ? selected : saved.latest_version_ref;
        const value = await read("/scope/versions/" + ref);
        if (current !== sequence) return;
        if (value.version_ref !== ref || value.sha256 !== saved.versions.find(v => v.version_ref === ref).sha256) throw Error("scope-version-differs");
        history = saved; selected = ref; snapshot = value; loading = false; render();
      } catch {if (current === sequence) {history = null; snapshot = null; loading = false; content.replaceChildren(); showNotice("unavailable");}}
    };
    const submit = async (kind, body) => {
      if (busy || loading || !available() || !history || !snapshot || selected !== snapshot.version_ref || held(kind)) return;
      const key = crypto.randomUUID();
      body = {key, revision: history.revision, index_sha256: view.index_sha256, input_version: view.input_version, confirmed: true, ...body};
      try {
        const previous = intents(), encoded = JSON.stringify(body);
        if (previous.length >= 128 || /\\u[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}/.test(encoded) || new TextEncoder().encode(encoded).length > 32768) throw Error("scope-body-bound");
        sessionStorage.setItem(ledgerName(), JSON.stringify([...previous, {key, kind, target: selected}]));
        if (!intents().some(r => r.key === key)) throw Error("intent-unobserved");
      } catch {showNotice("large"); return;}
      busy = true; showNotice("held");
      try {await write("/scope/" + kind, body); if (kind === "versions") selected = null;}
      catch {showNotice("held");}
      finally {busy = false; if (view) await load(view);}
    };
    translate();
    return {refresh: load, clear() {sequence++; view = null; history = null; snapshot = null; selected = null; loading = false; content.replaceChildren(); showNotice(null);}};
  });
})();
