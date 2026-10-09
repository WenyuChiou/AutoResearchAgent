/* A separate injected session overlay. Research records and source text stay unchanged. */
(() => {
  "use strict";
  const atlas = window.WORKSPACE_NATIVE_ATLAS;
  delete window.WORKSPACE_NATIVE_ATLAS;
  if (atlas && atlas.enabled !== true) return;
  const rows = {
    title: ["Session discussion & history", "会话对话与历史", "工作階段對話與歷史"],
    boundary: ["Injected session overlay · native authentication and live research are not verified. The Wiki above remains an offline reference.", "注入会话覆盖层 · 原生认证和真实研究尚未验收。上方 Wiki 仍为离线参考。", "注入工作階段覆蓋層 · 原生認證與實際研究尚未驗收。上方 Wiki 仍為離線參考。"],
    project: ["Project reference", "项目标识", "專案標識"],
    credential: ["Session credential", "会话凭据", "工作階段憑證"],
    connect: ["Read session", "读取会话", "讀取工作階段"],
    refresh: ["Refresh history", "刷新历史", "重新整理歷史"],
    disconnect: ["Disconnect display", "断开显示", "中斷顯示連線"],
    source: ["Bound source version", "绑定来源版本", "綁定來源版本"],
    send: ["Send answer", "提交回答", "提交回答"],
    decline: ["Decline request", "拒绝请求", "拒絕請求"],
    cancel: ["Cancel request", "取消请求", "取消請求"],
    interrupt: ["Interrupt active turn", "中断当前执行", "中斷目前執行"],
    approval: ["Native approval request", "原生审批请求", "原生核准請求"],
    held: ["Submission recorded locally; only read history now. No automatic resend.", "提交意图已在本地记录；现在只读取历史，不自动重发。", "提交意圖已在本機記錄；現在僅讀取歷史，不自動重送。"],
    history: ["Saved actions", "已保存操作", "已儲存操作"],
    empty: ["No pending questions", "没有待回答问题", "沒有待回答問題"],
    status: ["Observed status (dispatch is separate from resolution and completion)", "观察状态（派发、请求解决和执行完成分别记录）", "觀察狀態（派發、請求解決與執行完成分別記錄）"],
    error: ["Read or submission failed. Refresh history; do not resend.", "读取或提交失败。请刷新历史，不要重发。", "讀取或提交失敗。請重新整理歷史，不要重送。"],
    storage: ["Local intent storage is unavailable; submission is blocked.", "本地意图存储不可用，提交已阻止。", "本機意圖儲存不可用，提交已阻止。"],
    unknown: ["Local intent has no observed server receipt yet", "本地意图尚未观察到服务端回执", "本機意圖尚未觀察到伺服器回執"],
    large: ["Answer exceeds the 32 KiB limit; shorten it before submitting.", "回答超过 32 KiB，请缩短后提交。", "回答超過 32 KiB，請縮短後提交。"],
  };
  const make = (tag, text, parent, source = false) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (source) element.setAttribute("translate", "no");
    parent?.append(element);
    return element;
  };
  const label = (tag, key, parent) => {
    const element = make(tag, "", parent, true);
    element.dataset.nativeLabel = key;
    return element;
  };
  const root = make("section");
  root.id = "native-session-panel";
  root.className = "panel native-panel";
  root.setAttribute("aria-labelledby", "native-session-title");
  const title = label("h2", "title", root);
  title.id = "native-session-title";
  label("p", "boundary", root);
  const connection = make("form", undefined, root);
  connection.className = "native-connect";
  const input = (key, type) => {
    const wrapper = make("label", undefined, connection);
    label("span", key, wrapper);
    const field = make("input", undefined, wrapper);
    field.type = type;
    field.required = true;
    field.maxLength = type === "password" ? 4096 : 128;
    field.autocomplete = "off";
    field.setAttribute("aria-label", key);
    return field;
  };
  const projectInput = input("project", "text"), credentialInput = input("credential", "password");
  const connect = label("button", "connect", connection);
  connect.type = "submit";
  const toolbar = make("div", undefined, root);
  toolbar.className = "discussion-actions";
  const refreshButton = label("button", "refresh", toolbar);
  const disconnect = label("button", "disconnect", toolbar);
  const notice = make("p", "", root, true);
  notice.id = "native-notice";
  notice.setAttribute("role", "status");
  const binding = make("div", undefined, root, true);
  binding.id = "native-binding";
  const questions = make("div", undefined, root);
  questions.id = "native-questions";
  const operations = make("div", undefined, root);
  label("h3", "history", root);
  label("p", "status", root);
  const history = make("div", undefined, root, true);
  history.id = "native-history";
  document.querySelector(".footer-note")?.before(root);
  if (!root.isConnected) document.body.append(root);
  if (atlas) document.getElementById("host-panel")?.prepend(root);
  let credential = "", project = "", view = null, busy = false, generation = 0, readSequence = 0;
  const drafts = new Map(), extensions = []; let noticeKey = null;
  const locale = () => ({en: 0, "zh-Hans": 1, "zh-Hant": 2}[document.documentElement.lang] ?? 0);
  const t = key => rows[key][locale()];
  const showNotice = key => {noticeKey = key; notice.textContent = key ? t(key) : "";};
  const translate = () => {
    root.querySelectorAll("[data-native-label]").forEach(e => e.textContent = t(e.dataset.nativeLabel)); if (noticeKey) notice.textContent = t(noticeKey);
  };
  new MutationObserver(translate).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
  const ledgerName = () => `native-intents:${project}:${view.index_sha256}:${view.input_version}`;
  const ledger = () => {
    const records = JSON.parse(sessionStorage.getItem(ledgerName()) || "[]");
    if (!Array.isArray(records) || records.length > 128 || records.some(r =>
      !r || Object.keys(r).sort().join() !== "key,kind,target" ||
      !/^[a-z0-9-]{36}$/.test(r.key) || !/^[0-9a-f]{64}$/.test(r.target) ||
      !["answer", "interrupt"].includes(r.kind))) throw Error("invalid-local-intents");
    return records;
  };
  const held = target => ledger().some(r => r.target === target) ||
    view.actions.some(a => a.target_ref === target);
  const path = () => `/api/native/projects/${encodeURIComponent(project)}`;
  const sameBinding = (first, second) => Boolean(first && second) &&
    ["project_ref", "index_sha256", "input_version"].every(name => first[name] === second[name]);
  const request = async (method, suffix = "", body) => {
    const response = await fetch(path() + suffix, {
      method, credentials: "omit", cache: "no-store", redirect: "error",
      headers: {Authorization: "Bearer " + credential, ...(body ? {"Content-Type": "application/json"} : {})},
      ...(body ? {body: JSON.stringify(body)} : {}),
    });
    if (!response.ok) {
      const error = Error("session-request-failed");
      try {
        const body = await response.json();
        if (body && typeof body === "object" && Object.hasOwn(body, "receipt")) error.receipt = body.receipt;
      } catch {} // An unreadable rejection body leaves the outcome unknown.
      throw error;
    }
    return response.json();
  };
  const render = () => {
    binding.replaceChildren(); questions.replaceChildren(); operations.replaceChildren(); history.replaceChildren();
    if (!view) {extensions.forEach(e => e.clear()); return;}
    label("strong", "source", binding);
    make("pre", JSON.stringify({project_ref: view.project_ref, index_sha256: view.index_sha256,
      input_version: view.input_version, revision: view.revision, failure: view.failure}, null, 2), binding, true);
    for (const r of view.requests.filter(r => r.status === "pending")) {
      const card = make("form", undefined, questions);
      card.className = "native-request";
      card.dataset.requestRef = r.request_ref;
      make("code", r.request_ref + " · " + r.request_sha256, card, true);
      const locked = busy || Boolean(view.failure) || held(r.request_ref);
      if (r.method === "item/tool/requestUserInput") {
        const fields = [];
        for (const q of r.payload.questions) {
          const wrapper = make("label", undefined, card);
          make("p", q.question, wrapper, true);
          const field = make(q.isSecret ? "input" : "textarea", undefined, wrapper, true);
          if (q.isSecret) field.type = "password";
          field.setAttribute("aria-label", q.question);
          field.required = true; field.disabled = locked; field.maxLength = 8000;
          const id = r.request_ref + ":" + q.id;
          field.value = drafts.get(id) || "";
          field.oninput = () => drafts.set(id, field.value);
          fields.push([q.id, field]);
          for (const option of q.options || []) {
            const button = make("button", option.label, card, true);
            button.type = "button"; button.disabled = locked;
            button.onclick = () => {field.value = option.label; drafts.set(id, field.value);};
          }
        }
        const button = label("button", "send", card);
        button.type = "submit"; button.disabled = locked;
        card.onsubmit = event => {event.preventDefault(); submit("answer", r,
          {answers: Object.fromEntries(fields.map(([id, field]) => [id, {answers: [field.value]}]))});};
      } else if (["item/commandExecution/requestApproval", "item/fileChange/requestApproval"].includes(r.method)) {
        label("h3", "approval", card);
        make("pre", JSON.stringify(r.payload, null, 2), card, true);
        for (const decision of ["decline", "cancel"]) {
          const button = label("button", decision, card);
          button.type = "button"; button.disabled = locked;
          button.onclick = () => submit("answer", r, {decision});
        }
      } else make("p", r.method + " · unsupported", card, true);
      if (held(r.request_ref)) label("p", "held", card);
    }
    if (!questions.childElementCount) label("p", "empty", questions);
    for (const op of view.operations) {
      const button = label("button", "interrupt", operations);
      button.disabled = busy || !op.can_interrupt || Boolean(view.failure) || held(op.action_ref);
      button.onclick = () => submit("interrupt", op);
    }
    for (const action of view.actions) make("pre", JSON.stringify(action, null, 2), history, true);
    for (const pending of ledger()) if (!view.actions.some(a => a.client_key === pending.key)) {
      const card = make("div", undefined, history);
      label("p", "unknown", card); make("code", pending.key + " · " + pending.target, card, true);
    }
    translate();
    extensions.forEach(e => e.refresh(view));
  };
  const refresh = async () => {
    if (!credential || busy) return;
    const current = generation, sequence = ++readSequence;
    let loaded;
    try {loaded = await request("GET");}
    catch (error) {if (current !== generation || sequence !== readSequence) return; throw error;}
    if (current !== generation || sequence !== readSequence || (view && loaded.revision < view.revision)) return;
    if (Object.hasOwn(loaded, "project_id") && (typeof loaded.project_id !== "string" ||
        !loaded.project_id || loaded.project_id.length > 128 ||
        (atlas && window.WORKSPACE_VIEW?.index?.project_id !== undefined &&
          loaded.project_id !== window.WORKSPACE_VIEW.index.project_id))) throw Error("project-binding-changed");
    if (view && Object.hasOwn(view, "project_id") && loaded.project_id !== view.project_id) throw Error("project-binding-changed");
    if (!Number.isSafeInteger(loaded.revision) || loaded.revision < 0 || !Array.isArray(loaded.requests) || !Array.isArray(loaded.actions) || !Array.isArray(loaded.operations) || loaded.project_ref !== project || (atlas && (loaded.index_sha256 !== atlas.index_sha256 || loaded.input_version !== atlas.input_version)) || (view && (loaded.index_sha256 !== view.index_sha256 ||
      loaded.input_version !== view.input_version))) throw Error("binding-changed");
    view = loaded; render(); return loaded;
  };
  const submit = async (kind, target, result) => {
    if (!view || busy || held(target.request_ref || target.action_ref)) return;
    const key = crypto.randomUUID(), records = ledger();
    if (records.length >= 128) {showNotice("storage"); return;}
    const body = {key, revision: view.revision, index_sha256: view.index_sha256, input_version: view.input_version,
      ...(kind === "answer" ? {request_ref: target.request_ref, request_sha256: target.request_sha256, result} :
        {action_ref: target.action_ref, action_sha256: target.action_sha256})};
    const encoded = JSON.stringify(body);
    if (/\\u[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}/.test(encoded) || new TextEncoder().encode(encoded).length > 32768) {
      showNotice("large"); return;
    }
    const intent = {key, kind, target: target.request_ref || target.action_ref};
    try {
      sessionStorage.setItem(ledgerName(), JSON.stringify([...records, intent]));
      if (!ledger().some(r => r.key === key)) throw Error("intent-unobserved");
    } catch {showNotice("storage"); return;}
    busy = true; render(); showNotice("held");
    try {await request("POST", kind === "answer" ? "/answers" : "/interrupts", body);}
    catch {showNotice("error");}
    finally {busy = false; try {await refresh();} catch {showNotice("error");}}
  };
  connection.onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    const candidate = projectInput.value;
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(candidate)) return;
    const current = ++generation; credential = credentialInput.value; project = candidate;
    credentialInput.value = ""; view = null; drafts.clear(); render(); showNotice(null);
    try {await refresh();} catch {if (current === generation) {view = null; render(); showNotice("error");}}
  };
  refreshButton.onclick = async () => {try {await refresh();} catch {showNotice("error");}};
  disconnect.onclick = () => {if (busy) return; generation++; credential = ""; view = null; drafts.clear(); render(); showNotice(null);};
  window.NativePanel = {extend(factory) {
    const extension = factory({root, available: () => Boolean(view) && !view.failure && !busy,
    refresh: async expected => {
      const current = generation;
      if (!sameBinding(view, expected) || busy) throw Error("bound-refresh-blocked");
      const loaded = await refresh();
      if (current !== generation || !loaded || !sameBinding(loaded, expected)) throw Error("stale-display");
      return loaded;
    }, read: async suffix => {
      if (!/^(?:\/scope(?:\/versions\/[0-9a-f]{64})?|\/offer|\/transcript)$/.test(suffix) || !view) throw Error("invalid-scope-read");
      const current = generation, binding = view, value = await request("GET", suffix);
      if (current !== generation || !sameBinding(binding, view)) throw Error("stale-display");
      return value;
    }, write: async (suffix, body) => {
      if (!/^(?:\/scope\/(versions|reviews)|\/messages)$/.test(suffix) || !view || busy) throw Error("scope-write-blocked");
      const current = generation, binding = view;
      let value, failure;
      busy = true;
      try {value = await request("POST", suffix, body);}
      catch (error) {failure = error;}
      finally {
        busy = false;
        try {await refresh();} catch (error) {if (!failure) failure = error;}
      }
      if (current !== generation || !sameBinding(binding, view)) throw Error("stale-display");
      if (failure) throw failure;
      return value;
    }});
    extensions.push(extension);
    if (view) extension.refresh(view);
  }};
  if (atlas) {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(atlas.project_ref || "") ||
        !/^[a-f0-9]{64}$/.test(atlas.index_sha256 || "") ||
        !/^[a-f0-9]{64}$/.test(atlas.input_version || "") ||
        typeof atlas.credential !== "string" || !atlas.credential) {
      root.remove(); return;
    }
    credential = atlas.credential; project = atlas.project_ref;
    connection.hidden = true;
    refresh().catch(() => showNotice("error")); // GET only; no launcher or resend.
  }
  translate();
})();
