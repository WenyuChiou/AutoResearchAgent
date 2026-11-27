// Wiki V1 unified shell (DESIGN 2.1, 2.5, 8.1, 8.20). Display only: it reads the
// state other modules already loaded and never sends a request of its own.
// Simplified Chinese gets the new design everywhere; English and Traditional
// Chinese keep the previous pages unchanged so no page is half new, half old.
const v1StageNames = ['文献与证据', '比较与选方向', '研究计划与评审'];
const v1LaterNames = {4:'实验执行', 5:'分析与图表', 6:'写作与投稿'};
const v1OriginNames = {local:'本地项目', archive:'历史归档', synthetic:'合成样例', unknown:'来历未标注'};

function v1On(app) {
 return !!app && app.lang === 'zh' && typeof wikiHomeProjectOpened === 'function';
}

function v1Page(app) {
 if (!v1On(app)) return '';
 if (app.page === 'home') return 'home';
 if (app.page !== 'workspace') return 'other';
 return app.stage <= 3 ? 's' + app.stage : 'later';
}

function v1CurrentRow() {
 const project = rt.list.find(item => item.project_ref === rt.ref);
 return project && typeof wikiHomeRow === 'function' ? wikiHomeRow(project) : null;
}

function v1ProjectTitle() {
 return rt.overview?.project?.project_ref === rt.ref && rt.overview.project.brief?.original_description ||
  rt.savedRun?.entry?.project_ref === rt.ref && rt.savedRun.entry.label || v1CurrentRow()?.title || '';
}

// Each stage module may register a function returning [text, tone] for the sidebar.
const v1StageStatus = {};
v1StageStatus[1] = () => {
 const row = v1CurrentRow();
 if (!row) return ['未打开课题', ''];
 if (typeof wikiS1Index === 'function' && wikiS1Index()) return ['已保存', 'done'];
 const p = rt.overview?.project;
 if (p?.project_ref === rt.ref && !p.intake_report?.necessary_clarification_complete) return ['等你确认范围', 'wait'];
 if (p?.project_ref === rt.ref) return ['还没有交付', ''];
 return row.stage ? ['已保存', 'done'] : ['未提供', ''];
};

function v1StageLine(stage) {
 try {
  const value = v1StageStatus[stage]?.();
  if (Array.isArray(value) && value[0]) return value;
 } catch (_) { /* A status line never blocks the shell. */ }
 return ['还没开始', ''];
}

const v1PreviousSidebar = sidebar;
sidebar = function(app) {
 if (!v1On(app)) return v1PreviousSidebar(app);
 const page = v1Page(app);
 const locked = rt.busy || rt.loading || !!rt.pending;
 const home = page === 'home';
 const recent = home && typeof wikiHomeResume === 'function' ? wikiHomeResume(rt.list.map(wikiHomeRow)) : null;
 const opened = !!rt.ref && !home;
 const nav = (id, label) => `<button type="button" class="v1-nav-item" data-page="${id}" aria-current="${(id === 'workspace' ? ['home', 's1', 's2', 's3', 'later'].includes(page) : app.page === id) ? 'page' : 'false'}">${label}</button>`;
 const flow = [1, 2, 3].map(stage => {
  const [line, tone] = home ? (recent && stage <= (recent.stage || 0) ? ['有记录', 'done'] : ['还没开始', '']) : opened ? v1StageLine(stage) : ['未打开课题', ''];
  const disabled = home ? (locked || !recent || stage > (recent.stage || 0)) : (!opened || locked);
  // A greyed item says why in its status line (review P2-10).
  const why = !disabled ? null : locked ? '上次提交还没确认' : home && !recent ? '先新建或打开课题' : home ? '这个课题还没到这一段' : '先打开一个课题';
  const [shownLine, shownTone] = why ? [why, ''] : [line, tone];
  return `<button type="button" class="v1-flow-item" data-stage="${stage}" aria-current="${page === 's' + stage ? 'page' : 'false'}" ${disabled ? 'disabled' : ''}><span class="v1-flow-num">${stage}</span><span class="v1-flow-body"><b>${v1StageNames[stage - 1]}</b><small><i class="v1-dot ${shownTone}"></i>${shownLine}</small></span></button>`;
 }).join('');
 const later = [4, 5, 6].map(stage => `<button type="button" class="v1-later-item" data-stage="${stage}" aria-current="${page === 'later' && app.stage === stage ? 'page' : 'false'}" ${!opened || locked ? 'disabled' : ''}>${stage} ${v1LaterNames[stage]}</button>`).join('') + (!opened || locked ? `<small class="v1-later-why">${locked ? '上次提交还没确认' : '先打开一个课题'}</small>` : '');
 return `<aside class="hs-sidebar v1-side" id="v1-side" ${app.v1MenuOpen ? 'data-open' : ''}>
  <div class="hs-brand v1-brand"><span class="hs-logo">h</span><div><strong>Wiki V1</strong><small>RESEARCH WIKI</small></div></div>
  <button type="button" class="v1-menu-btn" data-v1-menu aria-controls="v1-side" aria-expanded="${app.v1MenuOpen ? 'true' : 'false'}">菜单</button>
  <nav class="v1-nav" aria-label="全局">${nav('workspace', '工作台')}${nav('files', '项目文件')}${nav('history', '操作历史')}${nav('settings', '连接与设置')}</nav>
  <div class="v1-side-label">研究流程</div>
  <nav class="v1-flow" aria-label="研究流程">${flow}</nav>
  <details class="v1-later" ${page === 'later' || app.v1LaterOpen ? 'open' : ''} data-v1-later><summary>后续阶段（未开放）</summary><div>${later}</div></details>
  <p class="v1-foot">你只需要点三处：确认范围和授权、选方向、对评审做决定。</p>
 </aside>`;
};

