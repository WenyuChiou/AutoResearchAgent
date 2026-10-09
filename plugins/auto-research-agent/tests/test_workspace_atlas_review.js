"use strict";
/* Synthetic DOM behavior only: no browser, server, research execution or private payload. */
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const atlas = path.resolve(__dirname, "../references/research-workspace/atlas");
const ui = fs.readFileSync(process.argv[2] || path.join(atlas, "atlas-ui.js"), "utf8");
const model = require(path.join(atlas, "atlas-model.js")), associations = require(path.join(atlas, "atlas-associations.js"));
const flatten = node => node.children.flatMap(child => [child, ...flatten(child)]);
class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.className = ""; this._text = "";
    this.classList = {add: name => { this.className += " " + name; }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(" "); }
  set innerHTML(value) { throw new Error(`Unsafe HTML insertion: ${value}`); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ""; this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  change(value) { this.value = value; this.onchange?.({target: this}); }
  click() { this.onclick?.({target: this, preventDefault() {}}); }
  querySelector(selector) {
    return flatten(this).find(node => selector === "span" ? node.tagName === "span" : selector === "details" ? node.tagName === "details" : selector === 'option[value="relevance"]' ? node.tagName === "option" && node.value === "relevance" : false);
  }
  scrollIntoView(options) { this.lastScrollIntoView = options; }
  focus() {}
}
let checks = 0;
const equal = (actual, expected, note) => { checks++; assert.deepEqual(actual, expected, note); };
const contains = (actual, expected, note) => { checks++; assert(actual.includes(expected), `${note}: ${expected}`); };
const freeze = value => { Object.values(value).forEach(child => { if (child && typeof child === "object") freeze(child); }); return Object.freeze(value); };
const text = {
  en: {review: "Review this stage with Codex", choices: ["Keep improving", "Request the next stage", "Hold this stage"], preview: "Preview Stage 2", missing: "These are unavailable, not zero or rejection.", separate: "A historical inclusion does not complete source review.", admission: "Current source selection", reason: "Recorded reason", path: "Saved discovery path", observed: "Recorded time", acquired: "Source acquisition time", attempts: "Saved source acquisition attempts", hash: "Original receipt file hash", state: "Access / identity", disconnected: "No matching Codex session accepted this draft.", prepared: "Draft placed in the connected conversation.", formal: "Formally included distinct works", unknown: "Unknown"},
  "zh-Hans": {review: "与 Codex 审阅本阶段", choices: ["继续补充", "申请进入下一阶段", "暂缓推进"], preview: "预览 Stage 2", missing: "这些信息缺失，不表示零次或被排除。", separate: "原来纳入不代表来源审查已完成。", admission: "当前来源纳入状态", reason: "已记录理由", path: "已保存发现路径", observed: "记录时间", acquired: "来源取得时间", attempts: "已保存来源取得尝试", hash: "原始回执文件哈希", state: "存取状态／身份核对", disconnected: "没有匹配的 Codex 会话接收草稿。", prepared: "草稿已放入已连接的对话", formal: "正式纳入的不同作品", unknown: "未知"},
  "zh-Hant": {review: "與 Codex 審閱本階段", choices: ["繼續補充", "申請進入下一階段", "暫緩推進"], preview: "預覽 Stage 2", missing: "這些資訊缺漏，不表示零次或被排除。", separate: "原先納入不代表來源審查已完成。", admission: "目前來源納入狀態", reason: "已記錄理由", path: "已儲存發現路徑", observed: "紀錄時間", acquired: "來源取得時間", attempts: "已儲存來源取得嘗試", hash: "原始回執檔案雜湊", state: "存取狀態／身分核對", disconnected: "沒有相符的 Codex 工作階段接收草稿。", prepared: "草稿已放入已連線的對話", formal: "正式納入的不同作品", unknown: "未知"}
};
function fixture(missing = false) {
  const payload = {index_sha256: "1".repeat(64), index: {project_id: "synthetic-review", topic: "Recorded topic <script>inert()</script>", status: "retained", papers: [], screening: [], sources: [], search: [], stages: [], claims: [], edges: []}, literature_selection: {rows: []}};
  for (let i = 1; i <= 15; i++) {
    const work_id = i === 15 ? "work-1" : `work-${i}`, version_id = i === 15 ? "v2" : "v1", source_id = `source-${i}`;
    payload.index.papers.push({work_id, version_id, title: `Recorded title ${i}`, year: 2000 + i, authors: ["Recorded author"], source_ids: [source_id], evidence_level: "full-text", url: `https://example.invalid/paper/${i}`, classification: {topic_cluster: ["Recorded direction"], method: ["Original shared method"]}, findings: {question: "Recorded question", method: "Original method claim", main_findings: `Saved observation ${i}`, relevance: "Recorded relevance"}});
    payload.index.screening.push({work_id, version_id, decision_id: `decision-${i}`, status: i < 15 ? "include" : "pending", reason: `Original rationale ${i}`, observed_at: `2020-02-${String(i).padStart(2, "0")}T03:04:05Z`, discovery_path: `original/screening-${i}.md`, query: `original/query-${i}.md`});
    payload.literature_selection.rows.push({work_id, version_id, status: "pending", reasons: [`Source review unresolved ${i}`]});
    payload.index.sources.push({work_id, version_id, source_id, result_sha256: String(i % 10).repeat(64), receipt: {retrieved_at: `2021-03-${String(i).padStart(2, "0")}T06:07:08Z`, status: i === 15 ? "metadata-only" : "available", identity_status: "verified", evidence_level: i === 15 ? "metadata" : "full-text"}, attempts: [{status: "network-error"}, {status: "available"}]});
  }
  // Wrong identities intentionally precede valid records; no work-only join is permitted.
  payload.index.screening.unshift({work_id: "work-1", version_id: "v9", decision_id: "POISON", status: "exclude", reason: "WRONG VERSION REASON", discovery_path: "wrong-version.md"});
  payload.literature_selection.rows.unshift({work_id: "work-1", version_id: "v9", status: "included", reasons: ["WRONG ADMISSION"]});
  payload.index.sources.unshift({work_id: "another-work", version_id: "v1", source_id: "source-1", result_sha256: "f".repeat(64), receipt: {retrieved_at: "WRONG RECEIPT DATE", status: "identity-mismatch"}, attempts: [{}, {}, {}]});
  if (missing) {
    payload.index.screening = payload.index.screening.filter(row => row.work_id !== "work-2");
    payload.index.screening.push({work_id: "work-2", version_id: "v9", reason: "WRONG VERSION HISTORY"});
    const source = payload.index.sources.find(row => row.source_id === "source-2");
    delete source.attempts; delete source.receipt.retrieved_at;
  }
  return freeze(payload);
}
function mount(language, acknowledge = false, eventSupport = true, missing = false) {
  const payload = fixture(missing), before = JSON.stringify(payload), body = new Element("body"), ids = {};
  for (const id of ["atlas-content", "atlas-stages", "atlas-language-label", "atlas-language", "atlas-original", "atlas-project", "atlas-status", "atlas-footer", "native-session-panel", "host-panel", "host-open"]) {
    const node = new Element(id === "atlas-language" ? "select" : "div"); node.id = id; ids[id] = node; body.append(node);
  }
  ids["atlas-language"].value = language;
  const drawerOpens = []; ids["host-panel"].hidden = true;
  ids["host-open"].onclick = () => { drawerOpens.push(true); ids["host-panel"].hidden = false; };
  const document = {body, documentElement: {lang: "en", dataset: {}}, getElementById: id => ids[id] || flatten(body).find(node => node.id === id), createElement: tag => new Element(tag), createElementNS: (namespace, tag) => { const node = new Element(tag); node.namespaceURI = namespace; return node; }, querySelectorAll: () => []};
  const events = [], listeners = {}, execution = [];
  const forbidden = name => () => { execution.push(name); throw new Error(`Unauthorized execution: ${name}`); };
  const window = {WORKSPACE_VIEW: payload, AtlasModel: model, AtlasAssociations: associations, innerWidth: 1200, scrollY: 0, scrollTo() {}, fetch: forbidden("fetch"), nativeExecute: forbidden("nativeExecute")};
  if (eventSupport) {
    window.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail; } };
    window.addEventListener = (name, handler) => { (listeners[name] ||= []).push(handler); };
    window.dispatchEvent = event => {
      if (event.type === "atlas-stage-review-draft") {
        events.push(JSON.parse(JSON.stringify(event.detail)));
        const respond = detail => window.dispatchEvent(new window.CustomEvent("atlas-stage-review-draft-result", {detail}));
        if (typeof acknowledge === "function") acknowledge(event.detail, respond);
        else if (acknowledge) respond({...event.detail, accepted: true});
      }
      for (const handler of listeners[event.type] || []) handler(event);
      return true;
    };
  }
  vm.runInContext(ui, vm.createContext({window, document, URL, fetch: forbidden("fetch"), XMLHttpRequest: forbidden("XMLHttpRequest")}));
  const get = id => document.getElementById(id), nodes = parent => flatten(parent || ids["atlas-content"]);
  const review = () => get("atlas-stage-review"), button = (parent, caption) => nodes(parent).find(node => node.tagName === "button" && node.textContent === caption);
  const field = (parent, label) => {
    for (const container of [parent, ...nodes(parent)]) {
      const at = container.children.findIndex(node => node.tagName === "dt" && node.textContent === label);
      if (at >= 0) return container.children[at + 1]?.textContent;
    }
  };
  const unchanged = () => { equal(JSON.stringify(payload), before, "all original source, method, selection and stage records remain byte-equivalent"); equal(execution, [], "review and preview perform no research or native execution"); };
  return {payload, ids, get, nodes, review, button, field, events, drawerOpens, unchanged};
}
function reviewCase(language, connected) {
  const app = mount(language, connected), words = text[language];
  const content = app.ids["atlas-content"];
  equal(app.review().children[0].textContent, words.review, "review heading follows the chosen language");
  const summary = app.get("atlas-direction-summary"), workflow = app.nodes().find(node => node.className.includes("atlas-workflow"));
  equal(content.children.indexOf(summary) < content.children.indexOf(app.review()), true, "Stage 1 review follows the direction summary");
  equal(content.children.indexOf(app.review()) < content.children.indexOf(workflow), true, "Stage 1 review precedes its workflow");
  const choices = ["reviewRevise", "reviewNext", "reviewHold"];
  choices.forEach((choice, i) => {
    app.nodes(app.review()).find(node => node.dataset.reviewChoice === choice).click();
    equal(app.get("atlas-review-draft"), undefined, "changing intention invalidates the previously prepared draft");
    equal(app.nodes(app.review()).filter(node => node.dataset.reviewChoice).map(node => node.attributes["aria-pressed"]), choices.map(value => value === choice ? "true" : "false"), "each review choice is a single selected intention");
    const note = app.get("atlas-review-note"); note.value = `User note ${i} <img onerror=execute()>`; note.oninput();
    app.get("atlas-review-prepare").click();
    const draft = app.get("atlas-review-draft"), detail = app.events.at(-1);
    equal(detail, {project_id: app.payload.index.project_id, index_sha256: app.payload.index_sha256, stage: "stage1", request_ref: `review-${i + 1}`, text: draft.value}, "draft event binds the exact project, source snapshot and distinct request, without an execution command");
    contains(draft.value, words.choices[i], "chosen intention appears in the prepared draft");
    contains(draft.value, note.value, "supplementary user text remains inert and is retained exactly");
    contains(draft.value, app.payload.index.topic, "draft retains the recorded source topic");
    equal(draft.readOnly, true, "the prepared draft is separately visible for copying");
    contains(app.review().textContent, words[connected ? "prepared" : "disconnected"], "connection result does not silently discard the draft");
    equal(app.ids["native-session-panel"].lastScrollIntoView?.block, connected ? "start" : undefined, "only acknowledged drafts focus the conversation panel");
    equal(app.drawerOpens.length, connected ? 1 : 0, "only a matched accepted draft opens the hidden conversation drawer");
    app.unchanged();
  });
  const previousDraft = app.get("atlas-review-draft").value, previousNote = app.get("atlas-review-note").value, count = app.events.length;
  app.button(app.review(), words.preview).click();
  equal(app.get("atlas-review-draft"), undefined, "Stage 2 keeps a separate review draft");
  equal(app.review().children[0].textContent, words.review, "Stage 2 preview has the same translated review component");
  const stage2Workflow = app.nodes().find(node => node.className.includes("atlas-workflow"));
  equal(content.children.indexOf(app.review()) < content.children.indexOf(stage2Workflow), true, "Stage 2 review precedes its workflow");
  equal(app.events.length, count, "preview does not prepare, submit or execute a stage request");
  const stage2Note = app.get("atlas-review-note"); stage2Note.value = "Separate Stage 2 note"; stage2Note.oninput(); app.get("atlas-review-prepare").click();
  equal(app.events.at(-1).stage, "stage2", "Stage 2 draft carries its own stage binding");
  const stage2Draft = app.get("atlas-review-draft").value;
  app.ids["atlas-stages"].children[0].click();
  equal([app.get("atlas-review-note").value, app.get("atlas-review-draft").value], [previousNote, previousDraft], "return from preview restores the Stage 1 draft and supplementary text");
  app.ids["atlas-language"].change(language === "en" ? "zh-Hans" : "en");
  equal(app.get("atlas-review-draft").value, previousDraft, "language redraw preserves the original prepared draft");
  app.ids["atlas-stages"].children[1].click();
  equal([app.get("atlas-review-note").value, app.get("atlas-review-draft").value], ["Separate Stage 2 note", stage2Draft], "Stage 2 draft is preserved independently across stage and language redraws");
  app.unchanged();
}
function provenanceCase(language) {
  const app = mount(language), words = text[language], seen = {include: 0, pending: 0};
  const records = app.payload.index.papers;
  records.forEach((paper, i) => {
    const canonical = JSON.stringify([paper.work_id, paper.version_id]);
    const node = app.nodes(app.get("atlas-network")).find(row => row.dataset.nodeKey === "paper:" + canonical);
    node.click();
    const ledger = app.nodes(app.get("atlas-process")).find(row => row.className === "atlas-process-ledger");
    const trail = app.nodes(ledger).find(row => row.className === "atlas-screening-trail");
    const saved = app.nodes(trail).filter(row => row.className === "atlas-screening-record");
    equal(saved.length, 1, "a displayed trail contains only this exact work/version decision");
    const status = i < 14 ? "include" : "pending"; seen[status]++;
    contains(saved[0].children[0].textContent, `decision-${i + 1} · ${status}`, "historical decision remains separate from source admission");
    equal([app.field(saved[0], words.reason), app.field(saved[0], words.path), app.field(saved[0], words.observed)], [`Original rationale ${i + 1}`, `original/screening-${i + 1}.md`, `2020-02-${String(i + 1).padStart(2, "0")}T03:04:05Z`], "saved reason, path and observed time are shown without invention");
    equal(app.field(ledger, words.admission), "pending", "historical include does not promote formal source selection");
    contains(trail.textContent, words.separate, "screening and source-review distinction remains explained");
    contains(ledger.textContent, words.missing, "missing discovery metrics are explained as unavailable rather than zero");
    equal(ledger.textContent.includes("WRONG VERSION REASON"), false, "another version cannot contribute its rationale");
    const detail = app.get("atlas-paper-detail"), access = app.nodes(detail).find(row => row.className === "atlas-access");
    const receipts = app.nodes(access).filter(row => row.className === "atlas-source-receipt");
    equal(receipts.length, 1, "only the exact paper-version source receipt is displayed");
    const receipt = receipts[0];
    equal(app.field(receipt, words.acquired), `2021-03-${String(i + 1).padStart(2, "0")}T06:07:08Z`, "source acquisition time is not screening observation time");
    contains(app.field(receipt, words.state), i === 14 ? "metadata-only" : "available", "access state remains the recorded source state");
    contains(app.field(receipt, words.state), "verified", "source identity state is displayed separately from admission");
    equal(app.field(receipt, words.hash), String((i + 1) % 10).repeat(64), "receipt hash binds the saved original receipt file");
    equal(app.field(receipt, words.attempts), "2", "recorded acquisition attempts are explicitly counted independently of absent search receipts");
    equal(access.textContent.includes("WRONG RECEIPT DATE"), false, "source ID collision from another identity cannot supply metadata");
  });
  equal(seen, {include: 14, pending: 1}, "all 15 historical rows retain their recorded 14 include / 1 pending counts");
  const formal = app.nodes().find(row => row.className.includes("atlas-collection-status"));
  contains(formal.children[0].textContent, `${words.formal}: 0`, "all formal source selections remain pending even with historical inclusions");
  contains(formal.textContent, words.unknown, "the unbound formal target remains unknown");
  app.unchanged();
}
for (const language of Object.keys(text)) { reviewCase(language, false); reviewCase(language, true); provenanceCase(language); }
for (const change of [detail => ({...detail, project_id: "wrong-project"}), detail => ({...detail, index_sha256: "f".repeat(64)}), detail => ({...detail, request_ref: "review-0"}), detail => ({...detail, request_ref: undefined})]) {
  const app = mount("en", (detail, respond) => respond({...change(detail), accepted: true}));
  app.get("atlas-review-prepare").click();
  contains(app.review().textContent, text.en.disconnected, "wrong-project, wrong-snapshot, stale or missing-request acknowledgment cannot show connected");
  equal(app.drawerOpens, [], "unbound acknowledgment cannot open the conversation drawer");
  equal(app.ids["native-session-panel"].lastScrollIntoView, undefined, "unbound acknowledgment cannot focus a conversation");
  app.unchanged();
}
let previousRequest;
const stale = mount("en", (detail, respond) => { if (previousRequest) respond({...previousRequest, accepted: true}); previousRequest = JSON.parse(JSON.stringify(detail)); });
stale.get("atlas-review-prepare").click(); stale.get("atlas-review-prepare").click();
equal(stale.events.map(event => event.request_ref), ["review-1", "review-2"], "repeated preparation produces distinct request references");
contains(stale.review().textContent, text.en.disconnected, "a real prior draft acknowledgment cannot accept the newer draft");
equal(stale.drawerOpens, [], "a delayed prior acknowledgment leaves the conversation closed");
stale.unchanged();
for (const language of Object.keys(text)) {
  const app = mount(language, false, true, true), words = text[language];
  app.nodes(app.get("atlas-network")).find(node => node.dataset.nodeKey === 'paper:["work-2","v1"]').click();
  const trail = app.nodes(app.get("atlas-process")).find(node => node.className === "atlas-screening-trail");
  equal(app.nodes(trail).filter(node => node.className === "atlas-screening-record").length, 0, "wrong-version rows cannot suppress the missing-history state");
  contains(trail.textContent, {en: "No saved screening decision is bound to this work/version.", "zh-Hans": "此论文版本没有绑定的筛选决定记录。", "zh-Hant": "此論文版本沒有綁定的篩選決定紀錄。"}[language], "the exact version's absent history is explained");
  const receipt = app.nodes(app.get("atlas-paper-detail")).find(node => node.className === "atlas-source-receipt");
  equal([app.field(receipt, words.acquired), app.field(receipt, words.attempts)], [words.unknown, words.unknown], "unrecorded acquisition time and attempt count stay unknown, never zero");
  app.get("atlas-review-prepare").click();
  const note = app.get("atlas-review-note"); note.value = "Supplement changes the intended request"; note.oninput();
  app.ids["atlas-language"].change(language);
  equal(app.get("atlas-review-draft"), undefined, "edited supplementary text invalidates the stale prepared draft on redraw");
  equal(app.get("atlas-review-note").value, note.value, "invalidating a draft preserves the user's supplementary text");
  equal(app.events.length, 1, "typing and language redraw do not dispatch another draft request");
  app.unchanged();
}
const noEvents = mount("en", false, false);
noEvents.get("atlas-review-note").value = "Keep this disconnected draft"; noEvents.get("atlas-review-note").oninput(); noEvents.get("atlas-review-prepare").click();
contains(noEvents.get("atlas-review-draft").value, "Keep this disconnected draft", "without CustomEvent support the copyable draft is still retained");
contains(noEvents.review().textContent, text.en.disconnected, "missing event support cannot be called connected");
noEvents.unchanged();
process.stdout.write(`Atlas review DOM regression: ${checks} checks passed (synthetic, no native execution).\n`);
