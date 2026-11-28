// Wiki V1 HOME uses the existing roster, project create receipt and bound reads.
const wikiHomeOrigins = {local:'本地项目', archive:'历史归档', synthetic:'合成样例', unknown:'来历未标注'};
const wikiHomeStageNames = ['文献与证据', '比较与选方向', '研究计划与评审'];
const wikiHomeDecisions = [
 ['确认题目范围和授权', 'Stage 1 开始前。确认后才会检索和查阅资料。'],
 ['选一个研究方向', 'Stage 2。系统给建议，你来选。'],
 ['对计划评审做决定', 'Stage 3。接受、修改后再评，或退回重选。']
];

function wikiHomeArchiveRef(ref) {
 return /^view:[A-Za-z0-9_-]{1,64}$/.test(ref || '');
}

function wikiHomeArchiveFragment() {
 try { return wikiHomeArchiveRef(decodeURIComponent(location.hash.slice(1).split('?')[0])); }
 catch (_) { return false; }
}

function wikiHomeArchiveBound(ref) {
 return wikiHomeArchiveRef(ref) && rt.savedRun?.entry?.project_ref === ref;
}

function wikiHomeRow(project) {
 const saved = canonicalEntry(project.project_ref);
 const synthetic = saved?.fixture === true || [rt.meta?.case_ref, rt.meta?.chat_ref].includes(project.project_ref);
 const archive = saved?.fixture === false || project.stage1_status === 'imported-verified-delivery';
 const failed = project.status === 'source-binding-failed';
 const stage = failed ? null : (saved?.stage2_available === true || project.stage2_status === 'delivery-received') ? 2 :
  saved || project.stage1_status ? 1 : null;
 // The initial create stores one intent and one result, advancing revision from 0 to 2.
 const waiting = stage === 1 && !saved && project.stage1_status === 'not-started' && project.stage1_intake_ready === false && project.revision === 2 && project.input_version === 1;
 const status = failed ? v1t('项目资料读取失败') : waiting ? v1t('确认研究范围') :
  saved ? v1t('已保存，只读') : stage === 2 ? v1t('已有交付材料') : archive ? v1t('已有保存材料') :
  project.stage1_intake_ready === true ? v1t('范围与计划已保存') : stage === 1 && project.revision > 2 ? v1t('范围已确认，文献还没交付') : v1t('当前状态未提供');
 return {
  ref:project.project_ref, title:project.topic || v1t('标题未提供'), origin:synthetic?'synthetic':archive?'archive':stage?'local':'unknown',
  stage, status, waiting, priorSaved:!!saved || project.stage1_status === 'imported-verified-delivery'
 };
}

function wikiHomeResume(rows) {
 let previous;
 try { previous = localStorage.getItem(liveProjectPreference); } catch (_) { /* Optional preference. */ }
 return rows.find(row => row.ref === previous) ||
  rows.filter(row => !canonicalEntry(row.ref) && row.stage).at(-1) ||
  rows.find(row => row.stage) || null;
}

function wikiHomeProgress(row) {
 if (!row.stage) return `<span class="wiki-home-muted">${v1t('未提供')}</span>`;
 const bars = [1,2,3].map(stage => `<b class="${stage < row.stage && row.priorSaved ? 'passed' : stage === row.stage ? (row.waiting ? 'waiting' : 'current') : ''}"></b>`).join('');
 return `<span class="wiki-home-progress"><span aria-hidden="true">${bars}</span>Stage ${row.stage}</span>`;
}