function v1Crumb(app, page) {
 if (page === 'home') return '<b>工作台</b>';
 const stageName = page === 'later' ? `Stage ${app.stage} ${v1LaterNames[app.stage]}` :
  page === 'other' ? ({files:'项目文件', history:'操作历史', settings:'连接与设置'})[app.page] || '' :
  `Stage ${app.stage} ${v1StageNames[app.stage - 1]}${page === 's1' && v1ScopePending() ? ' · 确认范围' : ''}`;
 const title = v1ProjectTitle();
 return `${title ? `<details class="v1-switch" data-v1-switch ${app.v1SwitchOpen && app.v1SwitchRef === rt.ref ? 'open' : ''}><summary>${esc(title)}</summary>${v1SwitchMenu()}</details><span aria-hidden="true">›</span>` : ''}<b>${esc(stageName)}</b>`;
}

function v1SwitchMenu() {
 if (rt.loading && !rt.list.length) return '<div class="v1-menu"><p class="v1-muted">正在读取项目</p></div>';
 if (rt.error && !rt.list.length) return '<div class="v1-menu"><p>项目读取失败</p><button type="button" class="v1-btn sm" data-v1-reload>重新读取</button></div>';
 if (!rt.list.length) return '<div class="v1-menu"><p>还没有项目</p><button type="button" class="v1-link" data-v1-home>去首页新建</button></div>';
 const locked = rt.busy || rt.loading || !!rt.pending;
 const rows = rt.list.map(wikiHomeRow).slice(-8).reverse();
 return `<div class="v1-menu">${locked ? '<p class="v1-reason">上次提交的结果还没确认，先核对</p>' : ''}<ul>${rows.map(row => `<li><button type="button" data-v1-open="${esc(row.ref)}" ${locked || row.ref === rt.ref ? 'disabled' : ''}><span class="v1-origin ${row.origin}">${v1OriginNames[row.origin]}</span><span>${esc(row.title)}</span><small>${row.stage ? 'Stage ' + row.stage : '未提供'}</small></button></li>`).join('')}</ul><button type="button" class="v1-link" data-v1-home>全部项目…</button></div>`;
}

function v1ScopePending() {
 const p = rt.overview?.project;
 return !!p && p.project_ref === rt.ref && !p.intake_report?.necessary_clarification_complete;
}

function v1Topbar(app, page) {
 const row = page !== 'home' && rt.ref ? v1CurrentRow() : null;
 const origin = row ? `<span class="v1-origin ${row.origin}">${v1OriginNames[row.origin]}</span>` : '';
 const models = rt.meta?.model;
 const conn = rt.error && !rt.meta ? ['err', '连接：读取失败'] : models === 'unconnected' || !rt.meta ? ['wait', '连接：Codex 未接通'] : ['done', '连接：正常'];
 return `<div class="v1-crumb">${v1Crumb(app, page)}</div><div class="v1-top-right">${origin}<button type="button" class="v1-conn" data-page="settings" title="连接状态，点开看连接与设置"><i class="v1-dot ${conn[0]}"></i>${conn[1]}</button></div>`;
}

const v1PreviousRender = render;
render = function(app) {
 v1PreviousRender(app);
 const page = v1Page(app);
 if (!page) {
  if (app.el.dataset.v1) delete app.el.dataset.v1;
  return;
 }
 app.el.dataset.v1 = page;
 const top = app.el.querySelector('.hs-topbar');
 if (top) {
  const language = top.querySelector('[data-language]');
  top.innerHTML = v1Topbar(app, page);
  if (language) { language.className = 'v1-lang'; top.querySelector('.v1-top-right').append(language); }
 }
 const footer = app.el.querySelector('.hs-footer');
 if (footer) footer.hidden = true;
 if (page === 'later') v1LaterPage(app);
 v1AlertMount(app);
};

