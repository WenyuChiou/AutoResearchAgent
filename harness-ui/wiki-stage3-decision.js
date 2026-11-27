// ---------- Stage 3 「你的决定」 (DESIGN 3.4 item 5, 2.5 decision block, 8.18 item 5) ----------
// Backend (project_stage3_decision.py, project_stage3_http.py): POST …/stage3/planning/decide with the current
// binding from GET stage3/planning → host_decision.binding (six plan bindings + plan_revision_receipt_sha256),
// a key, decision (accept | revise-then-review | return-to-stage2), text (optional, at most 4096 UTF-8 bytes; the
// 32768-byte figure is the whole request body) and confirmed:true. Every refusal happens before anything is written.
// A replay of the same key returns the saved record. The record is a local page record: identity not verified,
// never an execution grant. Records carry a sequence and recorded_at (UTC; null on older records).
const wikiS3DecTextBytes = 4096;
const wikiS3DecLabels = {'accept':'接受计划', 'revise-then-review':'按建议修改后再评审', 'return-to-stage2':'退回 Stage 2 重选'};
// Interface table (stage3-decision-backend-1127.md, 审查后更新 and 复核后第二次更新); the raw code goes in technical details.
const wikiS3DecCodes = {
 'explicit-stage3-decision-required':'需要你明确确认后才能保存。',
 'stage3-decision-invalid':'决定的选项不在三个选项里，请重新选。',
 'stage3-decision-text-invalid':'理由的格式不对，没有保存。',
 'stage3-decision-key-required':'这次请求缺少操作编号，没有保存；请再点一次保存。',
 'intake-fields-invalid':'请求缺少或多了字段，没有保存；页面和后台的版本可能不一致。',
 'credential-rejected':'凭据不对，没有保存；请从首页用这次启动的地址重新打开。',
 'cross-site-rejected':'请求来源不对，没有保存；请在本机页面里操作。',
 'stage3-planning-unconnected':'Stage 3 规划还没有接通，没有保存。',
 'stage3-decision-saved-plan-required':'还没有保存的计划，不能做决定。',
 'stage3-decision-version-differs':'这版计划已经变了，请刷新后再决定。',
 'stage3-decision-key-payload-differs':'同一个操作编号的内容不同，没有保存；再点一次保存会用新的编号。',
 'stage3-decision-plan-not-ready':'计划还有未填完的内容，或设计评审认为还缺信息，不能接受；你可以选「按建议修改后再评审」。',
 'stage3-decision-planning-status-missing':'保存的计划缺少规划状态，不能接受；你可以选「按建议修改后再评审」。',
 'stage3-decision-revision-ambiguous':'这份计划有两份并列的修订稿，请先在其中一份基础上继续修订，再做决定。',
 'stage3-planning-project-busy':'这个课题的另一次 Stage 3 保存正在进行，没有保存；稍后再试。',
 'stage3-planning-input-rejected':'同时有另一次保存，这次没有保存；请重新读取后再试。',
 'stage3-decision-record-bound':'这一版计划的决定已满 32 条，不能再保存。',
 'stage3-decision-record-differs':'决定记录的校验不一致，没有保存。',
 'stage3-decision-text-too-long':'理由超过 4096 字节，没有保存；原文还在，删短后再保存。',
 'stage3-decision-response-bound':'保存后回读会超过上限，没有保存。',
 'stage3-planning-body-bound-exceeded':'请求太大，没有保存。'
};
const wikiS3DecFollow = {
 'accept':'已保存：你接受了这版计划（本机页面记录，未经原生核验）。接受也不会启动实验。',
 'revise-then-review':'已保存你的意图。接下来可以用上面的「评语与修订」改计划。现在还不能针对修改后的计划再生成一次：后台生成计划时只读选方向时的材料，不读你修改过的版本。这个功能需要后台新增。保存这个决定本身不会修改计划，也不会启动新评审。',
 'return-to-stage2':'已保存你的意图。Stage 2 的选择一经保存不能更改；要换方向，目前需要新建课题。'
};
const wikiS3DecHonest = '本机页面记录，未核验身份，不授权执行';
// Per-topic page state. busy is per topic so leaving and coming back cannot drop an in-flight save.
const wikiS3Dec = {ref:null, pick:'', text:'', confirming:false, error:null, unknown:null, saved:null, busy:new Map(), usedKeys:new Set()};

