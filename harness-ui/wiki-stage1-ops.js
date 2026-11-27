// Wiki V1 Stage 1 "做操作" presentation (DESIGN 8.6 scope page, 8.7 run tab, 8.11 delivery).
// Presentation only: every write reuses an existing handler (data-real-action, data-live-action,
// data-v7-workflow, livePost). Reads never dispatch work. Chinese only; other languages keep the old panels.
const wsPhaseNames = {scope:'确认范围', planning:'检索规划', query:'查询与来源', screening:'文献筛选',
 reading:'阅读与证据', coverage:'覆盖检查', delivery:'保存交付'};
const wsTagKinds = {done:['✓','完成'], run:['↻','进行中'], part:['◐','部分完成'], wait:['●','等你'],
 block:['!','被拦下'], err:['✕','出错'], idle:['○','未开始']};
const wsReasons = {'scope-required':'还没有确认范围', 'plan-required':'还没有检索规划',
 'query-permission-required':'没有这一段的运行许可', 'screening-required':'还没有可筛选的检索结果',
 'reading-registration-required':'阅读还没完成', 'coverage-required':'覆盖检查还没开始',
 'delivery-required':'还没有生成交付', 'saved-records-unconnected':'保存记录还没接通'};
// Reasons the design defines for "consent file unusable". Codes come from the progression route.
const wsConsentBlocks = {
 'stage-progression-consent-required':['没带', '这次启动没有带同意书。每一步要你单独授权'],
 'stage-progression-consent-digest-differs':['核对不上', '同意书的内容和启动时登记的不一致，没有使用'],
 'stage-progression-consent-invalid':['无效', '同意书的格式不对，或没有写明已确认，没有使用'],
 'stage-progression-consent-binding-differs':['不是这个课题或这个版本', '同意书对应的是另一个课题，或这个课题的旧版本'],
 'stage-progression-consent-expired':['已过期', '同意书已过期，不会自动续期'],
 'stage-progression-consent-stage-not-covered':['没覆盖这一段', '同意书没有覆盖这一段']};
const wsAllowedProgress = new Set(['waiting-for-project-scope','waiting-for-predecessor','not-started',
 'execution-unknown','saved','in-progress','waiting-for-spending-grant']);

function wsTag(kind, label) {
 const [icon, name] = wsTagKinds[kind] || wsTagKinds.idle;
 return `<span class="ws-tag ws-${kind}"><span aria-hidden="true">${icon}</span> ${esc(label || name)}</span>`;
}
function wsReadonly() {
 return (typeof canonicalReadonly === 'function' && canonicalReadonly()) ||
  (typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref));
}
// The four fixed reasons from DESIGN 8.0; checked in the order the design lists them.
function wsLock() {
 if (rt.loading) return '正在读取保存记录';
 if (rt.busy) return '正在保存，请稍等';
 if (rt.pending) return '上次提交的结果还没确认，先核对';
 if (rt.controlHeld) return '有一条回执还没核对，先到操作历史里核对';
 return '';
}
const wsWhy = reason => `<small class="ws-why" role="note" ${reason ? '' : 'hidden'}>${esc(reason || '')}</small>`;
// A button is only clickable when no reason blocks it; the reason is always written under it.
function wsBtn(label, attrs, reason, cls='') {
 return `<span class="ws-btn"><button type="button" class="hs-button ${cls}" ${attrs} ${reason ? 'disabled' : ''}>${esc(label)}</button>${wsWhy(reason)}</span>`;
}
const wsArchiveNote = '<p class="wiki-s1-muted">这是历史归档，不能在这里改。</p>';

// ---------- progression (auto-advance) readback ----------
function wsProgKey() { return JSON.stringify([rt.ref, rt.overview?.project?.input_version, rt.overview?.project?.revision]); }
function wsProg() {
 const cache = rt.wsProg;
 return cache && cache.key === wsProgKey() ? cache : null;
}
async function wsProgLoad(force=false) {
 const key = wsProgKey(), ref = rt.ref;
 if (!ref || !rt.overview?.project || (!force && rt.wsProg?.key === key)) return;
 rt.wsProg = {key, state:'loading'};
 let next;
 try {
  const response = await fetch(projectPath(ref,'progression'), {headers:{Authorization:'Bearer '+window.RESEARCH_PROJECTS.credential},
   cache:'no-store', credentials:'same-origin'});
  const value = await response.json().catch(() => ({}));
  if (response.status === 404) next = {key, state:'absent'};
  else if (response.ok && wsAllowedProgress.has(value.status)) next = {key, state:'read', value};
  else next = {key, state:'error', code:value.error || 'HTTP ' + response.status};
 } catch (error) { next = {key, state:'error', code:String(error.message || error)}; }
 if (ref !== rt.ref || wsProgKey() !== key) return;
 rt.wsProg = next;
 livePaint();
}
// The only write on this page that bypasses livePost: the route accepts exactly three body fields.
async function wsAdvance() {
 const p = rt.overview?.project, ref = rt.ref;
 if (!p || wsLock() || wsReadonly()) return;
 rt.busy = true; rt.error = ''; livePaint();
 let outcome;
 try {
  const value = await liveRequest(projectPath(ref,'progression'), {input_version:p.input_version, brief_sha256:p.brief_sha256, confirmed:true});
  outcome = {key:wsProgKey(), state:'read', value};
 } catch (error) {
  outcome = {key:wsProgKey(), state:'error', code:error.message};
 }
 rt.busy = false;
 rt.wsProg = outcome;
 await liveRefresh(ref, {list:true});
 rt.wsProg = outcome; livePaint();
}
// Seven display states from DESIGN 8.7, plus the six "consent unusable" reasons.
function wsAuto() {
 const prog = wsProg(), p = rt.overview?.project, scoped = p?.intake_report?.necessary_clarification_complete === true;
 const none = {kind:'idle', label:'没带', text:'这次启动没有带同意书。每一步要你单独授权', button:null, installed:false};
 if (!prog || prog.state === 'loading') return {kind:'idle', label:'读取中', text:'正在读取推进状态', button:null, installed:null};
 if (prog.state === 'absent') return none;
 if (prog.state === 'error') {
  const reason = wsConsentBlocks[prog.code];
  if (reason) return {kind:'block', label:reason[0], text:reason[1], button:null, installed:true, blocked:true};
  if (prog.code === 'stage-progression-budget-unavailable' || prog.code === 'stage1-run-grant-expired')
   return {kind:'block', label:'缺运行许可', text:'同意书有，但这一段的运行许可还没有，所以没有推进', button:['去连接与设置','settings'], installed:true, blocked:true, raw:prog.code};
  return {kind:'err', label:'出错', text:'读取或推进时出错，没有重复执行', button:null, installed:true, raw:prog.code};
 }
 const status = prog.value.status;
 const out = {installed:true, raw:status};
 if (!scoped || status === 'waiting-for-project-scope') return {...out, kind:'wait', label:'等你确认范围', text:'范围还没确认，推进不了', button:['去确认范围','scope']};
 if (status === 'waiting-for-predecessor') return {...out, kind:'idle', label:'等上一段', text:'上一段还没有交付，这一段先等着', button:null};
 if (status === 'waiting-for-spending-grant') return {...out, kind:'block', label:'缺运行许可', text:'同意书有，但这一段的运行许可还没有，所以没有推进', button:['去连接与设置','settings']};
 if (status === 'in-progress') return {...out, kind:'run', label:'进行中', text:'正在推进。不需要你操作', button:null};
 if (status === 'execution-unknown') return {...out, kind:'block', label:'结果未确认', text:'上一次推进已经发出，结果还没确认。不会再发一次', button:['核对上次提交','history']};
 if (status === 'saved') return {...out, kind:'done', label:'已保存', text:'这一段已推进完并保存', button:null};
 return {...out, kind:'idle', label:'还没开始', text:'这一段还没有开始推进', button:['推进','advance']};
}
function wsAutoRow() {
 const a = wsAuto();
 if (a.installed === false) return '';
 const lock = wsLock();
 const button = a.button ? (a.button[1] === 'advance' ? wsBtn(a.button[0], 'data-ws-advance', lock || (wsReadonly() ? '这是历史归档，不能在这里改' : ''))
  : `<button type="button" class="hs-button" data-ws-go="${a.button[1]}">${a.button[0]}</button>`) : '';
 const stage2 = a.kind === 'done' || a.label === '已保存' ?
  `<p class="ws-conn-sub">${wsTag('idle','等上一段')} Stage 2 现在还不能自动推进，要你到 Stage 2 页接通 <button type="button" class="hs-button" data-ws-go="stage2">去 Stage 2</button></p>` : '';
 return `<section class="ws-conn" data-ws-auto="${a.kind}" aria-label="自动推进"><div><strong>自动推进</strong> ${wsTag(a.kind, a.label)} <span>${esc(a.text)}</span> ${button}</div>${stage2}${a.raw ? `<details class="ws-tech"><summary>技术细节：原始状态</summary><pre>${esc(a.raw)}</pre></details>` : ''}</section>`;
}