// DESIGN 2.5 / 8.3 alert bar under the page title. One at a time; it belongs to the page it was raised on.
function v1PlaceKey(app) { return [app.page, app.stage, rt.ref].join('|'); }
function v1Notice(text, recover) {
 const app = apps[0];
 app.v1Alert = {key:v1PlaceKey(app), tone:'warn', title:text, sub:'', buttons:recover ? [['核对上次提交', 'data-v1-recover']] : []};
 livePaint();
}
function v1AlertMount(app) {
 const content = app.el.querySelector('.hs-content');
 const a = app.v1Alert;
 if (!content || !a) return;
 if (a.key !== v1PlaceKey(app)) { app.v1Alert = null; return; }
 const html = `<div class="v1-alert ${a.tone}" role="${a.tone === 'err' ? 'alert' : 'status'}" data-v1-alert><div><b>${esc(a.title)}</b>${a.sub ? `<span>${esc(a.sub)}</span>` : ''}</div><div class="v1-alert-actions">${a.buttons.map(([label, attrs], i) => `<button type="button" class="v1-btn sm ${i === 0 && a.primary ? 'primary' : ''}" ${attrs}>${esc(label)}</button>`).join('')}<button type="button" class="v1-link" data-v1-alert-close>关掉提示</button></div></div>`;
 const heading = content.querySelector(':scope > .hs-heading, :scope > .v1-head, :scope > [data-v1-later-page] > .v1-head, :scope > [data-v1-global] > .v1-head');
 if (heading) heading.insertAdjacentHTML('afterend', html); else content.insertAdjacentHTML('afterbegin', html);
}

// Things typed on this page that would be lost by leaving the topic (runtime clears them on a topic change).
function v1UnsavedDrafts() {
 const names = [];
 const p = rt.overview?.project;
 if (rt.scopeDraft && typeof liveScopeBasis === 'function' && rt.scopeDraft.basis === liveScopeBasis()) {
  const v = rt.scopeDraft.values || {}, blank = {geography:'', geographyValue:'', target:'30', priority:'20', note:''};
  if (Object.keys(blank).some(key => String(v[key] ?? blank[key]) !== blank[key])) names.push('研究范围表单');
 }
 if (typeof realPlanDraftCurrent === 'function' && realPlanDraftCurrent()) names.push('检索规划修订');
 if (typeof rt.draft === 'string' && rt.draft.trim()) names.push('审阅意见');
 if (rt.followupDraft?.ref === rt.ref && p && rt.followupDraft.input_version === p.input_version && String(rt.followupDraft.question || '').trim()) names.push('追问');
 return names;
}

// DESIGN 8.1: before switching topic or going home, an unconfirmed submit or unsaved typing is raised first.
function v1Leave(label, go) {
 const app = apps[0];
 if (rt.pending || rt.busy) {
  app.v1Alert = {key:v1PlaceKey(app), tone:'warn', title:rt.busy ? '正在保存，请稍等。' : '上次提交的结果还没确认，已阻止切换。',
   sub:rt.busy ? '保存结果回来之前不能切换课题。' : '先核对上次提交；原来的请求还保留着，不会自动重发。', buttons:rt.busy ? [] : [['核对上次提交', 'data-v1-recover']]};
  livePaint();
  return;
 }
 const drafts = v1UnsavedDrafts();
 if (!drafts.length) { app.v1Alert = null; go(); return; }
 app.v1LeaveGo = go;
 app.v1Alert = {key:v1PlaceKey(app), tone:'warn', primary:false, title:`这一页有还没保存的内容：${drafts.join('、')}。`,
  sub:`${label}会丢掉这些内容；后台没有草稿存储，留在这里可以先保存或提交。`, buttons:[['留在这里', 'data-v1-leave="stay"'], ['仍然离开', 'data-v1-leave="go"']]};
 livePaint();
}

// DESIGN 8.20: Stage 4–6 preview template (static copy, no data).
const v1LaterNeeds = {
 4:['严格选定的方案包', '必需交付与独立校验值', '本人所见所选版本的可信绑定', '设计与可行性原件', '合法的当前运行映射', '配置、代码和依赖版本'],
 5:['运行清单、状态、日志与已有输出', '同版本 Stage 4 的真实结果', '指标、分析以及数据与运行的绑定', '失败、缺失与可比性记录'],
 6:['稿件版本与源文件', '书目、图表与结果证据的关系', '原始审阅记录']
};
function v1LaterPage(app) {
 const content = app.el.querySelector('.hs-content');
 if (!content || content.querySelector('[data-v1-later-page]')) return;
 const stage = app.stage;
 content.insertAdjacentHTML('afterbegin', `<div class="v1-page" data-v1-later-page>
  <div class="v1-head"><p class="v1-eyebrow">Stage ${stage} / 6 · ${v1LaterNames[stage]}</p><h1>${v1LaterNames[stage]}</h1></div>
  ${v1StatusMarkup({tone:'off', now:['这一段还没有开放。', '没有任何东西在运行。'], next:'等 Stage 3 的计划被接受。', you:null})}
  <div class="wiki-record v1-record-none"><strong class="wiki-record-chip">Harness 记录</strong><span>这一段还没有运行，没有记录。</span></div>
  <details class="v1-panel v1-fold"><summary>本阶段还需要哪些真实材料</summary><ul class="v1-needs">${v1LaterNeeds[stage].map(name => `<li><b>${name}</b><small>这是补件类别，不代表原生合同已核验。先核对核心原件和合法映射，再登记；不启动研究。</small></li>`).join('')}</ul></details>
 </div>`);
}

