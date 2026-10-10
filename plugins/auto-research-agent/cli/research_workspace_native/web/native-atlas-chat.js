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
    unsent: ["Message was rejected before admission. Prepare again to retry explicitly.", "消息在受理前被拒绝。请重新准备后明确重试。", "訊息在受理前遭拒絕。請重新準備後明確重試。"],
    error: ["Message unavailable. Read history; do not submit again while its outcome is unknown.", "消息暂不可用。请读取历史，结果未知时不要重复提交。", "訊息暫不可用。請讀取歷史，結果未知時請勿重複提交。"],
    large: ["Use nonblank text up to {limit} bytes.", "请输入非空文字，最多 {limit} 字节。", "請輸入非空文字，最多 {limit} 位元組。"],
    draft: ["Stage review draft prepared. Review it, then explicitly prepare and send the message.", "阶段审阅草稿已准备。检查文字后，再手动准备并发送消息。", "階段審閱草稿已準備。檢查文字後，再手動準備並傳送訊息。"],
    draftSource: ["The stage draft does not match the connected project and source version.", "阶段草稿与已连接项目或来源版本不一致。", "階段草稿與已連線專案或來源版本不一致。"],
    draftHeld: ["An action is busy or its outcome is unsettled. Read history before preparing another draft.", "有操作正在处理或结果未确认。请先读取历史，再准备另一份草稿。", "有操作正在處理或結果尚未確認。請先讀取歷史，再準備另一份草稿。"],
    draftUnavailable: ["Read an available, source-bound session before preparing a stage draft.", "请先读取可用且已绑定来源的会话，再准备阶段草稿。", "請先讀取可用且已綁定來源的工作階段，再準備階段草稿。"],
    transcript: ["Saved conversation", "已保存的对话", "已儲存的對話"],
    empty: ["No saved model reply yet. A sent message does not prove completion.", "尚无已保存的模型回复；消息已发送不代表执行完成。", "尚無已儲存的模型回覆；訊息已傳送不代表執行完成。"],
    partial: ["Partial transcript window; earlier or oversized content is not shown.", "此处仅显示部分对话；早期或超限内容未展示。", "此處僅顯示部分對話；較早或超限內容未顯示。"],
    user: ["You", "你", "你"], assistant: ["Codex", "Codex", "Codex"],
    tool: ["Tool status", "工具状态", "工具狀態"], system: ["Execution status", "执行状态", "執行狀態"],
  };
  window.NativePanel.extend(({root, available, read, write, refresh: reread}) => {
    const node = (tag, parent, text) => {
      const value = document.createElement(tag);
      if (text !== undefined) value.textContent = text;
      parent?.append(value); return value;
    };
    const panel = node("section", root); panel.className = "native-chat";
    const title = node("h3", panel), status = node("p", panel);
    status.setAttribute("role", "status");
    const form = node("form", panel), text = node("textarea", form);
    text.id = "native-chat-text"; text.rows = 4; text.maxLength = 16384;
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
    const sameReceiptBinding = (first, second) => Boolean(first && second) &&
      ["project_ref", "index_sha256", "input_version"].every(name => first[name] === second[name]);
    const sameBinding = (first, second) => sameReceiptBinding(first, second) && first.project_id === second.project_id;
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
    const ledgerKey = (binding = view) => `native-message-intents:${binding.project_ref}:${binding.index_sha256}:${binding.input_version}`;
    const local = (binding = view) => {
      const rows = JSON.parse(sessionStorage.getItem(ledgerKey(binding)) || "[]");
      if (!Array.isArray(rows) || rows.length > 128 || rows.some(r => !r ||
          Object.keys(r).sort().join() !== "key,offer_sha256,target" ||
          !/^[a-z0-9-]{36}$/.test(r.key) || !hash(r.target) || !hash(r.offer_sha256))) throw Error("invalid-message-intents");
      return rows;
    };
    const uncertain = () => local().some(r => {
      const action = view.actions.find(a => a.client_key === r.key && a.kind === "message" && a.target_ref === r.target);
      return !action || !["refused", "completed", "retired", "failed-known-unsent"].includes(action.status);
    });
    const unsettled = () => {
      const settled = action => action && ["refused", "completed", "retired", "failed-known-unsent"].includes(action.status);
      if (uncertain() || view.actions.some(action => !settled(action))) return true;
      const key = `native-intents:${view.project_ref}:${view.index_sha256}:${view.input_version}`;
      const saved = JSON.parse(sessionStorage.getItem(key) || "[]");
      if (!Array.isArray(saved) || saved.length > 128 || saved.some(record =>
        !exact(record, ["key", "kind", "target"]) || !/^[a-z0-9-]{36}$/.test(record.key) ||
        !["answer", "interrupt"].includes(record.kind) || !hash(record.target))) throw Error("invalid-native-intents");
      return saved.some(record => !settled(view.actions.find(action => action.client_key === record.key &&
        action.kind === record.kind && action.target_ref === record.target)));
    };
    window.addEventListener("atlas-stage-review-draft", event => {
      const draft = event.detail;
      let reason = "invalid";
      if (exact(draft, ["project_id", "index_sha256", "stage", "text", "request_ref"]) &&
          typeof draft.project_id === "string" && draft.project_id.length > 0 && draft.project_id.length <= 128 &&
          hash(draft.index_sha256) && typeof draft.stage === "string" && /^stage[1-6]$/.test(draft.stage) &&
          typeof draft.request_ref === "string" && /^review-[1-9][0-9]*$/.test(draft.request_ref) &&
          validText(draft.text) && draft.text.trim()) {
        if (!view || !view.project_id || !readable() || !available()) reason = "unavailable";
        else if (draft.project_id !== view.project_id || draft.index_sha256 !== view.index_sha256) reason = "binding-mismatch";
        else {
          try {reason = busy || unsettled() ? "held" : "prepared";} catch {reason = "held";}
        }
      }
      if (reason === "prepared") {
        sequence++; offer = null; text.value = draft.text; notice = "draft"; text.focus?.();
      } else notice = ({unavailable: "draftUnavailable", "binding-mismatch": "draftSource", held: "draftHeld"})[reason] || "large";
      controls();
      window.dispatchEvent(new CustomEvent("atlas-stage-review-draft-result", {
        detail: {accepted: reason === "prepared", reason,
          project_id: typeof draft?.project_id === "string" ? draft.project_id : null,
          index_sha256: typeof draft?.index_sha256 === "string" ? draft.index_sha256 : null,
          request_ref: typeof draft?.request_ref === "string" ? draft.request_ref : null,
          stage: typeof draft?.stage === "string" ? draft.stage : null},
      }));
    });
    const controls = () => {
      let held = true;
      try {held = !view || !readable() || uncertain();} catch {notice = "error";}
      prepare.disabled = busy || !view || !available() || held;
      send.disabled = prepare.disabled || !offer || offer.revision !== view.revision;
      text.disabled = busy || !view || !available() || !readable();
      title.textContent = t("title"); heading.textContent = t("transcript");
      text.setAttribute("aria-label", t("title"));
      prepare.textContent = t("prepare"); send.textContent = t("send");
      status.textContent = t(notice).replace("{limit}", String(offer?.max_text_bytes ?? 16384));
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
      const current = ++sequence, binding = view; busy = true; offer = null; controls();
      try {
        if (uncertain()) throw Error("unknown-message");
        const value = await read("/offer");
        if (current !== sequence || !sameBinding(binding, view) ||
            !exact(value, ["offer_ref", "offer_sha256", "revision", "max_text_bytes"]) ||
            !hash(value.offer_ref) || !hash(value.offer_sha256) || !Number.isSafeInteger(value.revision) ||
            value.revision < binding.revision || !Number.isSafeInteger(value.max_text_bytes) ||
            value.max_text_bytes < 1 || value.max_text_bytes > 16384) throw Error("stale-message-offer");
        const loaded = await reread(binding);
        if (current !== sequence || !sameBinding(binding, loaded) || !sameBinding(binding, view) ||
            loaded.revision !== value.revision || view.revision !== value.revision || !available() ||
            !readable() || uncertain()) throw Error("stale-message-offer");
        offer = value; notice = "ready";
      } catch {if (current === sequence) notice = "error";}
      finally {if (current === sequence) {busy = false; controls();}}
    };
    form.onsubmit = async event => {
      event.preventDefault();
      if (!view || !offer || busy || !available() || !readable() || offer.revision !== view.revision) return;
      const binding = view, prepared = offer;
      const body = {key: crypto.randomUUID(), revision: view.revision,
        offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, text: text.value};
      if (!body.text.trim() || !validText(body.text) ||
          new TextEncoder().encode(body.text).length > prepared.max_text_bytes) {notice = "large"; controls(); return;}
      try {
        const rows = local();
        if (uncertain() || rows.length >= 128) throw Error("message-held");
        const record = {key: body.key, target: body.offer_ref, offer_sha256: body.offer_sha256};
        sessionStorage.setItem(ledgerKey(), JSON.stringify([...rows, record]));
        if (!local().some(r => r.key === body.key)) throw Error("message-intent-unobserved");
      } catch {notice = "error"; controls(); return;}
      const current = ++sequence; busy = true; offer = null; notice = "held"; controls();
      try {
        const result = await write("/messages", body);
        if (!exact(result, ["action_ref", "action_sha256", "kind", "client_key", "target_ref", "status", "replayed", "failure"]) ||
            !hash(result.action_ref) || !hash(result.action_sha256) || result.kind !== "message" ||
            result.client_key !== body.key || result.target_ref !== body.offer_ref || typeof result.replayed !== "boolean" ||
            !["dispatch-unobserved", "intent-recorded", "refused", "write-observed", "dispatched", "completed", "retired", "failed-known-unsent", "execution-unknown"].includes(result.status) ||
            (result.failure !== null && typeof result.failure !== "string")) throw Error("unobserved-message-response");
        if (current === sequence && sameBinding(binding, view)) text.value = "";
      }
      catch (error) {
        if (current === sequence && sameBinding(binding, view)) {
          notice = "error";
          const receipt = error?.receipt;
          if (exact(receipt, ["schema_version", "status", "operation", "project_ref", "index_sha256",
            "input_version", "client_key", "offer_ref", "offer_sha256"]) &&
              receipt.schema_version === "NativeKnownUnsent.v1" && receipt.status === "known-unsent" &&
              receipt.operation === "message" && sameReceiptBinding(receipt, binding) &&
              receipt.client_key === body.key && receipt.offer_ref === body.offer_ref &&
              receipt.offer_sha256 === body.offer_sha256) {
            try {
              const matches = row => row.key === body.key && row.target === body.offer_ref && row.offer_sha256 === body.offer_sha256;
              const rows = local(binding);
              if (!rows.some(matches)) throw Error("message-intent-missing");
              sessionStorage.setItem(ledgerKey(binding), JSON.stringify(rows.filter(row => !matches(row))));
              if (local(binding).some(matches)) throw Error("message-intent-still-held");
              notice = "unsent";
            } catch {} // Unverified storage changes cannot release an uncertain intent.
          }
        }
      }
      finally {if (current === sequence) {busy = false; controls();}}
    };
    new MutationObserver(() => {controls(); renderTranscript();}).observe(document.documentElement,
      {attributes: true, attributeFilter: ["lang"]});
    controls(); renderTranscript();
    return {
      refresh(next) {
        if (!sameBinding(view, next)) {
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
