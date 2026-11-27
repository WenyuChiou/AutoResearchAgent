// Display only. Callers supply project-bound, persisted records from the Host.
const wikiRecordMissing = '这一段还没有运行，没有记录。';
const wikiRecordNumber = value => Number.isSafeInteger(value) && value >= 0;

function wikiRecordSummary(record) {
 const parts = [];
 if (wikiRecordNumber(record?.recordCount)) parts.push(record.recordCount + ' 条记录');
 if (wikiRecordNumber(record?.blockedCount)) parts.push('拦下 ' + record.blockedCount + ' 次');
 return parts.join(' · ') || wikiRecordMissing;
}

function wikiHarnessRecord(record) {
 const checks = (record?.checks || []).filter(row => row?.name && row.result && row.raw != null);
 const timeline = (record?.timeline || []).filter(row => row?.step && row.raw != null);
 const blocked = [
  ['failedCheck', '没通过的检查'], ['wrongProject', '错项目'], ['staleVersion', '旧版本'],
  ['duplicate', '重复点击'], ['overLimit', '超额度']
 ];
 const resume = record?.resume;
 const recordedBlocks = blocked.some(([key]) => wikiRecordNumber(record?.blocked?.[key]));
 const summary = typeof record?.summary === 'string' && record.summary ? record.summary : wikiRecordSummary(record);
 const raw = value => `<details><summary>看原始记录</summary><pre>${esc(JSON.stringify(value, null, 2))}</pre></details>`;
 const table = (headers, rows) => `<table><thead><tr>${headers.map(name => `<th scope="col">${name}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`;
 const missing = record?.summary ? '<p class="wiki-record-gap">这份交付没有保存这一项。</p>' : `<p>${wikiRecordMissing}</p>`;
 const chip = '<strong class="wiki-record-chip">Harness 记录</strong>';
 const chips = (record?.chips || []).map(([text, warn]) => `<span class="wiki-record-count${warn ? ' warn' : ''}">${esc(text)}</span>`).join('');
 if (summary === wikiRecordMissing && !checks.length && !timeline.length && !recordedBlocks && resume?.raw == null) {
  return `<div class="wiki-record" data-wiki-record>${chip}<span>${wikiRecordMissing}</span></div>`;
 }
 return `<details class="wiki-record" data-wiki-record>
  <summary>${chip}<span>${summary === wikiRecordMissing ? '有已保存的明细' : esc(summary)}</span>${chips ? `<span class="wiki-record-counts">${chips}</span>` : ''}<span class="wiki-record-expand">展开明细</span><span class="wiki-record-collapse">收起明细</span></summary>
  <div class="wiki-record-body">
   <p>这里只说做了哪些检查，不代表研究结论是对的。</p>${record?.source ? `<p class="wiki-record-gap">${esc(record.source)}</p>` : ''}
   <h3>这一段查了什么、留了什么</h3>
   ${checks.length ? table(['事项', '结果', '原始记录'], checks.map(row => `<tr><th scope="row">${esc(row.name)}</th><td>${esc(row.result)}</td><td>${raw(row.raw)}</td></tr>`)) : record?.checksNote ? `<p class="wiki-record-gap">${esc(record.checksNote)}</p>` : missing}
   <h3>被拦下的事</h3>
   ${recordedBlocks ? table(['事项', '结果'], blocked.map(([key, label]) => {
    const count = record.blocked[key];
    const why = record.blockedReasons?.[key];
    return `<tr><th scope="row">${label}</th><td>${count === 0 ? '0 次 · 没有发生' : wikiRecordNumber(count) ? count + ' 次' + (why?.length ? ' · ' + esc(why.join('；')) : '') : '未提供'}</td></tr>`;
   })) : missing}${record?.blockedNote ? `<p class="wiki-record-gap">${esc(record.blockedNote)}</p>` : ''}
   <h3>关掉重开</h3>
   ${resume?.raw != null ? `<p>${esc(resume.result || '未提供')}${wikiRecordNumber(resume.newJobs) ? ' · 新增作业 ' + resume.newJobs + ' 个' : ''}</p>${raw(resume.raw)}` : record?.reopenNote ? `<p class="wiki-record-gap">${esc(record.reopenNote)}</p>` : missing}
   <h3>运行过程</h3>
   ${!timeline.length && record?.timelineNote ? `<p class="wiki-record-gap">${esc(record.timelineNote)}</p>` : timeline.length ? table(['步骤', '开始–结束', '模型调用', '花费', '发生了什么', '原始记录'], timeline.map(row => `<tr><th scope="row">${esc(row.step)}</th><td>${esc(row.time || '未提供')}</td><td>${wikiRecordNumber(row.modelCalls) ? row.modelCalls : '未提供'}</td><td>${esc(row.cost ?? '未提供')}</td><td>${esc(row.result || '未提供')}</td><td>${raw(row.raw)}</td></tr>`)) : missing}
  </div>
 </details>`;
}

// ---------- Backend read of the Harness record (DESIGN 3.0, "11-27 补") ----------
// One stage per request, one request in flight at a time, never in parallel. The host queues the stages on
// one lock and a cut-off request keeps running there, so nothing is resent automatically. Read-only GET.
const wikiRecTimeoutMs = 30000;
const wikiRecRef = /^project-[A-Za-z0-9]+$/;
const wikiRecStore = new Map(); // 'ref|stage' -> {state:'loading'|'timeout'|'failed'|'unsupported'|'ok', data, error}
let wikiRecFlight = null; // {key}: really in flight; stays set after the 30 s display timeout until the request ends
let wikiRecWant = null; // newest wanted {ref, stage}; an older wish that never started is dropped
const wikiRecReasons = {
 'stage1-unconnected':'Stage 1 还没有接通', 'no-ledger-saved':'还没有保存的账本', 'stage2-unconnected':'Stage 2 还没有接通',
 'stage2-not-started':'Stage 2 还没有开始', 'stage3-unconnected':'Stage 3 还没有接通', 'stage3-not-registered':'Stage 3 的规划还没有登记'
};
const wikiRecLabels = {
 queries:'检索词', backend_attempts:'检索尝试', backend_failures:'检索失败', success_empty:'成功但没有结果', discoveries:'发现',
 decisions:'决定数', works:'文献', claims:'证据', source_attempts:'原文获取尝试', acquired_full_text:'取得全文',
 full_text_acquisition_fraction:'全文获取比例', access_state_counts:'访问状态', rounds:'检索轮数', recent_complete:'最近一轮完整',
 consecutive_zero_yield_rounds:'连续零收获轮数', budget_exhausted:'额度用尽', blockers:'阻塞项', next_allowed_action:'下一步允许',
 event_id:'检查点编号', current:'是当前版本', status:'状态', gate:'检查结果', blocking_items:'阻塞项', candidates:'候选数',
 reason:'原因', selection_status:'选择状态', receipt_saved:'已保存选择回执', planning_status:'规划状态', configured:'已登记', saved:'已保存'
};
const wikiRecBlockedKeys = {'failed-check':'failedCheck', 'wrong-project':'wrongProject', 'stale-version':'staleVersion', 'duplicate-click':'duplicate', 'over-limit':'overLimit'};
const wikiRecBlockedNote = '只数已保存的失败记录；在写入之前就被拒绝的请求不会留下记录，不在这些次数里。';

function wikiRecReason(code) {
 return wikiRecReasons[code] || (code ? '原因代码 ' + code : '没有给出原因');
}
function wikiRecInferred(row) {
 return row?.inferred === true || row?.source?.inferred === true;
}
function wikiRecScalar(value) {
 if (value === null || value === undefined) return '没有保存';
 if (value === true) return '是';
 if (value === false) return '否';
 if (typeof value === 'object') return JSON.stringify(value);
 return String(value);
}
// Counts are shown exactly as the host saved them; an unsaved value stays "还没有" with the host's own reason.
function wikiRecRowText(row) {
 const value = row.value;
 const inferredKeys = Array.isArray(row.inferred_keys) ? row.inferred_keys : [];
 let text;
 if (value === null || value === undefined) text = '还没有' + (row.missing ? '：' + row.missing : '');
 else {
  text = value && typeof value === 'object' && !Array.isArray(value)
   ? Object.entries(value).map(([key, item]) => (wikiRecLabels[key] || key) + ' ' + wikiRecScalar(item) + (inferredKeys.includes(key) ? '（推算）' : '')).join(' · ')
   : wikiRecScalar(value);
  if (row.missing) text += ' · 还没有：' + row.missing;
 }
 return (wikiRecInferred(row) ? '推算 · ' : '') + text;
}
// Saved failed-action counts per class with the host's own reasons, as the record block expects them.
function wikiRecBlockedPart(stage) {
 const blocked = {}, reasons = {};
 for (const cell of Array.isArray(stage.blocked) ? stage.blocked : []) {
  const key = wikiRecBlockedKeys[cell?.category];
  if (!key || !wikiRecordNumber(cell.count)) continue;
  blocked[key] = cell.count;
  if (Array.isArray(cell.reasons) && cell.reasons.length) reasons[key] = cell.reasons.map(String);
 }
 return {blocked, blockedReasons:reasons, blockedNote:wikiRecBlockedNote};
}
function wikiRecMap(stage) {
 const rows = Array.isArray(stage.rows) ? stage.rows : [];
 const {blocked, blockedReasons: reasons} = wikiRecBlockedPart(stage);
 const records = stage.summary?.records, shown = wikiRecordNumber(records) ? records : null;
 const summary = wikiRecordSummary({recordCount:shown, blockedCount:stage.blocked_total});
 const withData = stage.summary?.rows_with_data;
 const chips = [];
 if (wikiRecordNumber(withData)) chips.push([`${withData} / ${rows.length} 项有数据`, withData < rows.length]);
 if (stage.summary?.checkpoint_passed === false) chips.push(['检查点没有通过', true]);
 const note = part => part?.available === false ? '后台还没有提供这一块' : part ? '后台提供了这一块，页面还没有接入' : '后台还没有提供这一块';
 return {
  summary: summary === wikiRecordMissing ? undefined : summary + (stage.summary?.inferred === true ? '（推算）' : ''),
  source: '数字来自后台保存的记录（只读），页面没有自己加总。',
  chips, blocked, blockedReasons: reasons, blockedNote: wikiRecBlockedNote,
  checks: rows.filter(row => row?.label).map(row => ({name:row.label, result:wikiRecRowText(row), raw:row})),
  reopenNote: note(stage.reopen), timelineNote: note(stage.timeline)
 };
}

function wikiRecToken(ref, stage) {
 const entry = wikiRecStore.get(ref + '|' + stage);
 return (entry?.state || 'loading') + (wikiRecFlight ? ':busy' : ':idle');
}
function wikiRecRepaint() {
 if (typeof apps === 'undefined') return;
 for (const app of apps) {
  for (const el of app.el?.querySelectorAll?.('[data-wiki-record-stage]') || []) {
   const stage = Number(el.dataset.wikiRecordStage), ref = el.dataset.wikiRecordRef;
   if (typeof rt !== 'undefined' && rt.ref !== ref) continue;
   if (el.dataset.wikiRecordState === wikiRecToken(ref, stage)) continue;
   el.outerHTML = wikiRecordBlock(stage);
  }
 }
}
function wikiRecPump() {
 if (wikiRecFlight || !wikiRecWant) return;
 const {ref, stage, home} = wikiRecWant, key = ref + '|' + stage, entry = wikiRecStore.get(key);
 wikiRecWant = null;
 if (!entry || entry.state !== 'loading') return;
 // A page read is dropped when the page changed; a home read is dropped as soon as the user left the home page.
 if (home ? !wikiRecHomeActive() : typeof rt !== 'undefined' && rt.ref !== ref) { wikiRecStore.delete(key); return; }
 wikiRecFlight = {key};
 const timer = setTimeout(() => {
  if (entry.state === 'loading') { entry.state = 'timeout'; wikiRecRepaint(); wikiRecHomeStep(); }
 }, wikiRecTimeoutMs);
 let request;
 try { request = Promise.resolve(liveRequest(projectPath(ref, 'harness-record/stage-' + stage))); }
 catch (error) { request = Promise.reject(error); }
 request.then(value => {
  const data = value?.stages?.[stage];
  if (value?.kind !== 'HarnessRecordSummary' || value.project_ref !== ref || value.read_only !== true || !data || typeof data !== 'object') throw Error('harness-record-shape-differs');
  if (entry.state === 'loading' || entry.state === 'timeout') { entry.state = 'ok'; entry.data = data; }
 }).catch(error => {
  if (entry.state !== 'loading' && entry.state !== 'timeout') return;
  entry.state = error?.status === 404 ? 'unsupported' : 'failed';
  entry.error = String(error?.message || error);
 }).finally(() => {
  clearTimeout(timer);
  wikiRecFlight = null;
  wikiRecRepaint();
  wikiRecPump();
  wikiRecHomeStep();
 });
}
// retry=true only from the explicit button; a timed-out or failed stage is never resent by itself.
function wikiRecEnsure(ref, stage, retry, home) {
 if (!wikiRecRef.test(ref || '')) return;
 const key = ref + '|' + stage;
 let entry = wikiRecStore.get(key);
 if (entry && ['ok', 'unsupported'].includes(entry.state)) return;
 if (entry && ['timeout', 'failed'].includes(entry.state)) {
  if (!retry || wikiRecFlight) return;
  entry.state = 'loading'; entry.error = '';
 }
 if (!entry) wikiRecStore.set(key, entry = {state:'loading'});
 if (wikiRecFlight?.key === key || (wikiRecWant?.ref === ref && wikiRecWant.stage === stage)) return;
 if (wikiRecWant) {
  const oldKey = wikiRecWant.ref + '|' + wikiRecWant.stage;
  if (wikiRecStore.get(oldKey)?.state === 'loading' && wikiRecFlight?.key !== oldKey) wikiRecStore.delete(oldKey);
 }
 wikiRecWant = {ref, stage, home:home === true};
 wikiRecPump();
}

function wikiRecTag(html, ref, stage) {
 return html.replace('data-wiki-record', `data-wiki-record data-wiki-record-stage="${stage}" data-wiki-record-ref="${esc(ref)}" data-wiki-record-state="${wikiRecToken(ref, stage)}"`);
}
function wikiRecStrip(tone, label, text, extra) {
 return `<div class="wiki-record wiki-record-state ${tone}" data-wiki-record role="status"><strong class="wiki-record-chip">Harness 记录</strong>${label ? `<span class="wiki-record-tag ${tone}">${label}</span>` : ''}<span>${text}</span>${extra || ''}</div>`;
}
function wikiRecordBlock(stage) {
 const ref = typeof rt !== 'undefined' ? rt.ref : null;
 const own = stage === 1 && typeof v1S1Record === 'function' ? v1S1Record() : undefined;
 const saved = own?.summary ? own : undefined;
 const basis = why => saved ? {...saved, source: why + '下面的数字是页面按已保存的交付内容数出来的，不是后台的 Harness 记录汇总。'} : undefined;
 if (!wikiRecRef.test(ref || '')) return wikiHarnessRecord(basis('这份保存的记录没有后台的 Harness 记录汇总。'));
 const entry = wikiRecStore.get(ref + '|' + stage);
 if (!entry || entry.state === 'loading') {
  if (!entry) setTimeout(() => wikiRecEnsure(ref, stage), 0);
  return wikiRecTag(wikiRecStrip('loading', '读取中', '正在读取这一段的 Harness 记录，第一次可能要十几秒。不需要你操作。'), ref, stage);
 }
 let html;
 if (entry.state === 'timeout') {
  html = wikiRecStrip('timeout', '读取超时', '等了 30 秒还没读到。这不代表没有记录，也不代表记录有问题。',
   `<button type="button" class="wiki-home-button" data-wiki-record-retry ${wikiRecFlight ? 'disabled' : ''}>重新读取</button>${wikiRecFlight ? '<small>上一次读取还没结束</small>' : ''}`);
 } else if (entry.state === 'failed') {
  html = wikiRecStrip('failed', '读取失败', '这一段的记录这次没读到，已显示的结果不受影响。',
   `<button type="button" class="wiki-home-button" data-wiki-record-retry ${wikiRecFlight ? 'disabled' : ''}>重新读取</button>${wikiRecFlight ? '<small>上一次读取还没结束</small>' : ''}<details><summary>看原始错误</summary><pre>${esc(entry.error || '')}</pre></details>`);
 } else if (entry.state === 'unsupported') {
  html = saved ? wikiHarnessRecord(basis('这个后台没有提供 Harness 记录汇总。'))
   : wikiRecStrip('', '', '这一段的记录现在读不到：这个后台没有提供 Harness 记录汇总。');
 } else if (entry.data.status === 'recorded') {
  html = wikiHarnessRecord(wikiRecMap(entry.data));
 } else if (entry.data.status === 'not-run') {
  // Run counts stay hidden for a stage that has not run, but a saved blocked count is never hidden (coordinator, 11-27).
  const n = entry.data.blocked_total, part = wikiRecordNumber(n) && n > 0 ? wikiRecBlockedPart(entry.data) : null;
  const stopped = part && {...part, chips:[[`被拦下 ${n} 次`, true]], checksNote:'这一段还没有运行，没有运行类计数。', reopenNote:'后台还没有提供这一块', timelineNote:'后台还没有提供这一块'};
  html = saved ? wikiHarnessRecord({...basis(`后台说这一段没有保存的运行记录（${wikiRecReason(entry.data.reason)}）。`), ...(stopped ? {...part, chips:[...(saved.chips || []), ...stopped.chips]} : {})})
   : stopped ? wikiHarnessRecord({summary:`这一段还没有运行 · 被拦下 ${n} 次`, source:'这一段还没有运行；下面只有已保存的失败记录。', ...stopped})
   : wikiHarnessRecord();
 } else {
  html = saved ? wikiHarnessRecord(basis(`后台这一段的记录现在读不到（${wikiRecReason(entry.data.reason)}）。`))
   : wikiRecStrip('', '', '这一段的记录现在读不到：' + esc(wikiRecReason(entry.data.reason)) + '。');
 }
 return wikiRecTag(html, ref, stage);
}

// Home table: shows what was already read in this tab; wikiRecHomeStart below reads at most 8 rows, one at a time.
function wikiRecHome(ref) {
 let records = 0, blocked = 0, inferred = false, ran = false;
 const stages = [];
 for (const stage of [1, 2, 3]) {
  const data = wikiRecStore.get(ref + '|' + stage);
  if (data?.state !== 'ok' || !['recorded', 'not-run'].includes(data.data?.status)) continue;
  stages.push(stage);
  if (wikiRecordNumber(data.data.blocked_total)) blocked += data.data.blocked_total;
  if (data.data.status !== 'recorded') continue;
  ran = true;
  if (wikiRecordNumber(data.data.summary?.records)) records += data.data.summary.records;
  if (data.data.summary?.inferred === true) inferred = true;
 }
 if (!stages.length) return null;
 if (ran) return {text: wikiRecordSummary({recordCount:records, blockedCount:blocked}) + (inferred ? '（推算）' : ''), stages};
 return {text: '还没有运行' + (blocked > 0 ? ' · 被拦下 ' + blocked + ' 次' : ''), stages};
}

// ---------- Home: bounded, sequential reads (coordinator, 11-27) ----------
// First 8 visible rows, Stage 1 only (no writer lock), one request at a time, stops when the user leaves the
// home page, and stops for good on the first timeout. Read-only.
const wikiRecHomeLimit = 8;
const wikiRecHomeState = {queue:[], total:0, key:'', stopped:null};
function wikiRecHomeActive() {
 return typeof apps !== 'undefined' && apps[0]?.lang === 'zh' && apps[0].page === 'home';
}
function wikiRecHomeWaiting(ref) {
 return wikiRecHomeState.queue.some(item => item.ref === ref);
}
function wikiRecHomeNote() {
 const state = wikiRecHomeState;
 if (state.stopped === 'timeout') return '后台记录读取超时，已停止读取后续课题；没读到的课题写「打开课题后可见」。';
 if (state.queue.length) return `正在逐个读取前 ${state.total} 个课题的后台记录（${state.total - state.queue.length} / ${state.total}），一次只读一个。`;
 return '';
}
function wikiRecHomeRepaint() {
 if (typeof apps === 'undefined' || !wikiRecHomeActive() || typeof wikiHomeRecordCell !== 'function') return;
 const el = apps[0].el;
 for (const cell of el?.querySelectorAll?.('[data-wiki-home-record-ref]') || []) {
  const project = rt.list.find(item => item.project_ref === cell.dataset.wikiHomeRecordRef);
  if (project) cell.innerHTML = wikiHomeRecordCell(wikiHomeRow(project));
 }
 const note = el?.querySelector?.('[data-wiki-home-record-note]');
 if (note) note.textContent = wikiRecHomeNote();
}
function wikiRecHomeStep() {
 const state = wikiRecHomeState;
 if (!state.queue.length) return;
 if (!wikiRecHomeActive()) { state.queue = []; state.key = ''; return; }
 while (state.queue.length) {
  const {ref, stage} = state.queue[0], entry = wikiRecStore.get(ref + '|' + stage);
  if (entry?.state === 'timeout') { state.stopped = 'timeout'; state.queue = []; break; }
  if (entry && ['ok', 'unsupported', 'failed'].includes(entry.state)) { state.queue.shift(); continue; }
  wikiRecEnsure(ref, stage, false, true);
  break;
 }
 wikiRecHomeRepaint();
}
function wikiRecHomeStart(items) {
 const state = wikiRecHomeState;
 const list = (items || []).filter(item => wikiRecRef.test(item?.ref || '')).slice(0, wikiRecHomeLimit);
 const key = JSON.stringify(list);
 if (key === state.key) return;
 state.key = key; state.queue = list.map(item => ({ref:item.ref, stage:1})); state.total = list.length; state.stopped = null;
 wikiRecHomeStep();
}
function wikiRecHomeLeave() {
 Object.assign(wikiRecHomeState, {queue:[], key:'', stopped:null});
}
// Visible rows in table order (the origin filter hides rows), only rows that have a stage.
function wikiRecHomeVisible(app) {
 const refs = [...(app?.el?.querySelectorAll?.('tr[data-wiki-home-origin]:not([hidden]) [data-wiki-home-open]') || [])].map(button => button.dataset.wikiHomeOpen);
 return refs.filter(ref => {
  const project = rt.list.find(item => item.project_ref === ref);
  return project && wikiHomeRow(project).origin === 'local' && wikiHomeRow(project).stage;
 }).slice(0, wikiRecHomeLimit).map(ref => ({ref}));
}

if (typeof document !== 'undefined' && document.addEventListener) {
 document.addEventListener('click', event => {
  const button = event.target?.closest?.('[data-wiki-record-retry]');
  if (!button) return;
  const root = button.closest('[data-wiki-record-stage]');
  if (!root || wikiRecFlight) return;
  event.preventDefault();
  wikiRecEnsure(root.dataset.wikiRecordRef, Number(root.dataset.wikiRecordStage), true);
  wikiRecRepaint();
 });
}