// DESIGN 2.5 status bar. tone: done | wait | off | run | err.
function v1StatusMarkup(v) {
 const you = v.you ? `${v.you.wait ? '<span class="v1-wait">等你</span> ' : ''}${esc(v.you.text)}` : '<span class="v1-muted">不需要你操作</span>';
 const button = v.button ? `<button type="button" class="v1-btn ${v.button.primary === false ? '' : 'primary'}" ${v.button.attrs || ''} ${v.button.disabled ? 'disabled' : ''}>${esc(v.button.label)}</button>${v.button.disabled ? `<small class="v1-reason">${esc(v.button.disabled)}</small>` : ''}` : '';
 return `<section class="v1-status st-${v.tone}" role="status" data-v1-status="${v.tone}">
  <div><span class="v1-k">现在</span><p><b>${esc(v.now[0])}</b>${esc(v.now[1] || '')}</p></div>
  <div><span class="v1-k">下一步</span><p>${esc(v.next)}</p></div>
  <div class="v1-you"><span class="v1-k">需要你</span><p>${you}</p>${button}</div>
 </section>`;
}

// Non-normal states are shared by every stage page (DESIGN 3.5, 8.3).
function v1CommonStatus(app) {
 const state = typeof wikiShellState === 'function' ? wikiShellState(app).state : '';
 if (state === 'busy') return {tone:'run', now:['正在保存。', '有一次提交正在处理。'], next:'等这次提交的保存结果回来。', you:{text:'不用重复点击'}};
 if (state === 'pending' || state === 'create-pending') return {tone:'wait', now:['上次提交的结果还没确认。', '原来的请求还保留着，不会自动重发。'], next:'先核对上次提交的结果。', you:{wait:true, text:'核对上次提交'}, button:{label:'核对上次提交', attrs:'data-v1-recover'}};
 if (state === 'foreign-pending') return {tone:'wait', now:['另一个课题有未确认的提交。', ''], next:'先回到那个课题核对。', you:{wait:true, text:'回原课题核对'}};
 if (state === 'error') return {tone:'err', now:['这次读取没有完成。', '已经读到的内容没有丢。'], next:'重新读取；原因在本页技术细节里。', you:{text:'重新读取'}, button:{label:'重新读取', attrs:'data-v1-reload', primary:false}};
 if (state === 'loading' || (!rt.overview && !rt.savedRun && rt.ref)) return {tone:'run', now:['正在读取保存记录。', ''], next:'读完后这里会写现在到了哪一步。', you:null};
 return null;
}

// Pages register their own status (normal states) and the blocks they keep.
const v1PageStatus = {};

function v1Mount(app) {
 const page = v1Page(app);
 if (!['s1', 's2', 's3'].includes(page)) return;
 const content = app.el.querySelector('.hs-content');
 if (!content) return;
 const v = v1CommonStatus(app) || v1PageStatus[page]?.(app);
 const markup = v ? v1StatusMarkup(v) : '';
 const previous = content.querySelector('[data-v1-status]');
 if (previous?.v1Markup === markup) return;
 previous?.remove();
 if (!markup) return;
 const heading = content.querySelector(':scope > .hs-heading, :scope > [data-v1-head]');
 if (heading) heading.insertAdjacentHTML('afterend', markup); else content.insertAdjacentHTML('afterbegin', markup);
 content.querySelector('[data-v1-status]').v1Markup = markup;
}

function v1Heading(app) {
 const page = v1Page(app);
 if (!['s1', 's2', 's3'].includes(page)) return;
 const heading = app.el.querySelector('.hs-content > .hs-heading');
 if (!heading || heading.dataset.v1Head) return;
 heading.dataset.v1Head = 'true';
 const topic = v1ProjectTitle();
 const eyebrow = heading.querySelector('.hs-eyebrow');
 if (eyebrow) eyebrow.textContent = `Stage ${app.stage} / 3 · ${v1StageNames[app.stage - 1]}`;
 const title = heading.querySelector('h1');
 if (title && topic) title.textContent = topic;
 for (const node of heading.querySelectorAll('.hs-status, h1 + p')) if (!node.matches('.v1-sub')) node.remove();
 const brief = rt.overview?.project?.project_ref === rt.ref ? rt.overview.project.brief : null;
 const savedTopic = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref) ? rt.savedRun?.payload?.index?.topic : '';
 const raw = brief?.original_title || savedTopic;
 const original = typeof raw === 'string' && raw && raw !== topic ? raw : '';
 if (original && title) title.insertAdjacentHTML('afterend', `<p class="v1-sub">原题：${esc(original)}</p>`);
}

