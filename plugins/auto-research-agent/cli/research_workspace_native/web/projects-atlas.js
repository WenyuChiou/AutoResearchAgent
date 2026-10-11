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
  const inputWords = {
    en: ["Review Stage 1 → Stage 2 input", "This records your decision against the saved package. It does not start Stage 2, score papers, or grant model permission.", "Request Stage 2", "Continue Stage 1", "Hold", "Reason / remaining questions", "Save input decision", "Saved decision", "Not yet decided", "Earlier package — review again", "Read sources", "Limitations", "Stage 1 handoff is not eligible", "The current Stage 2 consumer cannot yet read this canonical version", "Missing source", "Reading not registered", "Claim source or location unavailable", "Claim level needs a versioned consumer"],
    "zh-Hans": ["审阅 Stage 1 → Stage 2 输入", "此操作把你的决定绑定到保存的交付包，不会启动 Stage 2、评分或授予模型权限。", "请求进入 Stage 2", "继续 Stage 1", "暂缓", "理由／尚待解决的问题", "保存输入决定", "已保存的决定", "尚未决定", "来自旧交付包，请重新审阅", "读取来源", "待补项", "Stage 1 交接尚未满足进入条件", "当前 Stage 2 接口尚不能读取这个 canonical 版本", "缺少来源", "尚未登记阅读", "缺少主张来源或定位", "此证据级别需要新版接口"],
    "zh-Hant": ["審閱 Stage 1 → Stage 2 輸入", "此操作將你的決定綁定至保存的交付包，不會啟動 Stage 2、評分或授予模型權限。", "請求進入 Stage 2", "繼續 Stage 1", "暫緩", "理由／尚待解決的問題", "保存輸入決定", "已保存的決定", "尚未決定", "來自舊交付包，請重新審閱", "讀取來源", "待補項", "Stage 1 交接尚未滿足進入條件", "目前 Stage 2 介面尚不能讀取這個 canonical 版本", "缺少來源", "尚未登記閱讀", "缺少主張來源或定位", "此證據層級需要新版介面"]
  };
  function reviewInput(binding, view, parent) {
    const value = view.stage2_input, w = inputWords[language] || inputWords.en;
    if (!equal(view, binding) || !value || value.schema !== "ProjectStage2InputContext/1"
        || value.project_ref !== binding.project_ref || value.input_version !== binding.input_version
        || value.artifact_ref !== binding.artifact_ref || value.manifest_sha256 !== binding.manifest_sha256
        || value.index_sha256 !== view.index_sha256 || !digest(value.context_sha256)
        || !Array.isArray(value.works) || value.execution_authorized !== false) throw new Error("input-context-binding-differs");
    parent.replaceChildren();
    const node = (tag, text, original = false) => {
      const element = document.createElement(tag); element.textContent = text;
      if (original) element.setAttribute("translate", "no"); return element;
    };
    const codes = ["stage1-handoff-not-eligible", "stage2-canonical-consumer-unconnected", "source-unavailable", "reading-not-registered", "claim-source-or-location-unavailable", "claim-level-needs-versioned-consumer"];
    const reason = code => codes.includes(code) ? w[12 + codes.indexOf(code)] : code;
    parent.append(node("p", w[1]));
    for (const code of value.limitations) parent.append(node("p", reason(code)));
    const list = node("div", ""); list.className = "history";
    for (const work of value.works) {
      const row = node("div", ""); row.className = "history-row";
      row.append(node("strong", work.title, true), node("p", work.work_id + " · " + work.version_id, true));
      row.append(node("p", work.screening_status + " · " + (work.reading_status || "Unknown"), true));
      row.append(node("p", w[10] + ": " + (work.source_ids.join(" · ") || "Unknown")));
      for (const code of work.limitations) row.append(node("p", reason(code)));
      list.append(row);
    }
    const saved = value.review;
    const choices = ["request-stage2", "keep-stage1", "hold"];
    parent.append(list, node("p", saved ? w[7] + ": " + (saved.stale ? w[9] : w[2 + choices.indexOf(saved.decision)]) : w[8]));
    if (saved) parent.append(node("p", saved.user_input, true));
    const form = document.createElement("form"), choice = document.createElement("select");
    choice.setAttribute("aria-label", w[0]);
    for (const [i, option] of ["request-stage2", "keep-stage1", "hold"].entries()) {
      const item = node("option", w[2 + i]); item.value = option; choice.append(item);
    }
    choice.value = "hold";
    const label = node("label", w[5]), input = document.createElement("textarea");
    input.rows = 3; input.required = true; input.maxLength = 4096; label.append(input);
    const button = node("button", w[6]); button.type = "submit";
    form.append(choice, label, button);
    form.onsubmit = event => {
      event.preventDefault();
      if (!current || !equal(current, binding) || !input.value.trim()
          || new TextEncoder().encode(input.value).length > 4096
          || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(input.value)) return;
      document.dispatchEvent(new CustomEvent("project-review-stage2-input", {detail: {
        ...binding, brief_sha256: value.brief_sha256, context_sha256: value.context_sha256,
        decision: choice.value, user_input: input.value
      }}));
    };
    parent.append(form);
    const details = node("details", ""); details.append(node("summary", "SHA-256"), node("p", value.context_sha256)); parent.append(details);
  }
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
    const w = inputWords[language] || inputWords.en, details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = w[0]; details.append(summary);
    const content = document.createElement("div"), read = document.createElement("button"); read.type = "button"; read.textContent = w[0]; content.append(read); details.append(content); area.append(details);
    const binding = {...current};
    read.onclick = async () => {
      read.disabled = true;
      try {
        const view = await get(route(binding));
        if (current && equal(current, binding) && content.isConnected) reviewInput(binding, view, content);
      } catch (_) { if (content.isConnected) { show("failed"); read.disabled = false; } }
    };
  });
  document.addEventListener("project-screening-clear", () => { current = null; close(); if (area) area.replaceChildren(); });
  window.addEventListener("pagehide", close);
}());
