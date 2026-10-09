/* Explicit offline Harness operations. GET never executes; a saved intent is never resubmitted. */
(() => {
  "use strict";
  const config = window.WORKSPACE_HARNESS, host = window.WORKSPACE_HOST;
  delete window.WORKSPACE_HARNESS;
  if (!config || typeof config !== "object") return;
  const credential = typeof host?.credential === "string" ? host.credential : "";
  const actions = ["validate-index", "derive-literature-selection", "export-selection"];
  const files = ["operation.json", ...["selection.json", "selection.csv", "selection.md", "catalog.xlsx", "included.bib", "screening.bib"].map(name => "literature/" + name)];
  const labels = {
    title: ["Harness tools", "Harness 工具", "Harness 工具"],
    boundary: ["Run the Harness's saved-input checks, screening and exports. Research and model execution require their separate connected session and permissions.", "调用 Harness 对已保存交付进行校验、文献筛选和导出。研究与模型执行仍需独立连接的会话及其权限。", "呼叫 Harness 對已儲存交付進行校驗、文獻篩選與匯出。研究與模型執行仍需獨立連線的工作階段及其權限。"],
    disabled: ["Harness operations are not registered on this host.", "当前服务尚未注册 Harness 操作。", "目前服務尚未註冊 Harness 操作。"],
    ready: ["Ready for this source version", "已连接当前来源版本", "已連線目前來源版本"],
    loading: ["Reading saved history…", "正在读取操作历史…", "正在讀取操作歷史…"],
    running: ["Running…", "正在执行…", "正在執行…"],
    succeeded: ["Completed", "已完成", "已完成"],
    failed: ["Failed — previous attempts are retained", "执行失败，原尝试已保留", "執行失敗，原嘗試已保留"],
    "execution-unknown": ["Outcome unknown. Read history; do not submit again.", "结果未知。请读取历史核查，不要重复提交。", "結果未知。請讀取歷史核查，不要重複提交。"],
    unavailable: ["Unable to verify this source-bound response. Previous records are retained.", "无法核验绑定当前来源的回执，仍保留原记录。", "無法核驗綁定目前來源的回執，仍保留原紀錄。"],
    storage: ["Unable to save a recovery key. No action was submitted.", "无法保存恢复记录，尚未提交操作。", "無法儲存復原紀錄，尚未提交操作。"],
    capacity: ["Saved operation limit reached. History and downloads remain available.", "已达到操作记录上限，仍可读取历史和下载文件。", "已達操作紀錄上限，仍可讀取歷史與下載檔案。"],
    refresh: ["Read operation history", "读取操作历史", "讀取操作歷史"],
    history: ["Saved operations & files", "操作记录与文件", "操作紀錄與檔案"],
    source: ["Source snapshot SHA-256", "来源快照 SHA-256", "來源快照 SHA-256"],
    canonical: ["Canonical input SHA-256", "规范化输入 SHA-256", "正規化輸入 SHA-256"],
    screened: ["Screened", "筛查", "篩查"], included: ["Included", "保留", "保留"], excluded: ["Excluded", "排除", "排除"], pending: ["Pending", "待审", "待審"],
    papers: ["papers", "篇文献", "篇文獻"],
    download: ["Download", "下载", "下載"],
    partial: ["Showing the latest 64 operations; older records remain saved.", "显示最近 64 次操作；更早记录仍然保留。", "顯示最近 64 次操作；更早紀錄仍然保留。"],
    "validate-index": ["Validate delivery", "校验交付", "校驗交付"],
    "derive-literature-selection": ["Update literature screening", "更新文献筛选", "更新文獻篩選"],
    "export-selection": ["Export literature", "导出文献", "匯出文獻"],
  };
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const key = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(value);
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const exact = (value, fields) => value !== null && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join() === [...fields].sort().join();
  const noExecution = value => value.research_execution === false && value.model_execution === false && value.scientific_admission === false;
  const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(value => value.toString(16).padStart(2, "0")).join("");
  const requestHash = request => digest(new TextEncoder().encode(JSON.stringify(Object.fromEntries(Object.entries({...request, project_ref: config.project_ref}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)))));
  const validRequest = value => exact(value, ["action", "index_sha256", "expected_revision", "key"]) && actions.includes(value.action) && value.index_sha256 === config.index_sha256 && integer(value.expected_revision) && key(value.key);
  const enabled = config.enabled === true && typeof config.project_ref === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(config.project_ref) && hash(config.index_sha256) && credential && location.origin !== "null";
  const api = "/api/harness/projects/" + encodeURIComponent(config.project_ref);
  const storageKey = "atlas-harness-intent:" + config.project_ref + ":" + config.index_sha256;
  let view = null, pending = null, busy = false, readable = false, state = enabled ? "loading" : "disabled", locale = "";
  try { const saved = JSON.parse(sessionStorage.getItem(storageKey)); if (saved !== null) {if (!validRequest(saved)) throw Error("invalid-saved-intent"); pending = saved; state = "execution-unknown";} }
  catch { pending = false; state = "unavailable"; }
  const t = name => labels[name][({en: 0, "zh-Hans": 1, "zh-Hant": 2})[document.documentElement.lang] ?? 0];
  const make = (tag, parent, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = String(text); if (className) node.className = className; parent?.append(node); return node;};
  const panel = make("section", null, undefined, "atlas-panel harness-panel"); panel.id = "atlas-harness-tools";
  const title = make("h2", panel), boundary = make("p", panel, undefined, "harness-boundary"), buttons = make("div", panel, undefined, "harness-actions");
  const controls = actions.map(action => {const node = make("button", buttons); node.type = "button"; node.dataset.harnessAction = action; node.onclick = () => execute(action); return node;});
  const refresh = make("button", buttons); refresh.type = "button"; refresh.id = "harness-history-refresh";
  const status = make("p", panel, undefined, "harness-status"); status.setAttribute("role", "status");
  const recoveryKey = make("code", panel); recoveryKey.translate = false;
  const history = make("details", panel), historyTitle = make("summary", history), rows = make("div", history, undefined, "harness-history");
  const validateReceipt = async row => {
    const base = ["key", "project_ref", "method", "action", "status", "request", "request_sha256", "index_sha256", "input_canonical_sha256", "contract_version", "output_ref", "artifacts", "intent_revision", "research_execution", "model_execution", "scientific_admission"];
    const terminal = ["completed", "failed"].includes(row?.status), success = row?.status === "completed";
    const fields = terminal ? [...base, "outcome", "completion_revision", success ? "result" : "error"] : base;
    if (!exact(row, fields) || row.project_ref !== config.project_ref || row.index_sha256 !== config.index_sha256 || !hash(row.input_canonical_sha256) ||
        (view && row.input_canonical_sha256 !== view.input_canonical_sha256) || !validRequest(row.request) || row.key !== row.request.key || row.action !== row.request.action ||
        row.method !== "harness-ops/" + row.action || row.contract_version !== "1.0.0" || !/^[a-f0-9]{32}$/.test(row.output_ref) || !noExecution(row) ||
        !["running", "completed", "failed", "execution-unknown"].includes(row.status) || !integer(row.intent_revision) || row.intent_revision !== row.request.expected_revision + 1 ||
        row.request_sha256 !== await requestHash(row.request) || !Array.isArray(row.artifacts) || row.artifacts.length > 7 || new Set(row.artifacts.map(item => item.name)).size !== row.artifacts.length ||
        !row.artifacts.every(item => exact(item, ["name", "sha256", "size"]) && files.includes(item.name) && hash(item.sha256) && integer(item.size) && item.size <= 33554432) ||
        row.artifacts.reduce((total, item) => total + item.size, 0) > 134217728) throw Error("invalid-operation-receipt");
    if (terminal && (!integer(row.completion_revision) || row.completion_revision <= row.intent_revision || row.outcome !== (success ? "succeeded" : "failed"))) throw Error("invalid-terminal");
    if (success) {
      const result = row.result, common = ["input_canonical_sha256", "research_execution", "scientific_admission", "official_stage2_import_eligible"];
      if (!exact(result, [...common, ...(row.action === "validate-index" ? ["validation", "papers"] : ["counts", "rule_version"])]) || result.input_canonical_sha256 !== row.input_canonical_sha256 ||
          result.research_execution !== false || result.scientific_admission !== false || result.official_stage2_import_eligible !== false) throw Error("invalid-operation-result");
      if (row.action === "validate-index" ? result.validation !== "passed" || !integer(result.papers) : !exact(result.counts, ["screened", "included", "excluded", "pending"]) || !Object.values(result.counts).every(integer) || result.counts.included + result.counts.excluded + result.counts.pending !== result.counts.screened || typeof result.rule_version !== "string" || !result.rule_version) throw Error("invalid-operation-counts");
    } else if (terminal && (!exact(row.error, ["code", "type"]) || ![row.error.code, row.error.type].every(value => typeof value === "string" && value.length <= 256))) throw Error("invalid-operation-error");
    return row;
  };
  const validateView = async value => {
    if (!exact(value, ["project_ref", "project_id", "index_sha256", "input_canonical_sha256", "revision", "capabilities", "operation_scope", "research_execution", "model_execution", "scientific_admission", "history", "history_count", "history_limit", "action_limit"]) ||
        value.project_ref !== config.project_ref || value.index_sha256 !== config.index_sha256 || value.project_id !== window.WORKSPACE_VIEW?.index?.project_id || !hash(value.input_canonical_sha256) ||
        (view && (value.input_canonical_sha256 !== view.input_canonical_sha256 || value.revision < view.revision)) || !integer(value.revision) || !noExecution(value) || value.operation_scope !== "offline-saved-input" ||
        !Array.isArray(value.capabilities) || value.capabilities.join() !== actions.join() || value.history_limit !== 64 || value.action_limit !== 128 || !integer(value.history_count) || value.history_count > 128 ||
        !Array.isArray(value.history) || value.history.length !== Math.min(64, value.history_count) || new Set(value.history.map(row => row.key)).size !== value.history.length) throw Error("invalid-harness-view");
    let previous = 0;
    for (const row of value.history) {await validateReceipt(row); if (row.input_canonical_sha256 !== value.input_canonical_sha256 || row.intent_revision <= previous || (row.completion_revision ?? row.intent_revision) > value.revision) throw Error("invalid-history-order"); previous = row.intent_revision;}
    return value;
  };
  const request = async (suffix = "", body) => {
    const headers = {Authorization: "Bearer " + credential}; if (body) headers["Content-Type"] = "application/json";
    const response = await fetch(api + suffix, {method: body ? "POST" : "GET", credentials: "omit", cache: "no-store", redirect: "error", headers, ...(body ? {body: JSON.stringify(body)} : {})});
    if (!response.ok) throw Error("harness-response-unavailable"); return response.json();
  };
  const controlsBusy = () => busy || !enabled || !readable || pending !== null || !view || view.history_count >= view.action_limit || view.history.some(row => ["running", "execution-unknown"].includes(row.status));
  const render = () => {
    locale = document.documentElement.lang; title.textContent = t("title"); boundary.textContent = t("boundary");
    controls.forEach((node, i) => {node.textContent = t(actions[i]); node.disabled = controlsBusy();});
    refresh.textContent = t("refresh"); refresh.disabled = busy || !enabled; status.textContent = t(state); status.dataset.state = state;
    recoveryKey.textContent = pending ? pending.key : ""; recoveryKey.hidden = !pending;
    historyTitle.textContent = t("history"); rows.replaceChildren();
    if (view) {make("code", rows, t("source") + " · " + view.index_sha256).translate = false; make("code", rows, t("canonical") + " · " + view.input_canonical_sha256).translate = false;}
    for (const row of view?.history || []) {
      const card = make("article", rows, undefined, "harness-record"); make("strong", card, t(row.action));
      make("p", card, t(row.status === "completed" ? "succeeded" : row.status));
      if (row.status === "completed") make("p", card, row.action === "validate-index" ? row.result.papers + " " + t("papers") : ["screened", "included", "excluded", "pending"].map(name => t(name) + " " + row.result.counts[name]).join(" · "));
      make("code", card, row.key + " · SHA-256 " + row.request_sha256).translate = false;
      for (const item of row.artifacts) {const button = make("button", card, t("download") + " · " + item.name); button.type = "button"; button.dataset.artifact = item.name; button.disabled = busy; button.onclick = () => download(row, item); make("code", card, item.sha256).translate = false;}
    }
    if ((view?.history_count || 0) > 64) make("p", rows, t("partial"));
  };
  const recover = async () => {
    if (!enabled || busy) return; busy = true; state = pending ? "execution-unknown" : "loading"; render();
    try {
      const loaded = await validateView(await request());
      if (pending) {
        const receipt = await validateReceipt(loaded.history.find(row => row.key === pending.key) || await request("/actions/" + encodeURIComponent(pending.key)));
        if (Object.keys(pending).some(name => receipt.request[name] !== pending[name]) || receipt.input_canonical_sha256 !== loaded.input_canonical_sha256 || (receipt.completion_revision ?? receipt.intent_revision) > loaded.revision) throw Error("recovery-binding-differs");
        state = receipt.status === "completed" ? "succeeded" : receipt.status;
        if (["completed", "failed"].includes(receipt.status)) {sessionStorage.removeItem(storageKey); pending = null;}
      } else state = pending === false ? "unavailable" : loaded.history.some(row => row.status === "execution-unknown") ? "execution-unknown" : loaded.history.some(row => row.status === "running") ? "running" : loaded.history_count >= loaded.action_limit ? "capacity" : "ready";
      view = loaded; readable = pending !== false;
    } catch {readable = false; state = pending ? "execution-unknown" : "unavailable";}
    finally {busy = false; render();}
  };
  const execute = async action => {
    if (controlsBusy() || !actions.includes(action)) return;
    let intent;
    try {intent = {action, index_sha256: config.index_sha256, expected_revision: view.revision, key: crypto.randomUUID()}; sessionStorage.setItem(storageKey, JSON.stringify(intent));} catch {state = "storage"; render(); return;}
    pending = intent; busy = true; state = "running"; history.open = true; render();
    try {const receipt = await validateReceipt(await request("/actions", intent)); if (Object.keys(intent).some(name => receipt.request[name] !== intent[name])) throw Error("action-binding-differs");}
    catch {state = "execution-unknown";}
    finally {busy = false; await recover();}
  };
  const download = async (row, item) => {
    if (busy || !enabled || !["completed", "failed"].includes(row.status)) return; busy = true; render();
    try {
      const response = await fetch(api + "/artifacts/" + encodeURIComponent(row.key) + "/" + item.name.split("/").map(encodeURIComponent).join("/") + "?sha256=" + item.sha256, {credentials: "omit", cache: "no-store", redirect: "error", headers: {Authorization: "Bearer " + credential}});
      if (!response.ok) throw Error("download-unavailable"); const bytes = await response.arrayBuffer();
      if (bytes.byteLength !== item.size || await digest(bytes) !== item.sha256) throw Error("download-bytes-differ");
      const url = URL.createObjectURL(new Blob([bytes])), link = make("a", null); link.href = url; link.download = item.name.split("/").pop(); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {state = "unavailable";} finally {busy = false; render();}
  };
  refresh.onclick = recover;
  const mount = () => {const review = document.getElementById("atlas-stage-review"); if (review?.parentNode && panel.nextSibling !== review) review.parentNode.insertBefore(panel, review); if (locale !== document.documentElement.lang) render();};
  new MutationObserver(mount).observe(document.getElementById("atlas-content") || document.body, {childList: true, subtree: true});
  new MutationObserver(mount).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
  window.addEventListener("languagechange", render); mount(); render(); if (enabled) recover();
})();