const v1PreviousAfter = v7AfterRender;
v7AfterRender = function(app) {
 v1PreviousAfter(app);
 if (!v1Page(app)) return;
 v1Heading(app);
 v1Mount(app);
 // Stage modules move their heading up after render; the alert bar sits right under it (2.1 order).
 const alert = app.el.querySelector('.hs-content > [data-v1-alert]');
 const head = app.el.querySelector('.hs-content > .hs-heading, .hs-content > [data-v1-head], .hs-content > .v1-head');
 if (alert && head && head.nextElementSibling !== alert) head.after(alert);
 // The embedded material panel keeps its handlers; its summary uses the design wording (8.12).
 for (const summary of app.el.querySelectorAll('[data-ws-materials-slot] .n9-materials > summary, .wiki-s2-fold .n9-materials > summary')) {
  const count = app.el.querySelectorAll('[data-n9-catalog] > *:not(p)').length;
  const text = `已保存的材料 · ${count} 份`;
  if (summary.textContent !== text) summary.textContent = text;
 }
};

document.addEventListener('click', event => {
 const app = apps[0];
 if (!v1On(app) || !app.el.contains(event.target)) return;
 const button = event.target.closest('[data-v1-open],[data-v1-reload],[data-v1-recover],[data-v1-home],[data-v1-leave],[data-v1-alert-close]');
 if (!button || button.disabled) return;
 event.preventDefault();
 event.stopImmediatePropagation();
 if (button.hasAttribute('data-v1-open')) {
  // Switching re-reads the whole project; nothing from the previous topic is kept.
  const ref = button.dataset.v1Open;
  app.v1SwitchOpen = false;
  v1Leave('切换课题', () => { app.page = 'home'; wikiHomeOpen(ref); });
 } else if (button.hasAttribute('data-v1-home')) { app.v1SwitchOpen = false; v1Leave('回到首页', () => wikiHomeShow()); }
 else if (button.hasAttribute('data-v1-leave')) {
  const go = app.v1LeaveGo;
  app.v1LeaveGo = null; app.v1Alert = null;
  if (button.dataset.v1Leave === 'go' && go) go(); else livePaint();
 } else if (button.hasAttribute('data-v1-alert-close')) { app.v1Alert = null; app.v1LeaveGo = null; livePaint(); }
 else if (button.hasAttribute('data-v1-reload')) liveRefresh(rt.ref, {list:true});
 else liveRecover();
}, true);
// Narrow screens (<= 900px, see wiki-v1.css): the sidebar is a top bar and this button opens its menu. The state lives on
// the app so a repaint keeps it; Enter/Space reach it as a click. Escape, a click outside, or picking an item closes it.
function v1MenuSet(app, open, focus) {
 if (!app) return;
 app.v1MenuOpen = !!open;
 const side = app.el.querySelector?.('.v1-side');
 const button = side?.querySelector('[data-v1-menu]');
 if (side) side.toggleAttribute('data-open', !!open);
 if (button) { button.setAttribute('aria-expanded', open ? 'true' : 'false'); if (focus) button.focus(); }
}
window.addEventListener('click', event => {
 const app = apps[0];
 if (!app || !app.v1MenuOpen && !event.target.closest?.('[data-v1-menu]')) return;
 const toggle = event.target.closest?.('[data-v1-menu]');
 if (toggle) v1MenuSet(app, !app.v1MenuOpen);
 else if (!event.target.closest?.('.v1-side') || event.target.closest?.('[data-page],[data-stage]')) v1MenuSet(app, false);
}, true);
window.addEventListener('keydown', event => {
 const app = apps[0];
 if (event.key === 'Escape' && app?.v1MenuOpen) v1MenuSet(app, false, app.el.querySelector('.v1-side')?.contains(document.activeElement));
}, true);

