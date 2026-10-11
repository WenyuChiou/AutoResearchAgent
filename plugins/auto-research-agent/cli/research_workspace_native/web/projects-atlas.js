/* Read-only project viewer. Credentials and execution controls stay here. */
(function () {
  "use strict";
  const bootstrap = window.RESEARCH_PROJECTS;
  if (!bootstrap || typeof bootstrap.credential !== "string") return;
  let area = null;
  const words = {
    en: {open: "Open saved literature network", help: "The same saved package opens in the v6 graph. Return here for Harness actions; viewing never reruns research.", loading: "Reading the bound delivery…", failed: "This saved view could not be opened. Refresh the project and check the delivery status.", popup: "Allow this project to open its saved graph window.", expired: "Project binding changed. Open the current saved view again."},
    "zh-Hans": {open: "打开已保存文献网络", help: "用 v6 图谱查看同一交付包。Harness 操作仍在此项目页；查看不会重跑研究。", loading: "正在读取绑定的交付包…", failed: "无法打开此交付视图。请刷新项目并检查交付状态。", popup: "请允许此项目打开已保存图谱窗口。", expired: "项目绑定已变化。请重新打开当前保存视图。"},
    "zh-Hant": {open: "開啟已保存文獻網絡", help: "用 v6 圖譜查看同一交付包。Harness 操作仍在此專案頁；查看不會重跑研究。", loading: "正在讀取綁定的交付包…", failed: "無法開啟此交付視圖。請重新整理專案並檢查交付狀態。", popup: "請允許此專案開啟已保存圖譜視窗。", expired: "專案綁定已變更。請重新開啟目前保存視圖。"}
  };
  const digest = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  let current = null, session = null, language = "en", generation = 0;
  const t = key => (words[language] || words.en)[key];
  function close() {
    ++generation;
    if (session) {
      clearTimeout(session.timer);
      if (session.port) session.port.close();
      if (!session.win.closed) session.win.close();
    }
    session = null;
  }
  function route(binding) {
    return "/api/projects/" + binding.project_ref + "/stage1/atlas/" + binding.input_version + "/" + binding.revision + "/" + binding.artifact_ref + "/" + binding.manifest_sha256;
  }
  function equal(view, binding) {
    return ["project_ref", "input_version", "revision", "artifact_ref", "manifest_sha256"].every(key => view[key] === binding[key]);
  }
  async function get(path) {
    const response = await fetch(path, {method: "GET", headers: {Authorization: "Bearer " + bootstrap.credential}, cache: "no-store", credentials: "omit", redirect: "error"});
    if (!response.ok) throw new Error("saved-view-refused");
    return response.json();
  }
  function show(key) {
    const notice = document.getElementById("project-atlas-notice");
    if (notice) notice.textContent = t(key);
  }
  async function fileRequest(active, message) {
    if (session !== active || active.win.closed || active.reads >= 4 || !message || !/^[A-Za-z0-9_-]{1,64}$/.test(message.id || "")) return;
    const file = active.view.files.find(row => row.file_ref === message.file_ref && row.sha256 === message.sha256);
    if (!file) return;
    const connection = active.connection; ++active.reads;
    try {
      const result = await get(route(active.binding) + "/files/" + file.file_ref + "/" + file.sha256);
      if (session !== active || active.win.closed || connection !== active.connection) return;
      if (!equal(result, active.binding) || result.index_sha256 !== active.view.index_sha256 || !result.file || result.file.file_ref !== file.file_ref || result.file.sha256 !== file.sha256) throw new Error("saved-file-binding-differs");
      active.port.postMessage({kind: "file", id: message.id, file: result.file});
    } catch (_) {
      if (session === active && !active.win.closed && connection === active.connection && active.port) active.port.postMessage({kind: "file-error", id: message.id});
    } finally { --active.reads; }
  }
  function connect(active) {
    if (session !== active || !active.ready || !active.view || active.port || active.win.closed) return;
    const channel = new MessageChannel(); active.port = channel.port1;
    active.port.onmessage = event => {
      if (session !== active || !event.data) return;
      if (event.data.kind === "return") { window.focus(); close(); }
      else if (event.data.kind === "language" && Object.hasOwn(words, event.data.language)) active.language = event.data.language;
      else if (event.data.kind === "file-read") fileRequest(active, event.data);
    };
    active.port.start();
    active.win.postMessage({kind: "project-atlas-bound", view: active.view, language: active.language || language}, location.origin, [channel.port2]);
    clearTimeout(active.timer); show("help");
  }
  window.addEventListener("message", event => {
    const active = session;
    if (active && event.origin === location.origin && event.source === active.win && event.data && event.data.kind === "project-atlas-ready") {
      active.ready = true;
      if (active.port) {
        // A refreshed child has retired its old port. Re-read the same binding;
        // no action key, channel owner, or native operation is created.
        active.port.close(); active.port = null; active.view = null; ++active.connection;
        load(active);
      } else connect(active);
    }
  });
  async function load(active) {
    active.timer = setTimeout(() => { if (session === active) { close(); show("failed"); } }, 45000);
    try {
      const view = await get(route(active.binding));
      if (session !== active) return;
      if (!equal(view, active.binding) || view.schema !== "ProjectStage1AtlasView/1" || !digest(view.index_sha256) || !view.payload || view.payload.index_sha256 !== view.index_sha256 || !Array.isArray(view.files) || view.files.length > 1024) throw new Error("saved-view-binding-differs");
      active.view = view; connect(active);
    } catch (_) { if (session === active) { close(); show("failed"); } }
  }
  async function open() {
    if (!current) return;
    const binding = {...current}; close();
    const win = window.open("/project-atlas.html", "_blank");
    if (!win) { show("popup"); return; }
    const active = {win, binding, generation, connection: 0, reads: 0, ready: false, view: null, port: null}; session = active;
    show("loading");
    await load(active);
  }
  document.addEventListener("project-atlas-state", event => {
    area = document.getElementById("project-atlas-entry");
    if (!area) { current = null; close(); return; }
    const {project, artifact} = event.detail || {}; language = (event.detail || {}).language || "en";
    const next = project && artifact && artifact.status === "saved-evidence-validated" && /^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref) && /^[A-Za-z0-9_-]{1,128}$/.test(artifact.artifact_ref) && Number.isSafeInteger(project.input_version) && Number.isSafeInteger(project.revision) && digest(artifact.manifest_sha256)
      ? {project_ref: project.project_ref, input_version: project.input_version, revision: project.revision, artifact_ref: artifact.artifact_ref, manifest_sha256: artifact.manifest_sha256} : null;
    if (!next || current && !equal(next, current)) close();
    current = next; area.replaceChildren();
    if (!current) return;
    const button = document.createElement("button"); button.id = "project-atlas-open"; button.type = "button"; button.textContent = t("open"); button.onclick = open;
    const help = document.createElement("p"); help.id = "project-atlas-notice"; help.className = "subtle"; help.setAttribute("role", "status"); help.textContent = t("help"); area.append(button, help);
  });
  document.addEventListener("project-screening-clear", () => { current = null; close(); if (area) area.replaceChildren(); });
  window.addEventListener("pagehide", close);
}());
