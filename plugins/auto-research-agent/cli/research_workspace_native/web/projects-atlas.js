/* Read-only project viewer. Credentials and execution controls stay here. */
(function () {
  "use strict";
  const bootstrap = window.RESEARCH_PROJECTS;
  if (!bootstrap || typeof bootstrap.credential !== "string") return;
  let area = null, inline = null, inputArea = null, inputPanel = null;
  const words = {
    en: {title: "Saved literature network", help: "The graph below shows this project's saved package. Viewing does not rerun research.", loading: "Reading this project's saved delivery…", failed: "This saved view was refused or could not be read. Refresh the project and check the delivery status.", empty: "Not generated yet. This project has no validated saved literature result. Complete Stage 1 and save its delivery to see the network here.", expired: "The project binding changed. The earlier saved view has been cleared."},
    "zh-Hans": {title: "已保存文献网络", help: "下方图谱显示当前项目已保存的交付包。查看不会重跑研究。", loading: "正在读取当前项目已保存的交付包…", failed: "此保存视图被拒绝或无法读取。请刷新项目并检查交付状态。", empty: "尚未生成。当前项目尚无通过校验的已保存文献结果。完成 Stage 1 并保存交付包后，图谱会显示在这里。", expired: "项目绑定已变化，旧保存视图已清除。"},
    "zh-Hant": {title: "已保存文獻網絡", help: "下方圖譜顯示目前專案已保存的交付包。檢視不會重跑研究。", loading: "正在讀取目前專案已保存的交付包…", failed: "此保存視圖被拒絕或無法讀取。請重新整理專案並檢查交付狀態。", empty: "尚未產生。目前專案尚無通過校驗的已保存文獻結果。完成 Stage 1 並保存交付包後，圖譜會顯示在這裡。", expired: "專案綁定已變更，舊保存視圖已清除。"}
  };
  const digest = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
  let current = null, session = null, language = "en", generation = 0;
  const t = key => (words[language] || words.en)[key];
  const inputWords = {
    en: ["Review Stage 1 → Stage 2 input", "This records your decision against the saved package. It does not start Stage 2, score papers, or grant model permission.", "Request Stage 2", "Continue Stage 1", "Hold", "Reason / remaining questions", "Save input decision", "Saved decision", "Not yet decided", "Earlier package — review again", "Read sources", "Limitations", "Stage 1 handoff is not eligible", "The current Stage 2 consumer cannot yet read this canonical version", "Missing source", "Reading not registered", "Claim source or location unavailable", "Claim level needs a versioned consumer"],
    "zh-Hans": ["审阅 Stage 1 → Stage 2 输入", "此操作把你的决定绑定到保存的交付包，不会启动 Stage 2、评分或授予模型权限。", "请求进入 Stage 2", "继续 Stage 1", "暂缓", "理由／尚待解决的问题", "保存输入决定", "已保存的决定", "尚未决定", "来自旧交付包，请重新审阅", "读取来源", "待补项", "Stage 1 交接尚未满足进入条件", "当前 Stage 2 接口尚不能读取这个 canonical 版本", "缺少来源", "尚未登记阅读", "缺少主张来源或定位", "此证据级别需要新版接口"],
    "zh-Hant": ["審閱 Stage 1 → Stage 2 輸入", "此操作將你的決定綁定至保存的交付包，不會啟動 Stage 2、評分或授予模型權限。", "請求進入 Stage 2", "繼續 Stage 1", "暫緩", "理由／尚待解決的問題", "保存輸入決定", "已保存的決定", "尚未決定", "來自舊交付包，請重新審閱", "讀取來源", "待補項", "Stage 1 交接尚未滿足進入條件", "目前 Stage 2 介面尚不能讀取這個 canonical 版本", "缺少來源", "尚未登記閱讀", "缺少主張來源或定位", "此證據層級需要新版介面"]
  };
  const inputStatusWords = {
    en: ["Saved Stage 1 input", "Handoff eligible", "Handoff not eligible", "Handoff eligibility unknown", "Canonical format", "Stage 2 consumer", "Existing canonical consumer", "Consumer unconnected", "Unknown", "No validated saved Stage 1 input is available for this project/version.", "Reading the saved Stage 1 input…", "The saved Stage 1 input was refused or could not be read. Refresh this project and check its delivery status."],
    "zh-Hans": ["已保存的 Stage 1 输入", "交接满足进入条件", "交接未满足进入条件", "交接条件未知", "规范格式", "Stage 2 接口", "已有规范格式接口", "接口尚未连接", "未知", "此项目／版本尚无通过校验的已保存 Stage 1 输入。", "正在读取已保存的 Stage 1 输入…", "已保存的 Stage 1 输入被拒绝或无法读取。请刷新当前项目并检查交付状态。"],
    "zh-Hant": ["已保存的 Stage 1 輸入", "交接滿足進入條件", "交接未滿足進入條件", "交接條件未知", "規範格式", "Stage 2 介面", "已有規範格式介面", "介面尚未連接", "未知", "此專案／版本尚無通過校驗的已保存 Stage 1 輸入。", "正在讀取已保存的 Stage 1 輸入…", "已保存的 Stage 1 輸入被拒絕或無法讀取。請重新整理目前專案並檢查交付狀態。"]
  };
  function reviewInput(binding, view, parent) {
    const value = view.stage2_input, w = inputWords[language] || inputWords.en, status = inputStatusWords[language] || inputStatusWords.en;
    if (!equal(view, binding) || !value || value.schema !== "ProjectStage2InputContext/1"
        || value.project_ref !== binding.project_ref || value.input_version !== binding.input_version
        || value.artifact_ref !== binding.artifact_ref || value.manifest_sha256 !== binding.manifest_sha256
        || value.index_sha256 !== view.index_sha256 || !digest(value.context_sha256)
        || !Array.isArray(value.works) || !Array.isArray(value.limitations) || value.execution_authorized !== false) throw new Error("input-context-binding-differs");
    parent.replaceChildren();
    const node = (tag, text, original = false) => {
      const element = document.createElement(tag); element.textContent = text;
      if (original) element.setAttribute("translate", "no"); return element;
    };
    const codes = ["stage1-handoff-not-eligible", "stage2-canonical-consumer-unconnected", "source-unavailable", "reading-not-registered", "claim-source-or-location-unavailable", "claim-level-needs-versioned-consumer"];
    const reason = code => codes.includes(code) ? w[12 + codes.indexOf(code)] : code;
    const eligibility = value.eligible_for_stage2 === true ? status[1] : value.eligible_for_stage2 === false ? status[2] : status[3];
    const consumer = value.consumer_status === "existing-contract" ? status[6] : value.consumer_status === "unconnected" ? status[7] : status[8];
    parent.append(node("h3", status[0]), node("p", eligibility + " · " + status[4] + ": " + (value.records_version || status[8]) + " · " + status[5] + ": " + consumer), node("p", w[1]));
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
      if (!current || !equal(current, binding) || !form.isConnected || !choices.includes(choice.value) || !input.value.trim()
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
  function clearInput() {
    if (inputPanel) inputPanel.remove();
    inputPanel = null;
    if (inputArea && inputArea !== area) inputArea.replaceChildren();
  }
  function renderInput(binding, view) {
    clearInput();
    inputArea = document.getElementById("stage2-input-entry") || area;
    if (!inputArea) return;
    const status = inputStatusWords[language] || inputStatusWords.en;
    if (!binding) {
      if (inputArea !== area) {
        const notice = document.createElement("p"); notice.textContent = status[9]; notice.setAttribute("role", "status"); inputArea.append(notice);
      }
      return;
    }
    const w = inputWords[language] || inputWords.en, details = document.createElement("details"), summary = document.createElement("summary");
    inputPanel = details; summary.textContent = w[0]; details.append(summary);
    const content = document.createElement("div"); details.append(content); inputArea.append(details);
    if (inputArea !== area) {
      details.open = true;
      if (view) reviewInput(binding, view, content);
      else { const notice = document.createElement("p"); notice.textContent = status[10]; notice.setAttribute("role", "status"); content.append(notice); }
      return;
    }
    // Legacy entry points retain their explicit read control. The Stage 2 slot
    // above reuses the already validated Atlas read without a second request.
    const read = document.createElement("button"); read.type = "button"; read.textContent = w[0]; content.append(read);
    read.onclick = async () => {
      read.disabled = true;
      try {
        const result = await get(route(binding));
        if (current && equal(current, binding) && content.isConnected) reviewInput(binding, result, content);
      } catch (_) { if (content.isConnected) { show("failed"); read.disabled = false; } }
    };
  }
  function inputFailure(binding) {
    const mount = document.getElementById("stage2-input-entry");
    if (!mount || !current || !equal(current, binding)) return;
    clearInput(); inputArea = mount;
    const notice = document.createElement("p"); notice.id = "stage2-input-notice";
    notice.textContent = (inputStatusWords[language] || inputStatusWords.en)[11];
    notice.setAttribute("role", "status"); inputArea.append(notice);
  }
  function close() {
    ++generation;
    if (session) {
      clearTimeout(session.timer);
      if (session.port) session.port.close();
      session.frame.remove();
    }
    session = null;
    clearInput();
    if (inline) inline.replaceChildren();
    show(current ? "expired" : "empty");
  }
  function route(binding) {
    return "/api/projects/" + binding.project_ref + "/stage1/atlas/" + binding.input_version + "/" + binding.revision + "/" + binding.artifact_ref + "/" + binding.manifest_sha256;
  }
  function artifactMatches(view, binding) {
    return ["project_ref", "input_version", "revision", "artifact_ref", "manifest_sha256"].every(key => view[key] === binding[key]);
  }
  function equal(view, binding) {
    const brief = view.schema === "ProjectStage1AtlasView/1" ? view.stage2_input?.brief_sha256 : view.brief_sha256;
    return artifactMatches(view, binding) && (!binding.brief_sha256 || brief === binding.brief_sha256);
  }
  async function get(path) {
    const response = await fetch(path, {method: "GET", headers: {Authorization: "Bearer " + bootstrap.credential}, cache: "no-store", credentials: "omit", redirect: "error"});
    if (!response.ok) throw new Error("saved-view-refused");
    return response.json();
  }
  function show(key) {
    const notice = document.getElementById("project-atlas-notice");
    if (notice) notice.textContent = t(key);
    if (!inline) return;
    inline.hidden = false;
    let title = document.getElementById("project-atlas-inline-title"), visible = document.getElementById("project-atlas-result-notice");
    if (!title || !visible) {
      title = document.createElement("h3"); title.id = "project-atlas-inline-title";
      visible = document.createElement("p"); visible.id = "project-atlas-result-notice";
      visible.className = "subtle"; visible.setAttribute("role", "status"); inline.append(title, visible);
    }
    title.textContent = t("title"); visible.textContent = t(key);
  }
  const live = active => session === active && active.generation === generation && active.frame.isConnected && current && equal(current, active.binding);
  function layout(active, height) {
    if (!live(active) || !Number.isSafeInteger(height) || height < 240 || height > 12000) return;
    active.frame.style.height = height + "px";
    document.dispatchEvent(new CustomEvent("project-atlas-layout", {detail: {...active.binding, height}}));
  }
  async function fileRequest(active, message) {
    if (!live(active) || !active.view || active.reads >= 4 || !message || !/^[A-Za-z0-9_-]{1,64}$/.test(message.id || "")) return;
    const file = active.view.files.find(row => row.file_ref === message.file_ref && row.sha256 === message.sha256);
    if (!file) return;
    const connection = active.connection; ++active.reads;
    try {
      const result = await get(route(active.binding) + "/files/" + file.file_ref + "/" + file.sha256);
      if (!live(active) || connection !== active.connection) return;
      if (!artifactMatches(result, active.binding) || result.index_sha256 !== active.view.index_sha256 || !result.file || result.file.file_ref !== file.file_ref || result.file.sha256 !== file.sha256) throw new Error("saved-file-binding-differs");
      active.port.postMessage({kind: "file", id: message.id, file: result.file});
    } catch (_) {
      if (live(active) && connection === active.connection && active.port) active.port.postMessage({kind: "file-error", id: message.id});
    } finally { --active.reads; }
  }
  function connect(active) {
    if (!live(active) || !active.ready || !active.view || active.port) return;
    const channel = new MessageChannel(), port = channel.port1, connection = active.connection; active.port = port;
    active.port.onmessage = event => {
      if (!live(active) || active.port !== port || active.connection !== connection || !event.data) return;
      if (event.data.kind === "return") { if (area) area.scrollIntoView({block: "start"}); }
      else if (event.data.kind === "language" && Object.hasOwn(words, event.data.language)) active.language = event.data.language;
      else if (event.data.kind === "file-read") fileRequest(active, event.data);
      else if (event.data.kind === "layout" && equal(event.data, active.binding)) layout(active, event.data.height);
      else if (event.data.kind === "view-error") { close(); show("failed"); inputFailure(active.binding); }
    };
    active.port.start();
    active.frame.contentWindow.postMessage({kind: "project-atlas-bound", view: active.view, binding: active.binding, language: active.language || language, inline: true}, location.origin, [channel.port2]);
    clearTimeout(active.timer); show("help");
  }
  window.addEventListener("message", event => {
    const active = session;
    if (active && live(active) && event.origin === location.origin && event.source === active.frame.contentWindow && event.data && event.data.kind === "project-atlas-ready") {
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
    clearTimeout(active.timer);
    const connection = active.connection;
    active.timer = setTimeout(() => { if (live(active) && connection === active.connection) { close(); show("failed"); inputFailure(active.binding); } }, 45000);
    try {
      const view = await get(route(active.binding));
      if (!live(active) || connection !== active.connection) return;
      if (!equal(view, active.binding) || view.schema !== "ProjectStage1AtlasView/1" || !digest(view.index_sha256) || !view.payload || view.payload.index_sha256 !== view.index_sha256 || !Array.isArray(view.files) || view.files.length > 1024 || !view.files.every(file => digest(file.file_ref) && digest(file.sha256) && /^(wiki\/[a-f0-9]{64}\.md|references\.bib|literature\/(screening|included)\.bib)$/.test(file.path) && ["text/markdown", "application/x-bibtex"].includes(file.mime))) throw new Error("saved-view-binding-differs");
      active.view = view;
      if (document.getElementById("stage2-input-entry")) renderInput(active.binding, view);
      connect(active);
    } catch (_) { if (live(active) && connection === active.connection) { close(); show("failed"); inputFailure(active.binding); } }
  }
  function open() {
    if (!current || !inline) return;
    const binding = {...current}; close();
    const frame = document.createElement("iframe"); frame.id = "project-atlas-frame";
    frame.title = t("title"); frame.setAttribute("referrerpolicy", "no-referrer");
    frame.style.width = "100%"; frame.style.height = "720px"; frame.style.border = "0";
    const active = {frame, binding, generation, connection: 0, reads: 0, ready: false, view: null, port: null}; session = active;
    inline.append(frame); frame.src = "/project-atlas.html";
    show("loading");
    load(active);
  }
  document.addEventListener("project-atlas-state", event => {
    area = document.getElementById("project-atlas-entry");
    inline = document.getElementById("project-atlas-inline");
    if (!area || !inline) { current = null; close(); return; }
    const {project, artifact} = event.detail || {}; language = (event.detail || {}).language || "en";
    const next = project && artifact && artifact.status === "saved-evidence-validated" && /^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref) && /^[A-Za-z0-9_-]{1,128}$/.test(artifact.artifact_ref) && Number.isSafeInteger(project.input_version) && project.input_version >= 1 && Number.isSafeInteger(project.revision) && project.revision >= 0 && digest(project.brief_sha256) && digest(artifact.manifest_sha256)
      ? {project_ref: project.project_ref, input_version: project.input_version, revision: project.revision, brief_sha256: project.brief_sha256, artifact_ref: artifact.artifact_ref, manifest_sha256: artifact.manifest_sha256} : null;
    if (!next || current && !equal(next, current)) close();
    current = next; area.replaceChildren();
    const help = document.createElement("p"); help.id = "project-atlas-notice"; help.className = "subtle"; help.setAttribute("role", "status"); area.append(help);
    show(current ? session && session.port ? "help" : "loading" : artifact ? "failed" : "empty");
    if (!current) { renderInput(null, null); return; }
    if (session) { session.language = language; session.frame.title = t("title"); if (session.port) session.port.postMessage({kind: "language", language}); }
    else open();
    renderInput({...current}, session && session.view);
  });
  document.addEventListener("project-screening-clear", () => { current = null; close(); if (area) { area.replaceChildren(); const notice = document.createElement("p"); notice.id = "project-atlas-notice"; notice.setAttribute("role", "status"); notice.textContent = t("expired"); area.append(notice); } });
  window.addEventListener("pagehide", close);
}());
