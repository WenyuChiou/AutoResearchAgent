/* Fixed v6 renderer receives saved data over an exact-parent memory channel. */
(function () {
  "use strict";
  const status = document.getElementById("project-atlas-status"), parent = window.parent !== window ? window.parent : null;
  const hash = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  const messages = {
    en: {ready: "Saved delivery view", loading: "Opening the saved literature network…", failed: "Saved view unavailable. Refresh the project workspace.", file: "This saved file could not be read. Refresh the project workspace.", version: "Input version"},
    "zh-Hans": {ready: "已保存交付视图", loading: "正在打开已保存文献网络…", failed: "保存视图不可用。请刷新项目工作台。", file: "无法读取已保存文件。请刷新项目工作台。", version: "输入版本"},
    "zh-Hant": {ready: "已保存交付視圖", loading: "正在開啟已保存文獻網絡…", failed: "保存視圖不可用。請重新整理專案工作台。", file: "無法讀取已保存檔案。請重新整理專案工作台。", version: "輸入版本"}
  };
  let port = null, view = null, binding = null, bound = false, language = "en", serial = 0;
  let resize = null, mutations = null, scheduled = false, lastHeight = 0;
  const pending = new Map();
  function notice(key) { status.textContent = (messages[language] || messages.en)[key]; }
  function ready() {
    notice("ready");
    const identity = document.createElement("span"); identity.setAttribute("translate", "no");
    identity.textContent = " · " + view.project_ref + " · " + messages[language].version + " " + view.input_version;
    status.append(identity);
    measure();
  }
  function measure() {
    if (!port || !binding || scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      if (!port || !binding) return;
      const height = Math.max(240, Math.min(12000, Math.ceil(document.body.getBoundingClientRect().height)));
      if (height === lastHeight) return;
      lastHeight = height; port.postMessage({kind: "layout", ...binding, height});
    });
  }
  function inlineLayout() {
    document.body.classList.add("project-atlas-inline");
    const style = document.createElement("style");
    style.textContent = ".project-atlas-inline{margin:0;min-height:0;overflow-x:hidden}.project-atlas-inline .atlas-shell{display:block;min-height:0}.project-atlas-inline .atlas-sidebar,.project-atlas-inline .atlas-topbar{display:none}.project-atlas-inline #atlas-content{padding:16px 0;max-width:none}.project-atlas-inline #project-atlas-status{margin:0 0 8px!important}.project-atlas-inline #atlas-footer{padding:12px 0}";
    document.head.append(style);
    if (typeof ResizeObserver === "function") { resize = new ResizeObserver(measure); resize.observe(document.body); }
    if (typeof MutationObserver === "function") { mutations = new MutationObserver(measure); mutations.observe(document.body, {childList: true, subtree: true, attributes: true}); }
    window.addEventListener("resize", measure);
  }
  function clear() {
    for (const row of pending.values()) clearTimeout(row.timer);
    pending.clear(); if (resize) resize.disconnect(); if (mutations) mutations.disconnect();
    resize = null; mutations = null; if (port) port.close(); port = null; view = null; binding = null;
    delete window.WORKSPACE_VIEW;
  }
  function script(name) {
    return new Promise((resolve, reject) => {
      const element = document.createElement("script");
      element.src = "/project-atlas-static/" + name;
      element.onload = resolve; element.onerror = reject; document.body.append(element);
    });
  }
  async function fileResult(message) {
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id); clearTimeout(request.timer);
    if (message.kind !== "file" || !message.file || message.file.file_ref !== request.file.file_ref || message.file.sha256 !== request.file.sha256 || typeof message.file.content !== "string" || message.file.content.length > 2 * 1024 * 1024) { notice("file"); return; }
    const bytes = new TextEncoder().encode(message.file.content);
    const actual = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))).map(value => value.toString(16).padStart(2, "0")).join("");
    if (!port || actual !== request.file.sha256) { notice("file"); return; }
    const blob = new Blob([bytes], {type: request.file.mime}), url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = request.file.path.split("/").pop();
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  window.addEventListener("message", async event => {
    if (bound || !parent || event.source !== parent || event.origin !== location.origin || !event.data || event.data.kind !== "project-atlas-bound" || event.data.inline !== true || event.ports.length !== 1) return;
    const item = event.data.view, identity = event.data.binding;
    if (!identity || !/^[A-Za-z0-9_-]{1,64}$/.test(identity.project_ref || "") || !/^[A-Za-z0-9_-]{1,128}$/.test(identity.artifact_ref || "") || !Number.isSafeInteger(identity.input_version) || identity.input_version < 1 || !Number.isSafeInteger(identity.revision) || identity.revision < 0 || !hash(identity.manifest_sha256) || !hash(identity.brief_sha256) || !item || !["project_ref", "input_version", "revision", "artifact_ref", "manifest_sha256"].every(key => item[key] === identity[key]) || item.stage2_input?.brief_sha256 !== identity.brief_sha256) return;
    if (!item || item.schema !== "ProjectStage1AtlasView/1" || !hash(item.index_sha256) || !item.payload || item.payload.index_sha256 !== item.index_sha256 || !Array.isArray(item.files) || item.files.length > 1024 || !item.files.every(file => hash(file.file_ref) && hash(file.sha256) && /^(wiki\/[a-f0-9]{64}\.md|references\.bib|literature\/(screening|included)\.bib)$/.test(file.path) && ["text/markdown", "application/x-bibtex"].includes(file.mime))) return;
    bound = true; view = item; binding = identity; language = messages[event.data.language] ? event.data.language : "en"; port = event.ports[0];
    port.onmessage = received => {
      if (!received.data) return;
      if (["file", "file-error"].includes(received.data.kind)) fileResult(received.data).catch(() => notice("file"));
      else if (received.data.kind === "language" && Object.hasOwn(messages, received.data.language)) {
        language = received.data.language;
        const control = document.getElementById("atlas-language");
        if (control) { control.value = language; control.dispatchEvent(new Event("change")); }
        ready();
      }
    };
    port.start(); notice("loading");
    const languageControl = document.getElementById("atlas-language"); if (languageControl) languageControl.value = language;
    window.WORKSPACE_VIEW = item.payload; inlineLayout();
    try {
      for (const name of ["atlas-model.js", "vendor/3d-force-graph-1.80.1.min.js", "atlas-associations.js", "atlas-spatial.js", "atlas-network.js", "project-atlas-screening.js", "atlas-ui.js"]) await script(name);
      ready();
      if (languageControl) languageControl.addEventListener("change", () => {
        if (Object.hasOwn(messages, languageControl.value)) {
          language = languageControl.value; ready(); if (port) port.postMessage({kind: "language", language});
        }
      });
    } catch (_) { if (port) port.postMessage({kind: "view-error"}); clear(); notice("failed"); }
  });
  function localLink(event) {
    const link = event.target.closest && event.target.closest("a[href]");
    if (!link || !view || !port) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    if (url.pathname === "/index.html" || url.pathname === "/") { event.preventDefault(); port.postMessage({kind: "return"}); return; }
    const file = view.files.find(row => url.pathname === "/" + row.path && !url.search && !url.hash);
    if (!file) return;
    event.preventDefault();
    if (pending.size >= 4) { notice("file"); return; }
    const id = "file-" + (++serial), timer = setTimeout(() => { pending.delete(id); notice("file"); }, 35000);
    pending.set(id, {file, timer}); port.postMessage({kind: "file-read", id, file_ref: file.file_ref, sha256: file.sha256});
  }
  document.addEventListener("click", localLink, true);
  document.addEventListener("auxclick", localLink, true);
  window.addEventListener("pagehide", clear);
  if (parent) parent.postMessage({kind: "project-atlas-ready"}, location.origin);
}());
