// Wiki V1 Codex chat drawer (DESIGN 8.4). Read-only Q&A on the right edge of every stage page.
// It talks only to /api/v9/chat/*: GET state is read-only; a POST happens only after a person
// clicks send, answer, stop or reconcile. It never grants permission (the grant is prepared
// outside the page) and never calls anything that could start research.
// Mounted by reassigning v7AfterRender, so no other module is edited.
const wikiChatAssistants = {1:'文献与证据助手', 2:'比较与选案助手', 3:'设计与可行性助手', 4:'实验执行助手', 5:'分析与图表助手', 6:'写作与投稿助手'};
const wikiChatSubtitles = {1:'核对检索、筛选理由、阅读证据与覆盖缺口', 2:'比较文献与路线，核验交接条件', 3:'讨论方案、可行性与待确认条件'};
const wikiChatQuick = {
 1:['读取本阶段已保存的交付，说明纳入、排除理由和缺失证据。', '列出当前阶段已登记的材料，先告诉我哪些能读、哪些还不能读。'],
 2:['读取当前 Stage 2 材料，对比各路线的证据、指标、缺口和待补条件，不强行排名。', '核验本阶段的交接状态，区分比较草稿、正式选案和执行许可。'],
 3:['读取本阶段已保存的规划，整理研究设计、可行性和缺失条件；不要启动实验。']
};
const wikiChatToolNames = {state:'读取课题状态', materials:'列出登记材料', read_material:'读取一份登记材料'};
const wikiChatFallback = '对话许可没有通过核对，界面只读，发送关闭';
const wikiChatMaxBytes = 8192, wikiChatAnswerBytes = 4096, wikiChatWorking = ['starting', 'running', 'waiting', 'stop-requested'];

function wikiChatBytes(text) { return new TextEncoder().encode(String(text)).length; }

// Why the message box cannot be sent yet (empty or too long), or ''.
function wikiChatDraftReason(text) {
 if (!String(text).trim()) return '消息是空的，先写一条';
 if (wikiChatBytes(text) > wikiChatMaxBytes) return '超过 8192 字节，没有发送';
 return '';
}