// Harness record column (3.0, 3.1). The home roster carries no delivery counts, so: counts this tab already
// read when the topic was opened (same wording as the Stage 1 page), otherwise what the roster status says.
const wikiHomeRanStatuses = /^(query-|offline-ledger-active|owner-reopen-required|imported-verified-delivery)/;
function wikiHomeRecordCell(row) {
 // Backend counts already read in this tab take priority; the home table never starts a read of its own.
 if (row.origin === 'synthetic') return v1t('演示数据，不计');
 const backend = typeof wikiRecHome === 'function' ? wikiRecHome(row.ref) : null;
 if (backend) return `<span class="wiki-home-record">${esc(backend.text)}</span><small>${v1t('后台记录 · 已读 Stage {stages}', {stages: backend.stages.join(v1t('、'))})}</small>`;
 if (typeof wikiRecHomeWaiting === 'function' && wikiRecHomeWaiting(row.ref)) return `<small>${v1t('等待读取后台记录…')}</small>`;
 let seen = null;
 try { seen = JSON.parse(sessionStorage.getItem('wiki-v1-record:' + row.ref) || 'null'); } catch (_) { seen = null; }
 const n = value => Number.isSafeInteger(value) && value >= 0;
 if (seen && n(seen.papers) && n(seen.checked) && n(seen.claims)) return `<span class="wiki-home-record">${v1t('按已保存交付统计：{papers} 篇文献 · 核对 {checked} / {claims}', {papers: seen.papers, checked: seen.checked, claims: seen.claims})}</span><small>${v1t('本次打开课题时数的')}</small>`;
 const project = rt.list.find(item => item.project_ref === row.ref);
 const ran = row.origin === 'archive' || wikiHomeRanStatuses.test(project?.stage1_status || '') || project?.stage2_status === 'delivery-received';
 return ran ? v1t('有 Stage 1 记录，打开课题后可见') : row.stage ? v1t('打开课题后可见') : v1t('还没有运行');
}

// Same titles are allowed (no merging, 8.27). The roster has no creation time, so the last characters of
// the project number tell them apart (design gap: the design does not say how).
function wikiHomeTwinText(row, rows) {
 return rows.filter(other => other.title === row.title).length > 1 ? ' · ' + v1t('编号尾号 {tail}', {tail: String(row.ref).slice(-6)}) : '';
}
function wikiHomeTwin(row, rows) {
 const text = wikiHomeTwinText(row, rows);
 return text ? `<small class="wiki-home-twin">${esc(text.slice(3))}</small>` : '';
}

function wikiHomeProjectTable(rows, ready, locked) {
 const filters = [['all', v1t('全部')], ...Object.entries(wikiHomeOrigins).map(([k, v]) => [k, v1t(v)])]
  .map(([key, label]) => [key, label, rows.filter(row => key === 'all' || row.origin === key).length])
  .filter(([key, , count]) => key === 'all' || count > 0);
 const tableRows = rows.map(row => `<tr data-wiki-home-origin="${row.origin}">
   <th scope="row">${esc(row.title)}${wikiHomeTwin(row, rows)}</th><td><span class="wiki-home-origin ${row.origin}">${v1t(wikiHomeOrigins[row.origin])}</span></td>
   <td>${wikiHomeProgress(row)}</td><td>${row.waiting ? `<span class="wiki-home-wait">${v1t('等你')}</span> ` : ''}${row.status}</td>
   <td class="wiki-home-muted" data-wiki-home-record-ref="${esc(row.ref)}">${wikiHomeRecordCell(row)}</td>
   <td><button type="button" class="wiki-home-button" data-wiki-home-open="${esc(row.ref)}" aria-label="${v1t('打开 {title}{twin}', {title: esc(row.title), twin: wikiHomeTwinText(row, rows)})}" ${locked?'disabled':''}>${v1t('打开')}</button></td>
  </tr>`).join('');
 return `<section aria-labelledby="wiki-home-projects"><div class="wiki-home-table-head">
  <h2 id="wiki-home-projects">${v1t('全部项目')}</h2>
  ${ready || rows.length ? `<div class="wiki-home-filters" role="group" aria-label="${v1t('按来历筛选')}">${filters.map(([key, label, count]) => `<button type="button" data-wiki-home-filter="${key}" aria-pressed="false">${label} <b>${count}</b></button>`).join('')}</div>` : ''}
 </div>
 <div class="wiki-home-table"><table><thead><tr>
  <th scope="col">${v1t('项目')}</th><th scope="col">${v1t('来历')}</th><th scope="col">${v1t('到了哪一段')}</th><th scope="col">${v1t('现在的状态')}</th><th scope="col">${v1t('Harness 记录')}</th><th scope="col"><span class="wiki-home-visually-hidden">${v1t('操作')}</span></th>
 </tr></thead><tbody>${tableRows || `<tr><td colspan="6" class="wiki-home-empty" role="status">${ready ? v1t('还没有保存的课题。输入标题开始第一个课题。') : rt.error ? v1t('暂时读不到项目列表。') : v1t('正在读取项目列表…')}</td></tr>`}</tbody></table></div>
 <p class="wiki-home-note">${v1t('「Harness 记录」显示项目已有的检查记录和拦截次数。历史归档可供查阅，合成样例只用于演示。')}${rows.some(row => row.origin === 'synthetic') ? ' ' + v1t('合成样例是自带的只读样例，不连 Codex 也能看。') : ''}</p></section>
 <p class="wiki-home-note" data-wiki-home-record-note role="status">${typeof wikiRecHomeNote === 'function' ? esc(wikiRecHomeNote()) : ''}</p>
 ${wikiHomeCases()}`;
}

