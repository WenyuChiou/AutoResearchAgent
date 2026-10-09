/* Ordinary discussion reuses NativePanel authentication, version binding and history.
   GET is passive. A saved local key is never automatically resubmitted. */
(() => {
  "use strict";
  if (!window.NativePanel) return;
  const labels = {
    title: ["Project discussion", "项目对话", "專案對話"],
    prepare: ["Prepare message", "准备消息", "準備訊息"],
    send: ["Send to this session", "发送到此会话", "傳送至此工作階段"],
    ready: ["Message bound to the current source version", "消息已绑定当前来源版本", "訊息已綁定目前來源版本"],
    idle: ["Prepare a message before sending. Refresh reads saved history only.", "发送前先准备消息；刷新只读取已保存的历史。", "傳送前請先準備訊息；重新整理只讀取已儲存的歷史。"],
    held: ["Submission recorded; read history to check the outcome. No automatic resend.", "提交已记录；请读取历史核查结果，不会自动重发。", "提交已記錄；請讀取歷史核查結果，不會自動重送。"],
    error: ["Message unavailable. Read history; do not submit again while its outcome is unknown.", "消息暂不可用。请读取历史，结果未知时不要重复提交。", "訊息暫不可用。請讀取歷史，結果未知時請勿重複提交。"],
    large: ["Use nonblank text up to 16 KiB. Server limits may be lower.", "请输入非空文字，最多 16 KiB；服务端可能设置更低的限制。", "請輸入非空文字，最多 16 KiB；伺服器可能設定更低的限制。"],
    transcript: ["Saved conversation", "已保存的对话", "已儲存的對話"],
    empty: ["No saved model reply yet. A sent message does not prove completion.", "尚无已保存的模型回复；消息已发送不代表执行完成。", "尚無已儲存的模型回覆；訊息已傳送不代表執行完成。"],
    partial: ["Partial transcript window; earlier or oversized content is not shown.", "此处仅显示部分对话；早期或超限内容未展示。", "此處僅顯示部分對話；較早或超限內容未顯示。"],
    user: ["You", "你", "你"], assistant: ["Codex", "Codex", "Codex"],
    tool: ["Tool status", "工具状态", "工具狀態"], system: ["Execution status", "执行状态", "執行狀態"],
  };
  window.NativePanel.extend(({root, available, read, write}) => {
    const node = (tag, parent, text) => {
      const value = document.createElement(tag);
      if (text !== undefined) value.textContent = text;
      parent?.append(value); return value;
    };
    const panel = node("section", root); panel.className = "native-chat";
    const title = node("h3", panel), status = node("p", panel);
    status.setAttribute("role", "status");
    const form = node("form", panel), text = node("textarea", form);
    text.id = "native-chat-text"; text.rows = 4; text.maxLength = 16000;
    text.setAttribute("translate", "no"); text.required = true;
    const actions = node("div", form); actions.className = "discussion-actions";
    const prepare = node("button", actions), send = node("button", actions);
    prepare.type = "button"; send.type = "submit";
    prepare.id = "native-chat-prepare"; send.id = "native-chat-send";
    const heading = node("h3", panel), transcript = node("div", panel);
    transcript.id = "native-chat-transcript"; transcript.setAttribute("translate", "no");
    let view = null, offer = null, busy = false, sequence = 0, notice = "idle";
    const locale = () => ({en: 0, "zh-Hans": 1, "zh-Hant": 2}[document.documentElement.lang] ?? 0);
    const t = key => labels[key][locale()];
    const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
    const exact = (value, fields) => value !== null && typeof value === "object" &&
      !Array.isArray(value) && Object.keys(value).sort().join() === [...fields].sort().join();
    const validText = value => {
      if (typeof value !== "string") return false;
      for (let n = 0; n < value.length; n++) {
        const unit = value.charCodeAt(n);
        if (unit >= 0xD800 && unit <= 0xDBFF) {
          const next = value.charCodeAt(++n);
          if (!(next >= 0xDC00 && next <= 0xDFFF)) return false;
        } else if (unit >= 0xDC00 && unit <= 0xDFFF) return false;
      }
      return new TextEncoder().encode(value).length <= 16384;
    };
    const validTranscript = saved => {
      if (!exact(saved, ["schema_version", "entries", "window"]) || saved.schema_version !== "1.0.0" ||
          !Array.isArray(saved.entries) || saved.entries.length > 128 ||
          !exact(saved.window, ["event_limit", "entry_limit", "text_byte_limit", "truncated", "omitted_frames"]) ||
          saved.window.event_limit !== 128 || saved.window.entry_limit !== 128 || saved.window.text_byte_limit !== 65536 ||
          typeof saved.window.truncated !== "boolean" || !Number.isSafeInteger(saved.window.omitted_frames) || saved.window.omitted_frames < 0) return false;
      let bytes = 0;
      for (const entry of saved.entries) {
        if (!exact(entry, ["entry_ref", "action_ref", "role", "kind", "status", "text", "failure", "frame_refs"]) ||
            !hash(entry.entry_ref) || !hash(entry.action_ref) ||
            !["user", "assistant", "tool", "system"].includes(entry.role) ||
            !["message-intent", "assistant-delta", "assistant-final", "assistant-conflict", "tool-status", "turn-terminal", "native-error"].includes(entry.kind) ||
            !["dispatch-unobserved", "intent-recorded", "refused", "write-observed", "dispatched", "completed", "retired", "failed-known-unsent", "execution-unknown", "partial", "unknown", "failed", "interrupted"].includes(entry.status) ||
            (entry.text !== null && !validText(entry.text)) ||
            (entry.failure !== null && typeof entry.failure !== "string") ||
            !Array.isArray(entry.frame_refs) || entry.frame_refs.length > 128 || entry.frame_refs.some(ref =>
              !exact(ref, ["frame_sequence", "raw_sha256"]) || !Number.isSafeInteger(ref.frame_sequence) || ref.frame_sequence <= 0 || !hash(ref.raw_sha256))) return false;
        bytes += new TextEncoder().encode(entry.text || "").length;
        if (bytes > 65536) return false;
      }
      return true;
    };
    const readable = () => !view || !Object.hasOwn(view, "transcript") || validTranscript(view.transcript);
    const ledgerKey = () => `native-message-intents:${view.project_ref}:${view.index_sha256}:${view.input_version}`;
    const local = () => {
      const rows = JSON.parse(sessionStorage.getItem(ledgerKey()) || "[]");
      if (!Array.isArray(rows) || rows.length > 128 || rows.some(r => !r ||
          Object.keys(r).sort().join() !== "key,offer_sha256,target" ||
          !/^[a-z0-9-]{36}$/.test(r.key) || !hash(r.target) || !hash(r.offer_sha256))) throw Error("invalid-message-intents");
      return rows;
    };
    const uncertain = () => local().some(r => {
      const action = view.actions.find(a => a.client_key === r.key);
      return !action || !["refused", "completed", "retired", "failed-known-unsent"].includes(action.status);
    });
    const controls = () => {
      let held = true;
      try {held = !view || !readable() || uncertain();} catch {notice = "error";}
      prepare.disabled = busy || !view || !available() || held;
      send.disabled = prepare.disabled || !offer || offer.revision !== view.revision;
      text.disabled = busy || !view || !available() || !readable();
      title.textContent = t("title"); heading.textContent = t("transcript");
      text.setAttribute("aria-label", t("title"));
      prepare.textContent = t("prepare"); send.textContent = t("send"); status.textContent = t(notice);
    };
    const renderTranscript = () => {
      transcript.replaceChildren();
      const saved = view?.transcript;
      if (!view || !Object.hasOwn(view, "transcript")) {node("p", transcript, t("empty")); return;}
      if (!validTranscript(saved)) {
        node("p", transcript, t("error")); return;
      }
      for (const entry of saved.entries) {
        const card = node("article", transcript); card.dataset.role = entry.role;
        node("strong", card, t(entry.role));
        node("p", card, `${entry.kind} · ${entry.status}${entry.failure ? " · " + entry.failure : ""}`);
        if (entry.text) node("div", card, entry.text);
      }
      if (!saved.entries.length) node("p", transcript, t("empty"));
      if (saved.window.truncated) node("p", transcript, t("partial"));
    };
    prepare.onclick = async () => {
      if (!view || busy || !available() || !readable()) return;
      const current = ++sequence; busy = true; offer = null; controls();
      try {
        if (uncertain()) throw Error("unknown-message");
        const value = await read("/offer");
        if (current !== sequence || !view || !hash(value.offer_ref) || !hash(value.offer_sha256) ||
            !Number.isSafeInteger(value.revision) || value.revision !== view.revision) throw Error("stale-message-offer");
        offer = value; notice = "ready";
      } catch {if (current === sequence) notice = "error";}
      finally {if (current === sequence) {busy = false; controls();}}
    };
    form.onsubmit = async event => {
      event.preventDefault();
      if (!view || !offer || busy || !available() || !readable() || offer.revision !== view.revision) return;
      const body = {key: crypto.randomUUID(), revision: view.revision,
        offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, text: text.value};
      const encoded = JSON.stringify(body);
      if (!body.text.trim() || /\\u[dD][89aAbBcCdDeEfF][0-9a-fA-F]{2}/.test(encoded) ||
          new TextEncoder().encode(body.text).length > 16384) {notice = "large"; controls(); return;}
      try {
        const rows = local();
        if (uncertain() || rows.length >= 128) throw Error("message-held");
        const record = {key: body.key, target: body.offer_ref, offer_sha256: body.offer_sha256};
        sessionStorage.setItem(ledgerKey(), JSON.stringify([...rows, record]));
        if (!local().some(r => r.key === body.key)) throw Error("message-intent-unobserved");
      } catch {notice = "error"; controls(); return;}
      busy = true; offer = null; notice = "held"; controls();
      try {await write("/messages", body); text.value = "";}
      catch {notice = "error";}
      finally {busy = false; controls();}
    };
    new MutationObserver(() => {controls(); renderTranscript();}).observe(document.documentElement,
      {attributes: true, attributeFilter: ["lang"]});
    controls(); renderTranscript();
    return {
      refresh(next) {
        if (!view || view.project_ref !== next.project_ref || view.index_sha256 !== next.index_sha256 || view.input_version !== next.input_version) {
          sequence++; busy = false; offer = null; text.value = ""; notice = "idle";
        }
        view = next;
        if (offer && offer.revision !== view.revision) {offer = null; notice = "idle";}
        controls(); renderTranscript();
      },
      clear() {sequence++; view = null; offer = null; busy = false; text.value = ""; notice = "idle"; controls(); renderTranscript();},
    };
  });
})();
