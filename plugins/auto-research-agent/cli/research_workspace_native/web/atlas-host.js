/* A local host readiness display. No native session or model turn is started. */
(() => {
  "use strict";
  const bootstrap = window.WORKSPACE_HOST;
  delete window.WORKSPACE_HOST;
  if (!bootstrap || typeof bootstrap !== "object") return;
  const credential = typeof bootstrap.credential === "string" ? bootstrap.credential : "";
  const labels = {
    open: ["Codex connection", "Codex 连接", "Codex 連線"],
    close: ["Close", "关闭", "關閉"],
    refresh: ["Read saved check", "读取检查记录", "讀取檢查紀錄"],
    readFailed: ["Unable to read the saved check. The last result is retained.", "无法读取检查记录，仍保留上次结果。", "無法讀取檢查記錄，仍保留上次結果。"],
    "check-passed": ["Last connection check passed", "最近一次连接检查通过", "最近一次連線檢查通過"],
    "needs-login": ["Sign in needed", "需要登录", "需要登入"],
    "check-failed": ["Check failed", "检查失败", "檢查失敗"],
    "not-checked": ["Not checked", "尚未检查", "尚未檢查"],
    boundary: ["Research session not started. No model turn tested.", "尚未启动研究会话，也未测试模型执行。", "尚未啟動研究工作階段，也未測試模型執行。"],
    checked: ["Checked at", "检查时间", "檢查時間"],
    account: ["Account type", "账户类型", "帳戶類型"],
    cli: ["Codex CLI version", "Codex CLI 版本", "Codex CLI 版本"],
    server: ["App-server version", "App-server 版本", "App-server 版本"],
    cases: ["Repository cases", "仓库案例", "儲存庫案例"],
    fixture: ["Synthetic repository fixture", "仓库合成测试案例", "儲存庫合成測試案例"],
    current: ["Current case", "当前案例", "目前案例"],
    view: ["View manifest", "页面清单", "頁面清單"],
    maintenance: ["UI maintenance needs a separate Codex task with tests, PR and preview. This readiness check does not connect that task.", "界面维护需要独立的 Codex 任务、测试、PR 和预览。本次连接检查尚未接通该任务。", "介面維護需要獨立的 Codex 任務、測試、PR 與預覽。本次連線檢查尚未接通該任務。"],
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
  const readNotice = make("p", panel, "host-boundary"); readNotice.setAttribute("role", "status");
  const metadata = make("dl", panel, "host-metadata");
  const refresh = make("button", panel, "host-refresh"); refresh.type = "button";
  const casesTitle = make("h3", panel, "host-cases-title"), cases = make("div", panel, "host-cases");
  const maintenance = make("p", panel, "host-maintenance");
  let connection = bootstrap.connection || {}, busy = false, readFailed = false;
  const render = () => {
    const key = ["check-passed", "needs-login", "check-failed", "not-checked"].includes(connection.status) ? connection.status : "not-checked";
    open.textContent = t("open"); title.textContent = t("open"); close.textContent = t("close");
    status.textContent = t(key); status.dataset.status = key;
    boundary.textContent = t("boundary"); refresh.textContent = t("refresh");
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
  render();
})();