// ---------- quota ----------
function wsBudget() {
 const b = rt.overview?.project?.settings?.budgets || rt.meta?.run_limits || null;
 const used = rt.overview?.models?.calls_reserved;
 return {b, used};
}
function wsQuota() {
 const auto = wsAuto(), {b, used} = wsBudget();
 if (auto.installed !== true && !(b && Number(b.model_calls) > 0)) {
  return '<div class="ws-quota ws-quota-gray"><b>额度</b><span>每一步的上限写在那一步的授权卡里</span></div>';
 }
 if (!b) return '<div class="ws-quota ws-quota-gray"><b>额度</b><span>还没有这一段的运行许可</span></div>';
 const num = value => Number.isFinite(Number(value)) ? `<code>${esc(value)}</code>` : '<code>未提供</code>';
 const usedPart = Number.isSafeInteger(used) ? `已用 ${num(used)} / ` : '';
 return `<div class="ws-quota"><b>额度</b><span>模型调用 ${usedPart}上限 ${num(b.model_calls)} · 检索 上限 ${num(b.search_calls)} · 每次最多 ${num(b.seconds)} 秒</span><em class="ws-ntag">工程记录</em><small>有效期以服务读到的运行许可为准，页面没有读到到期时间</small></div>`;
}

// ---------- scope page (8.6) ----------
function wsScopeConfirmed() { return rt.overview?.project?.intake_report?.necessary_clarification_complete === true; }
const wsIntOk = value => /^[1-9][0-9]*$/.test(String(value).trim());
function wsScopeMissing(values) {
 const missing = [], bytes = new TextEncoder().encode(values.note || '').length;
 if (!values.geography) missing.push('地域范围');
 if (values.geography === 'specified' && !String(values.geographyValue).trim()) missing.push('地区');
 if (!wsIntOk(values.target)) missing.push('正式文献目标');
 if (!wsIntOk(values.priority)) missing.push('优先阅读目标');
 if (!String(values.note || '').trim()) missing.push('范围说明');
 else if (bytes > 4096) missing.push('范围说明（超过 4096 字节）');
 return missing.length ? '还缺：' + missing.join('、') : '';
}
function wsScopeGate(app) {
 return wsScopeMissing(liveScopeValues()) || (wsReadonly() ? '这是历史归档，不能在这里改' : wsLock());
}
// Re-evaluates the confirm buttons without repainting, so typing keeps focus.
function wsPatchScopeButtons(app) {
 const gate = wsScopeGate(app);
 for (const button of app.el.querySelectorAll('[data-ws-confirm]')) {
  const reason = gate || (button.hasAttribute('data-ws-needs-check') && !app.wikiS1?.wsConsentOk ? '请先勾选确认' : '');
  button.disabled = !!reason;
  const why = button.parentElement.querySelector('.ws-why');
  if (why) { why.textContent = reason; why.hidden = !reason; }
 }
}
function wsScopePage(app) {
 const p = rt.overview?.project, values = liveScopeValues();
 const lock = wsLock(), readonly = wsReadonly();
 const disabled = lock || readonly ? 'disabled' : '';
 const choices = [['', '请明确选择'], ['specified', '指定地区'], ['unrestricted', '不限制'], ['not-applicable', '不适用']];
 const intOk = wsIntOk;
 const bytes = new TextEncoder().encode(values.note || '').length;
 const missingReason = wsScopeMissing(values);
 const err = (ok, value) => ok || value === '' ? '' : '<small class="ws-field-err">请填 1 以上的整数</small>';
 const checked = app.wikiS1?.wsConsentOk === true;
 const auto = wsAuto();
 // The service has no draft store for the scope; the form text is only kept in this page.
 const draftWhy = '后台还没有「范围草稿」，现在填的内容只留在这个页面里，刷新会丢';
 const gate = missingReason || (readonly ? '这是历史归档，不能在这里改' : lock);
 const form = `<section class="wiki-s1-card ws-scope" data-ws-scope-form><div class="ws-head"><h2>研究范围</h2><small>保存后生成「范围 v${esc(p?.input_version ?? 1)}」。以后修改会生成新版本，旧版本保留。</small></div>
 <div class="ws-grid">
  <label>研究主题<input value="${esc(p?.brief?.original_description || '')}" readonly></label>
  <label>地域范围<select data-live-geography ${disabled}>${choices.map(([v,l]) => `<option value="${v}" ${values.geography===v?'selected':''}>${l}</option>`).join('')}</select></label>
  ${values.geography === 'specified' ? `<label>地区<input data-live-geography-value maxlength="240" value="${esc(values.geographyValue)}" ${disabled} placeholder="选择指定地区时填写"></label>` : ''}
  <label>正式文献目标<input data-live-target type="number" min="1" value="${esc(values.target)}" ${disabled}><small>最后要纳入的篇数上限</small>${err(intOk(values.target), values.target)}</label>
  <label>优先阅读目标<input data-live-priority type="number" min="1" value="${esc(values.priority)}" ${disabled}><small>先精读的篇数</small>${err(intOk(values.priority), values.priority)}</label>
  <label class="ws-wide">范围说明<textarea data-live-scope rows="3" ${disabled}>${esc(values.note)}</textarea>${bytes > 4096 ? '<small class="ws-field-err">超过 4096 字节</small>' : '<small>必填，最多 4096 字节</small>'}</label>
 </div></section>`;
 let card;
 if (readonly) card = `<section class="decide ws-decide">${wsArchiveNote}</section>`;
 else if (auto.installed === true && !auto.blocked) {
  // 4a: a consent file was supplied at startup. Its contents are not readable from the page yet.
  const rows = [['有没有', '有', '这次启动带了同意书；页面读不到它的内容，核对由服务做'],
   ['覆盖 Stage 1', '还没有', '后台没有给出同意书内容的只读接口，页面不能显示它是否覆盖这一段'],
   ['覆盖 Stage 2、Stage 3', '没覆盖', '到那一段时要你单独接通'],
   ['有效到', '还没有', '后台没有给出到期时间的只读接口'],
   ['这一段的运行许可', wsBudget().b && Number(wsBudget().b.model_calls) > 0 ? '有' : '没有', '有同意书还不够，推进前还要有这一段的运行许可']];
  card = `<section class="decide ws-decide" data-ws-consent="provided"><span class="ws-label">你要点的第 1 处</span><h2>确认范围，并按这次启动带来的同意书开始</h2>
  <p>同意书是启动 Wiki 时带进来的，页面不能改它，只能照它推进。到上限或过了有效期就停。</p>
  <table class="ws-limits"><thead><tr><th>这份同意书</th><th>现在怎样</th><th>说明</th></tr></thead><tbody>${rows.map(r => `<tr><th scope="row">${r[0]}</th><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('')}</tbody></table>
  ${wsQuota()}
  <label class="ws-check"><input type="checkbox" data-ws-consent-check ${checked ? 'checked' : ''}> 我确认上面的范围，并同意按这份同意书自动推进 Stage 1。选方向和对评审的决定仍然由我本人做。</label>
  <div class="ws-actions">${wsBtn('确认范围并开始自动推进', 'data-ws-confirm="advance" data-ws-needs-check', gate || (checked ? '' : '请先勾选确认'), 'hs-button-primary')}${wsBtn('只保存范围草稿', 'data-ws-draft', draftWhy)}</div></section>`;
 } else {
  const blockedLine = auto.blocked ? `<p class="ws-blocked">${wsTag('block','被拦下')} 同意书用不了：${esc(auto.text)}。下面改按逐步授权走。</p>` : '';
  card = `<section class="decide ws-decide" data-ws-consent="${auto.blocked ? 'unusable' : 'absent'}"><span class="ws-label">你要点的第 1 处</span><h2>保存并确认范围</h2>
  ${blockedLine}<p>这次启动没有提供整轮同意书，所以后面每一步开始前都会单独请你授权。</p>
  <ol class="ws-preview"><li><b>现在：</b>只保存范围，不检索、不调用模型</li><li><b>接着：</b>到「运行与操作」授权一次检索规划，再授权执行查询</li><li><b>之后：</b>来源获取、阅读各自授权</li></ol>
  <div class="ws-actions">${wsBtn('保存并确认范围', 'data-ws-confirm="save"', gate, 'hs-button-primary')}${wsBtn('只保存范围草稿', 'data-ws-draft', draftWhy)}</div></section>`;
 }
 const note = rt.error ? `<div class="live-error ws-err" role="alert">${wsTag('err','出错')} 没有保存：${esc(rt.error)}，表单内容保留。</div>` : '';
 const busy = rt.busy ? `<p class="ws-run" role="status">${wsTag('run','进行中')} 正在保存范围</p>` : '';
 return `<section data-wiki-ops="scope" aria-label="确认范围">${note}${busy}${form}${card}
 <p class="wiki-s1-muted">范围表单里的「初始化」不再是单独的按钮：保存范围后页面会接着建立本课题的本地记录。</p></section>`;
}

// ---------- run tab: seven-row process table (8.7) ----------
function wsPhaseRows() {
 const phases = rt.overview?.stage1?.progress?.phases;
 const kinds = {recorded:'done', partial:'part', available:'wait', required:'wait', held:'block', running:'run',
  pending:'idle', unconnected:'idle', unknown:'block'};
 const rows = []; let before = true;
 for (const id of Object.keys(wsPhaseNames)) {
  const found = phases?.find(row => row.phase_id === id);
  let kind = found ? kinds[found.status] || 'idle' : 'idle';
  let label = '';
  if (kind === 'wait' && !before) { kind = 'idle'; label = '未开始'; }
  if (kind === 'wait' && id === 'scope') label = '等你';
  rows.push({id, name:wsPhaseNames[id], kind, label, raw:found || null,
   reason:wsReasons[found?.reason] || (found?.reason ? '' : '还没有读到这一步的状态')});
  before = before && kind === 'done';
 }
 return rows;
}
function wsScopeSummary() {
 const p = rt.overview?.project, scope = p?.intake_report?.scope;
 if (!wsScopeConfirmed()) return '还没有确认范围';
 const geo = scope?.geography, names = {unrestricted:'不限制', 'not-applicable':'不适用'};
 const geoText = geo?.status === 'specified' ? '指定地区：' + (geo.value ?? '未提供') : names[geo?.status] || '未提供';
 const target = p.intake_report.formal_final_count?.target, priority = scope?.priority_reading_target?.value;
 return `范围 v${p.input_version} · ${geoText} · 文献目标 ${target ?? '未提供'} · 优先阅读 ${priority ?? '未提供'}`;
}
function wsHasConsent() { return wsAuto().installed === true && !wsAuto().blocked; }
function wsLibraryCounts() {
 const library = rt.library;
 if (!library?.rows) return null;
 const count = key => library.rows.filter(row => row.screening_status === key).length;
 return {include:count('include'), exclude:count('exclude'), pending:count('pending'), loaded:library.rows.length, total:library.total};
}
function wsSavedPlan() {
 return (rt.modelHistory?.actions || []).some(a => (a.result || a).operation === 'plan-search' && (a.result || a).output_ref);
}
function wsSummary(row) {
 const s = rt.overview?.stage1, queries = Array.isArray(s?.queries) ? s.queries : [];
 if (row.id === 'scope') return wsScopeSummary();
 if (row.id === 'planning') return wsSavedPlan() ? '规划已保存' : row.reason || '还没有检索规划';
 if (row.id === 'query') return queries.length ? `已记录 ${queries.length} 条查询意图` : row.reason || '还没有查询';
 if (row.id === 'screening') {
  const c = wsLibraryCounts();
  return c ? `纳入 ${c.include} · 排除 ${c.exclude} · 待定 ${c.pending}${c.loaded < c.total ? `（已读取 ${c.loaded} / ${c.total} 条）` : ''}` : row.reason || '还没有可筛选的检索结果';
 }
 if (row.id === 'reading') {
  const r = s?.reading_registration;
  return r?.status === 'ready' ? '阅读登记已完整' : r?.missing_works?.length ? `缺 ${r.missing_works.length} 篇文献的阅读登记` : row.reason || '阅读还没完成';
 }
 if (row.id === 'coverage') return s?.coverage_actions?.blockers?.length ? `现在卡着 ${s.coverage_actions.blockers.length} 件事` : row.reason || '暂时没有阻塞记录';
 return s?.delivery?.canonical_package ? '交付已保存，等待审阅' : row.reason || '还没有生成交付';
}
function wsQueryTable() {
 const queries = rt.overview?.stage1?.queries;
 if (!Array.isArray(queries) || !queries.length) return '<p class="wiki-s1-muted">这里还没有查询。有了检索规划、你再授权执行以后才会出现。</p>';
 const names = {'intent-recorded-not-executed':'已记录，还没执行', 'not-executed':'还没执行'};
 return `<div class="ws-scroll"><table class="ws-table"><thead><tr><th scope="col">检索词</th><th scope="col">用途</th><th scope="col">状态</th><th scope="col">返回条数</th></tr></thead><tbody>${queries.map(q => `<tr><td>${esc(q.query ?? '未提供')}</td><td>${esc(q.purpose ?? '未提供')}</td><td>${esc(names[q.status] || q.status || '未提供')}</td><td>未提供</td></tr>`).join('')}</tbody></table></div><p class="wiki-s1-muted">每个检索渠道的返回条数、去重后条数和是否截断，后台还没有按查询给出，所以先写「未提供」。</p>`;
}
function wsPlanDetail(consent) {
 const p = rt.overview.project, offers = realModelOffers(), offer = offers.find(o => o.available && o.operation === 'plan-search');
 const planning = realPlanningState(), lock = wsLock();
 const remaining = Math.max(0, (p.settings?.budgets?.model_calls || 0) - (rt.overview.models?.calls_reserved || 0));
 const scoped = wsScopeConfirmed(), ro = wsReadonly();
 const blockedModel = !planning.allowed ? '模型任务还有未确认的结果。检查原任务，不重发；原记录和已预留的额度保留' : '';
 const common = ro ? '这是历史归档，不能在这里改' : lock;
 const authorizeWhy = common || (!scoped ? '还没有确认范围' : blockedModel || (!remaining ? '没有可用的额度' : '') || (wsLockedChecks('plan') ? '' : '请先勾选确认'));
 const planWhy = common || (!scoped ? '还没有确认范围' : blockedModel || (offer ? '' : '没有本课题的运行许可，见连接与设置'));
 const reviewable = wsSavedPlan();
 const stepwise = !consent;
 return `${realPlanningFailure()}
 ${stepwise && !ro ? `<section class="ws-grant" data-ws-grant="plan"><span class="ws-label">授权：检索规划</span><p><b>会做：</b>让 Codex 规划查询。<b>不会做：</b>不检索、不读来源。</p>${wsQuota()}
 <label class="ws-check"><input type="checkbox" data-ws-check="plan" ${wsLockedChecks('plan') ? 'checked' : ''}> 我确认只授权这一次、这一件事</label>
 <div class="ws-actions">${wsBtn('授权一次检索规划', 'data-real-action="authorize-plan" data-ws-gate="plan"', authorizeWhy)}${wsBtn('运行 Codex 检索规划', 'data-real-action="plan"', planWhy, 'hs-button-primary')}</div></section>` : ''}
 <div class="ws-actions">${reviewable ? wsBtn('审阅已保存规划', 'data-real-action="review-plan"', common) : ''}</div>
 <h4>已保存的检索规划</h4>${wsPlanTable()}
 ${ro ? '' : `<details class="ws-adv"><summary>高级</summary><p class="wiki-s1-muted">这是审阅导入，不是新模型输出；原模型输出保持保存。</p>${rt.overview.project.intake_report?.necessary_clarification_complete === true && rt.overview.project.plan === null ? wsBtn('导入已有规划（不调用模型）', 'data-real-action="import-plan"', common || (realPlanImportReady() ? '' : '现在还不能导入：要先有确认过的范围，且没有进行中的任务')) : '<p class="wiki-s1-muted">现在还不能导入：这个课题已经有规划，或范围还没确认。</p>'}${wsPlanDraft()}</details>`}`;
}
function wsLockedChecks(id) { return apps[0]?.wikiS1?.wsChecks?.[id] === true; }
function wsPlanTable() {
 const queries = rt.overview?.stage1?.queries;
 if (!wsSavedPlan() && !(Array.isArray(queries) && queries.length)) return '<p class="wiki-s1-muted">这里还没有检索规划。授权并运行以后，每条查询会列在这里。</p>';
 return `<p class="wiki-s1-muted">${wsSavedPlan() ? 'Codex 本次生成' : '后台记录的查询意图'}（原模型输出在「审阅已保存规划」里，修订不覆盖原文）</p>${wsQueryTable()}`;
}
function wsPlanDraft() {
 // The existing renderer owns the draft editor; show it inside the advanced fold when active.
 if (!realPlanDraftCurrent()) return '';
 const d = rt.planDraft;
 return `<div class="ws-draft"><label>规划原文<textarea data-real-plan rows="8" maxlength="65536">${esc(d.text || '')}</textarea></label>${wsBtn('校验并保存修订', 'data-real-action="compile-plan"', wsLock())}</div>`;
}
function wsQueryDetail(consent) {
 const s = rt.overview.stage1, q = s.query_execution, lock = wsLock(), ro = wsReadonly();
 const common = ro ? '这是历史归档，不能在这里改' : lock;
 const step = (key, label, prerequisite) => wsBtn(label, `data-real-action="${key}"`, common || (q?.[prerequisite] ? '' : '现在还不能做这一步：' + (q ? '服务当时没有给出这个操作' : '查询执行还没接通')));
 const owner = realQueryOwnerOffer();
 const stepwise = consent ? '' : `<section class="ws-grant" data-ws-grant="query"><span class="ws-label">授权：查询</span><p><b>会做：</b>按已保存的规划执行查询。<b>不会做：</b>不调用模型、不读论文全文。</p>${wsQuota()}</section>`;
 return `${stepwise}<div class="ws-actions">${consent ? '' : step('query-authorize', '授权已保存查询', 'authorization_offer')}${consent ? '' : step('query-bootstrap', '准备查询运行', 'bootstrap_offer')}${consent ? '' : step('query-execute', '执行当前查询', 'query_offer')}${wsBtn('刷新进度', 'data-live-action="refresh"', rt.loading ? '正在读取保存记录' : '')}${owner ? wsBtn('恢复已保存运行', 'data-real-action="query-restore-owner"', common) : ''}</div>
 ${owner ? '<p class="wiki-s1-muted">只恢复控制权和历史，不执行查询、不调用模型；下一步仍要你单独操作。</p>' : ''}
 ${consent ? '<p class="wiki-s1-muted">这一轮由同意书自动往下走，这里只有查看和刷新。</p>' : ''}
 <h4>查询</h4>${wsQueryTable()}<p class="wiki-s1-muted">下一个来源仍要用当前服务给出的操作，不会自动提交。</p>`;
}
function wsScreeningDetail() {
 const c = wsLibraryCounts();
 return `<p>${c ? `纳入 ${c.include} · 排除 ${c.exclude} · 待定 ${c.pending}` : '还没有可筛选的检索结果。'}</p><button type="button" class="hs-button" data-s1-tab="sources">去筛选</button>
 <p class="wiki-s1-muted">筛选决定要到「来源与图谱」里逐篇做；这里只汇总。</p>`;
}
function wsReadingDetail() {
 const s = rt.overview.stage1, r = s.reading_registration, lock = wsLock(), ro = wsReadonly();
 const ready = !!(s.ledger && s.checkpoint?.current === true && s.saved_records_connected === true && r?.status === 'ready' && r.grants_execution === false && r.missing_works?.length === 0 && realCurrent(r));
 const common = ro ? '这是历史归档，不能在这里改' : lock;
 return `<p>阅读登记：${esc(r?.status === 'ready' ? '已完整' : r?.status === 'unconnected' ? '保存记录还没接通' : r?.status ?? '未提供')} · 缺少登记的文献 ${esc(r?.missing_works?.length ?? '未提供')} 篇</p>
 <div class="ws-actions">${wsBtn('准备已审阅文献交付', 'data-v7-workflow="prepare"', common || (ready ? '' : '请先完成当前文献的阅读审阅登记'))}</div>
 <p class="wiki-s1-muted">单篇的来源获取和 Codex 阅读在「来源与图谱」里每篇论文的「这篇的处理」中做。</p>`;
}
function wsCoverageDetail() {
 const s = rt.overview.stage1, a = s.coverage_actions, lock = wsLock(), ro = wsReadonly();
 const blockers = (a?.blockers || []).map(x => typeof x === 'string' ? x : x.code);
 const round = a?.offers?.find(o => o.document?.round_number != null)?.document?.round_number;
 return `<p class="wiki-s1-muted">${esc(blockers.length ? '现在卡着：' + blockers.join('、') : '暂时没有阻塞记录')} · 目前第 ${esc(round ?? '未提供')} 轮 · <button type="button" class="ws-link" data-s1-tab="synthesis">看综合</button></p>
 <div class="ws-actions">${wsBtn('检查当前覆盖与状态', 'data-v7-workflow="checkpoint"', ro ? '这是历史归档，不能在这里改' : lock || (s.ledger ? '' : '现在还不能做这一步：还没有检索记录'))}</div>
 ${ro ? '' : wsCoverageForm()}<p class="ws-note">数量不能代替研究覆盖验收</p>`;
}
function wsCoverageForm() {
 const html = realCoverage();
 return html ? html.replace('<details class="real-workflow">', '<details class="real-workflow ws-cov" open>') : '<p class="wiki-s1-muted">现在没有服务给出的覆盖审阅操作。</p>';
}
// ---------- delivery (8.11) ----------
function wsDeliveryDetail(app) {
 const s = rt.overview.stage1, offer = s.delivery?.offers?.find(o => o.status === 'ready-for-saved-evidence-delivery');
 const lock = wsLock(), ro = wsReadonly(), saved = !!s.delivery?.canonical_package;
 const common = ro ? '这是历史归档，不能在这里改' : lock;
 const checks = wsPhaseRows().filter(r => r.id !== 'delivery');
 const table = `<table class="ws-table"><thead><tr><th scope="col">检查项</th><th scope="col">结果</th><th scope="col">缺什么</th></tr></thead><tbody>${checks.map(r => `<tr><th scope="row">${esc(r.name)}</th><td>${wsTag(r.kind, r.label)}</td><td>${r.kind === 'done' ? '—' : `<span class="ws-amber">${esc(r.reason || '未提供')}</span>`}</td></tr>`).join('')}</tbody></table>`;
 const context = rt.atlas?.stage2_input;
 return `<div class="ws-actions">${wsBtn(saved ? '重新检查当前交付' : '生成已保存证据的交付', 'data-live-action="deliver"', common || (offer ? '' : '现在还不能做这一步：还没有可交付的已保存证据'), 'hs-button-primary')}</div>
 <p class="wiki-s1-muted">只处理已保存的来源，不是启动检索，也不是自动完成 Stage 1。</p>
 <p>${saved ? wsTag('done', '已保存') + ' 交付已保存，等待审阅' : wsTag('idle', '未开始') + ' 还没有生成交付'}</p>${table}
 <details class="ws-tech"><summary>技术细节：原始检查记录</summary><pre>${esc(JSON.stringify(s.progress?.phases ?? null, null, 2))}</pre></details>
 ${wsDecision(app, context, ro)}`;
}
function wsDecision(app, context, ro) {
 const eligible = context?.eligible_for_stage2;
 const choice = app.wikiS1?.wsDecision || '';
 const lock = wsLock();
 const options = [['keep-stage1', '继续补充 Stage 1'], ['hold', '暂缓交接'], ['request-stage2', '申请进入 Stage 2']];
 const saved = context?.review;
 if (ro) return `<section class="decide ws-decide">${wsArchiveNote}</section>`;
 if (!context) return '<section class="decide ws-decide"><span class="ws-label">你的决定</span><h3>Stage 1 的交付怎么处理？</h3><p class="wiki-s1-muted">还没有交付，生成交付以后才能保存审阅记录。</p></section>';
 const reasons = eligible === true ? '' : '<small class="ws-why">申请进入 Stage 2 现在灰着：Stage 1 的交接条件还没满足</small>';
 return `<section class="decide ws-decide" data-ws-decision><span class="ws-label">你的决定</span><h3>Stage 1 的交付怎么处理？</h3>
 <div class="ws-choices" role="radiogroup" aria-label="Stage 1 的交付怎么处理">${options.map(([v, l]) => `<label class="choice"><input type="radio" name="ws-decision" value="${v}" data-ws-decision-radio ${choice === v ? 'checked' : ''} ${v === 'request-stage2' && eligible !== true ? 'disabled' : ''}> ${l}</label>`).join('')}</div>${reasons}
 <select data-live-decision hidden aria-hidden="true">${options.map(([v, l]) => `<option value="${v}" ${choice === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
 <label>审阅意见<textarea data-live-review rows="3" maxlength="4096">${esc(rt.draft)}</textarea></label>
 <p>进入资格：${eligible === true ? wsTag('done', '已满足记录的条件') : wsTag('block', '未满足；申请不会改变这个状态')}</p>
 <p class="wiki-s1-muted">申请只保存你的审阅意见，不会自动放行，也不会运行下一段。</p>
 ${wsBtn('保存审阅记录', 'data-live-action="review"', lock || (choice ? '' : '请先选一个') || (rt.draft && rt.draft.trim() ? '' : '请先写审阅意见'), 'hs-button-primary')}
 <h4>已保存的审阅记录</h4>${saved ? `<pre class="live-record">${esc(JSON.stringify(saved, null, 2))}</pre>` : '<p class="wiki-s1-muted">还没有审阅记录</p>'}</section>`;
}

function wsRowDetail(app, row, consent) {
 if (row.id === 'scope') return `<p>${esc(wsScopeSummary())}</p><p class="wiki-s1-muted">范围已确认，表单不再修改。要改范围会生成新版本；后台现在还没有这个操作，所以「修改范围」暂时不能点。</p>${wsBtn('修改范围', 'data-ws-edit-scope', '现在还不能做这一步：后台还没有生成新范围版本的操作')}`;
 if (row.id === 'planning') return wsPlanDetail(consent);
 if (row.id === 'query') return wsQueryDetail(consent);
 if (row.id === 'screening') return wsScreeningDetail();
 if (row.id === 'reading') return wsReadingDetail();
 if (row.id === 'coverage') return wsCoverageDetail();
 return wsDeliveryDetail(app);
}
function wsRunTab(app) {
 if (!rt.overview?.stage1) return '<section class="wiki-s1-card"><h2>运行与操作</h2><p class="wiki-s1-muted">这里还没有读到本课题的保存记录。</p></section>';
 const state = app.wikiS1, consent = wsHasConsent(), rows = wsPhaseRows();
 const open = state.wsOpen || (state.wsOpen = new Set());
 if (!state.wsOpenInit) { state.wsOpenInit = true; const first = rows.find(r => r.kind === 'wait' || r.kind === 'block' || r.kind === 'run'); if (first) open.add(first.id); }
 const ro = wsReadonly();
 return `<section class="wiki-s1-card ws-run-tab" data-wiki-ops="run" aria-label="运行与操作">${wsQuota()}${wsAutoRow()}
 ${rt.error ? `<div class="live-error ws-err" role="alert">${wsTag('err', '出错')} ${esc(rt.error)}</div>` : ''}
 <div class="ws-ps" role="list">${rows.map((row, i) => `<details class="ws-ps-row" data-ws-row="${row.id}" ${open.has(row.id) ? 'open' : ''} role="listitem"><summary><span class="ws-dot">${i + 1}</span><b>${row.name}</b>${wsTag(row.kind, row.label)}<span class="ws-result">${esc(wsSummary(row))}</span></summary><div class="ws-detail">${wsRowDetail(app, row, consent)}</div></details>`).join('')}</div>
 <details class="ws-tech"><summary>技术细节：原始进度记录</summary><pre>${esc(JSON.stringify(rt.overview.stage1.progress ?? null, null, 2))}</pre></details></section>`;
}

// ---------- hooks into the existing Stage 1 results page ----------
function wsOpsActive(app) {
 return wikiS1Active(app) && !!rt.ref && (!!rt.overview?.project || wsReadonly());
}
wikiS1Tabs.ops = '运行与操作';
const wsPrevResults = wikiS1Results;
wikiS1Results = function (app) {
 if (!wsOpsActive(app)) return wsPrevResults(app);
 if (rt.overview?.project && !wsReadonly() && !wsScopeConfirmed()) {
  wikiS1State(app, null);
  return `<section data-wiki-s1 data-wiki-ops-root aria-label="确认范围">${wsScopePage(app)}</section>`;
 }
 const state = wikiS1State(app, wikiS1Index());
 if (!state.wsTabInit) { state.wsTabInit = true; if (!wikiS1Index()) state.tab = 'ops'; }
 const html = wsPrevResults(app);
 if (state.tab === 'ops') {
  const panel = rt.overview?.stage1 ? wsRunTab(app) : `<section class="wiki-s1-card"><h2>运行与操作</h2>${wsArchiveNote}</section>`;
  return html.replace(/(<div role="tabpanel"[^>]*>)[\s\S]*(<\/div>\s*<\/section>\s*)$/, (all, open, close) => open + panel + close);
 }
 if (state.tab === 'sources' && !wikiS1Index()) {
  return html.replace(/(<div role="tabpanel"[^>]*>)[\s\S]*(<\/div>\s*<\/section>\s*)$/, (all, open, close) => open + wsCandidatePanel() + close);
 }
 return html;
};

const wsPrevAfter = v7AfterRender;
v7AfterRender = function (app) {
 wsPrevAfter(app);
 if (!wsOpsActive(app) || !app.el.querySelector('[data-wiki-s1]')) return;
 wsProgLoad();
 // The old operations body is replaced by the new tab; keep it in the DOM (other handlers read it) but hidden.
 for (const node of app.el.querySelectorAll('.lp-operations .lp-ops-body > :not([data-v7-expansion-panel])')) node.hidden = true;
 // Old per-paper blocks live in the saved-output panel; the new paper card replaces them. Keep them mounted, hidden.
 for (const node of app.el.querySelectorAll('[data-v7-paper-review],[data-v7-reading-review]')) node.hidden = true;
 for (const node of app.el.querySelectorAll('[data-wiki-s1-output] section.live-files')) if (/^已保存的检索候选/.test(node.querySelector('h3')?.textContent || '')) node.hidden = true;
 const slot = app.el.querySelector('[data-ws-expansion-slot]'), expansion = app.el.querySelector('.lp-operations [data-v7-expansion-panel]');
 if (slot && expansion) slot.append(expansion);
 for (const box of app.el.querySelectorAll('.lp-operations')) box.hidden = ![...box.querySelectorAll('.lp-ops-body > *')].some(node => !node.hidden);
 const scopePage = app.el.querySelector('[data-wiki-ops="scope"]'), shell = app.el.querySelector('[data-wiki-shell]');
 if (scopePage && shell) {
  const info = shell.querySelectorAll('dd');
  if (info.length >= 3) {
   info[0].textContent = '还没有确认范围。确认之前不会检索、不会调用模型';
   info[1].textContent = wsHasConsent() ? '你确认范围后，Stage 1 的检索、筛选、阅读按同意书自动推进' : '你保存范围后，到「运行与操作」逐步授权：先授权一次检索规划';
   info[2].textContent = '等你：确认范围和授权 ';
   info[2].insertAdjacentHTML('beforeend', '<button type="button" class="hs-button" data-ws-go="scope">去确认</button>');
  }
  const record = app.el.querySelector('[data-wiki-record]');
  if (record && !record.querySelector('.wiki-record-chip')?.nextElementSibling) record.insertAdjacentHTML('beforeend', '<span>这一段还没有运行，没有记录。</span>');
 }
};

// ---------- scope confirmation: the existing "confirm" body, then initialization, then optional advance ----------
async function wsConfirmScope(advance) {
 const p = rt.overview?.project;
 if (!p || wsLock() || wsReadonly()) return;
 const values = liveScopeValues(), note = String(values.note || '').trim();
 const target = Number(values.target), priority = Number(values.priority);
 if (!values.geography || !note || (values.geography === 'specified' && !String(values.geographyValue).trim()) ||
  !Number.isSafeInteger(target) || target < 1 || !Number.isSafeInteger(priority) || priority < 1 || new TextEncoder().encode(note).length > 4096) {
  rt.error = '请先把范围填完整'; livePaint(); return;
 }
 await livePost('confirm', {...liveBound(), choices:[{field:'geography', status:values.geography,
  value:values.geography === 'specified' ? String(values.geographyValue).trim() : null, reason:note, user_input:note}],
  formal_target:target, priority_reading_target:priority,
  resource_envelope:'No model or external search authorized by this scope confirmation.',
  budgets:{model_calls:0, seconds:0, search_calls:0, source_reads:0, rounds:0},
  consent:{external_search:false, public_source_read:false, browser_fallback:false}, user_input:note, confirmed:true});
 if (rt.error) return;
 // The old page offered a separate "initialize" button; the new page does it as part of the same click.
 const offer = typeof realInitializationOffer === 'function' ? realInitializationOffer() : null;
 if (offer) {
  await livePost('stage1/initialize', {...liveBound(), offer_ref:offer.offer_ref, offer_sha256:offer.offer_sha256, confirmed:true});
  if (rt.error) { rt.error = '范围已保存，但没能建立这个课题的本地记录：' + rt.error; livePaint(); return; }
 }
 if (advance) await wsAdvance();
}

document.addEventListener('click', event => {
 const app = apps[0], target = event.target.closest('[data-ws-confirm],[data-ws-advance],[data-ws-go],[data-ws-draft]');
 if (!target || target.disabled || !wsOpsActive(app)) return;
 event.preventDefault(); event.stopImmediatePropagation();
 if (target.dataset.wsConfirm) { wsConfirmScope(target.dataset.wsConfirm === 'advance'); return; }
 if (target.hasAttribute('data-ws-advance')) { wsAdvance(); return; }
 const go = target.dataset.wsGo;
 if (go === 'scope') app.el.querySelector('[data-ws-consent]')?.scrollIntoView({behavior:'smooth', block:'center'});
 else if (go === 'settings' || go === 'history') app.el.querySelector(`[data-page="${go}"]`)?.click();
 else if (go === 'stage2') app.el.querySelector('[data-stage="2"]')?.click();
}, true);
document.addEventListener('change', event => {
 const app = apps[0];
 if (!wsOpsActive(app) || !app.wikiS1) return;
 const state = app.wikiS1, target = event.target;
 if (target.matches('[data-ws-consent-check]')) {
  state.wsConsentOk = target.checked;
  wsPatchScopeButtons(app);
 } else if (target.matches('[data-ws-check]')) {
  state.wsChecks = {...state.wsChecks, [target.dataset.wsCheck]:target.checked};
  livePaint();
 } else if (target.matches('[data-ws-decision-radio]')) {
  state.wsDecision = target.value;
  const select = app.el.querySelector('select[data-live-decision]');
  if (select) select.value = target.value;
  livePaint();
 }
});
document.addEventListener('toggle', event => {
 const row = event.target;
 if (!row.isConnected || !row.matches?.('[data-ws-row]') || !apps[0].wikiS1?.wsOpen) return;
 const set = apps[0].wikiS1.wsOpen;
 row.open ? set.add(row.dataset.wsRow) : set.delete(row.dataset.wsRow);
}, true);

document.addEventListener('input', event => {
 const app = apps[0];
 if (event.target.closest?.('[data-ws-scope-form]') && wsOpsActive(app)) wsPatchScopeButtons(app);
});
document.addEventListener('change', event => {
 if (event.target.matches?.('[data-ws-scope-form] [data-live-geography]') && wsOpsActive(apps[0])) livePaint();
});

// ---------- 8.8 / 8.9 / 8.10: per-paper processing, evidence review, relation names ----------
// Seven relation names from DESIGN 8.9 (the old "不支持" becomes "相互矛盾").
Object.assign(wikiS1Relations, {contradicts:'相互矛盾', pending:'未核对', unclear:'不清楚', unverifiable:'无法核实', context:'只是背景'});
Object.assign(wikiS1Checks, {contradicts:'✕ 相互矛盾', unclear:'? 不清楚', unverifiable:'⊘ 无法核实', context:'· 只是背景'});
const wsPrevCheck = wikiS1Check;
wikiS1Check = function (claim) {
 const base = wsPrevCheck(claim);
 if (base !== 'unchecked') return base;
 const verifier = claim.core_event?.payload?.verifier;
 return verifier?.actor_type === 'human' && claim.locator && ['unclear','unverifiable','context'].includes(claim.relation) ? claim.relation : 'unchecked';
};
const wsScreenNames = {include:'纳入', exclude:'排除', pending:'待定', 'not-screened':'未筛选'};
const wsRelationOptions = [['pending','未核对（还没判断）'], ['supports','支持'], ['partial','部分支持'], ['contradicts','相互矛盾'],
 ['unclear','不清楚'], ['unverifiable','无法核实'], ['context','只是背景']];
const wsNoteGroups = [['分类', [['classification','topic_cluster'],['classification','method'],['classification','geography'],['classification','population'],['classification','data_type'],['classification','domain']]],
 ['内容', [['findings','question'],['findings','method'],['findings','data'],['findings','main_findings'],['findings','limitations']]],
 ['和本课题的关系', [['findings','relevance'],['findings','transferability']]]];
const wsFieldNames = {topic_cluster:'主题', method:'方法', geography:'地区', population:'研究对象', data_type:'数据类型', domain:'领域',
 question:'研究问题', data:'数据', main_findings:'主要发现', limitations:'局限', relevance:'相关性', transferability:'可迁移性'};

function wsDetailFor(workId) {
 const d = rt.paperDetail, ledger = rt.overview?.stage1?.ledger?.state_sha256;
 return d && workId && realCurrent(d) && d.binding?.ledger_state_sha256 === ledger && d.row?.work_id === workId ? d : null;
}
function wsLibraryRowFor(workId) { return (rt.library?.rows || []).find(row => row.work_id === workId); }
function wsSourceState(d) {
 const source = rt.overview?.stage1?.source_execution, jobs = Object.values(source?.jobs || {}).filter(job => job.work_ref === d.row.work_id);
 if (d.reading_offer?.available) return ['done', '已有可读来源', ''];
 const status = d.row.source_status;
 if (status === 'saved-import-bytes-recorded' || status === 'saved-import-intent-recorded') return ['done', '已获取', '已保存来源笔记'];
 if (jobs.some(job => job.status && !['saved', 'failed'].includes(job.status))) return ['run', '进行中', '正在获取'];
 const failures = jobs.filter(job => job.failure?.code || job.followup?.failure?.code);
 if (failures.length) return ['err', '失败', failures.map((job, i) => `第 ${i + 1} 次：${job.failure?.code || job.followup?.failure?.code}`).join('；')];
 return ['idle', '未获取', ''];
}
function wsNotes(view) {
 if (!view || !realCurrent(view)) return '<p class="wiki-s1-muted">还没有阅读。</p>';
 const source = view.source_mode === 'saved-source-review', notes = source ? view : view.draft, offer = view.reading_review_offer;
 if (!notes) return '<p class="wiki-s1-muted">还没有阅读。</p>';
 const lock = wsLock();
 return `<div class="ws-notes"><p class="wiki-s1-muted">原始输出保持不变，只保存你确认的注释；无法核实的字段写「未提供」。</p>
 <details><summary>查看来源与原文</summary><pre class="live-record">${esc(JSON.stringify(source ? {sources:view.sources, claims:view.claims} : view.draft, null, 2))}</pre></details>
 <details open><summary>编辑阅读笔记</summary>${wsNoteGroups.map(([title, fields]) => `<h5>${title}</h5><div class="ws-grid">${fields.map(([group, key]) => `<label>${wsFieldNames[key]}<textarea rows="2" maxlength="4096" data-v7-note="${group}.${key}">${esc(notes[group]?.[key] ?? '未提供')}</textarea></label>`).join('')}</div>`).join('')}
 <label class="ws-check"><input type="checkbox" data-v7-reading-confirm data-ws-gate-confirm> 我已审阅这些注释；保存不代表 Stage 1 完成</label>
 ${wsBtn('保存审阅笔记', 'data-v7-workflow="reading-save" data-ws-needs-confirm' + (offer?.offer_ref ? '' : ' data-ws-blocked'), lock || (!offer?.offer_ref ? '现在还不能做这一步：服务没有给出保存审阅笔记的操作' : '请先勾选「我已审阅这些注释」'))}</details></div>`;
}
function wsPaperProcess(workId) {
 if (!workId) return '';
 const ro = wsReadonly(), d = wsDetailFor(workId), row = wsLibraryRowFor(workId);
 const head = '<section class="ws-process" data-ws-process><h4>这篇的处理</h4>';
 if (ro) return head + wsArchiveNote + '</section>';
 if (!d) {
  const why = row ? '' : '这篇还没有出现在已保存的检索候选里，所以没有可处理的记录';
  return head + `<p class="wiki-s1-muted">先读取这篇的保存记录，再做筛选、来源获取和阅读。三件事各自单独做。</p>${wsBtn('读取这篇的处理', `data-ws-load-paper="${esc(row?.index ?? '')}"`, why || wsLock())}</section>`;
 }
 const lock = wsLock(), current = wsScreenNames[d.row.screening_status] || '未筛选';
 const source = rt.overview.stage1.source_execution, grants = Object.values(source?.grants || {});
 const jobs = Object.values(source?.jobs || {});
 const p = rt.overview.project;
 const allowed = (realActionEnvelope(source) ? grants : []).filter(g => g.work_ref === workId && g.status === 'authorized' && g.input_version === p.input_version && g.brief_sha256 === p.brief_sha256 && g.expires_at * 1000 > Date.now() && !jobs.some(j => j.grant_ref === g.grant_ref));
 const offers = realModelOffers(), reading = offers.filter(o => realReadingExecutable(o) && (!o.work_ref || o.work_ref === workId));
 const [sourceKind, sourceLabel, sourceNote] = wsSourceState(d);
 const offer = rt.sourceOffer && rt.sourceOffer.work_ref === workId ? rt.sourceOffer : null;
 const sourceOff = source ? '' : '来源获取现在不可用';
 return head + `
 <div class="ws-step"><h5>筛选决定 <span class="ws-tag ws-idle">现在：${esc(current)}</span></h5>
  <div class="ws-choices" role="radiogroup" aria-label="筛选决定">${[['include','纳入'],['exclude','排除'],['pending','待定']].map(([v, l]) => `<label class="choice"><input type="radio" name="ws-screen" value="${v}" data-ws-screen-radio> ${l}</label>`).join('')}</div>
  <select data-v7-screen hidden aria-hidden="true"><option value="pending">待定</option><option value="include">纳入</option><option value="exclude">排除</option></select>
  <label>决定理由（可选，最多 4096 字节）<textarea data-v7-screen-note rows="2" maxlength="4096"></textarea></label>
  ${wsBtn('保存筛选决定', 'data-v7-workflow="screen" data-ws-needs-screen', lock || '请先选一个')}<small class="wiki-s1-muted">筛选决定只更新这一篇；来源获取和阅读要单独做</small></div>
 <details class="ws-step" ${sourceKind === 'run' || sourceKind === 'err' ? 'open' : ''}><summary><b>来源与许可范围</b> ${wsTag(sourceKind, sourceLabel)} ${esc(sourceNote)}</summary>
  ${sourceKind === 'done' && d.reading_offer?.available ? '<p>已有可读来源，不再需要授权。</p>' : `
  <div class="ws-actions">${wsBtn('查看公开来源获取条件', 'data-v7-workflow="source-preview"', lock || sourceOff)}</div>
  ${offer ? `<p>来源获取条件：${esc(offer.status || offer.blocked_reason || offer.refusal || '未提供')}</p><details class="ws-tech"><summary>技术细节：来源与许可范围原文</summary><pre>${esc(JSON.stringify(offer, null, 2))}</pre></details>
  <section class="ws-grant"><span class="ws-label">授权：公开来源获取</span><p><b>会做：</b>只读取这一份公开来源。<b>不会做：</b>不读别的来源、不调用模型。</p>${wsBtn('授权此公开来源获取', 'data-v7-workflow="source-authorize"', lock || sourceOff || (offer.runner_connected === true && offer.offer_ref && offer.offer_sha256 ? '' : '不在授权范围：这份来源现在没有可用的获取许可'))}</section>` : ''}
  ${allowed.map(g => `<div class="ws-actions">${wsBtn('执行已授权来源获取', `data-v7-workflow="source-execute" data-v7-index="${grants.indexOf(g)}"`, lock)}</div>`).join('')}`}
  ${sourceKind === 'err' ? `<p class="ws-amber">${esc(sourceNote)}</p>` : ''}</details>
 <div class="ws-step"><h5>Codex 阅读 <span class="ws-tag ws-idle">${rt.readingView && realCurrent(rt.readingView) ? '已有阅读' : '还没有阅读'}</span></h5>
  <p>阅读条件：${esc(d.reading_offer?.available ? '已有可读来源' : d.reading_offer?.blocked_reason ?? '要先获取到可读来源')}</p>
  <section class="ws-grant"><span class="ws-label">授权：Codex 阅读</span><p>只读取这份已保存来源；这段说明保存到授权记录，<b>不会改 Harness 的阅读提示词</b>。</p>
  <label>本次阅读授权说明<textarea data-v7-reading-consent rows="2" maxlength="4096" placeholder="确认本次只读取这份已保存来源；此说明保存到授权记录。"></textarea></label>
  ${wsBtn('授权一次 Codex 阅读', 'data-v7-workflow="reading-authorize"', lock || (realReadingOffer(d) ? '' : '阅读还没有可用的来源或额度'))}
  ${reading.map(o => wsBtn('运行已授权 Codex 阅读', `data-v7-workflow="reading-execute" data-v7-index="${offers.indexOf(o)}"`, lock)).join('')}
  ${wsBtn('审阅已保存来源笔记', 'data-v7-workflow="source-review"', lock || (d.reading_offer?.available ? '' : '要先获取到可读来源'))}</section>
  ${wsNotes(rt.readingView)}</div>
 <div class="ws-step" data-ws-expansion-slot></div></section>`;
}
// Candidate list shown before a delivery exists (DESIGN 8.8).
function wsCandidatePanel() {
 const library = rt.library, current = rt.paperDetail;
 if (!library?.rows?.length) return '<section class="wiki-s1-card"><h2>来源清单</h2><p class="wiki-s1-muted">这里还没有检索候选。有了检索规划、查询结果，候选会列在这里；交付生成以后换成正式来源清单。</p></section>';
 const selected = current && realCurrent(current) ? current.row?.work_id : null;
 return `<div class="wiki-s1-columns"><section class="wiki-s1-card"><h2>已保存的检索候选 · ${esc(library.total)}</h2>
 <p class="wiki-s1-muted">这是当前查询的输出，还不是正式交付。来源、阅读和纳入决定要分别审阅。</p>
 <div class="ws-scroll"><table class="ws-table"><thead><tr><th scope="col">论文</th><th scope="col">年份</th><th scope="col">来源状态</th><th scope="col">筛选状态</th></tr></thead><tbody>${library.rows.map(row => `<tr ${row.work_id === selected ? 'class="ws-sel"' : ''}><td><button type="button" class="ws-link" data-real-paper="${esc(row.index)}">${esc(row.title ?? '未提供')}</button></td><td>${esc(row.year ?? '未提供')}</td><td>${esc(row.source_status ?? '未提供')}</td><td>${esc(wsScreenNames[row.screening_status] || row.screening_status || '未提供')}</td></tr>`).join('')}</tbody></table></div>
 ${library.next_offset !== null && library.next_offset !== undefined ? wsBtn('读取更多候选', 'data-v7-workflow="library-next"', wsLock()) : ''}</section>
 <section class="wiki-s1-card">${selected ? `<h2>${esc(current.row?.metadata?.title || selected)}</h2>${wsPaperProcess(selected)}` : '<h2>这篇的处理</h2><p class="wiki-s1-muted">点左边一篇论文，才会在这里做筛选、来源获取和阅读。</p>'}</section></div>`;
}
// The evidence-review fold (DESIGN 8.9). Saving goes through the reading view's evidence offers.
function wsEvidenceReview(claim, workId) {
 const view = rt.readingView, offers = view && realCurrent(view) ? view.offers || [] : [];
 const at = offers.findIndex(o => o.quote && o.quote === claim.quote && (!o.source_id || o.source_id === claim.source_id));
 const scope = ({abstract:'依据摘要', 'full-text':'依据全文'})[claim.evidence_level];
 const tag = scope ? `<span class="ws-tag ws-idle">${scope}</span>` : '';
 if (wsReadonly()) return tag;
 if (at < 0) return `${tag}<details class="ws-evrev"><summary>审阅这条证据</summary><p class="wiki-s1-muted">这条证据现在没有可保存的审阅入口：后台只对已读取的阅读输出开放审阅。先在「来源与图谱」里这篇的处理中点「审阅已保存来源笔记」。无法核实的字段保持「未提供」。</p></details>`;
 const lock = wsLock();
 return `${tag}<details class="ws-evrev" open><summary>审阅这条证据</summary>
 <label>此片段支持或反对的主张<textarea data-v7-claim-text="${at}" rows="2" maxlength="4096">${esc(claim.text || '')}</textarea></label>
 <label>关系<select data-v7-claim-relation="${at}" data-ws-relation>${wsRelationOptions.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></label>
 <label>证据范围<select data-v7-claim-level="${at}"><option value="abstract">摘要</option><option value="full-text">全文</option></select></label>
 <label>章节位置<input data-v7-claim-section="${at}" maxlength="4096"></label>
 <label class="ws-check"><input type="checkbox" data-ws-claim-confirm> 我已审阅这条证据</label>
 ${wsBtn('保存这条证据审阅', `data-v7-workflow="claim-save" data-v7-index="${at}" data-ws-needs-claim`, lock || '请先选关系')}</details>`;
}
const wsPrevEvidence = wikiS1Evidence;
wikiS1Evidence = function (index, state) {
 const html = wsPrevEvidence(index, state);
 const app = apps[0];
 if (!wsOpsActive(app)) return html;
 const row = wikiS1VisibleSources(state).find(item => item.paper.work_id === state.selected);
 if (!row) return html;
 const claims = row.claims.filter(claim => state.check === 'all' || wikiS1Check(claim) === state.check);
 const parts = html.split('</article>');
 return parts.map((part, i) => i < claims.length ? part + wsEvidenceReview(claims[i], row.paper.work_id) + '</article>' : part).join('');
};
const wsPrevSelected = wikiS1Selected;
wikiS1Selected = function (state) {
 const html = wsPrevSelected(state);
 return wsOpsActive(apps[0]) && state.selected ? html + wsPaperProcess(state.selected) : html;
};

// Loading a paper's record reuses the old click handler by clicking a real element it recognizes.
document.addEventListener('click', event => {
 const button = event.target.closest('[data-ws-load-paper]');
 if (!button || button.disabled) return;
 event.preventDefault(); event.stopImmediatePropagation();
 const probe = document.createElement('button');
 probe.hidden = true; probe.dataset.realPaper = button.dataset.wsLoadPaper;
 apps[0].el.append(probe); probe.click(); probe.remove();
}, true);
// Radio / checkbox gates patch buttons in place so typed text is not lost.
document.addEventListener('change', event => {
 const target = event.target, app = apps[0];
 if (!wsOpsActive(app)) return;
 const patch = (button, reason) => {
  if (!button) return;
  button.disabled = !!reason;
  const why = button.parentElement.querySelector('.ws-why');
  if (why) { why.textContent = reason; why.hidden = !reason; }
 };
 if (target.matches('[data-ws-screen-radio]')) {
  const scope = target.closest('[data-ws-process]'), select = scope.querySelector('select[data-v7-screen]');
  select.value = target.value;
  patch(scope.querySelector('[data-ws-needs-screen]'), wsLock());
 } else if (target.matches('[data-ws-relation]')) {
  const scope = target.closest('.ws-evrev'), confirm = scope.querySelector('[data-ws-claim-confirm]');
  patch(scope.querySelector('[data-ws-needs-claim]'), wsLock() || (target.value === 'pending' ? '请先选关系' : confirm.checked ? '' : '请明确确认已审阅'));
 } else if (target.matches('[data-ws-claim-confirm]')) {
  const scope = target.closest('.ws-evrev'), relation = scope.querySelector('[data-ws-relation]');
  patch(scope.querySelector('[data-ws-needs-claim]'), wsLock() || (relation.value === 'pending' ? '请先选关系' : target.checked ? '' : '请明确确认已审阅'));
 } else if (target.matches('[data-ws-gate-confirm]')) {
  const save = target.closest('.ws-notes').querySelector('[data-ws-needs-confirm]');
  if (!save.hasAttribute('data-ws-blocked')) patch(save, wsLock() || (target.checked ? '' : '请先勾选「我已审阅这些注释」'));
 }
});