function wikiS3DecState() {
 if (wikiS3Dec.ref !== rt.ref) Object.assign(wikiS3Dec, {ref:rt.ref, pick:'', text:'', confirming:false, error:null, saved:null});
 return wikiS3Dec;
}
function wikiS3DecBytes(text) { return new TextEncoder().encode(String(text)).length; }
function wikiS3DecKey() {
 let key;
 do key = typeof crypto?.randomUUID === 'function' ? crypto.randomUUID() : 'd-' + Date.now() + '-' + Math.random().toString(16).slice(2);
 while (wikiS3Dec.usedKeys.has(key));
 wikiS3Dec.usedKeys.add(key);
 return key;
}
function wikiS3DecView() {
 const basis = typeof v93Identity === 'function' ? v93Identity() : null;
 return basis && v93Matches(v93.basis, basis) ? v93.view : null;
}
// Newest manual revision the page already holds (v94f keeps the ones saved from this page); same rule as the
// backend: the highest revision_number, a tie is ambiguous.
function wikiS3DecLocalRevision() {
 const context = typeof v94fContext === 'function' ? v94fContext() : null;
 const state = context && typeof v94fState === 'function' ? v94fState(context) : null;
 const rows = (state?.records || []).filter(row => row.record.kind === 'revision');
 if (!rows.length) return null;
 const top = Math.max(...rows.map(row => row.record.revision_number));
 const newest = rows.filter(row => row.record.revision_number === top);
 return newest.length === 1 ? newest[0] : {ambiguous:true};
}
// Client copy of the backend accept test where the page can know it; a full plan's structure check stays server-side.
function wikiS3DecAcceptWhy(view, revision) {
 const status = view?.job?.planning_status;
 if (status === undefined || status === null) return '保存的计划缺少规划状态，后台不允许接受';
 if (!['draft', 'ready-for-plan-review'].includes(status)) return '设计评审认为这份计划还缺信息，不能接受';
 const plan = revision?.record?.plan || view?.plan;
 if (plan?.kind === 'Stage3DirectionPlanningResult') {
  if (plan.planning_status === undefined || plan.planning_status === null) return '计划自己没有写规划状态，后台不允许接受';
  if (plan.planning_status === 'needs-information') return '计划自己写明还缺信息，不能接受';
  const fields = ['method', 'materials', 'design', 'analysis', 'interpretation', 'validation', 'minimum_deliverable'];
  const rows = Array.isArray(plan.question_plans) ? plan.question_plans : [];
  if (!rows.length || rows.some(row => fields.some(name => typeof row?.[name] !== 'string' || !row[name].trim()))) return '计划还有未填完的内容，不能接受';
 }
 return '';
}