// DESIGN 8.5 (decided): published cases open the external read-only pages in a new tab.
function wikiHomeCases() {
 const base = 'https://wenyuchiou.github.io/AutoResearchAgent/stage-3/';
 const parts = [['household-case', v1t('研究设计案例')], ['data-methods', v1t('数据与方法')], ['validation', v1t('研究验证')], ['harness-evaluation', v1t('计划评估')]];
 return `<section class="wiki-home-cases" aria-labelledby="wiki-home-cases"><h2 id="wiki-home-cases">${v1t('已发布的只读案例')}</h2>
  <div class="wiki-home-case"><b>${v1t('美国居民消费')}</b><span class="wiki-home-origin archive">${v1t('历史归档')}</span>
  ${parts.map(([hash, name]) => `<a class="wiki-home-button" target="_blank" rel="noopener noreferrer" href="${base}#${hash}">${name} <span aria-hidden="true">↗</span><span class="wiki-home-visually-hidden">${v1t('（在新标签页打开）')}</span></a>`).join('')}</div>
  <p class="wiki-home-note">${v1t('这是独立的只读归档，不在这个 Wiki 里。')}</p></section>`;
}

// DESIGN 8.5 / 8.3: a create whose result is unknown, or another topic's unconfirmed submit. Never resends.
function wikiHomePendingBar() {
 const p = rt.pending;
 if (!p) return '';
 if (rt.busy) return `<div class="wiki-home-message" role="status">${p.ref ? v1t('正在等候上次提交的保存结果。') : v1t('正在保存新课题…')}</div>`;
 if (!p.ref) return `<div class="wiki-home-message" role="status">${v1t('新课题的创建结果还待核对，不会自动重建。')} <button type="button" class="wiki-home-button" data-wiki-home-recover>${v1t('回到原提交处核对')}</button></div>`;
 const title = rt.list.find(item => item.project_ref === p.ref)?.topic;
 return `<div class="wiki-home-message" role="status">${title ? v1t('另一个课题有未确认的提交（{title}），不会自动重发。', {title: esc(title)}) : v1t('另一个课题有未确认的提交，不会自动重发。')} <button type="button" class="wiki-home-button" data-wiki-home-pending-open="${esc(p.ref)}">${v1t('切回那个课题核对')}</button></div>`;
}

