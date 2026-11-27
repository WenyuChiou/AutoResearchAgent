// Wiki V1 Stage 2 (choose a direction). Presents saved, project-bound records only.
// Every control here is a read, a local draft, or one of the existing connection/request
// controls (same data attributes, same handlers). Nothing in this file calls a write route.
const wikiS2Tabs = {compare:'候选比较', literature:'文献与证据', materials:'材料'};
const wikiS2Opinion = {recommend:['系统建议','rec'], park:['系统暂缓','park'], revise:['系统建议先修订','rev']};
const wikiS2CheckNames = {answerability:'可回答性', execution:'执行条件', materials:'材料条件', opportunity:'研究缺口', value:'研究价值'};
const wikiS2ReviewNames = {opportunity:'机会定位', value:'研究价值', answerability:'可回答性', materials:'资料与材料', execution:'执行可行性'};
const wikiS2ReviewStatus = {complete:'评语已交付', resolved:'已裁决', pending:'待裁决', failed:'失败', missing:'缺件',
 unavailable:'不可用', interrupted:'已中断', empty:'空回复'};
const wikiS2PageSize = 8, wikiS2ChipPage = 12;

function wikiS2Active(app) {
 return app.wikiS2Enabled === true && app.page === 'workspace' && app.stage === 2 && app.lang === 'zh';
}

function wikiS2Text(value) {
 if (value === undefined || value === null || value === '') return null;
 if (Array.isArray(value)) return value.length ? value.map(row => typeof row === 'string' ? row : JSON.stringify(row)).join('；') : null;
 return typeof value === 'string' ? value : JSON.stringify(value);
}
function wikiS2Missing(note) {
 return `<span class="wiki-s2-missing">未提供</span>${note ? `<small>${esc(note)}</small>` : ''}`;
}
function wikiS2Cell(value, limit = 220) {
 const text = wikiS2Text(value);
 if (text === null) return wikiS2Missing();
 return text.length > limit ? `<details><summary>${esc(text.slice(0, limit))}…</summary><p>${esc(text)}</p></details>` : esc(text);
}
function wikiS2Letter(id, index) {
 const match = /^([A-Z])(?:-|$)/.exec(String(id));
 return match ? match[1] : String.fromCharCode(65 + index % 26);
}
const wikiS2Key = (id, version) => id + '@' + version;

// --- One model for the three places Stage 2 content can come from -------------------------
function wikiS2Route(base, index) {
 return {letter:wikiS2Letter(base.id, index), key:wikiS2Key(base.id, base.version), checks:null, evidenceIds:null,
  opinion:null, reason:null, nextStep:null, differs:null, data:null, tools:null, risks:null, ...base};
}

function wikiS2NativeModel() {
 const state = typeof wikiStage2State === 'undefined' ? null : wikiStage2State;
 if (!state?.selection || !wikiStage2CurrentSelection()) return null;
 const view = state.selection;
 const cards = Array.isArray(view.cards) ? view.cards : view.cards?.cards;
 if (!Array.isArray(cards)) return null;
 const eligible = new Set((Array.isArray(view.eligible) ? view.eligible : []).map(row =>
  typeof row === 'string' ? row : Array.isArray(row) ? wikiS2Key(row[0], row[1]) : wikiS2Key(row?.candidate_id, row?.version)));
 const review = card => {
  const found = card.closest_prior_work?.review;
  if (!found || typeof found !== 'object') return found ?? null;
  return ['summary','difference','differences','position','assessment'].map(key => found[key]).find(value => typeof value === 'string') ?? found;
 };
 const routes = cards.map((card, index) => wikiS2Route({
  id:card.candidate_id, version:card.candidate_version, question:card.candidate_question,
  differs:review(card), tools:card.requirements, risks:[...(Array.isArray(card.limitations) ? card.limitations : card.limitations ? [card.limitations] : []),
   ...(card.alternatives || []).flatMap(row => (row.alternatives || []).map(alt => typeof alt === 'string' ? alt : JSON.stringify(alt)))],
  nextChecks:(card.next_checks || []).map(row => row?.text).filter(Boolean),
  // The saved view lists only which versions the delivery recommends; it carries no park/revise value.
  opinion:eligible.has(wikiS2Key(card.candidate_id, card.candidate_version)) ? 'recommend' : null, raw:card
 }, index));
 return {origin:'native', routes, literature:null, evidence:null, comparisonText:null, reviews:null,
  receipt:view.selection_status === 'recorded' ? (view.selection_receipt || {}) : null,
  opinionsKnown:false, bound:null, complete:true};
}

function wikiS2ArchiveModel() {
 if (!canonicalReadonly() || !rt.savedRun) return null;
 const checked = canonicalStage2Validate(rt.savedRun.payload, rt.savedRun.binding);
 if (!checked.ok) return {origin:'archive', blocked:checked.reason, routes:[]};
 const attachment = checked.payload.stage2, view = checked.payload.stage2_comparison;
 const routes = view.directions.map((row, index) => wikiS2Route({
  id:row.candidate_id, version:row.version, question:row.question, differs:row.opportunity, tools:row.requirements,
  risks:row.limitations, opinion:wikiS2Opinion[row.disposition] ? row.disposition : null, reason:row.reason, nextStep:row.next_step,
  checks:row.checks && typeof row.checks === 'object' ? row.checks : null,
  evidenceIds:Array.isArray(row.evidence_ids) ? row.evidence_ids : null, value:row.value, raw:row
 }, index));
 const literature = view.literature.map(row => ({key:wikiS2Key(row.work_id, row.version_id), title:row.title || row.work_id,
  tag:row.evidence_level, workId:row.work_id, versionId:row.version_id,
  rows:{author:row.authors ?? null, level:row.evidence_level, role:null,
   notes:[row.cells?.findings?.text, row.cells?.limitations?.text].filter(Boolean).join('；') || null,
   method:row.cells?.method?.text ?? null, title:row.title, access:row.work_id + ' · ' + row.version_id}, raw:row}));
 return {origin:'archive', routes, literature, evidence:view.evidence, comparisonText:typeof view.comparison === 'string' ? view.comparison : null,
  reviews:null, hasEvaluation:Object.keys(attachment.evaluation).length > 0, receipt:null, opinionsKnown:true, bound:false,
  synthetic:checked.binding.fixture === true, complete:true};
}

function wikiS2ImportModel() {
 if (typeof p9 === 'undefined' || !p9.shown || !n2.model) return null;
 const model = n2.model;
 const routes = model.routes.map((route, index) => wikiS2Route({
  id:route.candidate.candidate_id, version:route.candidate.version, question:route.candidate.question,
  differs:route.candidate.opportunity, tools:route.candidate.requirements, risks:route.candidate.limitations,
  opinion:wikiS2Opinion[route.assessment?.disposition] ? route.assessment.disposition : null,
  reason:route.assessment?.reason ?? null, nextStep:route.assessment?.next_step ?? null,
  checks:route.assessment?.checks && typeof route.assessment.checks === 'object' ? route.assessment.checks : null,
  evidenceIds:Array.isArray(route.candidate.evidence_ids) ? route.candidate.evidence_ids : null, value:route.candidate.value, raw:route
 }, index));
 const literature = model.sources.map(source => ({key:wikiS2Key(source.work_id, source.version_id), title:source.title, tag:source.evidence_level,
  workId:source.work_id, versionId:source.version_id,
  rows:{author:source.authors, level:source.evidence_level, role:source.parsed.fields.role ?? null, notes:source.parsed.notes,
   excerpt:source.parsed.excerpts, method:source.parsed.fields.method || source.parsed.fields.data || null, title:source.title,
   access:source.version_id}, raw:source.card}));
 return {origin:'import', routes, literature, evidence:model.packet.evidence, comparisonText:model.packet.comparison || null,
  reviews:n2.reviewReading || null, receipt:null, opinionsKnown:true, bound:false, complete:true};
}