// Crossing the 900px breakpoint either way (a window dragged wide and back) must not leave the menu open or aria-expanded stale.
window.matchMedia?.('(max-width: 900px)')?.addEventListener?.('change', () => v1MenuSet(apps[0], false));
document.addEventListener('toggle', event => {
 if (event.target.matches?.('[data-v1-later]') && event.target.isConnected) apps[0].v1LaterOpen = event.target.open;
 // A background repaint (a read finishing) re-renders the top bar; keep the topic menu open if the user opened it.
 if (event.target.matches?.('[data-v1-switch]') && event.target.isConnected) { apps[0].v1SwitchOpen = event.target.open; apps[0].v1SwitchRef = rt.ref; }
}, true);
// The toggle event comes a moment later; a repaint in between would drop it, so note the click itself too.
document.addEventListener('click', event => {
 const summary = event.target.closest?.('[data-v1-switch] > summary');
 if (!summary) return;
 apps[0].v1SwitchOpen = !summary.parentElement.open;
 apps[0].v1SwitchRef = rt.ref;
}, true);
// Keeping the menu open across repaints must not keep it open forever (review P2-d): a click anywhere outside the
// menu, or Escape, closes it. Listened on window so a page handler that stops the event cannot skip this.
function v1SwitchClose(app) {
 if (!app?.v1SwitchOpen) return;
 app.v1SwitchOpen = false;
 const menu = app.el.querySelector?.('[data-v1-switch]');
 if (menu) menu.open = false;
}
window.addEventListener('click', event => {
 if (!event.target.closest?.('[data-v1-switch]')) v1SwitchClose(apps[0]);
}, true);
window.addEventListener('keydown', event => {
 if (event.key === 'Escape') v1SwitchClose(apps[0]);
}, true);

// ---------- Stage 1 status (DESIGN 3.2, 8.6) ----------
function v1S1Counts() {
 const index = typeof wikiS1Index === 'function' ? wikiS1Index() : null;
 if (!index) return null;
 const claims = index.claims.length;
 const checked = index.claims.filter(claim => wikiS1Check(claim) !== 'unchecked').length;
 return {papers:index.papers.length, claims, checked};
}
v1PageStatus.s1 = app => {
 const archive = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref);
 const counts = v1S1Counts();
 if (v1ScopePending()) {
  const consent = typeof wsHasConsent === 'function' && wsHasConsent();
  return {tone:'wait', now:['还没有确认范围。', '确认之前不会检索、不会调用模型。'],
   next: consent ? '你确认范围后，Stage 1 的检索、筛选、阅读按同意书自动推进。' : '你保存范围后，到「运行与操作」逐步授权：先授权一次检索规划。',
   you:{wait:true, text:'确认范围和授权'}, button:{label:'去确认', attrs:'data-v1-goto="scope"'}};
 }
 if (counts) {
  const rest = `${counts.papers} 个来源、${counts.claims} 条证据定位；` + (counts.checked ? `已核对 ${counts.checked} / ${counts.claims} 条。` : '证据都还没有人核对过。');
  return {tone:'done', now:['文献和证据已保存。', rest], next:'到 Stage 2 比较研究方向。',
   you:{text: archive ? '这是历史归档，不能在这里改；这一段不需要你操作' : '这一段不需要你操作'}, button:{label:'去 Stage 2', attrs:'data-stage="2"'}};
 }
 if (rt.overview?.project?.project_ref === rt.ref) {
  return {tone:'done', now:['范围已确认。', '文献交付还没有生成。'], next:'到「运行与操作」看每一步现在怎样。',
   you:{text:'有要你授权的步骤时，会在「运行与操作」里写明'}, button:{label:'去运行与操作', attrs:'data-s1-tab="ops"', primary:false}};
 }
 return null;
};
// Status-bar buttons sit outside the Stage 1 panel, so the panel's own tab handler ignores them (review P1-1).
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-v1-status] [data-s1-tab]');
 const app = apps[0];
 if (!button || button.disabled || !app.wikiS1 || typeof wikiS1ChangeTab !== 'function') return;
 event.preventDefault();
 event.stopImmediatePropagation();
 wikiS1ChangeTab(app, button.dataset.s1Tab, false);
 app.el.querySelector('.wiki-s1-tabs')?.scrollIntoView({behavior:'smooth', block:'start'});
 app.el.querySelector('#wiki-s1-' + button.dataset.s1Tab)?.focus({preventScroll:true});
}, true);
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-v1-goto="scope"]');
 if (!button) return;
 event.preventDefault();
 const target = apps[0].el.querySelector('[data-wiki-ops="scope"], .live-scope');
 target?.scrollIntoView({behavior:'smooth', block:'start'});
 target?.querySelector(':is(select, input, textarea):not([readonly]):not([disabled])')?.focus({preventScroll:true}); // first field to fill, not the read-only title (review P2-8)
}, true);