function wikiHomeMarkup() {
 const rows = rt.list.map(wikiHomeRow);
 const ready = !!rt.meta && !rt.loading && !rt.error;
 const recent = wikiHomeResume(rows);
 const locked = rt.busy || rt.loading || !!rt.pending;
 const disabled = ready ? liveDisabled() : 'disabled';
 return `<div class="wiki-home" data-wiki-home>
  ${rt.error ? `<div class="wiki-home-message" role="alert">${v1t('这次读取或保存没有完成。')} <button type="button" class="wiki-home-button" data-wiki-home-retry ${locked?'disabled':''}>${v1t('刷新检查')}</button><details><summary>${v1t('技术细节')}</summary><p>${esc(rt.error)}</p></details></div>` : ''}
  ${wikiHomePendingBar()}
  <div class="wiki-home-top">
   <section class="wiki-home-card">
    <h1>${v1t('开始一个新研究')}</h1>
    <p>${v1t('只填标题就能开始。确认范围和授权之前，不会检索、不会调用模型。')}</p>
    ${rt.controlHeld ? `<p role="status">${v1t('请先在原项目核对上次操作的结果，再新建课题。')}</p>` : ''}
    <form data-wiki-home-create>
     <label for="wiki-home-topic">${v1t('研究标题')}</label>
     <div class="wiki-home-entry">
      <input id="wiki-home-topic" data-live-topic required maxlength="240" placeholder="${v1t('例如：人口老龄化如何影响家庭消费')}" value="${esc(rt.topicDraft)}" ${disabled}>
      <button type="submit" class="wiki-home-button primary" ${disabled}>${rt.busy && rt.pending && !rt.pending.ref ? v1t('正在保存…') : v1t('开始')}</button>
     </div>
     <details ${rt.homeMore?'open':''} data-wiki-home-more><summary>${v1t('更多（可以不填）')}</summary>
      <label for="wiki-home-question">${v1t('想回答的问题')}</label>
      <input id="wiki-home-question" maxlength="240" value="${esc(rt.homeQuestion || '')}" ${disabled}>
      <p>${v1t('所填问题会随标题一起保存。')}</p>
     </details>
    </form>
   </section>
   <section class="wiki-home-card wiki-home-resume">
    <h2>${v1t('继续上次')}</h2>
    ${recent ? `<h3>${esc(recent.title)}${wikiHomeTwin(recent, rows)}</h3><p class="wiki-home-resume-meta"><span class="wiki-home-origin ${recent.origin}">${v1t(wikiHomeOrigins[recent.origin])}</span>${wikiHomeProgress(recent)} ${recent.stage ? '<span>'+v1t(wikiHomeStageNames[recent.stage - 1])+'</span>' : ''}</p>
    <p>${recent.waiting ? `<span class="wiki-home-wait">${v1t('等你')}</span> ` : ''}${recent.status}</p><button type="button" class="wiki-home-button" data-wiki-home-open="${esc(recent.ref)}" ${locked?'disabled':''}>${v1t('继续')}</button>`
    : `<p role="status">${ready ? v1t('新建课题后，可以从这里继续。') : rt.error ? v1t('刷新项目列表后可以继续。') : v1t('正在读取上次的项目…')}</p>`}
   </section>
  </div>
  <ol class="wiki-home-decisions" aria-label="${v1t('研究中的三处决定')}">${wikiHomeDecisions.map(([name, note], i) => `<li><span aria-hidden="true">${i+1}</span><div><strong>${v1t(name)}</strong><p>${v1t(note)}</p></div></li>`).join('')}</ol>
  ${wikiHomeGuide()}
  ${wikiHomeProjectTable(rows, ready, locked)}
 </div>`;
}