function wikiS2Model() {
 return wikiS2ArchiveModel() || wikiS2ImportModel() || wikiS2NativeModel();
}

// --- Connection and request block (8.13) ---------------------------------------------------
function wikiS2Why(m) {
 if (m.noLocks) return '这个浏览器不支持跨页面锁，只能查看，不能接通';
 if (m.writing) return '正在保存，请稍等';
 if (m.reading || rt.loading) return '正在读取保存记录';
 if (rt.pending) return '上次提交的结果还没确认，先核对';
 if (rt.controlHeld) return '有一条回执还没核对，先到操作历史里核对';
 if (rt.busy) return '正在保存，请稍等';
 return '现在还不能做这一步';
}
function wikiS2ConnectionLine(m) {
 const reason = String(m.code || '');
 const line = (tone, tag, text, extra = {}) => ({tone, tag, text, buttons:[], ...extra});
 if (m.phase === 'waiting') return line('run', '正在核对', '正在核对这个课题的接通记录');
 if (m.unknown) return line('warn', '结果未确认', '上次启用（或登记）的结果还没确认。原请求已保留，请核对原回执', {buttons:[{label:'核对上次提交', attr:'read'}]});
 if (m.reading && !m.row && !m.view.error) return line('run', '正在核对', '正在核对这个课题的接通记录');
 if (m.noLocks && m.action) return line('idle', '只能查看', '这个浏览器不支持跨页面锁，只能查看，不能接通', {buttons:[{label:'接通本课题', attr:'connect'}]});
 if (m.action === 'connect') return line('wait', '可以接通', '这个课题还没有接通。可以登记当前配置，登记不会启动研究', {buttons:[{label:'接通本课题', attr:'connect', primary:true}]});
 if (m.action === 'publish') return line('wait', '等你 · 第 1 步', '还差这个课题的 Stage 2 启用同意。先生成一份启用提议，看过再同意', {buttons:[{label:'生成本课题的启用提议', attr:'publish', primary:true}]});
 if (m.action === 'activate') return line('wait', '等你 · 第 2 步', '启用提议已生成（生成时间：还没有，后台没有给出）。同意后只登记启用，不会启动研究', {buttons:[{label:'同意这份提议并启用 Stage 2', attr:'activate', primary:true}]});
 if (m.connected) return line('done', '已接通', '这个课题已接通。接通只是登记，执行和交付各有自己的记录');
 if (reason === 'stage2-controller-current-input-required') return line('warn', '缺输入包', '还缺这个课题已接收的 Stage 2 输入包和接收回执。请先看 Stage 1 的交付', {buttons:[{label:'前往 Stage 1 查看交付', stage:1}]});
 if (/profile-unavailable$/.test(reason)) return line('warn', '缺运行配置', '这次启动没有提供 Stage 2 的运行配置。请联系原来的管理员，用核对过的配置从原目录重开', {buttons:[{label:'去连接与设置', page:'settings'}]});
 if (m.http === 404 || reason === 'stage-connection-interface-unavailable') return line('warn', '没带接通功能', '这次启动没有提供 Stage 2 的接通功能。请联系原来的管理员，确认能不能换支持的版本重开');
 if (reason === 'stage2-activation-record-unverified') return line('warn', '启用记录缺回执', '已有启用提议或记录，但缺少对得上的回执。请保留原记录，再只读核对一次', {buttons:[{label:'重新读取', attr:'read'}]});
 if (reason === 'project-lock-busy' || reason === 'project-lock-failed') return line('warn', '暂时拿不到锁', '另一个页面正在处理这个课题，暂时不能操作。请稍后再只读核对', {buttons:[{label:'重新读取', attr:'read'}]});
 if (m.http === 403 || reason === 'cross-site-rejected' || reason === 'credential-rejected') return line('warn', '访问被拒', '访问被拒绝。请从原来打开这个课题的页面查看记录');
 if (reason === 'stage2-continuation-result-not-current' || /binding-differs|project-stale|connection-differs|path-mismatch|current-input-differs|native-input-differs|receipt-differs|binding-mismatch/.test(reason))
  return line('warn', '记录对不上', '这次核对和原记录不一致。如果搬过目录，请回到原来的目录、用原配置重开，先只读核对。不要重新执行，也不要手改回执', {buttons:[{label:'重新读取', attr:'read'}]});
 return line('warn', '核对不了', '原记录暂时无法核对。请保留现有记录，看过技术细节后再只读核对', {buttons:[{label:'重新读取', attr:'read'}]});
}

function wikiS2RequestLine() {
 const state = typeof wikiStage2State === 'undefined' ? null : wikiStage2State;
 const line = (tone, tag, text, buttons = []) => ({tone, tag, text, buttons});
 const readButton = {label:'查看保存状态', act:'read'};
 if (!state || state.busy) return line('run', '正在读取', '正在读取请求状态');
 const code = state.error, status = state.result?.status;
 const byCode = {
  'stage2-continuation-original-admission-unavailable':['warn','许可缺失或过期','原运行许可缺失或已过期，请联系项目管理员',[{label:'去连接与设置', page:'settings'}]],
  'stage2-continuation-project-stale':['warn','版本不一致','课题的输入版本和已接入的作业不一致，请重新打开课题',[{label:'重新读取', act:'read'}]],
  'stage2-continuation-result-not-current':['warn','候选和记录不一致','保存的候选和当前记录不一致，请联系项目管理员。不会用示例内容补上',[]],
  'stage2-continuation-worker-busy':['warn','另一个请求在处理','另一个请求正在处理，请稍后再试',[readButton]],
  'stage2-continuation-request-exists':['warn','请求已保存','已有请求，请查看保存状态',[readButton]]};
 if (code && byCode[code]) return line(...byCode[code]);
 if (code) return line('warn', '读不到回执', '暂时无法读取回执，请再查一次保存状态', [readButton]);
 const mayRequest = typeof v9AllowsCandidateRequest !== 'function' || v9AllowsCandidateRequest();
 const byStatus = {
  ready:['plain','还没请求','文献包已接收，可以请求生成候选', [...(mayRequest ? [{label:'请求生成候选', act:'request', primary:true}] : []), readButton]],
  'request-saved':['run','请求已保存','请求已保存，可以查看处理状态',[readButton]],
  running:['run','处理中','正在处理这个请求。不需要你操作',[readButton]],
  'no-candidate':['warn','候选还没保存','后台已经回执，候选交付还没有保存',[readButton]],
  'execution-unknown':['warn','需要核对','请求已保存，结果还不清楚，请由管理员核对原运行记录',[readButton]],
  blocked:['warn','请求受阻','已保存的请求受阻，暂时无法继续，请由管理员检查交接',[readButton]]};
 if (byStatus[status]) return line(...byStatus[status]);
 return line('plain', '待核对', '候选请求状态待核对，原记录仍保留', [readButton]);
}

function wikiS2CandidatesSaved() {
 const state = typeof wikiStage2State === 'undefined' ? null : wikiStage2State;
 return ['candidate-ready','selection-available'].includes(state?.result?.status) && !state.error;
}