function wikiChatTime(seconds) {
 if (typeof seconds !== 'number' || !isFinite(seconds)) return '';
 const d = new Date(seconds * 1000), p = n => String(n).padStart(2, '0');
 return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function wikiChatTurns(state) { return Array.isArray(state?.turns) ? state.turns : []; }
function wikiChatWorkingTurn(state) { return wikiChatTurns(state).find(t => wikiChatWorking.includes(t.status)) || null; }
function wikiChatPendingCard(state) {
 return wikiChatTurns(state).find(t => t.status === 'waiting' && t.pending && (t.pending.answer === null || t.pending.answer === undefined)) || null;
}

// One pure function decides everything the panel shows. c: {stage, archive, phase, state, busy}.
function wikiChatPanel(c) {
 const st = c.state || null;
 let key;
 if (c.archive) key = 'archive';
 else if (c.stage > 3) key = 'stage-unconnected';
 else if (c.phase === 'error') key = 'read-failed';
 else if (!st) key = 'reading';
 else key = st.panel_state;
 const reason = st?.panel_reason?.text || '';
 const turn = wikiChatWorkingTurn(st), ask = wikiChatPendingCard(st);
 const p = {key, stale: c.phase === 'error' && !!st, dot:'off', label:'', note:'', canSend:false, sendReason:'', body:false, quota:false, recheck:false, settings:false};
 switch (key) {
  case 'archive':
   Object.assign(p, {label:'历史归档和合成样例不开放对话', note:'这是历史归档（或合成样例），不能在这里改；对话不在这里开放。', sendReason:'这是历史归档，不能在这里改'});
   break;
  case 'reading':
   Object.assign(p, {dot:'run', label:'正在读取对话状态', note:'正在读取这个课题在这一段的对话和材料，不调用模型。', sendReason:'读取完成后才能发送'});
   break;
  case 'read-failed':
   Object.assign(p, {dot:'err', label:'对话状态没读到', note:st ? '这次没能重新读取。下面是上次读到的内容，标了「上次读取」。' : '这次没能读取对话状态。', recheck:true, body:!!st, sendReason:'对话状态没读到，先重新读取'});
   break;
  case 'not-configured':
   Object.assign(p, {label:'本机还没有配置对话', note:'对话的配置和许可由本机操作者在页面外准备，页面上不能配置，也不能授权。' + (reason && reason !== '本机还没有配置对话' ? '这次启动的对话许可没有通过：' + reason + '。' : ''), recheck:true, settings:true, sendReason:'本机还没有配置对话'});
   break;
  case 'stage-unconnected':
   Object.assign(p, {label:'这一段的材料还没接通，对话关着', note:c.stage > 3 ? '这一段还没有开放，一直是这个状态。' : '对话要先能读到这一段的真实材料。', sendReason:'这一段的材料还没接通，对话关着'});
   break;
  case 'login-required':
   Object.assign(p, {label:'还没登录 Codex', note:'请在 Codex 自己的界面登录。这里不会要你输入密钥。', recheck:true, sendReason:'还没登录 Codex，请在 Codex 自己的界面登录'});
   break;
  case 'no-permit':
   Object.assign(p, {dot:'wait', label:'这个课题还没有对话许可', note:'这个课题还没有对话许可。许可由本机操作者在页面外准备，写明次数上限和有效期；页面上不能授权。Stage 1 整轮运行的同意书不能代用。', recheck:true, settings:true, body:true, sendReason:'这个课题还没有对话许可'});
   break;
  case 'ready':
   Object.assign(p, {dot:'done', label:'可以发送', body:true, quota:true, canSend:!!st.can_send, sendReason:st.can_send ? '' : '现在还不能发送'});
   break;
  case 'sending': {
   const waiting = turn?.status === 'starting' ? '本轮启动中' : turn?.status === 'stop-requested' ? '正在中断，等回复' : '等待回复';
   Object.assign(p, {dot: ask ? 'wait' : 'run', label: ask ? '等你回答 Codex 的问题' : waiting, body:true, quota:true, sendReason:'本轮进行中'});
   break;
  }
  case 'unknown-result':
   Object.assign(p, {dot:'wait', label:'这一轮的结果还没确认', note:'已预留的额度先保留，等核对完成，不会重发。', body:true, quota:true, sendReason:'先核对上一轮'});
   break;
  case 'other-turn':
   Object.assign(p, {dot:'wait', label:'别处有一轮对话还没结束', note:'这台电脑上同一时间只能有一轮对话。另一轮结束或核对完之前，所有课题、所有阶段都不能发。', body:true, quota:true, recheck:true, sendReason:'别处有一轮对话还没结束'});
   break;
  case 'blocked':
   Object.assign(p, {dot:'wait', label:'被拦下', note:reason || wikiChatFallback, body:true, quota:!!st.model, sendReason:reason || wikiChatFallback});
   break;
  default:
   Object.assign(p, {dot:'wait', label:'对话许可没有通过核对', note:wikiChatFallback, body:true, sendReason:wikiChatFallback});
 }
 if (c.busy && p.canSend) { p.canSend = false; p.sendReason = '本轮进行中'; }
 return p;
}

// ---------- markup ----------
function wikiChatOriginal(value) {
 return value && typeof value === 'object' ? value : {};
}

function wikiChatMaterialRows(state) {
 const rows = Array.isArray(state?.context?.materials) ? state.context.materials : [];
 if (!rows.length) return '<p class="wc-muted">还没有。</p>';
 return `<ul class="wc-materials">${rows.map(m => {
  const readable = wikiChatOriginal(m.readable);
  const version = String(m.version || m.sha256 || '').slice(0, 8);
  return `<li><div class="wc-mat-top"><b>${esc(m.name || '未命名')}</b>${version ? `<span class="wc-ver">版本 ${esc(version)}</span>` : ''}<span class="wc-origin">已登记文件</span><button type="button" class="wc-link" data-wc-original="${esc(m.id || '')}">看原件</button></div><small class="${readable.ok ? 'wc-ok' : 'wc-no'}">${esc(readable.text || (readable.ok ? '能读' : '不能读'))}</small></li>`;
 }).join('')}</ul>`;
}

function wikiChatOutputLine(turn, state) {
 const names = new Map((state?.context?.materials || []).map(m => [m.id, m.name]));
 const seen = [];
 for (const out of turn.outputs || []) {
  const value = wikiChatOriginal(out.value);
  const label = out.action === 'read_material' ? (names.get(value.material_id) || value.name || '一份登记材料') : out.action === 'materials' ? '登记材料清单' : out.action === 'state' ? '课题状态' : '';
  if (label && !seen.includes(label)) seen.push(label);
 }
 return seen.length ? `读取了：${seen.map(esc).join('、')}` : '';
}

function wikiChatTurnMarkup(turn, state, ctl) {
 const notices = (turn.notices || []).map(n => `<p class="wc-grey">${n.kind === 'auto-declined-file-change' ? 'Codex 请求修改文件，已自动拒绝' : 'Codex 请求执行命令，已自动拒绝'}</p>`).join('');
 const truncated = (turn.outputs || []).some(o => o.model_saw_truncated);
 const words = turn.response ? `<div class="wc-bubble wc-bot">${esc(turn.response)}</div>` : '';
 const meta = turn.response || (turn.outputs || []).length ? `<p class="wc-meta">${[wikiChatOutputLine(turn, state), turn.status === 'completed' || turn.status === 'failed' || turn.status === 'interrupted' ? '模型调用 1 次' : ''].filter(Boolean).join(' · ')}${truncated ? `<br>结果较长，Codex 只看到了开头` : ''}</p>` : '';
 const failure = turn.error_reason?.text || '这一轮没有完成，原始错误见技术细节';
 const tag = {
  completed:'<span class="wc-tag ok">本轮已完成</span>',
  failed:`<span class="wc-tag err">本轮失败</span> ${esc(failure)}；已预留的额度保留。`,
  interrupted:'<span class="wc-tag warn">本轮已中断</span> 中断请求已发出，是否真的停了还要核对。',
  unknown:'<span class="wc-tag warn">结果还没确认</span> 已预留的额度先保留，不会重发。',
  starting:'<span class="wc-tag run">本轮启动中</span>', running:'<span class="wc-tag run">等待回复</span>',
  waiting:'<span class="wc-tag run">等你回答</span>', 'stop-requested':'<span class="wc-tag run">正在中断</span>'
 }[turn.status] || '';
 const recon = ctl.reconciled?.[turn.id];
 return `<article class="wc-turn" data-wc-turn="${esc(turn.id)}"><div class="wc-bubble wc-user">${esc(turn.user_text || '')}</div>${words}${notices}${meta}<p class="wc-end">${tag}${recon ? ` <span class="wc-grey">${esc(recon)}</span>` : ''}</p></article>`;
}

function wikiChatAskMarkup(turn, ctl) {
 const pending = turn.pending, ask = pending.kind === 'harness-approval';
 if (ask) return `<section class="wc-ask" data-wc-ask="${esc(turn.id)}"><b>Codex 想用一个工具</b><p>这次对话只能读材料，不能用工具改东西。</p><button type="button" class="wc-btn" data-wc-decline="${esc(turn.id)}">拒绝请求</button></section>`;
 const questions = (pending.questions || []).slice(0, 3).map(q => {
  const id = String(q.id), saved = ctl.answers?.[turn.id + '|' + id] || '';
  return `<label class="wc-q"><span>${esc(q.question || q.header || id)}</span><textarea rows="2" data-wc-ans="${esc(turn.id + '|' + id)}" aria-label="${esc(q.header || q.question || '答复')}">${esc(saved)}</textarea><small class="wc-grey">最多 4096 字节</small></label>`;
 }).join('');
 return `<section class="wc-ask" data-wc-ask="${esc(turn.id)}"><b>Codex 在向你提问</b>${questions}<button type="button" class="wc-btn primary" data-wc-answer="${esc(turn.id)}">提交答复</button></section>`;
}

function wikiChatAskNote(state, p) {
 if (p.key === 'sending') return '这一轮正在运行，现在没有要你回答的。';
 const last = wikiChatTurns(state).slice(-1)[0];
 if (last?.status === 'completed') return '这一轮已完成并保存了回答。';
 if (last?.status === 'failed') return '这一轮失败了，原记录保留。';
 return p.key === 'ready' ? '对话可用，现在没有进行中的提问。' : '对话还不可用。';
}

function wikiChatTechRows(state, ctl) {
 const rows = [];
 if (state?.disabled_reason) rows.push(['配置', state.disabled_reason]);
 for (const code of state?.admission_blockers || []) rows.push(['拦下', code]);
 if (ctl.notice?.code) rows.push(['刚才的请求', ctl.notice.code]);
 for (const t of wikiChatTurns(state)) if (t.error) rows.push(['这一轮', String(t.error)]);
 if (ctl.error) rows.push(['读取', ctl.error]);
 return rows;
}

function wikiChatMarkup(c, p, ctl, state) {
 const title = c.title ? esc(c.title) : '当前课题';
 const subtitle = wikiChatSubtitles[c.stage] || '本阶段还没有开放';
 const settings = p.settings ? '<button type="button" class="wc-btn" data-wc-settings>去连接与设置</button>' : '';
 const recheck = p.recheck ? '<button type="button" class="wc-btn" data-wc-recheck>重新检查</button>' : '';
 const other = state?.other_turn;
 const where = p.key === 'other-turn' && other ? `<p class="wc-note">那一轮在「${esc(c.otherTitle || other.project_ref || '另一个课题')}」的 Stage ${esc(other.stage)}，${esc(wikiChatTime(other.created_at) || '时间未提供')} 发的。</p><button type="button" class="wc-btn" data-wc-other>去那一轮看看</button>` : '';
 const notice = ctl.notice ? `<div class="wc-alert ${ctl.notice.tone}" role="alert">${esc(ctl.notice.text)}${ctl.notice.code ? ' <button type="button" class="wc-link" data-wc-tech>看原始拒绝记录</button>' : ''}</div>` : '';
 let quota = '';
 if (p.quota && state) {
  const max = Number(state.max_turns) || 0, used = Number(state.reserved_turns) || 0;
  const until = wikiChatTime(state.expires_at);
  quota = `<div class="wc-quota"><div class="wc-bar" aria-hidden="true"><i style="width:${max ? Math.min(100, Math.round(used / max * 100)) : 0}%"></i></div><p>已预留 ${used} 轮，每轮最多 ${Number(state.turn_seconds) || 0} 秒 · 剩余 ${Number(state.remaining_turns) || 0} 轮${until ? ` · 有效到 ${esc(until)}` : ''}</p></div>`;
 }
 let materials = '';
 const expected = (state?.context?.expected_materials || []).map(m => m.category);
 if (p.key === 'stage-unconnected' && c.stage <= 3) {
  materials = `<div class="wc-expect"><b>接通后会读的材料</b><ul>${(expected.length ? expected : ({1:['来源包', '原文定位'], 2:['候选', '已保存的真人选择'], 3:['所选方向的计划', '流程图', '对应评审']})[c.stage]).map(n => `<li>${esc(n)}</li>`).join('')}</ul></div>`;
 } else if (p.body) {
  const count = (state?.context?.materials || []).length;
  materials = `<details class="wc-fold" data-wc-fold="materials" ${ctl.materialsOpen ? 'open' : ''}><summary>本阶段文件 · ${count} 份登记材料</summary>${p.stale ? '<p class="wc-grey">上次读取</p>' : ''}${wikiChatMaterialRows(state)}</details>`;
 } else if (p.key === 'reading') materials = '<p class="wc-muted">材料状态待读取</p>';
 const turns = p.body ? wikiChatTurns(state) : [];
 const ask = wikiChatPendingCard(state);
 let messages = '';
 if (p.body) {
  messages = `<div class="wc-messages" data-wc-messages tabindex="0" aria-label="对话记录">${state?.hidden_turn_count > 0 ? '<p class="wc-grey">更早的对话没有显示</p>' : ''}${turns.length ? turns.map(t => wikiChatTurnMarkup(t, state, ctl)).join('') : '<p class="wc-muted">这个课题在这一段还没有对话。先读取会话，再问和当前材料有关的问题。</p>'}${ask ? wikiChatAskMarkup(ask, ctl) : ''}${!ask && turns.length ? `<p class="wc-grey wc-ask-note">${esc(wikiChatAskNote(state, p))}</p>` : ''}</div>`;
 }
 const chips = c.stage > 3 ? '<p class="wc-muted">本阶段还没有开放</p>' : p.body ? `<div class="wc-chips" aria-label="快捷提问">${(wikiChatQuick[c.stage] || []).map((q, i) => `<button type="button" class="wc-chip" data-wc-chip="${i}">${esc(q)}</button>`).join('')}<small class="wc-grey">点击只填入，确认后再发送</small></div>` : '';
 const composer = c.stage > 3 || p.key === 'archive' ? '' : `<div class="wc-compose"><textarea rows="3" data-wc-input placeholder="发送给本阶段 Codex 的消息" aria-label="发送给本阶段 Codex 的消息"></textarea><div class="wc-send-row"><button type="button" class="wc-btn primary" data-wc-send>发送给 Codex</button><button type="button" class="wc-btn" data-wc-stop hidden>中断本轮 Codex</button></div><small class="v1-reason wc-reason" data-wc-reason></small><small class="wc-grey" data-wc-stop-note hidden>只停这一次对话，不代表整个研究停了；选方向和进入下一段仍要 Harness 放行。</small><small class="wc-grey">问答不能代替选方向、批准计划或启动研究。</small></div>`;
 const secondary = p.key === 'archive' || c.stage > 3 ? '' : `<div class="wc-actions"><button type="button" class="wc-btn" data-wc-refresh>读取会话／进度</button><button type="button" class="wc-btn" data-wc-new>新对话（保留历史）</button><button type="button" class="wc-btn" data-wc-reconcile hidden>只读核对原任务</button></div><small class="v1-reason wc-reason" data-wc-new-reason></small><small class="wc-grey" data-wc-new-note ${ctl.forceNew ? '' : 'hidden'}>下一条消息会开启新对话，历史保留。</small><small class="v1-reason wc-reason" data-wc-reconcile-reason></small>`;
 const tools = state ? (state.context?.supported_actions || ['state', 'materials', 'read_material']) : [];
 const toolFold = `<details class="wc-fold"><summary>本阶段的 Harness 工具声明</summary><p class="wc-grey">V1 的对话只读。列出的工具只代表声明，不代表已连接；任何会写入的操作（登记交付、保存评审）都不在对话里做。</p>${tools.length ? `<ul>${tools.map(t => `<li>${esc(wikiChatToolNames[t] || '只读工具')}</li>`).join('')}</ul>` : ''}</details>`;
 const rows = wikiChatTechRows(state, ctl);
 const tech = `<details class="wc-fold wc-tech" data-wc-techfold ${rows.length && ctl.techOpen ? 'open' : ''}><summary>技术细节</summary>${rows.length ? `<table>${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td><code class="${ctl.notice?.code === v ? 'wc-mark' : ''}">${esc(v)}</code></td></tr>`).join('')}</table>` : '<p class="wc-grey">没有原始记录。</p>'}</details>`;
 return `<aside class="wc-drawer" data-wc-drawer data-wc-state="${p.key}" aria-label="Codex 对话" ${ctl.open ? '' : 'hidden'}>
  <header class="wc-head"><div><h2>${esc(wikiChatAssistants[c.stage])}</h2><p class="wc-where">${title} · Stage ${c.stage}</p><p class="wc-sub">${esc(subtitle)}</p></div><button type="button" class="wc-btn sm" data-wc-close>收起</button></header>
  <div class="wc-state" role="status"><i class="wc-dot ${p.dot}"></i><b>${esc(p.label)}</b></div>
  ${p.note ? `<p class="wc-note">${esc(p.note)}</p>` : ''}${where}${recheck || settings ? `<div class="wc-actions">${recheck}${settings}</div>` : ''}${notice}${quota}
  <div class="wc-scroll" data-wc-scroll>${materials}${messages}${chips}${toolFold}${tech}</div>
  <div class="wc-foot">${composer}${secondary}</div>
 </aside>`;
}

function wikiChatTabMarkup(c, p, ctl) {
 const off = p.key === 'not-configured';
 const sub = off ? '对话未启用' : p.key === 'ready' ? '可发送' : p.key === 'archive' || p.key === 'stage-unconnected' ? '未接通' : p.key === 'reading' ? '读取中' : '';
 const title = off ? '对话未启用：' + (c.state?.panel_reason?.text || '本机还没有配置对话') : p.label;
 return `<button type="button" class="wc-tab" data-wc-open aria-expanded="${ctl.open ? 'true' : 'false'}" title="${esc(title)}" ${ctl.open ? 'hidden' : ''}><i class="wc-dot ${p.dot}"></i><span>Codex 对话</span>${sub ? `<small>${sub}</small>` : ''}</button>`;
}

// ---------- state and requests ----------
function wikiChatCtl(app) {
 return app.wikiChat || (app.wikiChat = {key:'', open:false, state:null, phase:'idle', notice:null, answers:{}, drafts:{}, focus:false, pollTimer:0, forceNew:false, sending:false, reconciled:{}, techOpen:false, materialsOpen:true, error:''});
}

function wikiChatStore(name, value) {
 try { if (value === undefined) return localStorage.getItem(name); localStorage.setItem(name, value); } catch (_) { /* Remembering open/closed is optional. */ }
 return null;
}

function wikiChatCurrent(app) {
 const origin = typeof v1CurrentRow === 'function' ? v1CurrentRow()?.origin : '';
 const other = state => state?.other_turn && Array.isArray(rt.list) ? rt.list.find(item => item.project_ref === state.other_turn.project_ref) : null;
 const ctl = wikiChatCtl(app);
 const otherRow = other(ctl.state);
 return {stage:app.stage, ref:rt.ref, archive:origin === 'archive' || origin === 'synthetic' || String(rt.ref || '').startsWith('view:'), title:typeof v1ProjectTitle === 'function' ? v1ProjectTitle() : '',
  otherTitle:otherRow && typeof wikiHomeRow === 'function' ? wikiHomeRow(otherRow).title : ''};
}

function wikiChatHeaders(json) {
 const headers = {Authorization:'Bearer ' + window.RESEARCH_PROJECTS.credential};
 if (json) headers['Content-Type'] = 'application/json';
 return headers;
}

async function wikiChatLoad(app, force) {
 const ctl = wikiChatCtl(app), here = wikiChatCurrent(app);
 if (!here.ref || here.archive || here.stage > 3 || ctl.loading) return;
 const key = here.ref + '|' + here.stage;
 ctl.loading = true;
 if (!ctl.state || force === 'visible') { ctl.phase = 'loading'; wikiChatPaint(app); }
 let state = null, error = '';
 try {
  const response = await fetch('/api/v9/chat/state?project=' + encodeURIComponent(here.ref) + '&stage=' + here.stage, {headers:wikiChatHeaders(false), cache:'no-store', credentials:'same-origin'});
  const value = await response.json().catch(() => ({}));
  if (response.ok && value.kind === 'V9HarnessConversation') state = value;
  else error = value.error || 'HTTP ' + response.status;
 } catch (exception) { error = String(exception.message || exception); }
 ctl.loading = false;
 if (key !== ctl.key) return;
 if (state) { ctl.state = state; ctl.phase = 'ready'; ctl.error = ''; } else { ctl.phase = 'error'; ctl.error = error; }
 wikiChatPaint(app);
 clearTimeout(ctl.pollTimer);
 if (state && wikiChatWorkingTurn(state) && !wikiChatPendingCard(state)) ctl.pollTimer = setTimeout(() => wikiChatLoad(app), 2000);
}

async function wikiChatPost(route, body) {
 const response = await fetch('/api/v9/chat/' + route, {method:'POST', headers:wikiChatHeaders(true), cache:'no-store', credentials:'same-origin', body:JSON.stringify(body)});
 const value = await response.json().catch(() => ({}));
 if (response.ok) return value;
 let text;
 if (value.reason?.text) text = value.reason.text;
 else if ([401, 403].includes(response.status)) text = '页面的登录信息失效了，请从 Wiki 首页重新打开';
 else text = '这次没有成功，请重新读取后再试';
 const error = new Error(text);
 error.code = value.error || 'HTTP ' + response.status;
 error.definite = true;
 throw error;
}

function wikiChatFail(app, exception, unknownText) {
 const ctl = wikiChatCtl(app);
 if (exception.definite) ctl.notice = {tone:'warn', text:exception.message, code:exception.code};
 else ctl.notice = {tone:'warn', text:unknownText, code:''};
 return !!exception.definite;
}

async function wikiChatSend(app) {
 const ctl = wikiChatCtl(app), here = wikiChatCurrent(app), project = rt.overview?.project;
 const draft = ctl.drafts[ctl.key] || '';
 if (ctl.sending || wikiChatDraftReason(draft) || !project || project.project_ref !== rt.ref || !Number.isInteger(project.input_version) || !project.brief_sha256) return;
 const session = ctl.forceNew ? '' : (ctl.state?.sessions || []).slice(-1)[0]?.id || '';
 // The same words keep the same key, so a repeated click replays the saved turn instead of a new one.
 if (!ctl.pendingSend || ctl.pendingSend.text !== draft) ctl.pendingSend = {text:draft, key:'wc-' + (crypto.randomUUID ? crypto.randomUUID().replaceAll('-', '') : Math.random().toString(16).slice(2).padEnd(24, '0'))};
 ctl.sending = true; ctl.notice = null; wikiChatPaint(app);
 try {
  const turn = await wikiChatPost('send', {project_ref:here.ref, stage:here.stage, text:draft, key:ctl.pendingSend.key, session_id:session, input_version:project.input_version, brief_sha256:project.brief_sha256});
  ctl.pendingSend = null; ctl.drafts[ctl.key] = ''; ctl.forceNew = false;
  if (ctl.state) { ctl.state.turns = [...wikiChatTurns(ctl.state).filter(t => t.id !== turn.id), turn]; ctl.state.panel_state = 'sending'; }
 } catch (exception) {
  if (wikiChatFail(app, exception, '这条消息的结果还没确认，不会自动重发。再点「发送给 Codex」只会重送同一条（编号和内容不变）。')) {
   ctl.pendingSend = null;
   if (/session-content-cleared|project-changed/.test(exception.code)) { ctl.forceNew = true; ctl.notice.text = '对话记录已清空（或课题已变），请开新对话'; }
  }
 }
 ctl.sending = false;
 wikiChatPaint(app);
 wikiChatLoad(app);
}

async function wikiChatAnswer(app, turnId) {
 const ctl = wikiChatCtl(app), turn = wikiChatTurns(ctl.state).find(t => t.id === turnId), pending = turn?.pending;
 if (!pending || ctl.sending) return;
 const value = {};
 for (const q of pending.questions || []) {
  const text = String(ctl.answers[turnId + '|' + q.id] || '').trim();
  if (!text || wikiChatBytes(text) > wikiChatAnswerBytes) { ctl.notice = {tone:'warn', text:'每个问题都要回答，每个答复最多 4096 字节', code:''}; wikiChatPaint(app); return; }
  value[q.id] = text;
 }
 ctl.sending = true; ctl.notice = null; wikiChatPaint(app);
 try { await wikiChatPost('answer', {turn_id:turnId, request_id:pending.id, request_sha256:pending.sha256, value}); }
 catch (exception) { wikiChatFail(app, exception, '答复 Codex 的结果还没确认，不会自动重发。'); }
 ctl.sending = false; wikiChatPaint(app); wikiChatLoad(app, true);
}

async function wikiChatDecline(app, turnId) {
 const ctl = wikiChatCtl(app), pending = wikiChatTurns(ctl.state).find(t => t.id === turnId)?.pending;
 if (!pending || ctl.sending) return;
 ctl.sending = true; wikiChatPaint(app);
 try { await wikiChatPost('answer', {turn_id:turnId, request_id:pending.id, request_sha256:pending.sha256, value:false}); }
 catch (exception) { wikiChatFail(app, exception, '拒绝请求的结果还没确认，不会自动重发。'); }
 ctl.sending = false; wikiChatPaint(app); wikiChatLoad(app, true);
}

async function wikiChatSimple(app, route, turnId, done) {
 const ctl = wikiChatCtl(app);
 if (ctl.sending || !turnId) return;
 ctl.sending = true; ctl.notice = null; wikiChatPaint(app);
 try { done(await wikiChatPost(route, {turn_id:turnId})); }
 catch (exception) {
  if (route === 'reconcile' && /native-turn-not-returned/.test(exception.code || '')) ctl.reconciled[turnId] = '找不到那一轮的记录。保留原记录，不会重发；要继续请开新对话。';
  else wikiChatFail(app, exception, route === 'stop' ? '中断请求的结果还没确认，不会自动重发。' : '核对没有成功，原提交仍未确认。');
 }
 ctl.sending = false; wikiChatPaint(app); wikiChatLoad(app, true);
}

// ---------- gray-button reasons that depend on the saved turns ----------
function wikiChatControls(ctl, p) {
 const state = ctl.state, turn = wikiChatWorkingTurn(state), unknown = wikiChatTurns(state).find(t => t.status === 'unknown');
 const controllable = new Set(state?.controllable_turn_ids || []);
 const target = unknown || (turn && !controllable.has(turn.id) ? turn : null);
 const out = {stopTurn:turn, reconcileTurn:target, stopReason:'', reconcileReason:'', newReason:''};
 if (turn && !controllable.has(turn.id)) out.stopReason = '服务重启过，这一轮只能核对';
 if (target && state?.budget_identity_preserved) out.reconcileReason = '这份许可下不能核对，请联系操作者';
 const sessions = state?.sessions || [];
 if (p.key !== 'ready') out.newReason = p.sendReason || '现在还不能开新对话';
 else if (!sessions.length) out.newReason = '还没有对话，直接发送就会开始';
 else if (ctl.sending) out.newReason = '本轮进行中';
 return out;
}

// Update everything that depends on the text box without rebuilding the drawer.
function wikiChatSync(app) {
 const ctl = wikiChatCtl(app), root = ctl.root;
 if (!root || !ctl.panel) return;
 const p = ctl.panel, c = wikiChatControls(ctl, p), draft = ctl.drafts[ctl.key] || '';
 const input = root.querySelector('[data-wc-input]'), send = root.querySelector('[data-wc-send]');
 if (input) { input.disabled = p.key === 'sending' || ctl.sending || !p.body; if (input.value !== draft) input.value = draft; }
 if (send) {
  const why = !p.canSend ? p.sendReason : ctl.sending ? '本轮进行中' : wikiChatDraftReason(draft);
  const bad = !p.canSend || ctl.sending || !!wikiChatDraftReason(draft) || !rt.overview?.project || rt.overview.project.project_ref !== rt.ref;
  send.disabled = bad;
  const reason = !bad ? '' : why || '课题还在读取，读完才能发送';
  const line = root.querySelector('[data-wc-reason]');
  if (line) { line.textContent = reason; line.hidden = !reason; }
 }
 const stop = root.querySelector('[data-wc-stop]'), stopNote = root.querySelector('[data-wc-stop-note]');
 if (stop) {
  stop.hidden = p.key !== 'sending'; stop.disabled = !!c.stopReason || ctl.sending;
  if (stopNote) { stopNote.hidden = p.key !== 'sending'; stopNote.textContent = c.stopReason || '只停这一次对话，不代表整个研究停了；选方向和进入下一段仍要 Harness 放行。'; }
 }
 const rec = root.querySelector('[data-wc-reconcile]'), recWhy = root.querySelector('[data-wc-reconcile-reason]');
 if (rec) { rec.hidden = !c.reconcileTurn; rec.disabled = !!c.reconcileReason || ctl.sending; }
 if (recWhy) { recWhy.textContent = c.reconcileTurn ? c.reconcileReason : ''; recWhy.hidden = !(c.reconcileTurn && c.reconcileReason); }
 const fresh = root.querySelector('[data-wc-new]'), freshWhy = root.querySelector('[data-wc-new-reason]');
 if (fresh) fresh.disabled = !!c.newReason || ctl.sending;
 if (freshWhy) { freshWhy.textContent = c.newReason; freshWhy.hidden = !c.newReason; }
}

function wikiChatPaint(app) {
 const ctl = wikiChatCtl(app), here = wikiChatCurrent(app);
 if (!ctl.root) { ctl.root = document.createElement('div'); ctl.root.className = 'wc-root'; ctl.root.dataset.wcRoot = ''; }
 const c = Object.assign({}, here, {phase:ctl.phase, state:ctl.state, busy:ctl.sending});
 const p = wikiChatPanel(c);
 ctl.panel = p;
 const markup = wikiChatTabMarkup(c, p, ctl) + wikiChatMarkup(c, p, ctl, ctl.state);
 const keep = ctl.root.querySelector('[data-wc-scroll]');
 const scroll = keep ? keep.scrollTop : 0, atEnd = keep ? keep.scrollHeight - keep.scrollTop - keep.clientHeight < 40 : true;
 if (ctl.root.v1Markup !== markup) {
  ctl.root.innerHTML = markup;
  ctl.root.v1Markup = markup;
  for (const area of ctl.root.querySelectorAll('[data-wc-ans]')) area.value = ctl.answers[area.dataset.wcAns] || '';
  const list = ctl.root.querySelector('[data-wc-scroll]');
  if (list) list.scrollTop = atEnd && ctl.stickBottom !== false ? list.scrollHeight : scroll;
 }
 wikiChatSync(app);
 if (ctl.focus && ctl.open) {
  const input = ctl.root.querySelector('[data-wc-input]');
  if (input && document.activeElement !== input && !input.disabled) input.focus({preventScroll:true});
 }
}

function wikiChatMount(app) {
 if (typeof v1Page !== 'function') return;
 const page = v1Page(app), ctl = wikiChatCtl(app);
 if (!['s1', 's2', 's3', 'later'].includes(page) || !rt.ref) {
  if (ctl.root?.isConnected) ctl.root.remove();
  return;
 }
 const key = rt.ref + '|' + app.stage;
 if (key !== ctl.key) {
  clearTimeout(ctl.pollTimer);
  Object.assign(ctl, {key, state:null, phase:'idle', notice:null, error:'', forceNew:false, sending:false, loading:false, pendingSend:null, techOpen:false});
  ctl.open = wikiChatStore('wikiChat.open.' + key) === '1';
 }
 wikiChatPaint(app);
 if (!ctl.root.isConnected || ctl.root.parentNode !== app.el) app.el.append(ctl.root);
 if (ctl.phase === 'idle') { ctl.phase = 'loading'; wikiChatPaint(app); wikiChatLoad(app); }
 else if (ctl.focus && ctl.open) wikiChatPaint(app);
}

const wikiChatPreviousAfter = v7AfterRender;
v7AfterRender = function(app) {
 wikiChatPreviousAfter(app);
 try { wikiChatMount(app); } catch (error) { /* The drawer never blocks a page. */ }
};

function wikiChatOpen(app, open) {
 const ctl = wikiChatCtl(app);
 ctl.open = open;
 wikiChatStore('wikiChat.open.' + ctl.key, open ? '1' : '0');
 ctl.root.v1Markup = '';
 wikiChatPaint(app);
 if (open) { ctl.root.querySelector('[data-wc-close]')?.focus({preventScroll:true}); wikiChatLoad(app, 'visible'); }
 else { ctl.focus = false; ctl.root.querySelector('[data-wc-open]')?.focus({preventScroll:true}); }
}

document.addEventListener('click', event => {
 const app = apps[0], ctl = app && app.wikiChat;
 if (!ctl?.root || !ctl.root.contains(event.target)) return;
 const hit = selector => event.target.closest?.(selector);
 const button = event.target.closest?.('button');
 if (!button || button.disabled) return;
 if (hit('[data-wc-open]')) wikiChatOpen(app, true);
 else if (hit('[data-wc-close]')) wikiChatOpen(app, false);
 else if (hit('[data-wc-recheck]') || hit('[data-wc-refresh]')) { ctl.notice = null; wikiChatLoad(app, 'visible'); }
 else if (hit('[data-wc-settings]')) { wikiChatOpen(app, false); app.el.querySelector('.v1-nav-item[data-page="settings"]')?.click(); }
 else if (hit('[data-wc-chip]')) { ctl.drafts[ctl.key] = (wikiChatQuick[app.stage] || [])[Number(button.dataset.wcChip)] || ''; ctl.focus = true; wikiChatSync(app); ctl.root.querySelector('[data-wc-input]')?.focus(); }
 else if (hit('[data-wc-send]')) wikiChatSend(app);
 else if (hit('[data-wc-answer]')) wikiChatAnswer(app, button.dataset.wcAnswer);
 else if (hit('[data-wc-decline]')) wikiChatDecline(app, button.dataset.wcDecline);
 else if (hit('[data-wc-stop]')) { const turn = wikiChatWorkingTurn(ctl.state); wikiChatSimple(app, 'stop', turn?.id, () => {}); }
 else if (hit('[data-wc-reconcile]')) {
  const target = wikiChatControls(ctl, ctl.panel).reconcileTurn;
  wikiChatSimple(app, 'reconcile', target?.id, value => {
   if (value.reconciliation === 'native-terminal-not-observed') ctl.reconciled[value.id] = '还没结束，过一会儿再核对。';
   else delete ctl.reconciled[value.id];
  });
 }
 else if (hit('[data-wc-new]')) { ctl.forceNew = true; ctl.notice = null; ctl.root.v1Markup = ''; wikiChatPaint(app); }
 else if (hit('[data-wc-tech]')) { ctl.techOpen = true; ctl.root.v1Markup = ''; wikiChatPaint(app); ctl.root.querySelector('[data-wc-techfold]')?.scrollIntoView({block:'nearest'}); }
 else if (hit('[data-wc-original]')) {
  // The chat backend gives no page locator for a file yet, so go to the saved-materials list.
  const catalog = app.el.querySelector('[data-n9-catalog], .n9-materials');
  if (catalog) { const fold = catalog.closest('details'); if (fold) fold.open = true; catalog.scrollIntoView({behavior:'smooth', block:'center'}); }
  else app.el.querySelector('.v1-nav-item[data-page="files"]')?.click();
  wikiChatOpen(app, false);
 }
 else if (hit('[data-wc-other]')) {
  const other = ctl.state?.other_turn;
  if (other?.project_ref === rt.ref) app.el.querySelector(`.v1-flow-item[data-stage="${other.stage}"]`)?.click();
  else if (other && typeof wikiHomeOpen === 'function') { app.page = 'home'; wikiHomeOpen(other.project_ref); }
  wikiChatOpen(app, false);
 }
}, true);

document.addEventListener('input', event => {
 const app = apps[0], ctl = app && app.wikiChat;
 if (!ctl?.root || !ctl.root.contains(event.target)) return;
 if (event.target.matches('[data-wc-input]')) { ctl.drafts[ctl.key] = event.target.value; wikiChatSync(app); }
 else if (event.target.matches('[data-wc-ans]')) ctl.answers[event.target.dataset.wcAns] = event.target.value;
}, true);

document.addEventListener('focusin', event => {
 const ctl = apps[0]?.wikiChat;
 if (ctl?.root?.contains(event.target)) ctl.focus = event.target.matches('[data-wc-input]');
}, true);

document.addEventListener('keydown', event => {
 const app = apps[0], ctl = app && app.wikiChat;
 if (!ctl?.root?.contains(event.target)) return;
 if (event.key === 'Escape' && ctl.open) { event.preventDefault(); wikiChatOpen(app, false); }
 else if (event.key === 'Tab') ctl.focus = false;
}, true);

document.addEventListener('toggle', event => {
 const ctl = apps[0]?.wikiChat;
 if (!ctl?.root?.contains(event.target) || !event.target.isConnected) return;
 if (event.target.matches('[data-wc-fold="materials"]')) ctl.materialsOpen = event.target.open;
 else if (event.target.matches('[data-wc-techfold]')) ctl.techOpen = event.target.open;
}, true);