// Harness record for Stage 1, built only from counts in the saved delivery (3.0).
function v1S1Record() {
 const index = typeof wikiS1Index === 'function' ? wikiS1Index() : null;
 if (!index) return undefined;
 const latest = new Map();
 for (const row of index.screening || []) {
  const key = JSON.stringify([row.work_id, row.version_id]);
  if (!latest.has(key) || row.observed_at >= latest.get(key).observed_at) latest.set(key, row);
 }
 const decisions = [...latest.values()];
 const by = status => decisions.filter(row => row.status === status).length;
 const located = index.claims.filter(row => row.locator).length;
 const checked = index.claims.filter(row => wikiS1Check(row) !== 'unchecked').length;
 const stopped = (index.coverage || []).filter(row => typeof row.stop_reason === 'string' && row.stop_reason).length;
 const groups = (index.coverage || []).length;
 // Remember these counts for the home table (same wording, no extra request); cleared with the tab.
 try { sessionStorage.setItem('wiki-v1-record:' + rt.ref, JSON.stringify({papers:index.papers.length, located, checked, claims:index.claims.length})); } catch (_) { /* Optional. */ }
 return {
  summary:`按已保存交付统计：记录了 ${index.papers.length} 篇文献的筛选决定和 ${located} 条证据的出处位置；核对了 ${checked} / ${index.claims.length} 条。`,
  source:'这些数字是页面按已保存的交付内容数出来的，不是后台的 Harness 记录汇总（后台还没有这个汇总）。',
  chips:[[`${index.papers.length} 篇文献`], [`核对 ${checked} / ${index.claims.length}`, checked < index.claims.length]],
  checks:[
   {name:'筛选决定', result:`纳入 ${by('include')} · 排除 ${by('exclude')} · 待定 ${decisions.length - by('include') - by('exclude')}（共 ${decisions.length} 条决定）`, raw:{decisions:decisions.length, include:by('include'), exclude:by('exclude')}},
   {name:'证据出处', result:`${located} / ${index.claims.length} 条有保存位置`, raw:{claims:index.claims.length, located}},
   {name:'出处核对', result:`核对了 ${checked} / ${index.claims.length} 条`, raw:{checked, claims:index.claims.length}},
   {name:'覆盖和停止', result:`${groups} 个需求分组，${stopped} 个写了停止原因`, raw:(index.coverage || []).map(row => ({need_id:row.need_id, works:(row.work_ids || []).length, stop_reason:row.stop_reason ?? null}))}
  ]
 };
}

// ---------- Stage 2 status (DESIGN 3.3, 8.13) ----------
function v1Split(text) {
 const value = String(text || '');
 const at = value.indexOf('。');
 return at < 0 ? [value + '。', ''] : [value.slice(0, at + 1), value.slice(at + 1)];
}
v1StageStatus[2] = () => {
 const model = typeof wikiS2Model === 'function' ? wikiS2Model() : null;
 if (model?.receipt) return ['已选定方向', 'done'];
 if (model?.blocked) return ['被拦下', 'wait'];
 if (model?.routes?.length) return model.origin === 'native' ? ['等你选方向', 'wait'] : ['候选已保存（只读）', 'done'];
 return ['还没有候选', ''];
};
v1PageStatus.s2 = app => {
 if (typeof wikiS2StatusText !== 'function') return null;
 const model = wikiS2Model(), status = wikiS2StatusText(app);
 if (!status) return null;
 const human = String(status.human || '');
 const waiting = /^等你/.test(human);
 const you = human === '不需要你操作' ? null : {wait:waiting, text:human.replace(/^等你\s*·\s*/, '')};
 if (model?.blocked) return {tone:'wait', now:v1Split(status.now), next:'重新读取一次。', you:null, button:{label:'重新读取', attrs:'data-v1-reload', primary:false}};
 if (model?.receipt) return {tone:'done', now:v1Split(status.now), next:status.next + '。', you, button:{label:'去 Stage 3', attrs:'data-stage="3"'}};
 if (model?.routes?.length) return {tone:waiting ? 'wait' : 'done', now:v1Split(status.now), next:status.next + '。', you,
  button: waiting ? {label:'去选方向', attrs:'data-v1-goto="decide"'} : null};
 return {tone:waiting ? 'wait' : 'off', now:v1Split(status.now), next:String(status.next).replace(/。?$/, '。'), you};
};
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-v1-goto="decide"]');
 if (!button) return;
 event.preventDefault();
 apps[0].el.querySelector('.wiki-s2-decide, [data-s2-decide], .decide')?.scrollIntoView({behavior:'smooth', block:'start'});
}, true);