function wikiS2ConnBlock(app) {
 if (typeof v9ConnectionModel !== 'function') return '';
 const m = v9ConnectionModel(app);
 if (!m) return '';
 const top = wikiS2ConnectionLine(m);
 const lower = m.connected || (typeof v9LegacyConnection === 'function' && v9LegacyConnection('stage2-controller'))
  ? wikiS2RequestLine() : null;
 // Connected and saved: the block disappears; the status bar carries a small tag instead.
 if (m.connected && wikiS2CandidatesSaved()) return '';
 const gate = wikiS2Why(m);
 const render = (row, kind) => `<div class="wiki-s2-conn-row" data-s2-conn-row="${kind}" data-tone="${row.tone}">
  <span class="wiki-s2-st" data-tone="${row.tone}">${esc(row.tag)}</span><p>${esc(row.text)}</p>
  <div class="wiki-s2-actions">${row.buttons.map(button => {
   const blocked = kind === 'connect' && button.attr && button.attr !== 'read' && (!m.canWrite || m.writing)
    || kind === 'connect' && button.attr === 'read' && (m.reading || m.writing)
    || kind === 'request' && button.act && (rt.busy || rt.loading || rt.pending || rt.controlHeld || wikiStage2State?.busy);
   const cls = 'hs-button' + (button.primary ? ' hs-button-primary' : '');
   const data = button.attr ? `data-v9-connection="${button.attr}" data-connection-basis="${esc(m.token)}"`
    : button.act ? `data-wiki-stage2-action="${button.act}"` : button.stage ? `data-stage="${button.stage}"` : `data-page="${button.page}"`;
   return `<span><button type="button" class="${cls}" ${data} ${blocked ? 'disabled' : ''}>${esc(button.label)}</button>${blocked ? `<small class="wiki-s2-reason">${esc(gate)}</small>` : ''}</span>`;
  }).join('')}</div></div>`;
 const detail = m.code || m.offerRef
  ? `<details class="wiki-s2-tech"><summary>技术细节</summary>${m.code ? `<code>${esc(m.code)}</code>` : ''}${m.offerRef ? `<p>启用提议编号 · <code>${esc(m.offerRef)}</code></p>` : ''}</details>` : '';
 return `<section class="wiki-s2-conn" data-wiki-s2-conn aria-label="本课题的 Stage 2"><h2 tabindex="-1">本课题的 Stage 2</h2>
  ${render(top, 'connect')}${lower ? '<hr>' + render(lower, 'request') : ''}${detail}</section>`;
}

// --- Compare tab (3.3, 8.16, 8.17) ---------------------------------------------------------
function wikiS2Opinions(model) {
 const known = model.routes.filter(route => route.opinion);
 if (!known.length) {
  return `<section class="wiki-s2-advice" data-s2-advice><b>系统建议 · 不是你的选择</b><p>还没有：这份保存的结果没有给出每条路线的系统意见。页面不会自己归类。</p></section>`;
 }
 const part = key => known.filter(route => route.opinion === key);
 const names = rows => rows.map(route => '方向 ' + route.letter).join('、');
 const bits = [];
 if (part('recommend').length) bits.push('建议 ' + names(part('recommend')) + (model.opinionsKnown ? '' : '（保存的结果只列出了建议的方向，没有给其他方向的系统意见）'));
 if (part('revise').length) bits.push(names(part('revise')) + ' 建议先修订');
 if (part('park').length) bits.push(names(part('park')) + ' 暂缓');
 const reasons = known.filter(route => route.reason).map(route => `<li><b>方向 ${esc(route.letter)}</b> · ${esc(wikiS2Opinion[route.opinion][0])}：${wikiS2Cell(route.reason, 180)}</li>`).join('');
 return `<section class="wiki-s2-advice" data-s2-advice><b>系统建议 · 不是你的选择</b><p>${esc(bits.join('；'))}。页面没有预选任何方向。</p>${reasons ? `<ul>${reasons}</ul>` : ''}</section>`;
}

function wikiS2CheckCell(route) {
 if (!route.checks) return '<span class="wiki-s2-missing">还没有</span><small>这份保存的结果里没有这条路线的五项检查</small>';
 const tag = check => check?.blocking === true ? ['卡住','block'] : check?.blocking === false ? ['不卡','free'] : ['未提供','unk'];
 const keys = Object.keys(wikiS2CheckNames);
 const next = keys.map(key => route.checks[key]?.next_check).filter(Boolean);
 return `<ul class="wiki-s2-checks">${keys.map(key => {
  const [label, tone] = tag(route.checks[key]);
  return `<li><span>${wikiS2CheckNames[key]}</span><b data-tone="${tone}">${label}</b></li>`;
 }).join('')}</ul>${next.length ? `<p class="wiki-s2-next"><b>待核实的下一步</b>${wikiS2Cell(next, 180)}</p>` : ''}`;
}

function wikiS2EvidenceCell(route) {
 if (!route.evidenceIds) return '<span class="wiki-s2-missing">还没有</span><small>这份保存的结果没有给出这条路线引用的证据</small>';
 return route.evidenceIds.length ? `<span>${route.evidenceIds.length} 条保存的证据</span><small>编号见本页技术细节</small>` : '<span>没有引用证据</span>';
}

function wikiS2CompareTable(app, model, state) {
 const pages = Math.max(1, Math.ceil(model.routes.length / wikiS2PageSize));
 state.page = Math.max(0, Math.min(state.page, pages - 1));
 const shown = model.routes.slice(state.page * wikiS2PageSize, (state.page + 1) * wikiS2PageSize);
 const tentative = state.tentative?.key;
 const picked = model.receipt?.candidate_id ? wikiS2Key(model.receipt.candidate_id, model.receipt.candidate_version ?? model.receipt.version) : null;
 const head = route => {
  const [opinion, tone] = route.opinion ? wikiS2Opinion[route.opinion] : ['系统意见未提供', 'none'];
  const flagged = state.flags.has(route.key);
  return `<th scope="col" ${route.key === picked ? 'class="picked"' : ''}><b class="wiki-s2-letter">${esc(route.letter)}</b>
   <span class="wiki-s2-opinion" data-tone="${tone}">${opinion}</span>${route.key === tentative ? '<span class="wiki-s2-opinion" data-tone="draft">暂定</span>' : ''}

   <button type="button" class="wiki-s2-flag" data-s2-flag="${esc(route.key)}" aria-pressed="${flagged}">${flagged ? '已标记待审' : '标记待审'}</button>
   <small>仅本机草稿，未提交 Harness</small></th>`;
 };
 const row = (title, cell) => `<tr><th scope="row">${title}</th>${shown.map(route => `<td ${route.key === picked ? 'class="picked"' : ''}>${cell(route)}</td>`).join('')}</tr>`;
 const risks = route => wikiS2Cell(route.risks);
 return `<div class="wiki-s2-scroll" tabindex="0" aria-label="候选比较表${shown.length > 4 ? '，可以横向滚动，第一列固定' : ''}">
  <table class="wiki-s2-compare" data-s2-compare><thead><tr><th scope="col">维度</th>${shown.map(head).join('')}</tr></thead><tbody>
  ${row('研究问题', route => wikiS2Cell(route.question))}
  ${row('和最接近研究的区别', route => wikiS2Cell(route.differs))}
  ${row('数据能不能拿到', route => `<span class="wiki-s2-avail">未提供</span><small>后台没有保存这条路线的数据可获得性结论，不替它判断</small>`)}
  ${row('工具和投入', route => wikiS2Cell(route.tools))}
  ${row('风险和退路', risks)}
  ${row('卡住的条件', wikiS2CheckCell)}
  ${row('依据的证据', wikiS2EvidenceCell)}
  </tbody></table></div>
  ${pages > 1 ? `<div class="wiki-s2-pager"><button type="button" class="hs-button" data-s2-page="-1" ${state.page === 0 ? 'disabled' : ''}>上一页</button><span>第 ${state.page + 1} 页，共 ${pages} 页</span><button type="button" class="hs-button" data-s2-page="1" ${state.page + 1 === pages ? 'disabled' : ''}>下一页</button></div>` : ''}`;
}