// DESIGN 8.5: first-visit three steps between the decisions and the project table; closable, remembered in
// this browser; 连接与设置 can show it again. Links only move focus or change page; nothing is sent.
const wikiHomeGuideKey = 'wiki-v1-guide-closed';
function wikiHomeGuideClosed() {
 try { return localStorage.getItem(wikiHomeGuideKey) === '1'; } catch (_) { return false; }
}
function wikiHomeGuide() {
 if (wikiHomeGuideClosed()) return '';
 const steps = [
  [v1t('开新课题'), v1t('在左上角写一个研究标题，点「开始」。只保存选题，不会检索、不会调用模型。'), v1t('去填标题'), 'data-wiki-home-focus="topic"'],
  [v1t('你要点的三处'), v1t('确认范围和授权、选方向、对评审做决定。其余步骤按你的授权自动往下走。'), v1t('看这三处'), 'data-wiki-home-focus="decisions"'],
  [v1t('产物在哪看'), v1t('每一段的结果在对应的 Stage 页；保存的文件都在「项目文件」页，每份带版本。'), v1t('去项目文件'), 'data-page="files"']
 ];
 return `<section class="wiki-home-guide" aria-labelledby="wiki-home-guide" data-wiki-home-guide>
  <div class="wiki-home-guide-head"><h2 id="wiki-home-guide">${v1t('第一次用：三步看懂')}</h2><button type="button" class="wiki-home-link" data-wiki-home-guide-close>${v1t('关闭引导')}</button></div>
  <ol>${steps.map(([name, text, link, attrs], i) => `<li><span aria-hidden="true">${i + 1}</span><div><strong>${name}</strong><p>${text}</p><button type="button" class="wiki-home-link" ${attrs}>${link}</button></div></li>`).join('')}</ol>
  <p class="wiki-home-guide-codex">${v1t('要让 Codex 帮你检索和阅读，先做连接检查：')}<button type="button" class="wiki-home-link" data-page="settings" data-wiki-home-codex>${v1t('连接 Codex')}</button><span>${v1t('只读检查，不会要你贴任何密钥。')}</span></p>
 </section>`;
}

function wikiHomeFilter(app, choice) {
 const buttons = [...app.el.querySelectorAll('[data-wiki-home-filter]')];
 const current = buttons.some(button => button.dataset.wikiHomeFilter === choice) ? choice : 'all';
 app.wikiHomeFilter = current;
 for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.wikiHomeFilter === current));
 for (const row of app.el.querySelectorAll('[data-wiki-home-origin]')) row.hidden = current !== 'all' && row.dataset.wikiHomeOrigin !== current;
}

function wikiHomeShow() {
 const app = apps[0], base = location.pathname + location.search;
 app.page = 'home';
 rt.projectFallback = false;
 if (location.hash) history.pushState(history.state, '', base);
 liveRefresh(null, {list:true});
 window.scrollTo(0, 0);
}

function wikiHomeTopicOpen() {
 return !!rt.ref && (rt.overview?.project?.project_ref === rt.ref || wikiHomeArchiveBound(rt.ref));
}

function wikiHomeProjectOpened(ref, stage) {
 const app = apps[0];
 if (!v1Lang(app) || app.page !== 'home' || rt.error || rt.ref !== ref ||
     (rt.overview?.project?.project_ref !== ref && rt.savedRun?.entry?.project_ref !== ref)) return;
 localStage(app, stage, {historyMode:'restore'});
 history.pushState(history.state, '', location.pathname + location.search + v93Fragment(ref, app, stage));
 liveRememberProject();
 livePaint();
 window.scrollTo(0, 0);
}

async function wikiHomeOpen(ref, stage) {
 const project = rt.list.find(item => item.project_ref === ref);
 if (!project || rt.busy || rt.loading || rt.pending) return;
 rt.projectFallback = false;
 await liveRefresh(ref);
 wikiHomeProjectOpened(ref, stage || wikiHomeRow(project).stage || 1);
}

// Opens the topic that owns the unconfirmed submit (reads only); the check itself stays on that topic's page.
async function wikiHomePendingOpen(ref) {
 const project = rt.list.find(item => item.project_ref === ref);
 if (!project || rt.busy || rt.loading || rt.pending?.ref !== ref) return;
 await liveRefresh(ref);
 wikiHomeProjectOpened(ref, wikiHomeRow(project).stage || 1);
}

const wikiHomePreviousPage = otherPage;
otherPage = app => v1Lang(app) && app.page === 'home' ? wikiHomeMarkup() : wikiHomePreviousPage(app);

