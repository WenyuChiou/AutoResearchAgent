/* Trusted saved Stage1 deliveries are read-only references, never native intake state. */
(function () {
  "use strict";

  const copy = {
    en: {
      title: "Saved Stage1 delivery · read-only",
      choice: "Choose a saved Stage1 delivery",
      project: "Original project",
      version: "Input version",
      unavailable: "No valid saved Stage1 delivery is available."
    },
    "zh-Hans": {
      title: "已保存的 Stage1 交付 · 只读",
      choice: "选择已保存的 Stage1 交付",
      project: "原始项目",
      version: "输入版本",
      unavailable: "没有可用的有效 Stage1 已保存交付。"
    },
    "zh-Hant": {
      title: "已保存的 Stage1 交付 · 唯讀",
      choice: "選擇已保存的 Stage1 交付",
      project: "原始專案",
      version: "輸入版本",
      unavailable: "沒有可用的有效 Stage1 已保存交付。"
    }
  };
  const refPattern = /^[A-Za-z0-9_-]{1,64}$/;
  const hashPattern = /^[0-9a-f]{64}$/;
  let section = null, frame = null, selectedRef = null;
  let state = {selection: null, stage: 1, language: "en"};

  function validVersion(value) {
    return (typeof value === "string" && value.length <= 128 && value.trim().length > 0)
      || (Number.isSafeInteger(value) && value > 0);
  }

  function validView(row) {
    if (!row || typeof row !== "object" || Array.isArray(row)
        || !refPattern.test(row.ref || "")
        || typeof row.label !== "string" || !row.label.trim() || row.label.length > 160
        || typeof row.project_id !== "string" || !row.project_id.trim() || row.project_id.length > 128
        || !validVersion(row.input_version)
        || !["index_sha256", "manifest_sha256", "html_sha256"].every(key => hashPattern.test(row[key] || ""))
        || row.fixture !== false || row.read_only !== true
        || row.execution_authorized !== false || row.accepted !== false
        || typeof row.url !== "string") return false;
    try {
      const url = new URL(row.url, window.location.origin);
      return row.url === url.pathname && url.origin === window.location.origin
        && !url.username && !url.password && !url.search && !url.hash
        && url.pathname === "/project-stage1-saved/" + row.ref + "/index.html";
    } catch (_) { return false; }
  }

  function bindings() {
    try {
      const source = document.getElementById("project-saved-view-bindings");
      const value = JSON.parse(source?.textContent || "");
      if (!value || value.kind !== "SavedStage1References" || value.schema_version !== "1.0.0"
          || !Array.isArray(value.views) || value.views.length < 1 || value.views.length > 16
          || value.views.some(row => !validView(row))
          || new Set(value.views.map(row => row.ref)).size !== value.views.length) return [];
      return value.views.slice();
    } catch (_) { return []; }
  }
  const views = bindings();

  function clearFrame() {
    frame?.remove();
    frame = null;
  }

  function language() {
    return Object.hasOwn(copy, state.language) ? state.language : "en";
  }

  function visible(value) {
    return (value.selection === null || value.selection === undefined) && value.stage === 1;
  }

  function add(parent, tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  }

  function render() {
    if (!section || section.hidden) return;
    clearFrame();
    section.replaceChildren();
    const words = copy[language()];
    add(section, "h3", words.title);
    if (!views.length) {
      add(section, "p", words.unavailable).setAttribute("role", "status");
      return;
    }
    if (views.length === 1) selectedRef = views[0].ref;
    else {
      const select = add(section, "select");
      select.setAttribute("aria-label", words.choice);
      const placeholder = add(select, "option", words.choice);
      placeholder.value = "";
      for (const view of views) {
        const option = add(select, "option", view.label);
        option.value = view.ref;
      }
      select.value = views.some(view => view.ref === selectedRef) ? selectedRef : "";
      select.onchange = () => {
        selectedRef = views.some(view => view.ref === select.value) ? select.value : null;
        render();
      };
    }
    const view = views.find(row => row.ref === selectedRef);
    if (!view) return;
    add(section, "p", words.project + ": " + view.project_id + " · " + words.version + ": " + String(view.input_version));
    const child = document.createElement("iframe");
    frame = child;
    child.id = "project-saved-stage1-frame";
    child.title = "Saved Stage1 delivery";
    child.setAttribute("sandbox", "allow-scripts allow-same-origin allow-downloads");
    child.referrerPolicy = "no-referrer";
    child.style.cssText = "width:100%;height:700px;border:0;display:block;margin-top:16px";
    child.onload = () => {
      try {
        if (frame !== child || child.contentDocument?.URL === "about:blank") return;
        const height = Math.ceil(child.contentDocument.body.getBoundingClientRect().height);
        if (Number.isFinite(height) && height >= 0) child.style.height = Math.min(30000, Math.max(260, height)) + "px";
      } catch (_) { /* Cross-origin or incomplete documents keep the fixed safe height. */ }
    };
    section.append(child);
    child.src = view.url;
  }

  function mount(options) {
    const anchor = options?.anchor;
    if (!anchor || typeof anchor.after !== "function") return false;
    if (!section) {
      section = document.createElement("section");
      section.id = "project-saved-stage1";
    }
    anchor.after(section);
    section.hidden = state.selection !== null && state.selection !== undefined || state.stage !== 1;
    render();
    return true;
  }

  function update(next) {
    if (!next || typeof next !== "object") return false;
    const wasVisible = visible(state), priorLanguage = language();
    state = {selection: next.selection, stage: next.stage, language: next.language};
    if (!section) return true;
    const hidden = !visible(state);
    if (hidden) {
      section.hidden = true;
      clearFrame();
      section.replaceChildren();
    } else {
      const rerender = !wasVisible || section.hidden || priorLanguage !== language();
      section.hidden = false;
      if (rerender) render();
    }
    return true;
  }

  window.ResearchSavedStage1Views = Object.freeze({mount, update});
}());