function wikiS2Reviews(model) {
 const reading = model.reviews;
 const have = model.routes.filter(route => route.checks).length;
 if (!reading && !model.hasEvaluation) return `<details class="wiki-s2-fold" data-s2-reviews><summary>独立复核与可行性评估 · <span class="wiki-s2-muted">这份归档没有保存独立评估</span></summary></details>`;
 if (!reading) return `<details class="wiki-s2-fold" data-s2-reviews><summary>独立复核与可行性评估 · ${have} 个候选有可行性评估</summary><p>评估原文在归档里，这个页面还没有读取它的逐条复核意见。</p><p class="wiki-s2-muted">这是报告质量评审，不是路线效果排名。评分未提供。</p></details>`;
 const records = reading.records, source = reading.source;
 const status = record => wikiS2ReviewStatus[record.status] || '状态未知';
 const cards = model.routes.map(route => {
  const mine = records.filter(record => record.candidate_id === route.id && record.candidate_version === route.version);
  const checks = route.checks ? Object.keys(wikiS2ReviewNames).map(key => {
   const check = route.checks[key];
   return `<li><b>${wikiS2ReviewNames[key]}</b> <span class="wiki-s2-st" data-tone="idle">${check ? esc(check.status === 'assessed' ? '已有评估' : check.status ?? '状态未知') : '未提供'}</span> ${check ? `理由：${wikiS2Cell(check.rationale, 160)}` : ''}</li>`;
  }).join('') : '<li>这个候选没有保存可行性评估</li>';
  const reviewer = mine.map(record => {
   const assessment = record.review?.assessment;
   const role = record.role === 'challenger' ? '挑战审查' : record.role === 'feasibility' ? '可行性审查' : record.role;
   const todo = Object.values(assessment?.checks || {}).map(check => check?.next_check).filter(Boolean);
   return `<div class="wiki-s2-reviewer"><h4>${esc(role)} · ${esc(status(record))}</h4><p>理由：${wikiS2Cell(assessment?.reason ?? record.error)}</p>
    ${todo.length ? `<p><b>需要补查</b> ${wikiS2Cell(todo, 200)}</p>` : ''}<p><b>下一步</b> ${wikiS2Cell(assessment?.next_step)}</p>
    <details><summary>完整原始记录</summary><pre>${esc(JSON.stringify(record, null, 2))}</pre></details></div>`;
  }).join('');
  return `<article class="wiki-s2-reviewcard"><h3>方向 ${esc(route.letter)}</h3><ul>${checks}</ul>${reviewer}</article>`;
 }).join('');
 const state = source.delivery_status === 'draft-not-ready' ? '草稿 · 尚未选案' : '保存报告 · 尚未选案';
 return `<details class="wiki-s2-fold" data-s2-reviews><summary>独立复核与可行性评估 · ${have} 个候选有可行性评估 · 复核意见 ${records.length} 条</summary>
  <p class="wiki-s2-muted">这是报告质量评审，不是路线效果排名。评分未提供。 <span class="wiki-s2-opinion" data-tone="draft">${state}</span></p>${cards}
  <details><summary>来源与版本（技术细节）</summary><pre>${esc(JSON.stringify({packet_sha256:source.packet_sha256, delivery_manifest_sha256:source.delivery_manifest_sha256, reviews_file_sha256:source.reviews_file_sha256}, null, 2))}</pre></details></details>`;
}

function wikiS2DraftStatus(state) {
 return ({'saved':'已保存本机草稿','unsaved':'本机草稿未保存','cleared':'本机草稿已清除','error':'本机保存失败'})[state.draftStatus] || '本地待审 · 未提交 Harness';
}
function wikiS2Decision(app, model, state) {
 if (model.receipt) return ''; // After a selection the decision area is closed; the receipt above replaces it.
 const pick = model.routes.find(route => route.key === state.pick);
 const blocked = wikiS2DecisionReason(model);
 let formal;
 if (blocked === null) formal = '<div data-v93-choice></div>';
 else formal = `<fieldset class="wiki-s2-choices"><legend>你选哪一个方向？（没有预选）</legend>${model.routes.map(route =>
  `<label class="wiki-s2-choice"><input type="radio" name="wiki-s2-pick" data-s2-pick="${esc(route.key)}" ${route.key === state.pick ? 'checked' : ''}> <b>方向 ${esc(route.letter)}</b> ${esc(wikiS2Text(route.question)?.slice(0, 80) ?? '问题未提供')}</label>`).join('')}</fieldset>
  <label class="wiki-s2-reasonbox">理由（可选）<textarea data-s2-note rows="3" maxlength="4096">${esc(state.note)}</textarea></label>
  ${pick && ['park','revise'].includes(pick.opinion) ? `<p class="wiki-s2-warnline">你选的是「${wikiS2Opinion[pick.opinion][0]}」的方向。这不会被拦下，但请确认已看过理由。</p>` : ''}
  <div class="wiki-s2-actions"><span><button type="button" class="hs-button hs-button-primary" disabled>${pick ? `确认选择方向 ${esc(pick.letter)}…` : '请先选一个'}</button><small class="wiki-s2-reason">${esc(blocked)}</small></span></div>`;
 const tentative = `<details class="wiki-s2-tentative" data-s2-tentative ${state.tentOpen ? 'open' : ''}><summary>先存一个暂定偏好（不是正式选择）</summary>
  <p class="wiki-s2-muted">暂定偏好只存在这台电脑的这个浏览器里，不会提交 Harness，也不能触发进入 Stage 3。</p>
  <div class="wiki-s2-actions"><button type="button" class="hs-button" data-s2-tentative-save ${pick ? '' : 'disabled'}>保存暂定偏好</button>${pick ? '' : '<small class="wiki-s2-reason">请先在上面选一个方向</small>'}</div>
  ${state.tentative ? `<p>当前暂定偏好：方向 ${esc(state.tentative.letter)}${state.tentative.note ? ' · ' + esc(state.tentative.note) : ''} · 本机草稿</p>` : ''}</details>`;
 const localDraft = blocked === null ? '' : `<div class="wiki-s2-actions"><button type="button" class="hs-button" data-s2-save ${pick ? '' : 'disabled'}>保存本地草稿</button><button type="button" class="hs-button" data-s2-clear>清除本地草稿</button>
  <small aria-live="polite">${wikiS2DraftStatus(state)}</small>${pick ? '' : '<small class="wiki-s2-reason">请先选一个方向</small>'}</div>`;
 if (model.origin === 'archive') return `<section class="wiki-s2-decide" data-s2-decide><span class="wiki-s2-label">你的决定</span>
  <h2>选一个研究方向，带进 Stage 3</h2><p class="wiki-s2-muted">这是${model.synthetic ? '合成样例' : '历史归档'}，不能在这里改。归档里${model.receipt ? '已有选择回执，见上方' : '没有真人选择记录'}。</p></section>`;
 return `<section class="wiki-s2-decide" data-s2-decide><span class="wiki-s2-label">你的决定</span>
  <h2>选一个研究方向，带进 Stage 3</h2><p class="wiki-s2-muted">这一步由你来选，系统建议只是参考。选了以后，Stage 3 才能接着规划。</p>${formal}${localDraft}${tentative}</section>`;
}

