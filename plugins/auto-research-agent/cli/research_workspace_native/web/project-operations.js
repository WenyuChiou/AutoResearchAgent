/* One project workspace. Navigation reads saved state; action ownership stays in the broker. */
(function () {
  "use strict";
  if (document.body.classList.contains("project-embedded")) {
    document.addEventListener("click", event => {
      const link = event.target.closest?.("a[href]");
      if (!link || !link.closest(".studio-nav")) return;
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin || url.search || url.hash
          || !(url.pathname === "/" || /^\/views\/[A-Za-z0-9_-]{1,64}\/atlas\.html$/.test(url.pathname))) return;
      // Explicit historical navigation retains the same top-level window.
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
  Object.assign(words.en, {help: "Use the Harness operations above, then read this project's delivered results below.", current: "Current project", none: "Choose or create a project to begin", history: "Historical reference · new deliveries appear in the current stage above", planned: "Stage3–6 are planned and unconnected. No research starts from navigation."});
  Object.assign(words["zh-Hans"], {help: "在上方操作 Harness，交付后直接在下方查看当前项目的结果。", current: "当前项目", none: "选择或创建项目后开始", history: "历史参考 · 新交付显示在上方当前阶段结果区", planned: "Stage3–6 尚在规划，未接通。切换页面不会启动研究。"});
  Object.assign(words["zh-Hant"], {help: "在上方操作 Harness，交付後直接在下方檢視目前專案的結果。", current: "目前專案", none: "選擇或建立專案後開始", history: "歷史參考 · 新交付顯示於上方目前階段結果區", planned: "Stage3–6 尚在規劃，未接通。切換頁面不會啟動研究。"});
  const w = () => words[language?.value] || words.en;
  function node(tag, id, parent) {
    const result = document.createElement(tag); if (id) result.id = id; if (parent) parent.append(result); return result;
  }
  const button = document.createElement("button"), workspace = document.createElement("section");
  button.type = "button"; button.id = "project-operations-open";
  button.setAttribute("aria-controls", "project-operations-workspace");
  workspace.id = "project-operations-workspace";
  workspace.setAttribute("aria-label", "Project workspace");
  const controls = document.querySelector(".atlas-topbar-controls");
  if (!controls) return;
  controls.prepend(button);

  // Both anchors are outside the renderer's replaceChildren containers.
  const content = document.getElementById("atlas-content"), stages = document.getElementById("atlas-stages");
  if (!content) { button.remove(); return; }
  const card = node("section", "project-intake-card"); card.setAttribute("aria-labelledby", "project-intake-title"); content.before(card);
  card.after(workspace);
  const historical = node("details", "project-historical-view");
  const historicalLabel = node("summary", null, historical);
  workspace.after(historical); historical.append(content); content.hidden = true;
  historical.addEventListener("toggle", () => {
    content.hidden = !historical.open;
    if (!historical.open) translate();
  });
  document.body.classList.add("project-unified");
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
  stages?.addEventListener("click", event => {
    if (historical.open) return;
    const control = event.target.closest?.("[data-atlas-focus]");
    const target = control?.dataset.atlasFocus;
    if (!/^stage:[1-6]$/.test(target || "")) return;
    event.preventDefault(); event.stopImmediatePropagation();
    showStage(Number(target.slice(6)));
  }, true);
  document.querySelector(".atlas-workspace-nav")?.addEventListener("click", event => {
    if (historical.open) return;
    const link = event.target.closest?.("a[id]");
    const target = {"atlas-view-workbench": "stage1-progress", "atlas-view-files": "project-atlas-inline", "atlas-view-history": "history", "atlas-view-settings": "intake-card"}[link?.id];
    if (!target) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (target === "stage1-progress" || target === "project-atlas-inline" || target === "history") {
      showStage(1).then(() => openWorkspace(target));
    } else openWorkspace(target);
  }, true);
  let frame = null, frameLoaded = false, portal = null, readyPromise = null, projects = [], selection = null, busy = false, listBusy = false, listGeneration = 0, topicRef = null, statusKey = "loading", resizeObserver = null, resizeQueued = false, displayedBinding = null, activeStage = 1;
  function stageNavigation() {
    for (const control of stages?.querySelectorAll("[data-atlas-focus]") || []) control.setAttribute("aria-pressed", String(control.dataset.atlasFocus === "stage:" + activeStage));
  }
  async function showStage(stage) {
    if (!Number.isInteger(stage) || stage < 1 || stage > 6) return;
    try {
      const api = await ensurePortal();
      if (api.showStage(stage) !== true) return;
      activeStage = stage; historical.open = false; content.hidden = true;
      stageNavigation(); openWorkspace("project-stage-" + stage);
    } catch (_) { statusKey = "unavailable"; showSummary(); }
  }
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
  function fitPortal() {
    if (!frameLoaded || resizeQueued) return;
    resizeQueued = true;
    requestAnimationFrame(() => {
      resizeQueued = false;
      const body = frame.contentDocument?.body;
      if (!body) return;
      const height = Math.ceil(body.getBoundingClientRect().height);
      if (Number.isFinite(height) && height >= 0) frame.style.height = Math.min(30000, Math.max(260, height + 8)) + "px";
    });
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
      const binding = selection ? selection.project_ref + "/" + selection.input_version + "/" + selection.revision : null;
      if (binding !== displayedBinding) { historical.open = false; content.hidden = true; displayedBinding = binding; }
      const projectTitle = document.getElementById("atlas-project");
      if (projectTitle) projectTitle.textContent = selection?.topic || w().title;
      if (selection) {
        choice.value = selection.project_ref;
        if (topicRef !== selection.project_ref) { topic.value = selection.topic; topicRef = selection.project_ref; }
        if (!listBusy && !projects.some(row => row.project_ref === selection.project_ref)) {
          refreshProjects().catch(() => { statusKey = "unavailable"; showSummary(); });
        }
      }
      showSummary(); fitPortal();
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
    button.textContent = copy.open; historicalLabel.textContent = copy.history;
    workspace.setAttribute("aria-label", copy.drawer);
    const projectTitle = document.getElementById("atlas-project");
    if (projectTitle) projectTitle.textContent = selection?.topic || copy.title;
    [step.textContent, heading.textContent, help.textContent, choiceText.textContent, topicText.textContent] = [copy.step, copy.title, copy.help, copy.choice, copy.topic];
    for (const [element, key] of [[select, "select"], [create, "create"], [confirm, "confirm"], [next, "next"], [refresh, "refresh"]]) element.textContent = copy[key];
    if (nav) nav.textContent = copy.title;
    renderChoices(); showSummary(); stageNavigation(); if (frame) frame.title = copy.drawer;
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
      frame.src = "/projects-panel.html";
      frame.onload = () => {
        frameLoaded = true; translate(); resizeObserver?.disconnect();
        if (typeof ResizeObserver === "function") {
          resizeObserver = new ResizeObserver(fitPortal); resizeObserver.observe(frame.contentDocument.body);
        }
        frame.contentDocument.addEventListener("project-atlas-layout", fitPortal);
        frame.contentDocument.addEventListener("research-project-navigate", event => {
          if (typeof event.detail?.target === "string" && /^[a-z0-9-]{1,64}$/.test(event.detail.target)) openWorkspace(event.detail.target);
        });
        fitPortal();
      };
      workspace.append(frame);
    }
    readyPromise = new Promise((resolve, reject) => {
      let attempts = 0;
      function ready() {
        const api = frameLoaded ? frame.contentWindow?.ResearchProjectPortal : null;
        if (api && ["listProjects", "selection", "selectProject", "beginTopic", "showStage", "activeStage"].every(name => typeof api[name] === "function")) resolve(api);
        else if (++attempts >= 200) reject(Error("project-portal-unavailable"));
        else setTimeout(ready, 50);
      }
      ready();
    }).then(async api => {
      portal = api; frame.contentWindow.addEventListener("research-project-selection", syncSelection);
      frame.contentWindow.addEventListener("research-project-stage", () => {
        const stage = api.activeStage();
        if (Number.isInteger(stage) && stage >= 1 && stage <= 6) { activeStage = stage; stageNavigation(); fitPortal(); }
      });
      translate(); await refreshProjects(); return api;
    }).catch(error => { portal = null; readyPromise = null; statusKey = "unavailable"; showSummary(); throw error; });
    return readyPromise;
  }
  function openWorkspace(target = "project-stage-" + activeStage) {
    translate();
    const requestedSelection = selection, requestedStage = activeStage, requestedFrame = frame;
    const section = frame?.contentDocument?.getElementById(target);
    for (let parent = section; parent; parent = parent.parentElement) if (parent.tagName === "DETAILS") parent.open = true;
    fitPortal();
    // Scroll the owning page, so opening a step never creates an inner scroll trap.
    requestAnimationFrame(() => {
      if (selection !== requestedSelection || activeStage !== requestedStage || frame !== requestedFrame) return;
      if (section?.isConnected && !section.closest("[hidden]")) window.scrollTo({top: window.scrollY + frame.getBoundingClientRect().top + section.getBoundingClientRect().top - 20, behavior: "smooth"});
      else workspace.scrollIntoView({block: "start", behavior: "smooth"});
    });
  }
  async function openProject(projectRef, scope) {
    if (busy || !ref(projectRef)) return;
    busy = true; statusKey = "loading"; showSummary();
    try {
      const api = await ensurePortal();
      if (await api.selectProject(projectRef) !== true) throw Error("project-navigation-held");
      syncSelection(); if (selection?.project_ref !== projectRef) throw Error("project-navigation-differs");
      statusKey = "ready";
      if (scope) openWorkspace("intake-card");
    } catch (_) { statusKey = "unavailable"; }
    finally { busy = false; showSummary(); }
  }
  select.onclick = () => { if (projects.some(row => row.project_ref === choice.value)) return openProject(choice.value, false); };
  confirm.onclick = () => selection && openProject(selection.project_ref, true);
  next.onclick = () => selection && openWorkspace();
  create.onclick = async () => {
    if (busy) return;
    if (!validTopic(topic.value)) { statusKey = "invalid"; showSummary(); return; }
    busy = true; buttons();
    try {
      const api = await ensurePortal();
      if (api.beginTopic(topic.value) !== true) throw Error("project-topic-held");
      selection = null; topicRef = null; choice.value = ""; statusKey = "prepared";
      openWorkspace("create-card");
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
  button.onclick = () => { openWorkspace(); ensurePortal().catch(() => {}); };
  choice.onchange = () => { buttons(); if (projects.some(row => row.project_ref === choice.value)) openProject(choice.value, false); };
  topic.oninput = buttons;
  language?.addEventListener("change", translate);
  translate();
  // Initialisation reads only. The one broker keeps all credentials, permits
  // and action identities; no saved-case identity is adopted as a project.
  ensurePortal().catch(() => {});
}());
