/* Independent citation grants use the shared project intent/history broker.
 * Rendering performs no requests. Local held state is not durable authority. */
(function () {
  "use strict";
  const words = {
    en: {
      title: "Trace the closest papers", help: "References and citing papers require a separate permission. Each grant allows one exact paper/version, round and backend attempt, within the existing query and project budget. No budget is added.",
      unavailable: "Citation expansion is not connected for this project.", authorize: "Authorize this citation attempt", execute: "Execute this saved citation permission",
      authorization: "Permission proposals", execution: "Saved permissions", history: "Saved citation actions",
      references: "References", "cited-by": "Citing papers", version: "Version", round: "Round", backend: "Backend", seconds: "Reserved seconds", attempts: "Remaining shared attempts",
      confirm: "I authorize this one exact citation attempt using the existing budget.", held: "Submitted locally. Read shared action history before taking another action; refresh never resends.",
      unresolved: "The response is unresolved. Read shared action history; this attempt will not be resent automatically.", empty: "No citation attempt is currently offered.", refusal: "Unavailable reason", invalid: "An invalid offer was omitted; no action is available from it.", bounded: "Additional records remain in the shared history.",
      limits: "An observed attempt does not establish source reading, Stage 1 completion or scientific acceptance."
    },
    "zh-Hans": {
      title: "追踪最接近的论文", help: "参考文献和引用这些论文的研究需要独立许可。每项许可只允许一次精确绑定论文／版本、轮次与后端的尝试，共用已有查询与项目预算，不增加预算。",
      unavailable: "当前项目尚未接通引文追踪。", authorize: "授权这次引文追踪", execute: "执行这项已保存的引文许可",
      authorization: "待确认的许可", execution: "已保存许可", history: "已保存引文操作",
      references: "参考文献", "cited-by": "引用该论文的研究", version: "版本", round: "轮次", backend: "后端", seconds: "预留秒数", attempts: "共用预算剩余尝试次数",
      confirm: "我明确授权这一次精确绑定的引文追踪，使用已有预算。", held: "已在本地提交。请先查看全局操作历史；刷新不会重发。",
      unresolved: "响应结果尚不确定。请查看全局操作历史；不会自动重发这次尝试。", empty: "当前没有可用的引文追踪尝试。", refusal: "不可用原因", invalid: "无效许可已略去，不提供操作。", bounded: "其余记录保留在全局操作历史中。",
      limits: "尝试记录不代表已阅读来源、Stage 1 已完成或科学结论已获认可。"
    },
    "zh-Hant": {
      title: "追蹤最接近的論文", help: "參考文獻及引用這些論文的研究需要獨立許可。每項許可只允許一次精確綁定論文／版本、輪次與後端的嘗試，共用既有查詢及專案預算，不增加預算。",
      unavailable: "目前專案尚未接通引文追蹤。", authorize: "授權這次引文追蹤", execute: "執行這項已儲存的引文許可",
      authorization: "待確認的許可", execution: "已儲存許可", history: "已儲存引文操作",
      references: "參考文獻", "cited-by": "引用該論文的研究", version: "版本", round: "輪次", backend: "後端", seconds: "預留秒數", attempts: "共用預算剩餘嘗試次數",
      confirm: "我明確授權這一次精確綁定的引文追蹤，使用既有預算。", held: "已在本機提交。請先查看全域操作歷史；重新整理不會重發。",
      unresolved: "回應結果尚不確定。請查看全域操作歷史；不會自動重發這次嘗試。", empty: "目前沒有可用的引文追蹤嘗試。", refusal: "不可用原因", invalid: "無效許可已略去，不提供操作。", bounded: "其餘紀錄保留在全域操作歷史中。",
      limits: "嘗試紀錄不代表已閱讀來源、Stage 1 已完成或科學結論已獲認可。"
    }
  };
  const states = new WeakMap(), hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const string = (value, maximum) => typeof value === "string" && value.length > 0 && value.length <= maximum;
  const operations = new Set(["references", "cited-by"]), maximumRows = 256;
  function offerValid(offer) {
    const row = offer && offer.document;
    return offer && string(offer.offer_ref, 256) && hash(offer.offer_sha256) && row
      && string(row.work_id, 256) && string(row.version_id, 256) && string(row.title, 4096)
      && operations.has(row.operation) && row.backend === "semantic-scholar"
      && Number.isSafeInteger(row.round_number) && row.round_number > 0
      && Number.isFinite(row.reserved_seconds) && row.reserved_seconds > 0
      && Number.isSafeInteger(row.remaining_attempts) && row.remaining_attempts >= 0;
  }
  function render(container, options) {
    if (!container || typeof container.replaceChildren !== "function") return false;
    const settings = options || {}, value = settings.value || {}, w = words[settings.language] || words.en;
    const state = states.get(container) || {generation: 0, submitted: new Set()};
    states.set(container, state); const generation = ++state.generation;
    state.blocked = settings.blocked !== false; state.busy = state.busy === true;
    container.replaceChildren();
    const add = (parent, tag, text, className) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = String(text == null ? "Unknown" : text);
      if (className) node.className = className;
      parent.append(node); return node;
    };
    add(container, "h3", w.title); add(container, "p", w.help, "subtle");
    if (value.refusal) add(container, "p", w.refusal + " · " + value.refusal, "subtle");
    for (const row of (Array.isArray(value.unavailable) ? value.unavailable : []).slice(0, maximumRows)) {
      add(container, "p", (row.work_id || "Unknown") + " · " + (w[row.operation] || row.operation || "Unknown") + " · " + w.refusal + " · " + (row.code || "Unknown"), "subtle");
    }
    if (value.connected !== true) add(container, "p", w.unavailable, "subtle");
    const controls = [];
    const disable = () => {
      for (const item of controls) {
        const held = state.submitted.has(item.token);
        item.button.disabled = state.blocked || state.busy || held || value.connected !== true
          || typeof settings.onAction !== "function" || item.offer.document.remaining_attempts === 0
          || Boolean(item.check && !item.check.checked);
        if (item.check) item.check.disabled = state.blocked || state.busy || held || value.connected !== true;
      }
    };
    state.disable = disable;
    let count = 0, invalid = false;
    for (const [field, action, title] of [
      ["authorization_offers", "expansion-authorize", w.authorization],
      ["execution_offers", "expansion-execute", w.execution]
    ]) {
      const offers = Array.isArray(value[field]) ? value[field] : [];
      if (offers.length) add(container, "h4", title);
      for (const original of offers.slice(0, maximumRows)) {
        if (!offerValid(original)) { invalid = true; continue; }
        const offer = JSON.parse(JSON.stringify(original)), row = offer.document;
        const token = action + ":" + offer.offer_ref + ":" + offer.offer_sha256;
        const card = add(container, "div", undefined, "history-row");
        add(card, "strong", row.title);
        add(card, "p", w[row.operation] + " · " + row.work_id + " · " + w.version + " " + row.version_id);
        add(card, "p", w.round + " " + row.round_number + " · " + w.backend + " " + row.backend
          + " · " + w.seconds + " " + row.reserved_seconds + " · " + w.attempts + " " + row.remaining_attempts, "subtle");
        let check = null;
        if (action === "expansion-authorize") {
          const label = add(card, "label", undefined, "check");
          check = add(label, "input"); check.type = "checkbox"; check.checked = false;
          add(label, "span", w.confirm); check.onchange = disable;
        }
        const message = add(card, "p", state.submitted.has(token) ? w.held : "", "subtle");
        message.setAttribute("role", "status");
        const button = add(card, "button", action === "expansion-authorize" ? w.authorize : w.execute);
        button.type = "button"; controls.push({token, button, check, offer}); count++;
        button.onclick = async event => {
          if (event) event.preventDefault();
          if (state.generation !== generation || button.disabled || state.blocked || state.busy
              || state.submitted.has(token) || (check && !check.checked)) return;
          state.submitted.add(token); state.busy = true; disable(); message.textContent = w.held;
          try { await settings.onAction(action, offer); }
          catch (_) { if (state.generation === generation) message.textContent = w.unresolved; }
          finally { state.busy = false; state.disable(); }
        };
      }
      if (offers.length > maximumRows) add(container, "p", w.bounded, "subtle");
    }
    if (!count) add(container, "p", w.empty, "subtle");
    if (invalid) add(container, "p", w.invalid, "subtle");
    const history = Array.isArray(value.history) ? value.history : [];
    if (history.length) add(container, "h4", w.history);
    for (const row of history.slice(0, maximumRows)) {
      if (!row || typeof row !== "object") continue;
      const card = add(container, "div", undefined, "history-row");
      add(card, "p", (row.title || row.work_id || "Unknown") + " · "
        + (w[row.operation] || row.operation || "Unknown") + " · " + (row.status || "Unknown"));
    }
    if (history.length > maximumRows) add(container, "p", w.bounded, "subtle");
    add(container, "p", w.limits, "subtle"); disable(); return true;
  }
  window.ProjectExpansions = Object.freeze({render});
})();