function wikiS2DecisionReason(model) {
 if (model.origin === 'archive') return '这是历史归档，不能在这里改';
 if (model.origin === 'import') return '这是接入的候选包，不是本课题自己的 Stage 2。没有这个课题的接通记录和 Stage 1 绑定，不能提交正式选择';
 if (typeof v93ChoiceIdentity === 'function' && v93ChoiceIdentity()) return null;
 const connected = typeof v9ConnectionConnected === 'function' && v9ConnectionConnected('stage2-controller');
 return connected ? '现在还不能做这一步：这次启动没有提供当前交付的正式选择入口' : '现在还不能做这一步：Stage 2 还没有接通';
}

function wikiS2Receipt(model) {
 if (!model?.receipt) return '';
 const receipt = model.receipt, field = (name, value, why) => `<div><dt>${name}</dt><dd>${value ? esc(value) : `<span class="wiki-s2-missing">还没有</span><small>${why}</small>`}</dd></div>`;
 return `<section class="wiki-s2-receipt" data-s2-receipt role="status"><span class="wiki-s2-tick" aria-hidden="true">✓</span><div><h2>你已选定方向${receipt.candidate_id ? ' ' + esc(receipt.candidate_id) : ''}</h2>
  <dl>${field('理由', receipt.reason, '选择回执里没有保存这一项')}${field('和系统建议是否一致', receipt.agrees_with_recommendation === true ? '一致' : receipt.agrees_with_recommendation === false ? '不一致' : '', '选择回执里没有保存这一项')}
  ${field('带进下一段的限制', Number.isSafeInteger(receipt.limitation_count) ? receipt.limitation_count + ' 条' : '', '选择回执里没有保存这一项')}${field('时间', receipt.recorded_at || receipt.created_at, '选择回执里没有保存这一项')}</dl>
  <button type="button" class="hs-button hs-button-primary" data-stage="3">进入下一段：Stage 3</button></div></section>`;
}