// What the decision block can do now. Returns {why, acceptWhy, decision (host_decision when usable), notice}.
function wikiS3DecModel(app) {
 const state = wikiS3DecState(), view = wikiS3DecView();
 const connected = typeof v9ConnectionConnected === 'function' && v9ConnectionConnected('stage3-planning');
 const hd = view?.host_decision;
 const out = {view, hd:null, why:'', acceptWhy:'', notice:null};
 if (!connected) { out.why = '现在还不能做这一步：Stage 3 还没有接通。'; return out; }
 if (!view?.plan) { out.why = '现在还不能做这一步：还没有计划。'; return out; }
 if (!hd || typeof hd !== 'object') { out.why = '现在还不能做这一步：这次启动的后台没有提供决定记录。'; return out; }
 if (typeof hd.error === 'string') {
  out.notice = {tone:'warn', tag:'读不出来', text:'决定记录这次读不出来（日志校验没有通过）。计划和评语不受影响；已保存的决定没有被改。', code:hd.error};
  out.why = '决定记录读不出来，现在不能保存新的决定。'; return out;
 }
 if (hd.omitted) {
  const count = Number.isSafeInteger(hd.count) ? hd.count : null;
  out.notice = count ? {tone:'idle', tag:'放不下', text:`已经保存了 ${count} 条决定，最新一条（第 ${hd.latest_sequence ?? '?'} 次）是「${wikiS3DecLabels[hd.latest_decision] || hd.latest_decision || '未提供'}」。这次读取放不下全部内容，页面没有显示详情。`, code:hd.omitted}
   : {tone:'idle', tag:'放不下', text:'这次读取放不下决定记录' + (count === 0 ? '；后台说还没有决定。' : '，页面不知道有没有决定。'), code:hd.omitted};
  out.why = '这次读取没有带回当前版本的绑定，现在不能保存。'; return out;
 }
 if (hd.kind !== 'ProjectStage3PlanDecisionView' || !hd.binding || !Array.isArray(hd.records)) { out.why = '现在还不能做这一步：决定记录的格式不对。'; return out; }
 out.hd = hd;
 const feedback = view.feedback?.records;
 if (hd.revision_ambiguous) {
  out.why = Array.isArray(feedback) && feedback.length >= 32 ? '这份计划有两份并列的修订稿，修订记录已满，请重新生成计划。'
   : '这份计划有两份并列的修订稿，请先在其中一份基础上继续修订，再做决定。';
  return out;
 }
 const local = wikiS3DecLocalRevision();
 if (local && !local.ambiguous && local.receipt_sha256 !== hd.binding.plan_revision_receipt_sha256) {
  out.why = '计划刚被修订过，页面先要重新读取这一版才能决定。'; out.stale = true; return out;
 }
 if (wikiS3Dec.unknown?.ref === rt.ref) { out.why = wikiS3Dec.unknown.absent ? '核对完了：这次没有保存。点上面的「知道了」后可以重新决定。' : '上次保存的结果还没确认，先只读核对。'; return out; }
 if (wikiS3Dec.busy.has(rt.ref)) { out.why = '正在保存，请稍等'; return out; }
 if (rt.loading || v93.busy) { out.why = '正在读取保存记录'; return out; }
 if (rt.busy || rt.pending || rt.controlHeld) { out.why = rt.pending || rt.controlHeld ? '有一次提交的结果还没确认，先核对' : '正在保存，请稍等'; return out; }
 out.acceptWhy = wikiS3DecAcceptWhy(view, local && !local.ambiguous ? local : null);
 return out;
}