// ---------- Stage 3 status (DESIGN 3.4, 8.13, 8.19) ----------
function v1S3Plan() {
 if (typeof v93Identity !== 'function') return null;
 const basis = v93Identity();
 return basis && v93Matches(v93.basis, basis) && v93.view?.plan ? v93.view : null;
}
v1StageStatus[3] = () => {
 if (v1S3Plan()) return typeof wikiS3DecStatus === 'function' && wikiS3DecStatus() ? ['已保存决定', 'done'] : ['等你做决定', 'wait'];
 return ['还没有规划', ''];
};
v1PageStatus.s3 = app => {
 if (typeof v93Identity !== 'function') return null;
 const basis = v93Identity(), view = v1S3Plan();
 if (basis && v93.busy) return {tone:'run', now:['正在读取已保存的规划。', '不会重新生成。'], next:'读完后这里会写计划和评审的情况。', you:null};
 if (basis && v93Matches(v93.errorBasis, basis) && v93.error) return {tone:'err', now:['读取规划没有完成。', '没有读到已保存的规划，也没有重新生成。'], next:'重新读取；原因在读取详情里。', you:{text:'重新读取'}, button:{label:'重新读取', attrs:'data-v93-read', primary:false}};
 if (view) {
  const decided = typeof wikiS3DecStatus === 'function' ? wikiS3DecStatus() : null;
  if (decided) return decided;
  const review = typeof wikiS3Review === 'function' ? wikiS3Review(view) : null;
  return {tone:'wait', now:['计划写好了。', review?.findings?.length ? `评审给了 ${review.findings.length} 条意见。` : '还没有评审意见（后台读取不返回评审）。'],
   next:'看完计划和评审后做决定。', you:{wait:true, text:'对计划做决定'}, button:{label:'去做决定', attrs:'data-v1-goto="s3-decide"', primary:false}};
 }
 // Without a connected Stage 3 the saved-selection read (v93Identity) is unavailable; go by what /connections says.
 const conn = !basis && typeof v9ConnectionModel === 'function' ? v9ConnectionModel(app) : null;
 if (conn?.phase === 'ready' && !conn.unknown) {
  if (conn.action === 'reconnect') return {tone:'wait', now:['Stage 3 未接通。', conn.reconnectError ? '上次点「重新接通」没有成功；规划登记仍然保存着。' : '规划登记已保存；如果上次是强行关闭，这次启动后会先显示未接通。'],
  next:conn.reconnectError ? '可以再点一次下面的「重新接通」；原因代码在接通块的技术细节里。' : '点下面的「重新接通」恢复，不会重复执行任何步骤，也不会新增记录。', you:{wait:true, text:'重新接通'}};
  if (conn.action === 'connect') return {tone:'wait', now:['还没有规划。', 'Stage 3 还没有接通；接通只是登记，不会启动研究。'], next:'在下面的接通块点「接通本课题」。', you:{wait:true, text:'接通本课题'}};
  // Connected but no selection read: not "cannot connect" (review P2-c).
  if (conn.connected) return {tone:'off', now:['还没有规划。', 'Stage 3 已接通，但这次没有读到选定的方向。'], next:'重新读取一次。', you:null, button:{label:'重新读取', attrs:'data-v1-reload', primary:false}};
  if (conn.code && conn.code !== 'stage3-current-selection-required') return {tone:'off', now:['还没有规划。', 'Stage 3 现在接不上，原因写在下面的接通块里。'], next:'按接通块里的说法处理。', you:null};
 }
 if (!basis) return {tone:'off', now:['还没有规划。', 'Stage 2 还没有选定方向，Stage 3 不会生成计划。'], next:'先到 Stage 2 选一个方向。', you:null, button:{label:'去 Stage 2', attrs:'data-stage="2"', primary:false}};
 const request = typeof wikiS3RequestLine === 'function' ? wikiS3RequestLine(view || (v93.basis && v93Matches(v93.basis, basis) ? v93.view : null)) : null;
 const requestGate = request?.tag === '还没请求' ? request.buttons[0]?.gate : request?.tag === '等你授权' && request.grant?.gate !== '请先勾选确认' ? request.grant?.gate : '';
 if (request && requestGate) return {tone:'off', now:['还没有规划。', `已经接通，但现在不能生成计划：${requestGate}。`], next:'条件满足后在下面「本课题的 Stage 3」里请求生成计划。', you:null};
 if (request && ['还没请求', '等你授权'].includes(request.tag)) return {tone:'wait', now:['还没有规划。', '已经接通，还没有保存的计划。'], next:'在下面「本课题的 Stage 3」里请求生成计划；生成前会先请你授权。', you:{wait:true, text:'请求生成计划'}};
 if (request) return {tone:request.tone === 'err' ? 'err' : request.tone === 'run' ? 'run' : 'off', now:['还没有规划。', /[。]$/.test(request.text) ? request.text : request.text + '。'], next:'看下面「本课题的 Stage 3」里请求一行的说明。', you:null};
 return {tone:'off', now:['还没有规划。', '已经有选定的方向，但还没有保存的计划。'], next:'接通本课题的 Stage 3 后，请求生成计划。', you:null};
};
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-v1-goto="s3-decide"]');
 if (!button) return;
 event.preventDefault();
 apps[0].el.querySelector('[data-s3-decision]')?.scrollIntoView({behavior:'smooth', block:'start'});
}, true);