function wikiS2InputTable() {
 const index = typeof wikiS1Index === 'function' ? wikiS1Index() : null;
 if (!index) {
  const delivered = rt.overview?.stage1?.delivery?.canonical_package;
  return `<section class="wiki-s2-empty" data-s2-input><h2>Stage 1 输入文献</h2><p>${delivered ? '这个课题的 Stage 1 文献包已交付，这里还没有读取它的文献清单。Stage 2 的研究方向还没有生成。' : 'Stage 2 在等这个课题的 Stage 1 文献包。'}</p></section>`;
 }
 const latest = new Map();
 for (const row of index.screening || []) {
  const key = JSON.stringify([row.work_id, row.version_id]), prior = latest.get(key);
  if (!prior || row.observed_at >= prior.observed_at) latest.set(key, row);
 }
 const decisions = {include:'纳入', exclude:'排除', pending:'待定'};
 const rows = index.papers.map(paper => {
  const key = JSON.stringify([paper.work_id, paper.version_id]);
  const claims = (index.claims || []).filter(claim => claim.work_id === paper.work_id && claim.version_id === paper.version_id);
  return `<tr><th scope="row">${esc(paper.title)}</th><td>${decisions[latest.get(key)?.status] || '未提供'}</td><td>${claims.length ? claims.length + ' 条保存的证据' : '还没有阅读记录'}</td><td><span class="wiki-s2-missing">未提供</span></td></tr>`;
 }).join('');
 return `<section class="wiki-s2-empty" data-s2-input><h2>Stage 1 输入文献</h2><p>这是交接过来的输入，Stage 2 的研究方向还没有生成。</p>
  <div class="wiki-s2-scroll"><table class="wiki-s2-compare"><thead><tr><th scope="col">标题</th><th scope="col">筛选</th><th scope="col">阅读</th><th scope="col">已记录的限制</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function wikiS2CompareTab(app, model, state) {
 if (model?.blocked) return `<section class="wiki-s2-empty" data-s2-blocked role="alert"><h2>保存的结果没有通过核对</h2><p>保存的结果没有通过核对，没有显示，也不会用示例内容补上。</p><button type="button" class="hs-button" data-wiki-stage2-action="read">重新读取</button><details class="wiki-s2-tech"><summary>技术细节</summary><code>${esc(model.blocked)}</code></details></section>`;
 if (!model || !model.routes.length) return wikiS2InputTable();
 return `${wikiS2Opinions(model)}${wikiS2CompareTable(app, model, state)}${wikiS2Reviews(model)}${wikiS2Decision(app, model, state)}`;
}

// --- Literature and evidence tab (8.15, 8.17) ----------------------------------------------
const wikiS2LitRows = [['author','作者／机构'],['level','阅读层级（原记录）'],['role','在本报告里的用途'],['notes','来源卡说明与限制'],
 ['excerpt','原文摘录／保存的证据'],['title','题名'],['access','访问与版本'],['method','研究方法与样本']];

function wikiS2Metrics(model) {
 const text = model.comparisonText || '';
 const match = text.match(/(?:^|\n)#{2,4}\s*(?:建議指標|建议指标|Metrics|Proposed metrics)[^\n]*\n([\s\S]*?)(?=\n#{1,4}\s|$)/i);
 const lines = match ? match[1].split(/\r?\n/).map(line => line.replace(/^\s*[-*]\s*/, '').trim()).filter(Boolean) : [];
 return `<section class="wiki-s2-card" data-s2-metrics><h2>指标与可比条件</h2>
  <p class="wiki-s2-muted">下面是交付报告里的验证计划。目前没有统一的实测数值和可比条件，<b>不画效果排名</b>。单位、条件和可比性还没核实，不画图。</p>
  ${lines.length ? `<table class="wiki-s2-compare"><thead><tr><th scope="col">指标</th><th scope="col">准备测什么</th><th scope="col">实测值</th><th scope="col">对照实验</th></tr></thead><tbody>${lines.map((line, i) => `<tr><th scope="row">指标 ${i + 1}</th><td>${wikiS2Cell(line, 200)}</td><td>未提供</td><td><span class="wiki-s2-opinion" data-tone="none">待验证</span></td></tr>`).join('')}</tbody></table>` : '<p><span class="wiki-s2-missing">未提供</span> 交付报告里没有读到验证计划的指标。</p>'}</section>`;
}

function wikiS2Matrix(model, state) {
 const keyOfEvidence = new Map((model.evidence || []).map(row => [row.evidence_id, wikiS2Key(row.work_id, row.version_id)]));
 const columns = model.literature.filter(lit => model.routes.some(route => (route.evidenceIds || []).some(id => keyOfEvidence.get(id) === lit.key)));
 const open = state.card && model.literature.find(lit => lit.key === state.card);
 return `<section class="wiki-s2-card" data-s2-matrix><h2>证据关系矩阵</h2>
  <p class="wiki-s2-muted">只画候选方向到来源的引用关系。空格表示没有保存绑定，不等于不相关；引用数不是相似度，也不是推荐或评分。</p>
  ${columns.length ? `<div class="wiki-s2-scroll"><table class="wiki-s2-compare"><thead><tr><th scope="col">方向</th>${columns.map(lit => `<th scope="col">${esc(lit.title)}</th>`).join('')}</tr></thead><tbody>
  ${model.routes.map(route => `<tr><th scope="row">方向 ${esc(route.letter)}</th>${columns.map(lit => (route.evidenceIds || []).some(id => keyOfEvidence.get(id) === lit.key)
   ? `<td><button type="button" class="wiki-s2-dot" data-s2-card="${esc(lit.key)}" aria-label="打开 ${esc(lit.title)} 的来源卡">●</button></td>` : '<td><span class="wiki-s2-muted">未绑定</span></td>').join('')}</tr>`).join('')}</tbody></table></div>`
   : '<p><span class="wiki-s2-missing">还没有</span> 保存的候选没有绑定到任何来源。</p>'}
  <p class="wiki-s2-muted">文献之间的关系：未提供。当前保存的契约没有给出明确关系，不能用共同标签推断。</p>
  ${open ? `<details open class="wiki-s2-fold"><summary>来源卡 · ${esc(open.title)}</summary><pre>${esc(JSON.stringify(open.raw, null, 2))}</pre></details>` : ''}</section>`;
}

function wikiS2Literature(model, state) {
 if (!model?.literature) return `<section class="wiki-s2-card" data-s2-literature><h2>文献对比</h2><p><span class="wiki-s2-missing">还没有</span> 当前读取到的保存记录里没有文献对比数据（后台没有给这个页面提供它）。</p></section>`;
 const lits = model.literature, pages = Math.max(1, Math.ceil(lits.length / wikiS2ChipPage));
 state.litPage = Math.max(0, Math.min(state.litPage, pages - 1));
 const chosen = lits.filter(lit => state.lit.includes(lit.key));
 const chips = lits.slice(state.litPage * wikiS2ChipPage, (state.litPage + 1) * wikiS2ChipPage).map(lit =>
  `<button type="button" class="wiki-s2-chip" data-s2-lit="${esc(lit.key)}" aria-pressed="${state.lit.includes(lit.key)}">${esc(lit.title)} <span class="wiki-s2-opinion" data-tone="none">${esc(lit.tag ?? '类型未提供')}</span></button>`).join('');
 let rows = wikiS2LitRows.map(([key, label]) => ({key, label, value:lit => lit.rows[key] ?? null}));
 if (state.hideSame && chosen.length > 1) rows = rows.filter(row => new Set(chosen.map(lit => JSON.stringify(row.value(lit)))).size > 1);
 return `<section class="wiki-s2-card" data-s2-literature><h2>文献对比</h2><p class="wiki-s2-muted">选 2–3 篇并排对照。这里比较的是原始来源卡（含论文、官方报告和数据指南），不是统一的全文论文表。没提供的字段写「未提供」。</p>
  <div class="wiki-s2-chips" role="group" aria-label="选择来源">${chips}</div>${state.litNote ? `<p class="wiki-s2-warnline" role="status">${esc(state.litNote)}</p>` : ''}
  ${pages > 1 ? `<div class="wiki-s2-pager"><button type="button" class="hs-button" data-s2-litpage="-1" ${state.litPage === 0 ? 'disabled' : ''}>上一页</button><span>第 ${state.litPage + 1} 页，共 ${pages} 页</span><button type="button" class="hs-button" data-s2-litpage="1" ${state.litPage + 1 === pages ? 'disabled' : ''}>下一页</button></div>` : ''}
  <label class="wiki-s2-hide"><input type="checkbox" data-s2-hide ${state.hideSame ? 'checked' : ''}> 隐藏相同字段</label>
  ${chosen.length ? `<div class="wiki-s2-scroll" tabindex="0" aria-label="文献对照表"><table class="wiki-s2-compare"><thead><tr><th scope="col">对照维度</th>${chosen.map(lit => `<th scope="col">${esc(lit.title)}</th>`).join('')}</tr></thead><tbody>
  ${rows.map(row => `<tr><th scope="row">${row.label}</th>${chosen.map(lit => `<td>${wikiS2Cell(row.value(lit), 240)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p><button type="button" class="hs-button" data-s2-card-open="${esc(chosen[0].key)}">查看完整来源卡</button></p>`
   : '<div class="wiki-s2-dashed">选 2–3 篇并排对照</div>'}
  ${state.card && chosen.find(lit => lit.key === state.card) ? `<details open class="wiki-s2-fold"><summary>来源卡 · ${esc(chosen.find(lit => lit.key === state.card).title)}</summary><pre>${esc(JSON.stringify(chosen.find(lit => lit.key === state.card).raw, null, 2))}</pre></details>` : ''}</section>`;
}

function wikiS2SaveRow(model) {
 const matching = typeof m9Matching === 'function' && model?.origin === 'import' ? m9Matching() : [];
 const material = matching[0], draft = material && typeof m9Draft === 'function' ? m9Draft(material) : null;
 const busy = typeof m9 !== 'undefined' && m9.busy;
 const note = typeof m9 !== 'undefined' && typeof n9Message === 'function' ? n9Message(m9.status) : '';
 if (!material) return `<section class="wiki-s2-card" data-s2-saverow><div class="wiki-s2-actions"><span><button type="button" class="hs-button" disabled>保存当前文献与路线比较</button><small class="wiki-s2-reason">现在还不能做这一步：保存比较清单要先接入一份候选包材料</small></span><span><button type="button" class="hs-button" disabled>恢复已保存比较</button><small class="wiki-s2-reason">现在还不能做这一步：还没有已保存的比较</small></span></div></section>`;
 return `<section class="wiki-s2-card" data-s2-saverow><div class="wiki-s2-actions"><span><button type="button" class="hs-button" data-n9-choice-save="${esc(material.id)}" ${busy ? 'disabled' : ''}>保存当前文献与路线比较</button>${busy ? '<small class="wiki-s2-reason">正在保存，请稍等</small>' : ''}</span>
  <span><button type="button" class="hs-button" data-n9-choice-restore="${esc(material.id)}" ${busy || !draft?.selection ? 'disabled' : ''}>恢复已保存比较</button>${!busy && !draft?.selection ? '<small class="wiki-s2-reason">还没有已保存的比较</small>' : ''}</span></div>
  <p role="status" class="wiki-s2-muted">${esc(note || (draft?.selection ? '已有保存的比较清单；未提交正式选择' : '还没有保存过比较清单；保存不会提交正式选择'))}</p></section>`;
}

function wikiS2LiteratureTab(model, state) {
 if (!model || model.blocked || !model.routes.length) return '<section class="wiki-s2-card"><p>这个课题还没有 Stage 2 候选包，这里暂时是空的。</p></section>';
 return `${model.origin === 'archive' ? '' : wikiS2SaveRow(model)}${wikiS2Literature(model, state)}${model.literature ? wikiS2Matrix(model, state) : ''}${wikiS2Metrics(model)}`;
}

// --- Materials tab (8.14) -------------------------------------------------------------------
function wikiS2MaterialsTab(app) {
 const delivered = rt.overview?.stage1?.delivery?.canonical_package;
 const index = typeof wikiS1Index === 'function' ? wikiS1Index() : null;
 const m = typeof v9ConnectionModel === 'function' ? v9ConnectionModel(app) : null;
 const waiting = m?.code === 'stage2-controller-current-input-required';
 const row = delivered
  ? `<div class="wiki-s2-package"><b>这个课题的 Stage 1 文献包</b><span>${index ? index.papers.length + ' 篇文献' : '条数：还没有（这里没有读取它的文献清单）'}</span><span class="wiki-s2-st" data-tone="${waiting ? 'wait' : 'done'}">${waiting ? '等待接收' : '已接收'}</span><span class="wiki-s2-opinion" data-tone="none">只读</span></div>`
  : '<p class="wiki-s2-package">Stage 2 在等这个课题的 Stage 1 文献包</p>';
 const imported = typeof p9 !== 'undefined' && p9.shown;
 return `<section class="wiki-s2-card" data-s2-materials><h2>材料</h2>${row}
  <details class="wiki-s2-fold"><summary>接入其他候选包（本地已解包）· 高级</summary>
  <p class="wiki-s2-muted">使用 Harness 原有的候选包格式；目录要放在配置的接入目录里；核对全部来源字节，原有科学规则不放宽。</p>
  <p class="wiki-s2-muted">接入别的候选包的内容不会冒充本课题的 Stage 2，血缘按原包保留，页面用来历标签区分。</p>
  ${imported ? '<p role="status">已核验导入材料，下面显示该版本；还没有生成新研究。</p>' : ''}
  ${typeof m9Panel === 'function' ? m9Panel(app) : ''}</details></section>`;
}

// --- Page ----------------------------------------------------------------------------------
function wikiS2State(app, model) {
 const key = JSON.stringify([rt.ref, rt.overview?.project?.revision ?? null, model?.routes?.map(route => route.key) ?? null]);
 if (app.wikiS2?.key !== key) {
  const flags = new Set(), stored = wikiS2Load(rt.ref, 'flags');
  for (const id of Array.isArray(stored) ? stored : []) flags.add(String(id));
  const tentative = wikiS2Load(rt.ref, 'tentative'), draft = wikiS2Load(rt.ref, 'draft');
  const route = model?.routes?.find(row => row.key === tentative?.key);
  app.wikiS2 = {key, tab:'compare', page:0, pick:null, note:'', flags, lit:(model?.literature || []).slice(0, 2).map(lit => lit.key),
   litPage:0, litNote:'', hideSame:false, card:null, tentOpen:false, draftStatus:'',
   tentative:route ? {key:route.key, letter:route.letter, note:typeof tentative.note === 'string' ? tentative.note : ''} : null};
  const mine = model?.routes?.find(row => row.key === draft?.key);
  if (mine) { app.wikiS2.pick = mine.key; app.wikiS2.note = typeof draft.note === 'string' ? draft.note.slice(0, 4096) : ''; app.wikiS2.draftStatus = 'saved'; }
 }
 return app.wikiS2;
}

function wikiS2Storage(ref, name) { return 'wiki-s2-' + name + ':' + ref; }
function wikiS2Load(ref, name) {
 try { return JSON.parse(sessionStorage.getItem(wikiS2Storage(ref, name)) || 'null'); } catch (_) { return null; }
}
function wikiS2Store(ref, name, value) {
 try {
  const key = wikiS2Storage(ref, name);
  if (value === null) { sessionStorage.removeItem(key); return sessionStorage.getItem(key) === null; }
  const text = JSON.stringify(value);
  sessionStorage.setItem(key, text);
  return sessionStorage.getItem(key) === text;
 } catch (_) { return false; }
}

function wikiS2Banner(app, model) {
 // Origin of what is shown, when it is not this project's own Stage 2.
 if (model?.origin === 'import') return '<p class="wiki-s2-line" data-s2-import>本页显示的是接入的候选包，不是本课题自己的 Stage 2。 <span class="wiki-s2-opinion" data-tone="archive">导入</span></p>';
 if (model?.origin === 'archive') return `<p class="wiki-s2-line" data-s2-archive>本页显示的是${model.synthetic ? '合成样例' : '历史归档'}，只读。 <span class="wiki-s2-opinion" data-tone="${model.synthetic ? 'synth' : 'archive'}">${model.synthetic ? '合成样例' : '历史归档'}</span></p>`;
 return '';
}

function wikiS2Page(app) {
 const model = wikiS2Model(), state = wikiS2State(app, model);
 const tabs = `<div class="wiki-s2-tabs" role="tablist" aria-label="Stage 2">${Object.entries(wikiS2Tabs).map(([key, label]) =>
  `<button type="button" role="tab" id="wiki-s2-${key}" aria-selected="${key === state.tab}" tabindex="${key === state.tab ? 0 : -1}" aria-controls="wiki-s2-panel" data-s2-tab="${key}">${label}</button>`).join('')}</div>`;
 const panel = state.tab === 'literature' ? wikiS2LiteratureTab(model, state) : state.tab === 'materials' ? wikiS2MaterialsTab(app) : wikiS2CompareTab(app, model, state);
 const unbound = model && !model.blocked && model.routes.length && model.bound !== true && model.origin !== 'native'
  ? '<p class="wiki-s2-unbound" data-s2-unbound><span class="wiki-s2-unbound-tag">! 没有绑定</span> 这份候选和某个课题的 Stage 1 文献包之间没有正式的绑定记录。系统的建议不会自动批准进入 Stage 3。</p>' : '';
 return `<section data-wiki-s2 aria-label="选方向">${wikiS2ConnBlock(app)}${wikiHarnessRecord()}${unbound}${wikiS2Receipt(model)}${wikiS2Banner(app, model)}${tabs}
  <div role="tabpanel" id="wiki-s2-panel" aria-labelledby="wiki-s2-${state.tab}">${panel}</div>${wikiS2TechDetails(model)}</section>`;
}

function wikiS2TechDetails(model) {
 const rows = [['project_ref', rt.ref], ['input_version', rt.overview?.project?.input_version], ['revision', rt.overview?.project?.revision],
  ['origin', model?.origin], ...(model?.routes || []).flatMap(route => [['candidate ' + route.letter, route.id + ' · v' + route.version], ['evidence ' + route.letter, (route.evidenceIds || []).join(' · ') || null]])]
  .filter(([, value]) => value !== undefined && value !== null);
 return `<details class="wiki-s2-tech wiki-s2-page-tech" data-s2-tech><summary>本页技术细节</summary><dl>${rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd><code>${esc(value)}</code></dd></div>`).join('')}</dl></details>`;
}

function wikiS2Heading(html) {
 const topic = rt.overview?.project?.brief?.original_description || rt.savedRun?.entry?.label;
 return String(html)
  .replace(/<p class="hs-eyebrow">[^<]*<\/p>/, '<p class="hs-eyebrow">Stage 2 · 选方向</p>')
  .replace(/<h1>[^<]*<\/h1>(?:<p>[^<]*<\/p>)?/, '<h1>' + esc(topic || '选方向') + '</h1>');
}

// wikiS2 wiring: nothing above this line touches the document or the global handlers.
const wikiS2Previous = stage2;
stage2 = function (app) {
 // The earlier chain also starts the project reads (request state, connection discovery) that this
 // page depends on; its markup is not used.
 const earlier = wikiS2Previous(app);
 if (!wikiS2Active(app)) return earlier;
 const base = canonicalReadonly() ? canonicalHeading(app) : liveHeader(app);
 return `${canonicalTop()}${wikiS2Heading(base)}${wikiS2Page(app)}`;
};

function wikiS2StatusText(app) {
 const model = wikiS2Model();
 if (model?.blocked) return {now:'保存的结果没有通过核对，没有显示', next:'点「重新读取」再读一次', human:'不需要你操作'};
 if (model?.receipt) return {now:'你已选定方向', next:'进入 Stage 3 请求生成研究计划', human:'不需要你操作'};
 if (model?.routes.length && model.origin === 'archive') return {now:`${model.routes.length} 个候选已保存（${model.synthetic ? '合成样例' : '历史归档'}）`, next:'只读查看比较', human:'不需要你操作'};
 if (model?.routes.length && model.origin === 'import') return {now:`${model.routes.length} 个候选来自接入的候选包`, next:'比较后保存本机草稿', human:'这份候选包不能提交正式选择'};
 if (model?.routes.length) return {now:`${model.routes.length} 个候选已比较好，等你选`, next:'比较后在「你的决定」里选一个方向', human:'等你 · 选一个方向'};
 const m = typeof v9ConnectionModel === 'function' ? v9ConnectionModel(app) : null;
 if (!m) return null;
 const line = wikiS2ConnectionLine(m), req = m.connected ? wikiS2RequestLine() : null;
 const row = req && ['plain', 'run', 'warn'].includes(req.tone) ? req : line;
 const human = row.tone === 'wait' || row.buttons.some(button => button.primary || button.attr === 'connect') ? '等你 · ' + (row.buttons[0]?.label || row.tag) : '不需要你操作';
 return {now:'还没有候选。' + row.text, next:row.buttons[0]?.label ? '使用「' + row.buttons[0].label + '」' : '等这一步完成', human};
}

const wikiS2After = v7AfterRender;
v7AfterRender = function (app) {
 wikiS2After(app);
 const panel = app.el.querySelector('[data-wiki-s2]'), shell = app.el.querySelector('[data-wiki-shell]');
 if (!panel || !wikiS2Active(app)) return;
 const badge = app.el.querySelector('.hs-preview');
 if (badge) badge.textContent = 'Wiki V1 · 本地记录';
 if (shell) {
  const info = shell.querySelectorAll('dd'), status = wikiS2StatusText(app);
  if (status && info.length >= 3) { info[0].textContent = status.now; info[1].textContent = status.next; info[2].textContent = status.human; }
  const first = shell.querySelector('dt');
  const old = shell.querySelector('[data-s2-tag]');
  const connected = typeof v9ConnectionConnected === 'function' && v9ConnectionConnected('stage2-controller');
  if (first && connected && wikiS2CandidatesSaved()) {
   if (!old) first.insertAdjacentHTML('afterend', '<span class="wiki-s2-tag" data-s2-tag>已接通 · 候选已保存</span>');
  } else old?.remove();
 }
 if (!panel.dataset.s2Chooser) {
  panel.dataset.s2Chooser = '1';
  const chooser = app.el.querySelector('.lp-topic,.canonical-project-switch');
  if (chooser && rt.ref) {
   const details = document.createElement('details');
   details.className = 'hs-panel wiki-s2-project';
   details.innerHTML = '<summary>切换项目</summary>';
   chooser.before(details);
   details.append(chooser);
   panel.after(details);
  }
 }
};

function wikiS2Repaint(app, focus) {
 livePaint();
 if (focus) app.el.querySelector(focus)?.focus({preventScroll:true});
}
function wikiS2FindRoute(app, key) {
 return wikiS2Model()?.routes.find(route => route.key === key);
}

document.addEventListener('click', event => {
 const app = apps[0], state = app?.wikiS2;
 if (!state || !wikiS2Active(app)) return;
 const button = event.target.closest('[data-s2-tab],[data-s2-flag],[data-s2-page],[data-s2-litpage],[data-s2-lit],[data-s2-card],[data-s2-card-open],[data-s2-tentative-save],[data-s2-save],[data-s2-clear]');
 if (!button || button.disabled || !button.closest('[data-wiki-s2]')) return;
 const data = button.dataset;
 if (data.s2Tab) { state.tab = data.s2Tab; return wikiS2Repaint(app, '#wiki-s2-' + state.tab); }
 if (data.s2Flag) {
  if (state.flags.has(data.s2Flag)) state.flags.delete(data.s2Flag); else state.flags.add(data.s2Flag);
  wikiS2Store(rt.ref, 'flags', [...state.flags]);
  return wikiS2Repaint(app, `[data-s2-flag="${CSS.escape(data.s2Flag)}"]`);
 }
 if (data.s2Page) { state.page += Number(data.s2Page) || 0; return wikiS2Repaint(app); }
 if (data.s2Litpage) { state.litPage += Number(data.s2Litpage) || 0; return wikiS2Repaint(app); }
 if (data.s2Lit) {
  state.litNote = '';
  if (state.lit.includes(data.s2Lit)) state.lit = state.lit.filter(key => key !== data.s2Lit);
  else if (state.lit.length >= 3) state.litNote = '最多并排 3 个，请先取消一个';
  else state.lit.push(data.s2Lit);
  return wikiS2Repaint(app, `[data-s2-lit="${CSS.escape(data.s2Lit)}"]`);
 }
 if (data.s2Card || data.s2CardOpen) { state.card = data.s2Card || data.s2CardOpen; return wikiS2Repaint(app); }
 if (Object.hasOwn(data, 's2TentativeSave')) {
  const route = state.pick && wikiS2FindRoute(app, state.pick);
  if (!route) return;
  state.tentative = {key:route.key, letter:route.letter, note:state.note};
  state.tentOpen = true;
  if (!wikiS2Store(rt.ref, 'tentative', {key:route.key, note:state.note})) state.draftStatus = 'error';
  return wikiS2Repaint(app);
 }
 if (Object.hasOwn(data, 's2Save')) {
  state.draftStatus = state.pick && wikiS2Store(rt.ref, 'draft', {key:state.pick, note:state.note}) ? 'saved' : 'error';
  return wikiS2Repaint(app);
 }
 if (Object.hasOwn(data, 's2Clear')) {
  state.draftStatus = wikiS2Store(rt.ref, 'draft', null) ? 'cleared' : 'error';
  if (state.draftStatus === 'cleared') { state.pick = null; state.note = ''; }
  return wikiS2Repaint(app);
 }
});

document.addEventListener('change', event => {
 const app = apps[0], state = app?.wikiS2;
 if (!state || !wikiS2Active(app) || !event.target.closest?.('[data-wiki-s2]')) return;
 if (event.target.matches('[data-s2-pick]')) {
  if (state.pick !== event.target.dataset.s2Pick) state.draftStatus = 'unsaved';
  state.pick = event.target.dataset.s2Pick;
  return wikiS2Repaint(app, `[data-s2-pick="${CSS.escape(state.pick)}"]`);
 }
 if (event.target.matches('[data-s2-hide]')) { state.hideSame = event.target.checked; wikiS2Repaint(app, '[data-s2-hide]'); }
});
document.addEventListener('input', event => {
 const app = apps[0];
 if (app?.wikiS2 && event.target.matches?.('[data-s2-note]')) { app.wikiS2.note = event.target.value.slice(0, 4096); app.wikiS2.draftStatus = 'unsaved'; }
});
document.addEventListener('keydown', event => {
 const tab = event.target.closest?.('[role="tab"][data-s2-tab]');
 if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
 const keys = Object.keys(wikiS2Tabs), at = keys.indexOf(tab.dataset.s2Tab);
 const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : (at + (event.key === 'ArrowRight' ? 1 : keys.length - 1)) % keys.length;
 event.preventDefault();
 apps[0].wikiS2.tab = keys[next];
 wikiS2Repaint(apps[0], '#wiki-s2-' + keys[next]);
});
apps[0].wikiS2Enabled = true;
