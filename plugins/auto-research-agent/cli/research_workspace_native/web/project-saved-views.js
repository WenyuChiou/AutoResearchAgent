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
  const projectRefPattern = /^project-[0-9a-f]{32}$/;
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
    const bindingFields = ["project_ref", "project_input_sha256", "binding_origin"];
    const boundFields = bindingFields.filter(key => Object.hasOwn(row, key)).length;
    if (boundFields && (boundFields !== bindingFields.length
        || typeof row.project_ref !== "string" || !projectRefPattern.test(row.project_ref)
        || typeof row.project_input_sha256 !== "string" || !hashPattern.test(row.project_input_sha256)
        || row.binding_origin !== "trusted-host-stage1-view-binding")) return false;
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

  function matchingViews(value) {
    const selection = value.selection;
    if (selection === null || selection === undefined) return views;
    if (typeof selection !== "object" || Array.isArray(selection)
        || typeof selection.project_ref !== "string" || !projectRefPattern.test(selection.project_ref)
        || !validVersion(selection.input_version)) return [];
    return views.filter(view => view.project_ref === selection.project_ref
      && view.input_version === selection.input_version);
  }

  function visible(value) {
    return value.stage === 1 && ((value.selection === null || value.selection === undefined)
      || matchingViews(value).length > 0);
  }

  function projectInputBinding(selection) {
    if (!selection || typeof selection !== "object" || Array.isArray(selection)) return null;
    const matches = matchingViews({selection});
    if (!matches.length || matches.some(view => !view.project_input_sha256
        || view.project_input_sha256 !== matches[0].project_input_sha256)) return null;
    return Object.freeze({
      kind: "SavedStage1ProjectInputBinding", schema_version: "1.0.0",
      project_ref: matches[0].project_ref, input_version: matches[0].input_version,
      project_input_sha256: matches[0].project_input_sha256, execution_authorized: false
    });
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
    const available = matchingViews(state);
    add(section, "h3", words.title);
    if (!available.length) {
      add(section, "p", words.unavailable).setAttribute("role", "status");
      return;
    }
    if (available.length === 1) selectedRef = available[0].ref;
    else {
      const select = add(section, "select");
      select.setAttribute("aria-label", words.choice);
      const placeholder = add(select, "option", words.choice);
      placeholder.value = "";
      for (const view of available) {
        const option = add(select, "option", view.label);
        option.value = view.ref;
      }
      select.value = available.some(view => view.ref === selectedRef) ? selectedRef : "";
      select.onchange = () => {
        selectedRef = available.some(view => view.ref === select.value) ? select.value : null;
        render();
      };
    }
    const view = available.find(row => row.ref === selectedRef);
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
    const changedSelection = state.selection?.project_ref !== next.selection?.project_ref
      || state.selection?.input_version !== next.selection?.input_version;
    const selection = next.selection && typeof next.selection === "object" && !Array.isArray(next.selection)
      ? {...next.selection} : next.selection;
    state = {selection, stage: next.stage, language: next.language};
    if (!section) return true;
    const hidden = !visible(state);
    if (hidden) {
      section.hidden = true;
      clearFrame();
      section.replaceChildren();
    } else {
      const rerender = !wasVisible || section.hidden || changedSelection || priorLanguage !== language();
      section.hidden = false;
      if (rerender) render();
    }
    return true;
  }

  window.ResearchSavedStage1Views = Object.freeze({mount, update, projectInputBinding});
}());
