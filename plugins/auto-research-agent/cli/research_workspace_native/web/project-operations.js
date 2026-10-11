/* Additive controls only. Atlas selection, graph and source records stay intact. */
(function () {
  "use strict";
  if (document.body.classList.contains("project-embedded")) {
    document.addEventListener("click", event => {
      const link = event.target.closest?.("a[href]");
      if (!link || !link.closest(".studio-nav")) return;
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin || url.search || url.hash
          || !(url.pathname === "/" || /^\/views\/[A-Za-z0-9_-]{1,64}\/atlas\.html$/.test(url.pathname))) return;
      // Saved views cannot be framed; user navigation leaves the operation
      // frame. This does not change the project's bound saved-data popup.
      event.preventDefault(); window.top.location.assign(url.href);
    });
    return;
  }
  const language = document.getElementById("atlas-language");
  const words = {
    en: {open: "Codex & Harness", drawer: "Research operations", close: "Close operations", hint: "The selected operation project is separate from the saved Atlas below. Opening this panel does not run research.", title: "Project & research topic", step: "BEFORE STAGE 1", help: "Choose an existing project or prepare a new topic. Create and confirm its scope in the same operation panel; the saved Atlas remains a historical result.", choice: "Existing research project", choose: "Choose a project explicitly", topic: "New research topic or area", select: "Open selected project", create: "New project from this topic", confirm: "Review and confirm scope", next: "Continue current project", refresh: "Refresh project list", none: "No operation project selected", current: "Current operation project", version: "Input version", loading: "Reading saved projects…", ready: "Project selection and topic preparation do not submit or run research.", invalid: "Enter a research topic using valid Unicode within 4096 UTF-8 bytes.", unavailable: "Project navigation is unavailable. Refresh the project list or inspect the operation panel.", prepared: "Topic prepared. Complete the research needs and create the project in the panel."},
    "zh-Hans": {open: "Codex 与 Harness", drawer: "研究操作", close: "关闭操作面板", hint: "所选操作项目与下方已保存图谱独立。打开面板不会执行研究。", title: "项目与研究题目", step: "STAGE 1 之前", help: "选择已有项目，或准备一个新题目。在同一个操作面板中创建项目并确认范围；下方已保存图谱仍是历史结果。", choice: "已有研究项目", choose: "请明确选择项目", topic: "新研究题目或方向", select: "打开所选项目", create: "用此题目新建项目", confirm: "审阅并确认研究范围", next: "继续当前项目", refresh: "刷新项目列表", none: "尚未选择当前操作项目", current: "当前操作项目", version: "输入版本", loading: "正在读取已保存项目…", ready: "选择项目与准备题目不会提交或执行研究。", invalid: "请使用完整 Unicode 填写研究题目，不超过 4096 个 UTF-8 字节。", unavailable: "项目导航暂不可用。请刷新项目列表，或查看操作面板。", prepared: "题目已预填。请在面板中补全研究需要，再创建项目。"},
    "zh-Hant": {open: "Codex 與 Harness", drawer: "研究操作", close: "關閉操作面板", hint: "所選操作專案與下方已保存圖譜獨立。開啟面板不會執行研究。", title: "專案與研究題目", step: "STAGE 1 之前", help: "選擇既有專案，或準備一個新題目。在同一個操作面板中建立專案並確認範圍；下方已保存圖譜仍是歷史結果。", choice: "既有研究專案", choose: "請明確選擇專案", topic: "新研究題目或方向", select: "開啟所選專案", create: "以此題目建立專案", confirm: "審閱並確認研究範圍", next: "繼續目前專案", refresh: "重新整理專案清單", none: "尚未選擇目前操作專案", current: "目前操作專案", version: "輸入版本", loading: "正在讀取已保存專案…", ready: "選擇專案與準備題目不會提交或執行研究。", invalid: "請使用完整 Unicode 填寫研究題目，不超過 4096 個 UTF-8 位元組。", unavailable: "專案導覽暫不可用。請重新整理專案清單，或查看操作面板。", prepared: "題目已預填。請在面板中補全研究需要，再建立專案。"}
  };
  const w = () => words[language?.value] || words.en;
  function node(tag, id, parent) {
    const result = document.createElement(tag); if (id) result.id = id; if (parent) parent.append(result); return result;
  }
  const button = document.createElement("button"), dialog = document.createElement("dialog");
  button.type = "button"; button.id = "project-operations-open";
  button.setAttribute("aria-haspopup", "dialog"); button.setAttribute("aria-controls", "project-operations-dialog");
  dialog.id = "project-operations-dialog"; dialog.setAttribute("aria-labelledby", "project-operations-title");
  const header = document.createElement("header"), title = document.createElement("h2"), close = document.createElement("button"), hint = document.createElement("p");
  title.id = "project-operations-title"; close.type = "button"; close.id = "project-operations-close";
  header.append(title, close); dialog.append(header, hint); document.body.append(dialog);
  const controls = document.querySelector(".atlas-topbar-controls");
  if (!controls) { dialog.remove(); return; }
  controls.prepend(button);

  // Both anchors are outside the renderer's replaceChildren containers.
  const content = document.getElementById("atlas-content"), stages = document.getElementById("atlas-stages");
  if (!content) { dialog.remove(); button.remove(); return; }
  const card = node("section", "project-intake-card"); card.setAttribute("aria-labelledby", "project-intake-title"); content.before(card);
  const step = node("p", "project-intake-step", card), heading = node("h2", "project-intake-title", card), help = node("p", "project-intake-help", card);
  const summary = node("p", "project-intake-summary", card); summary.setAttribute("aria-live", "polite");
  const grid = node("div", "project-intake-fields", card);
  const choiceLabel = node("label", null, grid), choiceText = node("span", null, choiceLabel), choice = node("select", "project-intake-choice", choiceLabel);
  const topicLabel = node("label", null, grid), topicText = node("span", null, topicLabel), topic = node("textarea", "project-intake-topic", topicLabel); topic.rows = 2; topic.maxLength = 4096;
  const actions = node("div", "project-intake-actions", card);
  const select = node("button", "project-intake-select", actions), create = node("button", "project-intake-new", actions), confirm = node("button", "project-intake-confirm", actions), next = node("button", "project-intake-continue", actions), refresh = node("button", "project-intake-refresh", actions);
  for (const action of [select, create, confirm, next, refresh]) action.type = "button";
  const status = node("p", "project-intake-status", card); status.setAttribute("role", "status");
  const nav = stages ? node("button", "project-intake-nav") : null;
  if (nav) { nav.type = "button"; nav.onclick = () => { card.scrollIntoView({block: "start"}); choice.focus(); }; stages.before(nav); }
  let frame = null, frameLoaded = false, portal = null, readyPromise = null, projects = [], selection = null, busy = false, listBusy = false, listGeneration = 0, topicRef = null, statusKey = "loading";
  const ref = value => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
  function validTopic(value) {
    if (!value.trim() || new TextEncoder().encode(value).length > 4096) return false;
    for (let i = 0; i < value.length; i++) {
      const code = value.charCodeAt(i);
      if (code >= 0xD800 && code <= 0xDBFF) { const next = value.charCodeAt(++i); if (!(next >= 0xDC00 && next <= 0xDFFF)) return false; }
      else if (code >= 0xDC00 && code <= 0xDFFF) return false;
    }
    return true;
  }
  function buttons() {
    choice.disabled = topic.disabled = busy || !portal;
    select.disabled = busy || !portal || !projects.some(row => row.project_ref === choice.value);
    create.disabled = busy || !portal || !topic.value.trim();
    confirm.disabled = next.disabled = busy || !portal || !selection;
    refresh.disabled = busy;
  }
  function showSummary() {
    summary.textContent = selection ? w().current + ": " + selection.topic + " · " + w().version + " " + selection.input_version : w().none;
    status.textContent = w()[statusKey]; buttons();
  }
  function renderChoices() {
    const chosen = choice.value; choice.replaceChildren();
    const placeholder = node("option", null, choice); placeholder.value = ""; placeholder.textContent = w().choose;
    for (const project of projects) { const option = node("option", null, choice); option.value = project.project_ref; option.textContent = project.topic + " · v" + project.input_version; }
    choice.value = projects.some(row => row.project_ref === chosen) ? chosen : "";
  }
  function syncSelection() {
    try {
      const value = portal.selection();
      if (value !== null && (!value || !ref(value.project_ref) || typeof value.topic !== "string"
          || !Number.isInteger(value.input_version) || value.input_version < 1 || !Number.isInteger(value.revision)
          || value.revision < 0 || typeof value.brief_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.brief_sha256))) throw Error("invalid-project-selection");
      selection = value;
      if (selection) {
        choice.value = selection.project_ref;
        if (topicRef !== selection.project_ref) { topic.value = selection.topic; topicRef = selection.project_ref; }
        if (!listBusy && !projects.some(row => row.project_ref === selection.project_ref)) {
          refreshProjects().catch(() => { statusKey = "unavailable"; showSummary(); });
        }
      }
      showSummary();
    } catch (_) { selection = null; statusKey = "unavailable"; showSummary(); }
  }
  async function refreshProjects() {
    const generation = ++listGeneration; listBusy = true;
    try {
      const result = await portal.listProjects();
      if (generation !== listGeneration) return;
      if (!Array.isArray(result) || result.length > 128 || result.some(row => !row || !ref(row.project_ref)
          || typeof row.topic !== "string" || new TextEncoder().encode(row.topic).length > 4096
          || !Number.isInteger(row.input_version) || row.input_version < 1)
          || new Set(result.map(row => row.project_ref)).size !== result.length) throw Error("invalid-project-list");
      projects = result; renderChoices(); statusKey = "ready"; syncSelection();
    } finally { if (generation === listGeneration) listBusy = false; }
  }
  function translate() {
    const copy = w();
    [button.textContent, title.textContent, close.textContent, hint.textContent] = [copy.open, copy.drawer, copy.close, copy.hint];
    [step.textContent, heading.textContent, help.textContent, choiceText.textContent, topicText.textContent] = [copy.step, copy.title, copy.help, copy.choice, copy.topic];
    for (const [element, key] of [[select, "select"], [create, "create"], [confirm, "confirm"], [next, "next"], [refresh, "refresh"]]) element.textContent = copy[key];
    if (nav) nav.textContent = copy.title;
    renderChoices(); showSummary(); if (frame) frame.title = copy.drawer;
    // Only the existing same-origin selector is changed. No credential, source
    // binding, action key or message is copied across this presentation seam.
    const frameLanguage = frame?.contentDocument?.getElementById("language");
    if (frameLanguage && language && frameLanguage.value !== language.value) {
      frameLanguage.value = language.value; frameLanguage.dispatchEvent(new Event("change"));
    }
  }
  function ensurePortal() {
    if (portal) return Promise.resolve(portal);
    if (readyPromise) return readyPromise;
    if (!frame) {
      frame = document.createElement("iframe"); frame.id = "project-operations-frame";
      frame.src = "/projects-panel.html"; frame.onload = () => { frameLoaded = true; translate(); }; dialog.append(frame);
    }
    readyPromise = new Promise((resolve, reject) => {
      let attempts = 0;
      function ready() {
        const api = frameLoaded ? frame.contentWindow?.ResearchProjectPortal : null;
        if (api && ["listProjects", "selection", "selectProject", "beginTopic"].every(name => typeof api[name] === "function")) resolve(api);
        else if (++attempts >= 200) reject(Error("project-portal-unavailable"));
        else setTimeout(ready, 50);
      }
      ready();
    }).then(async api => {
      portal = api; frame.contentWindow.addEventListener("research-project-selection", syncSelection);
      translate(); await refreshProjects(); return api;
    }).catch(error => { portal = null; readyPromise = null; statusKey = "unavailable"; showSummary(); throw error; });
    return readyPromise;
  }
  function openDrawer() {
    translate(); dialog.showModal(); close.focus();
  }
  async function openProject(projectRef, scope) {
    if (busy || !ref(projectRef)) return;
    busy = true; statusKey = "loading"; showSummary(); openDrawer();
    try {
      const api = await ensurePortal();
      if (await api.selectProject(projectRef) !== true) throw Error("project-navigation-held");
      syncSelection(); if (selection?.project_ref !== projectRef) throw Error("project-navigation-differs");
      statusKey = "ready";
      if (scope) { const intake = frame.contentDocument.getElementById("intake-card"); if (intake) { intake.open = true; intake.scrollIntoView({block: "start"}); } }
    } catch (_) { statusKey = "unavailable"; }
    finally { busy = false; showSummary(); }
  }
  select.onclick = () => { if (projects.some(row => row.project_ref === choice.value)) return openProject(choice.value, false); };
  confirm.onclick = () => selection && openProject(selection.project_ref, true);
  next.onclick = () => selection && openProject(selection.project_ref, false);
  create.onclick = async () => {
    if (busy) return;
    if (!validTopic(topic.value)) { statusKey = "invalid"; showSummary(); return; }
    busy = true; buttons(); openDrawer();
    try {
      const api = await ensurePortal();
      if (api.beginTopic(topic.value) !== true) throw Error("project-topic-held");
      selection = null; topicRef = null; choice.value = ""; statusKey = "prepared";
      frame.contentDocument.getElementById("needs")?.focus();
    } catch (_) { statusKey = "unavailable"; }
    finally { busy = false; showSummary(); }
  };
  refresh.onclick = async () => {
    if (busy) return; busy = true; statusKey = "loading"; showSummary();
    try { if (portal) await refreshProjects(); else await ensurePortal(); }
    catch (_) { statusKey = "unavailable"; }
    finally { busy = false; showSummary(); }
  };
  button.onclick = () => { openDrawer(); ensurePortal().catch(() => {}); };
  choice.onchange = topic.oninput = buttons;
  close.onclick = () => dialog.close();
  dialog.addEventListener("close", () => button.focus());
  language?.addEventListener("change", translate);
  translate();
  // Initialisation reads only. The one broker keeps all credentials, permits
  // and action identities; no saved-case identity is adopted as a project.
  ensurePortal().catch(() => {});
}());
