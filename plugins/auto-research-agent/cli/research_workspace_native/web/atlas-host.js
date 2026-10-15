/* A local host readiness display. No native session or model turn is started. */
(() => {
  "use strict";
  const bootstrap = window.WORKSPACE_HOST;
  delete window.WORKSPACE_HOST;
  if (!bootstrap || typeof bootstrap !== "object") return;
  const credential = typeof bootstrap.credential === "string" ? bootstrap.credential : "";
  const labels = {
    open: ["Codex & feedback", "Codex 与反馈", "Codex 與回饋"],
    close: ["Close", "关闭", "關閉"],
    refresh: ["Read saved check", "读取检查记录", "讀取檢查紀錄"],
    readFailed: ["Unable to read the saved check. The last result is retained.", "无法读取检查记录，仍保留上次结果。", "無法讀取檢查記錄，仍保留上次結果。"],
    "check-passed": ["Last connection check passed", "最近一次连接检查通过", "最近一次連線檢查通過"],
    "needs-login": ["Sign in needed", "需要登录", "需要登入"],
    "check-failed": ["Check failed", "检查失败", "檢查失敗"],
    "not-checked": ["Not checked", "尚未检查", "尚未檢查"],
    "native-ready": ["Codex session handshake observed", "已观察到 Codex 会话握手", "已觀察到 Codex 工作階段握手"],
    "native-stopped": ["Codex session stopped; saved history retained", "Codex 会话已停止，已保存历史保留", "Codex 工作階段已停止，已儲存歷史保留"],
    nativeBoundary: ["Pinned Codex process and session replies were observed. No saved model reply is visible yet; research is not verified.", "已观察固定 Codex 进程和会话握手；目前尚未看到已保存的模型回复，研究尚未验收。", "已觀察固定 Codex 程序與工作階段握手；目前尚未看到已儲存的模型回覆，研究尚未驗收。"],
    replyObserved: ["Saved Codex reply observed. This conversation does not establish successful research or native authentication.", "已观察到保存的 Codex 回复；本次对话不代表研究成功或原生身份认证已验收。", "已觀察到儲存的 Codex 回覆；本次對話不代表研究成功或原生身分認證已驗收。"],
    partialObserved: ["Partial conversation observed; a completed model reply is not established in this window.", "已观察到部分对话；此窗口尚未证明完整模型回复。", "已觀察到部分對話；此視窗尚未證明完整模型回覆。"],
    fixtureReply: ["Saved fixture reply observed; this does not prove a real model ran.", "已观察到保存的演示回复；这不能证明真实模型运行。", "已觀察到儲存的示範回覆；這不能證明真實模型執行。"],
    transcriptWindow: ["The transcript window is partial.", "当前对话窗口不完整。", "目前對話視窗不完整。"],
    boundary: ["Research session not started. No model turn tested.", "尚未启动研究会话，也未测试模型执行。", "尚未啟動研究工作階段，也未測試模型執行。"],
    unavailable: ["Requested session or feedback service is unavailable.", "请求的会话或反馈服务不可用。", "要求的工作階段或回饋服務目前無法使用。"],
    unconnected: ["Registered session is awaiting connection.", "已注册的会话尚未连接。", "已註冊的工作階段尚未接通。"],
    checked: ["Checked at", "检查时间", "檢查時間"],
    account: ["Account type", "账户类型", "帳戶類型"],
    cli: ["Codex CLI version", "Codex CLI 版本", "Codex CLI 版本"],
    server: ["App-server version", "App-server 版本", "App-server 版本"],
    cases: ["Repository cases", "仓库案例", "儲存庫案例"],
    fixture: ["Synthetic repository fixture", "仓库合成测试案例", "儲存庫合成測試案例"],
    current: ["Current case", "当前案例", "目前案例"],
    view: ["View manifest", "页面清单", "頁面清單"],
    maintenance: ["UI maintenance needs a separate Codex task with tests, PR and preview. This readiness check does not connect that task.", "界面维护需要独立的 Codex 任务、测试、PR 和预览。本次连接检查尚未接通该任务。", "介面維護需要獨立的 Codex 任務、測試、PR 與預覽。本次連線檢查尚未接通該任務。"],
    feedbackTitle: ["Improve this interface", "改进这个界面", "改善這個介面"],
    feedbackLabel: ["Describe the issue or change you want", "描述遇到的问题或希望的改动", "描述遇到的問題或希望的改動"],
    save: ["Save feedback", "保存反馈", "儲存回饋"],
    history: ["Read feedback history", "读取反馈历史", "讀取回饋歷史"],
    historyMore: ["Read next feedback page", "读取下一页反馈", "讀取下一頁回饋"],
    recorded: ["Recorded — not dispatched to Codex", "已记录，尚未派给 Codex", "已記錄，尚未派給 Codex"],
    saving: ["Saving…", "正在保存…", "正在儲存…"],
    unknownSave: ["Response unavailable. Read history to check this key; do not submit again.", "未收到回执。请读取历史核查此记录，请勿重复提交。", "未收到回執。請讀取歷史核查此記錄，請勿重複提交。"],
    feedbackReadFailed: ["Feedback history could not be read. Previous records are retained.", "无法读取反馈历史，仍保留上次记录。", "無法讀取回饋歷史，仍保留上次記錄。"],
    feedbackBound: ["Use 1–4,000 UTF-8 bytes. Your text is saved with this case, source version and stage.", "请输入 1–4,000 个 UTF-8 字节。文字随当前案例、来源版本和阶段保存。", "請輸入 1–4,000 個 UTF-8 位元組。文字會隨目前案例、來源版本與階段儲存。"],
    intentUnavailable: ["The browser cannot save a recovery key. Feedback was not submitted.", "浏览器无法保存恢复记录，反馈尚未提交。", "瀏覽器無法儲存復原紀錄，回饋尚未提交。"],
    stage: ["Stage", "阶段", "階段"],
  };
  const language = document.getElementById("atlas-language");
  const t = key => labels[key][({en: 0, "zh-Hans": 1, "zh-Hant": 2})[language?.value] ?? 0];
  const make = (tag, parent, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    parent?.append(node);
    return node;
  };
  const safeUrl = value => {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value, location.href);
      return ["http:", "https:"].includes(url.protocol) && url.origin === location.origin &&
        !url.username && !url.password ? url.href : null;
    } catch { return null; }
  };
  const open = make("button", document.body, "host-open");
  open.id = "host-open"; open.type = "button";
  open.setAttribute("aria-controls", "host-panel"); open.setAttribute("aria-expanded", "false");
  const panel = make("section", document.body, "host-drawer");
  panel.id = "host-panel"; panel.hidden = true;
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-labelledby", "host-title");
  const header = make("div", panel, "host-header"), title = make("h2", header);
  title.id = "host-title";
  const close = make("button", header, "host-close"); close.type = "button";
  const status = make("p", panel, "host-status"); status.setAttribute("role", "status");
  const boundary = make("p", panel, "host-boundary");
  const capabilityNotice = make("p", panel, "host-boundary");
  const readNotice = make("p", panel, "host-boundary"); readNotice.setAttribute("role", "status");
  const metadata = make("dl", panel, "host-metadata");
  const refresh = make("button", panel, "host-refresh"); refresh.type = "button";
  const casesTitle = make("h3", panel, "host-cases-title"), cases = make("div", panel, "host-cases");
  const maintenance = make("p", panel, "host-maintenance");
  const feedback = make("section", panel, "host-feedback");
  feedback.hidden = bootstrap.maintenance_enabled !== true;
  const feedbackTitle = make("h3", feedback), feedbackLabel = make("label", feedback);
  feedbackLabel.htmlFor = "host-feedback-text";
  const feedbackText = make("textarea", feedback); feedbackText.id = "host-feedback-text";
  feedbackText.rows = 4;
  const feedbackBound = make("p", feedback, "host-boundary");
  const feedbackButtons = make("div", feedback, "host-feedback-buttons");
  const save = make("button", feedbackButtons), history = make("button", feedbackButtons), historyMore = make("button", feedbackButtons);
  save.type = history.type = historyMore.type = "button";
  const feedbackNotice = make("p", feedback, "host-boundary"); feedbackNotice.setAttribute("role", "status");
  const feedbackKey = make("code", feedback, "host-case-sha");
  const feedbackRows = make("div", feedback, "host-feedback-history");
  let feedbackBusy = false, feedbackState = "", feedbackRecords = [], pending = null;
  let historyCursor = 0, historyHasMore = false;
  const caseBinding = bootstrap.cases.find(row => row.ref === bootstrap.current_case);
  const storageKey = "atlas-feedback-intent:" + bootstrap.current_case + ":" + caseBinding?.index_sha256 + ":" + caseBinding?.manifest_sha256;
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const digest = async value => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(value))))].map(b => b.toString(16).padStart(2, "0")).join("");
  const requestHash = (stage, message, key) => digest({binding: {index_sha256: caseBinding.index_sha256, manifest_sha256: caseBinding.manifest_sha256, project_id: caseBinding.project_id}, case_ref: bootstrap.current_case, key, message, stage});
  const validateReceipt = async row => {
    const fields = ["case_ref", "created_at", "feedback_ref", "index_sha256", "key", "manifest_sha256", "message", "project_id", "record_sha256", "replayed", "sequence", "stage", "status"];
    if (!row || typeof row !== "object" || Array.isArray(row) || Object.keys(row).sort().join() !== fields.sort().join() ||
        row.case_ref !== bootstrap.current_case || row.project_id !== caseBinding?.project_id || row.index_sha256 !== caseBinding?.index_sha256 || row.manifest_sha256 !== caseBinding?.manifest_sha256 ||
        row.status !== "recorded-not-dispatched" || !Number.isSafeInteger(row.stage) || row.stage < 1 || row.stage > 6 || !Number.isSafeInteger(row.sequence) || row.sequence < 1 || typeof row.replayed !== "boolean" ||
        typeof row.key !== "string" || !/^[A-Za-z0-9._:-]{1,128}$/.test(row.key) || typeof row.created_at !== "string" || !Number.isFinite(Date.parse(row.created_at)) ||
        typeof row.message !== "string" || !row.message.trim() || new TextEncoder().encode(row.message).length > 4000 || !hash(row.feedback_ref) || !hash(row.record_sha256) ||
        await digest([row.case_ref, row.key]) !== row.feedback_ref || await requestHash(row.stage, row.message, row.key) !== row.record_sha256) throw Error("invalid-feedback-record");
    return row;
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey));
    if (saved && typeof saved.key === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(saved.key) && hash(saved.record_sha256) && Number.isInteger(saved.stage) && saved.stage >= 1 && saved.stage <= 6) {
      pending = saved; feedbackState = "unknownSave";
    }
  } catch { /* Storage is optional; no secret or user text is persisted here. */ }
  let connection = bootstrap.connection || {}, busy = false, readFailed = false, conversation = null;
  const native = window.WORKSPACE_NATIVE_ATLAS;
  const nativeBinding = native?.enabled === true ? Object.fromEntries(
    ["project_ref", "index_sha256", "input_version"].map(key => [key, native[key]])) : null;
  const nativeReady = () => connection.status === "native-ready" && connection.actual_codex_process_observed === true;
  window.NativeHostDisplay = Object.freeze({nativeReady, observeConversation(view, observed) {
    if (!nativeBinding || !view || !observed ||
        !["project_ref", "index_sha256", "input_version"].every(key => view[key] === nativeBinding[key])) return false;
    conversation = {reply: observed.reply === true, partial: observed.partial === true, stopped: Boolean(view.failure)};
    render(); return true; // Presentation only; no new I/O or authority.
  }});
  const render = () => {
    const capability = bootstrap.capability_state;
    capabilityNotice.textContent = capability && Object.values(capability).includes("unavailable") ? t("unavailable") : capability?.native === "registered-unconnected" ? t("unconnected") : "";
    const key = nativeReady() ? conversation?.stopped ? "native-stopped" : "native-ready" :
      ["check-passed", "needs-login", "check-failed", "not-checked"].includes(connection.status) ? connection.status : "not-checked";
    open.textContent = t("open"); title.textContent = t("open"); close.textContent = t("close");
    status.textContent = t(key); status.dataset.status = key;
    const boundaryKey = nativeReady() ? conversation?.reply ? "replyObserved" : conversation?.partial ? "partialObserved" : "nativeBoundary" :
      conversation?.reply ? "fixtureReply" : "boundary";
    boundary.textContent = t(boundaryKey) + (conversation?.reply && conversation.partial ? " " + t("transcriptWindow") : "");
    refresh.textContent = t("refresh");
    readNotice.textContent = readFailed ? t("readFailed") : "";
    refresh.disabled = busy || !credential || location.origin === "null";
    metadata.replaceChildren();
    for (const [field, label] of [["checked_at", "checked"], ["account_type", "account"], ["cli_version", "cli"], ["server_version", "server"]]) {
      if (typeof connection[field] !== "string" || !connection[field]) continue;
      make("dt", metadata, "", t(label));
      make("dd", metadata, "", connection[field]).translate = false;
    }
    casesTitle.textContent = t("cases"); cases.replaceChildren();
    for (const row of Array.isArray(bootstrap.cases) ? bootstrap.cases : []) {
      if (!row || typeof row !== "object") continue;
      const url = safeUrl(row.url); if (!url) continue;
      const card = make("div", cases, "host-case");
      const link = make("a", card, "", typeof row.label === "string" ? row.label : row.ref);
      link.href = url; link.translate = false;
      if (row.ref === bootstrap.current_case) {
        link.setAttribute("aria-current", "page"); make("span", card, "host-case-marker", t("current"));
      }
      if (row.fixture === true) make("p", card, "host-case-kind", t("fixture"));
      if (typeof row.index_sha256 === "string" && /^[a-f0-9]{64}$/.test(row.index_sha256)) {
        make("code", card, "host-case-sha", "SHA-256 " + row.index_sha256).translate = false;
      }
      if (typeof row.manifest_sha256 === "string" && /^[a-f0-9]{64}$/.test(row.manifest_sha256)) {
        make("p", card, "host-case-kind", t("view") + " · " + row.manifest_sha256.slice(0, 16) + "…");
      }
    }
    maintenance.textContent = t("maintenance");
    feedbackTitle.textContent = t("feedbackTitle"); feedbackLabel.textContent = t("feedbackLabel");
    feedbackBound.textContent = t("feedbackBound");
    save.textContent = t("save"); history.textContent = t("history");
    historyMore.textContent = t("historyMore"); historyMore.hidden = !historyHasMore;
    save.disabled = feedbackBusy || !!pending || !credential;
    history.disabled = feedbackBusy || !credential;
    historyMore.disabled = feedbackBusy || !credential;
    feedbackNotice.textContent = feedbackState ? t(feedbackState) : "";
    feedbackKey.textContent = pending ? pending.key : "";
    feedbackRows.replaceChildren();
    for (const row of feedbackRecords) {
      const card = make("article", feedbackRows, "host-case");
      make("p", card, "host-case-kind", t("stage") + " " + row.stage + " · " + t("recorded"));
      make("p", card, "", row.message).translate = false;
      make("code", card, "host-case-sha", row.key).translate = false;
    }
  };
  const hide = () => { panel.hidden = true; open.setAttribute("aria-expanded", "false"); open.focus(); };
  open.addEventListener("click", () => {
    panel.hidden = !panel.hidden; open.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) close.focus();
  });
  close.addEventListener("click", hide);
  panel.addEventListener("keydown", event => { if (event.key === "Escape") hide(); });
  language?.addEventListener("change", render);
  refresh.addEventListener("click", async () => {
    if (busy || !credential) return;
    busy = true; render();
    try {
      const response = await fetch("/api/connection", {method: "GET", credentials: "omit", cache: "no-store", redirect: "error", headers: {Authorization: "Bearer " + credential}});
      if (!response.ok) throw Error("connection-read-failed");
      const value = await response.json();
      if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("invalid-connection-record");
      connection = value;
      readFailed = false;
    } catch { readFailed = true; }
    finally { busy = false; render(); }
  });
  const feedbackUrl = "/api/maintenance/" + encodeURIComponent(bootstrap.current_case);
  const fetchFeedback = async (method, body, suffix = "") => {
    const headers = {Authorization: "Bearer " + credential};
    if (body) headers["Content-Type"] = "application/json";
    const response = await fetch(feedbackUrl + suffix, {method, credentials: "omit", cache: "no-store", redirect: "error", headers, ...(body ? {body: JSON.stringify(body)} : {})});
    if (!response.ok) throw Error("feedback-rejected");
    return response.json();
  };
  const readHistory = async (append = false) => {
    if (feedbackBusy || !credential) return;
    if (append && !historyHasMore) return;
    feedbackBusy = true; render();
    try {
      const cursor = append ? historyCursor : 0;
      const rows = await fetchFeedback("GET", null, "?after_seq=" + cursor + "&limit=100");
      if (!Array.isArray(rows) || rows.length > 100) throw Error("invalid-history");
      const validated = await Promise.all(rows.map(validateReceipt));
      if (new Set(validated.map(row => row.key)).size !== validated.length) throw Error("duplicate-history");
      let nextCursor = cursor;
      for (const row of validated) {
        if (row.sequence <= nextCursor) throw Error("invalid-history-order");
        nextCursor = row.sequence;
      }
      if (pending && !rows.some(row => row.key === pending.key)) {
        const saved = await validateReceipt(await fetchFeedback("GET", null, "/" + encodeURIComponent(pending.key)));
        if (saved.key === pending.key) validated.push(saved);
      }
      const recovered = pending && validated.find(row => row.key === pending.key);
      if (recovered && (recovered.stage !== pending.stage || recovered.record_sha256 !== pending.record_sha256)) throw Error("recovery-binding-differs");
      const merged = new Map((append ? feedbackRecords : []).map(row => [row.key, row]));
      for (const row of validated) {
        const old = merged.get(row.key);
        if (old && (old.sequence !== row.sequence || old.record_sha256 !== row.record_sha256)) throw Error("history-binding-differs");
        merged.set(row.key, row);
      }
      feedbackRecords = [...merged.values()]; historyCursor = nextCursor; historyHasMore = rows.length === 100;
      if (recovered) {
        pending = null; try { sessionStorage.removeItem(storageKey); } catch { /* A later reload recovers again with GET. */ } feedbackState = "recorded";
      } else if (!pending) feedbackState = "";
    } catch { feedbackState = "feedbackReadFailed"; }
    finally { feedbackBusy = false; render(); }
  };
  history.addEventListener("click", () => readHistory());
  historyMore.addEventListener("click", () => readHistory(true));
  save.addEventListener("click", async () => {
    if (feedbackBusy || pending || !credential) return;
    const message = feedbackText.value, size = new TextEncoder().encode(message).length;
    if (!message.trim() || size > 4000 || /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(message)) {
      feedbackState = "feedbackBound"; render(); return;
    }
    const key = "ui-" + crypto.randomUUID();
    const stage = Number(document.documentElement.dataset.atlasStage || "1");
    feedbackBusy = true; feedbackState = "saving"; render();
    try {
      pending = {key, stage, record_sha256: await requestHash(stage, message, key)};
      sessionStorage.setItem(storageKey, JSON.stringify(pending));
    } catch { pending = null; feedbackBusy = false; feedbackState = "intentUnavailable"; render(); return; }
    try {
      const row = await validateReceipt(await fetchFeedback("POST", {key, stage, message}));
      if (row.key !== key || row.stage !== stage || row.record_sha256 !== pending.record_sha256) throw Error("invalid-receipt");
      feedbackRecords = [row, ...feedbackRecords.filter(r => r.key !== key)];
      pending = null; try { sessionStorage.removeItem(storageKey); } catch { /* GET remains the only recovery path. */ }
      feedbackText.value = ""; feedbackState = "recorded";
    } catch { feedbackState = "unknownSave"; }
    finally { feedbackBusy = false; render(); }
  });
  render();
})();
