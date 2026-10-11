/* Fixed v6 renderer receives saved data over an exact-parent memory channel. */
(function () {
  "use strict";
  const status = document.getElementById("project-atlas-status"), parent = window.opener;
  const hash = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  const messages = {
    en: {ready: "Saved delivery view · Return to the project workspace for Harness actions.", loading: "Opening the saved literature network…", failed: "Saved view unavailable. Open it again from the project workspace.", file: "This saved file could not be read. Refresh the project before reopening the view.", back: "Return to project"},
    "zh-Hans": {ready: "已保存交付视图 · Harness 操作请返回项目工作台。", loading: "正在打开已保存文献网络…", failed: "保存视图不可用。请从项目工作台重新打开。", file: "无法读取已保存文件。请刷新项目后重新打开视图。", back: "返回项目"},
    "zh-Hant": {ready: "已保存交付視圖 · Harness 操作請返回專案工作台。", loading: "正在開啟已保存文獻網絡…", failed: "保存視圖不可用。請從專案工作台重新開啟。", file: "無法讀取已保存檔案。請重新整理專案後再開啟視圖。", back: "返回專案"}
  };
  let port = null, view = null, bound = false, language = "en", serial = 0;
  const pending = new Map();
  function notice(key) { status.textContent = (messages[language] || messages.en)[key]; }
  function ready() {
    notice("ready");
    const back = document.createElement("button"); back.type = "button"; back.textContent = messages[language].back; back.onclick = () => { if (port) port.postMessage({kind: "return"}); }; status.append(" ", back);
  }
  function clear() {
    for (const row of pending.values()) clearTimeout(row.timer);
    pending.clear(); if (port) port.close(); port = null; view = null;
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
    if (bound || !parent || event.source !== parent || event.origin !== location.origin || !event.data || event.data.kind !== "project-atlas-bound" || event.ports.length !== 1) return;
    const item = event.data.view;
    if (!item || item.schema !== "ProjectStage1AtlasView/1" || !hash(item.index_sha256) || !item.payload || item.payload.index_sha256 !== item.index_sha256 || !Array.isArray(item.files) || item.files.length > 1024 || !item.files.every(file => hash(file.file_ref) && hash(file.sha256) && /^(wiki\/[a-f0-9]{64}\.md|references\.bib|literature\/(screening|included)\.bib)$/.test(file.path) && ["text/markdown", "application/x-bibtex"].includes(file.mime))) return;
    bound = true; view = item; language = messages[event.data.language] ? event.data.language : "en"; port = event.ports[0];
    port.onmessage = received => { if (received.data && ["file", "file-error"].includes(received.data.kind)) fileResult(received.data).catch(() => notice("file")); };
    port.start(); notice("loading");
    const languageControl = document.getElementById("atlas-language"); if (languageControl) languageControl.value = language;
    window.WORKSPACE_VIEW = item.payload;
    try {
      for (const name of ["atlas-model.js", "vendor/3d-force-graph-1.80.1.min.js", "atlas-associations.js", "atlas-spatial.js", "atlas-network.js", "project-atlas-screening.js", "atlas-ui.js"]) await script(name);
      ready();
      if (languageControl) languageControl.addEventListener("change", () => {
        if (Object.hasOwn(messages, languageControl.value)) {
          language = languageControl.value; ready(); if (port) port.postMessage({kind: "language", language});
        }
      });
    } catch (_) { clear(); notice("failed"); }
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