// The one gate for the confirm button, used when drawing, while typing and again right before sending.
function wikiS3DecGate(m, state) {
 if (m.why) return m.why;
 if (!wikiS3DecLabels[state.pick]) return '请先选一个';
 if (state.pick === 'accept' && m.acceptWhy) return m.acceptWhy + '；你可以选「按建议修改后再评审」。';
 if (wikiS3DecBytes(state.text) > wikiS3DecTextBytes) return `理由超过 ${wikiS3DecTextBytes} 字节，原文保留；删短后才能保存`;
 return '';
}
// recorded_at is the server's UTC ISO 8601 write time (null for records saved before the field existed). Shown in
// the viewer's local time zone; the UTC original is the hover title.
function wikiS3DecTime(value) {
 if (value === null || value === undefined) return '这条记录保存时还没有记录时间';
 const date = new Date(value);
 if (typeof value !== 'string' || Number.isNaN(date.getTime())) return `<span title="${wikiS3Escape(value)}">${wikiS3Escape(value)}</span>`;
 const local = date.toLocaleString('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false});
 return `<time datetime="${wikiS3Escape(value)}" title="UTC ${wikiS3Escape(value)}" data-s3-dec-time>${wikiS3Escape(local)}</time>`;
}
function wikiS3DecRecord(row, old) {
 const r = row.record || {};
 return `<li class="ws3-dec-record" data-s3-dec-record="${wikiS3Escape(r.sequence)}"><b>第 ${wikiS3Escape(r.sequence ?? '?')} 次：${wikiS3Escape(wikiS3DecLabels[r.decision] || r.decision)}</b>${old ? ' <span class="ws3-dec-old">针对旧版本</span>' : ''}
  <div>理由：${r.text ? wikiS3Escape(r.text) : '<span class="ws3-muted">没有写理由</span>'}</div>
  <div class="ws3-muted">时间：${wikiS3DecTime(r.recorded_at)} · ${wikiS3DecHonest}</div></li>`;
}

function wikiS3DecMarkup(app) {
 const state = wikiS3DecState(), m = wikiS3DecModel(app), hd = m.hd;
 const busy = wikiS3Dec.busy.has(rt.ref);
 const latest = hd?.latest;
 const tech = codes => codes.filter(Boolean).length ? `<details class="wiki-s2-tech"><summary>技术细节</summary>${codes.filter(Boolean).map(code => `<code>${wikiS3Escape(code)}</code>`).join(' ')}</details>` : '';
 const line = (tone, tag, text, extra = '') => `<div class="wiki-s2-conn-row" data-tone="${tone}" data-s3-dec-line><span class="wiki-s2-st" data-tone="${tone}">${wikiS3Escape(tag)}</span><p>${wikiS3Escape(text)}</p>${extra}</div>`;
 let result = '';
 if (busy) result = line('run', '正在保存', '正在保存你的决定，请稍等');
 else if (wikiS3Dec.unknown?.ref === rt.ref) result = line('warn', '结果未知', wikiS3Dec.unknown.absent
   ? '核对时没有找到这次的记录，说明没有保存。原请求不会重发；如果还要保存，请重新确认（会用新的编号）。'
   : wikiS3Dec.unknown.note || '保存的结果还不清楚。不会自动重发；先只读核对。',
  `<div class="wiki-s2-actions"><button type="button" class="hs-button" data-s3-dec="check" ${v93.busy ? 'disabled' : ''}>${wikiS3Dec.unknown.absent ? '知道了' : '只读核对'}</button></div>`) + tech([wikiS3Dec.unknown.code]);
 else if (state.error) result = line('warn', '被拦下', (wikiS3DecCodes[state.error.code] || '服务拒绝了这次保存，原因代码在技术细节里。') + '没有留下任何记录。') + tech([state.error.code]);
 if (m.notice) result += line(m.notice.tone, m.notice.tag, m.notice.text) + tech([m.notice.code]);
 const summary = state.summarySaved?.ref === rt.ref && m.view?.host_decision?.omitted ? state.summarySaved : null;
 if (summary) result += line('done', '已保存', `按读取摘要判断已经写入：第 ${summary.seq} 次「${wikiS3DecLabels[summary.decision]}」。这次读取放不下详情，没能按编号逐条核对。`);
 let saved = '';
 if (latest) {
  const d = latest.record?.decision;
  const fresh = state.saved && state.saved === latest.receipt_sha256;
  const goto = d === 'revise-then-review' ? `<div class="wiki-s2-actions"><span><button type="button" class="hs-button" data-s3-dec="feedback">去「评语与修订」</button></span>
   <span><button type="button" class="hs-button" disabled>请求生成计划</button><small class="wiki-s2-reason">现在还不能针对修改后的计划再生成一次：后台生成计划时只读选方向时的材料，不读你修改过的版本。这个功能需要后台新增。</small></span></div>` : '';
  saved = `<div class="ws3-dec-saved" data-s3-dec-saved role="status">${line('done', fresh ? '已保存' : '已有决定', wikiS3DecFollow[d] || '已保存。')}${goto}</div>`;
 }
 // Two tied revisions: the backend cannot tell which one a decision is for; that is not "no decision".
 const records = hd?.revision_ambiguous ? line('warn', '对不上版本', m.why)
  : hd?.records?.length ? `<h3>这一版计划的决定</h3><ol class="ws3-dec-list">${hd.records.slice().reverse().map(row => wikiS3DecRecord(row, false)).join('')}</ol>` : hd ? '<p class="ws3-muted" data-s3-dec-none>这一版计划还没有决定。</p>' : '';
 const history = hd?.history?.length ? `${hd.has_manual_revision && !hd.records.length && !hd.revision_ambiguous ? '<p class="ws3-note" data-s3-dec-moved>之前的决定针对修订前的计划，已移到历史；请对当前这版重新决定。</p>' : ''}
  <details class="ws3-dec-history" data-s3-dec-history ${hd.records.length ? '' : 'open'}><summary>历史决定（${hd.history.length}）</summary><ol class="ws3-dec-list">${hd.history.slice().reverse().map(row => wikiS3DecRecord(row, true)).join('')}</ol></details>` : '';
 // The form.
 const off = !!m.why || busy;
 const bytes = wikiS3DecBytes(state.text), tooLong = bytes > wikiS3DecTextBytes;
 const pick = state.pick && wikiS3DecLabels[state.pick] ? state.pick : '';
 const gate = busy ? '正在保存，请稍等' : wikiS3DecGate(m, state);
 // 「接受」 is grayed with its reason when the saved plan does not meet the accept condition.
 const choices = Object.entries(wikiS3DecLabels).map(([key, label]) => {
  const acceptOff = key === 'accept' && !!m.acceptWhy;
  return `<label class="ws3-choice"><input type="radio" name="s3-decision" value="${key}" data-s3-dec-pick ${pick === key ? 'checked' : ''} ${off || acceptOff ? 'disabled' : ''}> ${label}${acceptOff && !m.why ? ` <small class="ws3-why-off" data-s3-dec-accept-why>（${wikiS3Escape(m.acceptWhy)}）</small>` : ''}</label>`;
 }).join('');
 const count = `<small data-s3-dec-count class="${tooLong ? 'ws-field-err' : ''}">${tooLong ? `超过 ${wikiS3DecTextBytes} 字节，原文保留（现在 ${bytes} 字节）` : `可选，最多 ${wikiS3DecTextBytes} 字节（现在 ${bytes} 字节）`}</small>`;
 const confirm = state.confirming && !gate ? `<div class="ws3-dec-confirm" data-s3-dec-confirm role="group" aria-label="确认保存决定">
   <p><b>将保存的决定：</b>${wikiS3Escape(wikiS3DecLabels[pick])}</p><p><b>理由：</b>${state.text.trim() ? wikiS3Escape(state.text) : '没有写理由'}</p>
   <p class="ws3-note">这是在本机页面里保存的决定，没有经过原生核验，也不会启动任何实验或模型调用。</p>
   <div class="wiki-s2-actions"><button type="button" class="hs-button hs-button-primary" data-s3-dec="save">保存这个决定</button><button type="button" class="hs-button" data-s3-dec="back">返回修改</button></div></div>` : '';
 const again = latest && !m.why ? '<p class="ws3-muted">再保存一次会新增一条，以最新一条为准；之前的保留。</p>' : '';
 const read = m.stale ? `<div class="wiki-s2-actions"><button type="button" class="hs-button" data-v93-read ${v93.busy ? 'disabled' : ''}>重新读取这一版</button></div>` : '';
 return `<section class="ws3-decide" data-s3-decision><span class="ws3-label">你的决定</span><h2>这份计划怎么处理？</h2>
 <p class="ws3-note">接受也不会启动实验。系统的评审不是你的选择。决定只记在这台电脑的页面记录里：${wikiS3DecHonest}。</p>
 ${result}${saved}${records}${history}${again}
 <fieldset class="ws3-dec-form"><legend class="wiki-home-visually-hidden">三个选项，没有预选</legend>${choices}</fieldset>
 <label class="ws3-dec-reason">理由（可选）<textarea data-s3-dec-text rows="3" ${off ? 'disabled' : ''}>${wikiS3Escape(state.text)}</textarea>${count}</label>
 ${confirm || `<span><button type="button" class="hs-button hs-button-primary" data-s3-dec="confirm" ${gate ? 'disabled' : ''}>${pick ? `确认：${wikiS3DecLabels[pick]}…` : '请先选一个'}</button>${gate && gate !== '请先选一个' ? `<small class="wiki-s2-reason" data-s3-dec-why>${wikiS3Escape(gate)}</small>` : ''}</span>`}
 ${read}</section>`;
}

function wikiS3DecFind(view, key) {
 const hd = view?.host_decision;
 return [...(hd?.records || []), ...(hd?.history || [])].find(row => row?.record?.request?.key === key) || null;
}

async function wikiS3DecSave(app) {
 const state = wikiS3DecState(), m = wikiS3DecModel(app), ref = rt.ref;
 // Same gate as the page, checked again at the moment of sending; a busy topic sends nothing (double click).
 if (!m.hd || wikiS3Dec.busy.has(ref) || !state.confirming || wikiS3DecGate(m, state)) return;
 const pick = state.pick;
 const {project_ref, ...binding} = m.hd.binding;
 const key = wikiS3DecKey();
 const body = {...binding, key, decision:pick, text:state.text, confirmed:true};
 const basis = v93Identity(), epoch = rt.epoch;
 wikiS3Dec.busy.set(ref, key); state.error = null; state.confirming = false; state.summarySaved = null; livePaint();
 let outcome = 'unknown', code = '';
 try {
  const answer = await liveRequest(projectPath(ref, 'stage3/planning/decide'), body);
  const record = answer?.record;
  if (record?.request?.key !== key || record?.decision !== pick || typeof answer.receipt_sha256 !== 'string') throw Error('stage3-decision-receipt-differs');
  outcome = 'saved';
  if (wikiS3Dec.ref === ref) { state.saved = answer.receipt_sha256; state.pick = ''; state.text = ''; }
 } catch (error) {
  code = String(error.message || error);
  // Every backend refusal happens before writing (4xx): nothing was saved. Anything else may have been saved.
  if (Number.isInteger(error.status) && error.status >= 400 && error.status < 500) outcome = 'refused';
 } finally {
  wikiS3Dec.busy.delete(ref);
 }
 if (outcome === 'refused' && wikiS3Dec.ref === ref) state.error = {code};
 // What the page saw before saving, so a size-marker re-read can still tell whether anything was written.
 const rows = [...m.hd.records, ...(m.hd.history || [])];
 const before = {count:m.hd.records.length, seq:rows.reduce((top, row) => Math.max(top, Number(row?.record?.sequence) || 0), 0)};
 if (outcome === 'unknown') wikiS3Dec.unknown = {ref, key, code, pick, before};
 // Every outcome is followed by a read-only re-read; an unknown outcome is then looked up by its key.
 if (epoch === rt.epoch && ref === rt.ref) { await v93ReadSaved(app, basis); if (outcome === 'unknown') wikiS3DecSettle(ref); }
 livePaint();
}
// Settle an unknown save from the re-read (review P1-1). Only a full decision view can say "not saved" by key; a size
// marker is judged by its count and latest sequence against what the page saw before saving; a damaged journal or
// any other shape keeps the outcome unknown.
function wikiS3DecSettle(ref) {
 const unknown = wikiS3Dec.unknown;
 if (!unknown || unknown.ref !== ref || !v93.view) return;
 const hd = v93.view.host_decision, state = wikiS3DecState();
 const done = () => { wikiS3Dec.unknown = null; state.pick = ''; state.text = ''; };
 unknown.note = '';
 if (hd?.kind === 'ProjectStage3PlanDecisionView' && Array.isArray(hd.records)) {
  const found = wikiS3DecFind(v93.view, unknown.key);
  if (found) { done(); state.saved = found.receipt_sha256; } else unknown.absent = true;
  return;
 }
 const before = unknown.before;
 if (hd?.omitted && before && Number.isSafeInteger(hd.count)) {
  const seq = Number.isSafeInteger(hd.latest_sequence) ? hd.latest_sequence : 0;
  if (hd.count === before.count && seq <= before.seq) { unknown.absent = true; return; } // nothing was written
  if (seq > before.seq && hd.latest_decision === unknown.pick) { done(); state.summarySaved = {ref, seq, decision:unknown.pick}; return; }
  unknown.note = '这次读取放不下决定详情，看到有新的写入但对不上这次的选择，还不能确认有没有保存；不会自动重发，稍后再点「只读核对」。';
  return;
 }
 unknown.note = typeof hd?.error === 'string' ? '这次读取读不出决定记录（日志校验没有通过），还不能确认有没有保存；不会自动重发，稍后再点「只读核对」。'
  : '这次读取看不到决定详情，还不能确认有没有保存；不会自动重发，稍后再点「只读核对」。';
}
async function wikiS3DecCheck(app) {
 const unknown = wikiS3Dec.unknown;
 if (!unknown || unknown.ref !== rt.ref || v93.busy) return;
 if (unknown.absent) { wikiS3Dec.unknown = null; return livePaint(); } // already looked: nothing saved, the form opens again
 await v93ReadSaved(app, v93Identity());
 wikiS3DecSettle(unknown.ref);
 livePaint();
}

// Hook-up: replace the disabled stub only for a saved plan; the no-plan reasons keep the stub's wording.
const wikiS3DecisionStub = wikiS3Decision;
wikiS3Decision = function (noPlan = false) {
 if (noPlan !== false) return wikiS3DecisionStub(noPlan);
 return wikiS3DecMarkup(apps[0]);
};
// Stage 3 status line once a decision is saved (wiki-v1.js reads this).
function wikiS3DecStatus() {
 const latest = wikiS3DecView()?.host_decision?.latest;
 const d = latest?.record?.decision;
 if (!wikiS3DecLabels[d]) return null;
 const next = {'accept':'接受不会启动实验；后续阶段还没有开放。', 'revise-then-review':'用「评语与修订」改计划。', 'return-to-stage2':'Stage 2 的选择不能更改；要换方向，目前需要新建课题。'}[d];
 return {tone:'done', now:['计划写好了。', `你的决定已保存：${wikiS3DecLabels[d]}（${wikiS3DecHonest}）。`], next, you:null, button:{label:'看你的决定', attrs:'data-v1-goto="s3-decide"', primary:false}};
}

document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-s3-dec]');
 if (!button || button.disabled) return;
 const app = apps.find(item => item.el.contains(button));
 if (!app) return;
 event.preventDefault();
 const state = wikiS3DecState(), act = button.dataset.s3Dec;
 if (act === 'confirm') { state.confirming = true; state.error = null; livePaint(); }
 else if (act === 'back') { state.confirming = false; livePaint(); }
 else if (act === 'save') wikiS3DecSave(app);
 else if (act === 'check') wikiS3DecCheck(app);
 else if (act === 'feedback') app.el.querySelector('[data-s3-feedback]')?.scrollIntoView?.({behavior:'smooth', block:'start'});
});
document.addEventListener('change', event => {
 if (!event.target.matches?.('[data-s3-dec-pick]')) return;
 const state = wikiS3DecState();
 state.pick = event.target.value; state.confirming = false; state.error = null;
 livePaint();
});
// Typing updates the counter and the button in place (a repaint would move the caret).
document.addEventListener('input', event => {
 if (!event.target.matches?.('[data-s3-dec-text]')) return;
 const state = wikiS3DecState();
 state.text = event.target.value; state.confirming = false;
 const block = event.target.closest('[data-s3-decision]');
 const bytes = wikiS3DecBytes(state.text), tooLong = bytes > wikiS3DecTextBytes;
 const count = block?.querySelector('[data-s3-dec-count]');
 if (count) { count.className = tooLong ? 'ws-field-err' : ''; count.textContent = tooLong ? `超过 ${wikiS3DecTextBytes} 字节，原文保留（现在 ${bytes} 字节）` : `可选，最多 ${wikiS3DecTextBytes} 字节（现在 ${bytes} 字节）`; }
 const button = block?.querySelector('[data-s3-dec="confirm"]');
 if (button) {
  const gate = wikiS3DecGate(wikiS3DecModel(apps[0]), state);
  button.disabled = !!gate;
  let why = block.querySelector('[data-s3-dec-why]');
  if (gate && gate !== '请先选一个') { if (!why) { why = document.createElement('small'); why.className = 'wiki-s2-reason'; why.dataset.s3DecWhy = ''; button.after(why); } why.textContent = gate; }
  else why?.remove();
 }
 // The confirm panel (if it was open) closes on typing: what will be saved has changed.
 const panel = block?.querySelector('[data-s3-dec-confirm]');
 if (panel) livePaint();
});