const wikiHomePreviousRender = render;
render = function(app) {
 wikiHomePreviousRender(app);
 const active = v1Lang(app) && app.page === 'home';
 if (!active && app.el.dataset.wikiHomeShell !== 'true') return;
 app.el.dataset.wikiHomeShell = String(active);
 if (app.wikiHomePreviousTitle === undefined) app.wikiHomePreviousTitle = document.title;
 document.title = active ? v1t('Wiki V1 · 工作台') : app.wikiHomePreviousTitle;
 if (!active) { if (typeof wikiRecHomeLeave === 'function') wikiRecHomeLeave(); return; }
 app.el.querySelector('.hs-project-name').textContent = v1t('工作台');
 app.el.querySelector('[data-page="workspace"]').setAttribute('aria-current', 'page');
 const recent = wikiHomeResume(rt.list.map(wikiHomeRow));
 for (const button of app.el.querySelectorAll('.hs-stage-nav [data-stage]')) {
  const stage = Number(button.dataset.stage);
  if (stage > 3) continue;
  button.querySelector('span:last-child').textContent = v1t(wikiHomeStageNames[stage - 1]);
  button.disabled = rt.busy || rt.loading || !!rt.pending || !recent || stage > (recent.stage || 0);
 }
 wikiHomeFilter(app, app.wikiHomeFilter);
};

const wikiHomePreviousAfter = v7AfterRender;
v7AfterRender = function(app) {
 wikiHomePreviousAfter(app);
 if (!v1Lang(app) || app.page !== 'home') return;
 if (typeof wikiRecHomeStart === 'function') wikiRecHomeStart(wikiRecHomeVisible(app));
 const side = app.el.querySelector('.hs-sidebar-foot');
 if (!side) return; // The V1 sidebar has its own fixed footer line.
 side.textContent = rt.busy || rt.loading || rt.pending ? v1t('等当前请求处理完，可打开课题。') :
  rt.list.some(project => wikiHomeRow(project).stage) ? v1t('侧栏可打开上次课题已有记录的阶段。') : v1t('新建课题后，可打开该课题的阶段页。');
};

document.addEventListener('click', event => {
 const app = apps[0];
 if (!v1Lang(app) || !app.el.contains(event.target)) return;
 const button = event.target.closest('[data-page="workspace"],[data-wiki-home-open],[data-wiki-home-pending-open],[data-wiki-home-guide-close],[data-wiki-home-focus],[data-wiki-home-filter],[data-wiki-home-retry],[data-wiki-home-recover],[data-stage]');
 if (!button || button.disabled || (button.dataset.stage && app.page !== 'home')) return;
 event.preventDefault();
 event.stopImmediatePropagation();
 if (button.dataset.page === 'workspace') {
  // DESIGN 8.1: "工作台" is the open topic's stage page. Only without an open topic does it go home;
  // the home table is reached from the topic menu's "全部项目…". Viewing never clears drafts.
  if (app.page === 'home') return;
  if (wikiHomeTopicOpen()) { app.page = 'workspace'; livePaint(); window.scrollTo(0, 0); return; }
  if (rt.busy || rt.loading || rt.pending) {
   if (typeof v1Notice === 'function') v1Notice(rt.busy ? v1t('正在保存，请稍等，保存完再回首页。') : rt.loading ? v1t('正在读取保存记录，读完再回首页。') : v1t('上次提交的结果还没确认，先核对，再回首页。'), !!rt.pending && !rt.busy);
   return;
  }
  wikiHomeShow();
 } else if (button.dataset.stage) {
  const recent = wikiHomeResume(rt.list.map(wikiHomeRow));
  if (recent) wikiHomeOpen(recent.ref, Number(button.dataset.stage));
 } else if (button.hasAttribute('data-wiki-home-open')) wikiHomeOpen(button.dataset.wikiHomeOpen);
 else if (button.hasAttribute('data-wiki-home-pending-open')) wikiHomePendingOpen(button.dataset.wikiHomePendingOpen);
 else if (button.hasAttribute('data-wiki-home-guide-close')) {
  try { localStorage.setItem(wikiHomeGuideKey, '1'); } catch (_) { /* Without storage the guide closes for this view only. */ }
  app.el.querySelector('[data-wiki-home-guide]')?.remove();
 } else if (button.dataset.wikiHomeFocus) {
  const target = app.el.querySelector(button.dataset.wikiHomeFocus === 'topic' ? '#wiki-home-topic' : '.wiki-home-decisions');
  target?.scrollIntoView({behavior:'smooth', block:'center'});
  if (button.dataset.wikiHomeFocus === 'topic') target?.focus({preventScroll:true});
  // 「看这三处」: the list is already on screen on a one-screen page, so scrolling shows nothing. Move focus to it and mark it.
  if (button.dataset.wikiHomeFocus === 'decisions' && target) {
   target.setAttribute('tabindex', '-1');
   target.focus({preventScroll:true});
   target.classList.add('wiki-home-flash');
   setTimeout(() => target.classList.remove('wiki-home-flash'), 2000);
  }
 }
 else if (button.hasAttribute('data-wiki-home-filter')) wikiHomeFilter(app, button.dataset.wikiHomeFilter);
 else if (button.hasAttribute('data-wiki-home-retry')) liveRefresh(null, {list:true});
 else liveRecover();
}, true);

document.addEventListener('submit', event => {
 if (!event.target.matches('[data-wiki-home-create]')) return;
 event.preventDefault();
 event.stopImmediatePropagation();
 const field = event.target.querySelector('[data-live-topic]'), topic = field.value.trim();
 if (!topic) {
  field.setCustomValidity(v1t('请输入研究标题。'));
  field.reportValidity();
  return;
 }
 const question = event.target.querySelector('#wiki-home-question').value.trim();
 livePost('', question ? {topic, needs:[{need_id:'main', question}]} : {topic}, null);
}, true);

document.addEventListener('input', event => {
 if (event.target.id === 'wiki-home-question') rt.homeQuestion = event.target.value;
 if (event.target.id === 'wiki-home-topic') event.target.setCustomValidity('');
});
document.addEventListener('toggle', event => {
 if (event.target.matches('[data-wiki-home-more]') && event.target.isConnected) rt.homeMore = event.target.open;
}, true);
document.addEventListener('change', event => {
 if (!event.target.matches('[data-language]')) return;
 const app = apps[0], target = event.target.value;
 app.v1Alert = null; app.v1LeaveGo = null; // a notice written in the old language is dropped, not shown untranslated
 // Write the choice into the topic link at once. While the topic's first read is still running, the runtime
 // re-applies the link's language when that read finishes, which switched a language chosen meanwhile back.
 const at = location.hash.indexOf('?'), tag = {zh:'zh-CN', tw:'zh-TW', en:'en'}[target];
 if (at > 0 && tag) {
  const params = new URLSearchParams(location.hash.slice(at + 1));
  if (params.get('lang') !== tag) {
   params.set('lang', tag);
   history.replaceState(history.state, '', location.pathname + location.search + location.hash.slice(0, at + 1) + params.toString());
  }
 }
 // All three languages share the V1 pages, so a language change keeps the page; only a bare address goes home.
 if (v1Lang({lang:target}) && !location.hash && !rt.ref) app.page = 'home';
}, true);
window.addEventListener('popstate', () => {
 if (v1Lang(apps[0]) && !location.hash && apps[0].page !== 'home' && !rt.busy) wikiHomeShow();
});

// A topic link carries its language (lang=en|zh-TW|zh-CN). Use it from the first paint: the runtime applies it
// only after the project read finishes, so a slow machine first showed the topic in the default language and
// then repainted (which also closed any menu opened in between).
(() => {
 let mapped;
 try {
  const raw = location.hash.slice(1), at = raw.indexOf('?');
  mapped = at < 0 ? null : {en:'en', 'zh-TW':'tw', 'zh-CN':'zh'}[new URLSearchParams(raw.slice(at + 1)).get('lang')];
 } catch (_) { mapped = null; }
 if (mapped && apps[0] && apps[0].lang !== mapped) { apps[0].lang = mapped; livePaint(); }
})();

if (v1Lang(apps[0]) && !location.hash) {
 apps[0].page = 'home';
 livePaint();
}
