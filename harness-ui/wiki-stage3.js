// Wiki V1 Stage 3 page (plan and review). Display only: it re-presents the saved plan that
// v9-stage3-bridge.js already read with a GET. Nothing here writes, plans or grants execution.
const wikiS3Tabs = {plan:'计划与评审', materials:'材料'};
const wikiS3Missing = '这一版没有提供';
const wikiS3Kinds = {question:['?','问题'], material:['▤','材料'], decision:['◇','条件判断'], method:['⚙','方法'],
 comparison:['⇄','比较'], validation:['✓','验证'], output:['▣','交付'], fallback:['↳','替代路径']};
const wikiS3Cards = [['question','要回答的问题'], ['data','数据'], ['baseline','基线和对照'],
 ['pass','通过线'], ['minimum','最低可行方案'], ['stop','停止条件']];
const wikiS3Axes = {answerability:'可回答性', 'resource-fit':'资料与材料', 'inference-boundary':'推断边界',
 'result-interpretation':'结果判读', feasibility:'执行可行性'};
const wikiS3Verdicts = {adequate:['✓','通过','ok'], 'needs-revision':['✎','要修改','edit'],
 'not-adequate':['✕','不通过','no'], unknown:['?','待补充','unk']};
const wikiS3Availability = {available:'已记录可用', restricted:'访问有限制', unavailable:'目前不可用', unknown:'待核验'};

function wikiS3Active(app) {
 return app.wikiS3Enabled === true && app.page === 'workspace' && app.stage === 3 && app.lang === 'zh';
}

function wikiS3Text(value) {
 return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function wikiS3Short(text, limit = 60) {
 const chars = Array.from(text.split(/[：:\n]/u, 1)[0].trim());
 return chars.length <= limit ? chars.join('') : chars.slice(0, limit - 1).join('') + '…';
}

// ---- Data model: only what the saved plan says. Absent fields stay null. ----

function wikiS3Pointer(plan, pointer) {
 let value = plan;
 try {
  for (const token of pointer.slice(1).split('/')) value = Array.isArray(value) ? value[Number(token)] : value[token];
 } catch (_) { return null; }
 return wikiS3Text(value);
}

// Direction plans keep their method as "Step n: … — title" blocks with labelled lines.
function wikiS3MethodSteps(method) {
 const text = wikiS3Text(method);
 if (!text) return [];
 const labels = {Inputs:'inputs', Procedure:'operation', Output:'outputs', Decision:'criteria',
  'If blocked':'blocked', Timebox:'timebox'};
 const steps = [];
 for (const block of text.split(/\n\s*\n/)) {
  const lines = block.split('\n');
  const head = /^Step\s*(\d+)\s*[:：]\s*(.+)$/.exec(lines[0].trim());
  if (!head) continue;
  const row = {title:head[2].includes(' — ') ? head[2].split(' — ').slice(1).join(' — ').trim() : head[2].trim(),
   kind:head[2].includes(' — ') ? head[2].split(' — ')[0].trim() : null, fields:{}};
  let current = null;
  for (const line of lines.slice(1)) {
   const label = /^(Inputs|Procedure|Output|Decision|If blocked|Timebox)\s*[:：]\s*(.*)$/.exec(line.trim());
   if (label) { current = labels[label[1]]; row.fields[current] = label[2]; }
   else if (current) row.fields[current] += '\n' + line;
  }
  steps.push(row);
 }
 return steps;
}

function wikiS3Steps(plan, row) {
 const steps = [];
 if (Array.isArray(plan?.milestones) && plan.milestones.length) {
  const ids = plan.milestones.map(item => item.milestone_id);
  plan.milestones.forEach((milestone, index) => {
   const base = '/milestones/' + index, step = milestone.step;
   const cells = key => Array.isArray(step?.[key])
    ? step[key].map(pointer => ({location:pointer, text:wikiS3Pointer(plan, pointer)})).filter(cell => cell.text) : null;
   const operation = typeof step?.operation === 'string' ? wikiS3Pointer(plan, step.operation) : null;
   steps.push({id:'m' + index, number:index + 1, title:wikiS3Text(milestone.description) || wikiS3Missing,
    location:base, why:null,
    inputs:cells('inputs'), operation:operation ? {location:step.operation, text:operation} : null,
    outputs:cells('outputs'), criteria:cells('success_criteria'),
    needs:(milestone.depends_on || []).map(id => ids.indexOf(id)).filter(i => i >= 0).map(i => 'm' + i),
    branch:null, timebox:wikiS3Text(milestone.duration_basis)});
  });
  for (const item of steps) item.next = steps.filter(other => other.needs.includes(item.id)).map(other => other.id);
  return steps;
 }
 const parsed = wikiS3MethodSteps(row?.method);
 const prefix = '/question_plans/' + (row?.index ?? 0) + '/method';
 parsed.forEach((item, index) => {
  const one = key => wikiS3Text(item.fields[key]) ? [{location:prefix, text:wikiS3Text(item.fields[key])}] : null;
  steps.push({id:'s' + index, number:index + 1, title:item.title, location:prefix, why:null,
   inputs:one('inputs'), operation:one('operation') && one('operation')[0], outputs:one('outputs'), criteria:one('criteria'),
   needs:index ? ['s' + (index - 1)] : [], next:index + 1 < parsed.length ? ['s' + (index + 1)] : [],
   branch:wikiS3Text(item.fields.blocked), timebox:wikiS3Text(item.fields.timebox)});
 });
 return steps;
}

function wikiS3Model(view, plan) {
 if (!plan || typeof plan !== 'object') return null;
 const strict = plan.kind === 'Stage3ResearchPlan';
 const questions = Array.isArray(view?.direction_context?.questions) ? view.direction_context.questions : [];
 const rows = strict ? (plan.question_plans || []) : (plan.question_plans || []);
 const row = rows.map((item, index) => ({...item, index}))[0] || null;
 const questionText = strict
  ? wikiS3Text(plan.questions?.[0]?.text)
  : wikiS3Text(questions.find(item => item.question_ref === row?.question_ref)?.text);
 const steps = wikiS3Steps(plan, row);
 const list = values => { const rowsOut = (values || []).map(wikiS3Text).filter(Boolean); return rowsOut.length ? rowsOut : null; };
 let overview;
 if (strict) {
  overview = {question:questionText ? [questionText] : null,
   data:list((plan.resources || []).map(item => wikiS3Text(item.minimum) && item.resource_id + '：' + item.minimum)),
   baseline:list((plan.designs || []).map(item => item.family)),
   pass:list((plan.analyses || []).flatMap(item => item.criteria || [])),
   minimum:list(rows.map(item => item.minimum_deliverable)),
   stop:list((plan.designs || []).flatMap(item => item.stop_conditions || []))};
 } else {
  overview = {question:questionText ? [questionText] : null, data:list([row?.materials]), baseline:list([row?.design]),
   pass:list([row?.interpretation]), minimum:list([row?.minimum_deliverable]),
   stop:list(steps.map(item => item.branch))};
 }
 const unknowns = strict
  ? (plan.unknowns || []).map(item => ({text:wikiS3Text(item.description) || wikiS3Missing, location:null}))
  : rows.flatMap(item => (item.unknowns || []).filter(value => wikiS3Text(typeof value === 'string' ? value : null))
     .map((value, index) => ({text:value.trim(), location:'/question_plans/' + item.index + '/unknowns/' + index})));
 return {strict, plan, row, rows, steps, overview, unknowns,
  conditional:plan.planning_status === 'conditional-draft', resources:strict ? plan.resources || [] : []};
}

function wikiS3Review(view) {
 const review = view?.review || view?.plan_review || view?.semantic_review;
 if (!review || review.kind !== 'Stage3SemanticReview' || !Array.isArray(review.findings)) return null;
 return review;
}

function wikiS3JumpTarget(model, location) {
 if (typeof location !== 'string') return null;
 const milestone = /^\/milestones\/(\d+)/.exec(location);
 if (milestone) return 'step:m' + milestone[1];
 const field = /^\/question_plans\/\d+\/(\w+)/.exec(location)?.[1];
 const card = {materials:'data', design:'baseline', interpretation:'pass', analysis:'pass', validation:'pass',
  minimum_deliverable:'minimum', measurement:'data', unknowns:'unknowns'}[field];
 if (card === 'unknowns') return 'unknowns';
 if (field === 'method' && model.steps[0]) return 'step:' + model.steps[0].id;
 return card ? 'card:' + card : null;
}

// ---- State ----

function wikiS3State(app, model) {
 const key = JSON.stringify([rt.ref, v93.basis?.revision, v94?.key ?? null]);
 if (app.wikiS3?.key !== key) app.wikiS3 = {key, tab:'plan', drawing:'flow', selected:null, flash:null, unknowns:false};
 const state = app.wikiS3;
 if (model && !model.steps.some(step => step.id === state.selected)) state.selected = model.steps[0]?.id ?? null;
 return state;
}

// ---- Markup ----

const wikiS3Escape = value => rx(String(value));
const wikiS3Para = text => text.split('\n').filter(Boolean).map(line => `<p>${wikiS3Escape(line)}</p>`).join('');

function wikiS3Heading() {
 const topic = rt.overview?.project?.brief?.original_description;
 return `<div class="hs-heading"><p class="hs-eyebrow">Stage 3 · 研究计划与评审</p><h1>${wikiS3Escape(topic || '研究计划与评审')}</h1></div>`;
}

function wikiS3ReadLine(app, model) {
 const basis = v93Identity();
 if (!basis) return '<p class="ws3-note" role="status">目前没有已保存的规划。Stage 2 选定方向、并接通本课题的 Stage 3 之后，这里才会有计划；图解、评审和你的决定都会出现在这里。</p>';
 if (v93.busy) return '<p class="ws3-note ws3-run" role="status">正在读取已保存的规划，不会重新生成。</p>';
 if (basis && v93Matches(v93.errorBasis, basis) && v93.error)
  return `<div class="ws3-alert ws3-err" role="alert"><p><strong>读取失败</strong>：没有读到已保存的规划，也没有重新生成。</p><button type="button" class="hs-button" data-v93-read>重新读取</button><details><summary>读取详情</summary><p>${wikiS3Escape(v93.error)}</p></details></div>`;
 if (!model && v93.view) return '<p class="ws3-note" role="status">目前没有已保存的规划，图里只显示已有的问题和待确认事项。</p>';
 if (!model) return '<p class="ws3-note ws3-run" role="status">正在读取已保存的规划，不会重新生成。</p>';
 return '';
}

function wikiS3SummaryRow(app, model, revisionNumber) {
 const label = revisionNumber ? `人工规划草案 · v${revisionNumber}` : `${model.conditional ? '条件式草案' : '规划草案'} · v1`;
 const first = model.unknowns[0];
 const link = typeof v9StaticStage3Read === 'function' && v9StaticStage3Read() ? ''
  : `<a class="hs-button" href="${wikiS3Escape('/project-stage3-planning.html' + v93Fragment(rt.ref, app, 3))}">打开规划与收据</a>`;
 return `<section class="ws3-summary" data-s3-summary aria-label="规划摘要">
 <div><b>这份规划</b><strong>${label}</strong><small>还没有执行实验</small></div>
 <div><b>待确认</b><strong>${model.unknowns.length} 项条件待确认</strong>${model.unknowns.length ? '<button type="button" class="ws3-link" data-s3-unknowns>看待查事项</button>' : '<small>没有待查事项</small>'}</div>
 <div><b>流程起点</b><strong>${wikiS3Escape(model.steps[0]?.title || '未提供')}</strong></div>
 <div><b>先确认</b><strong>${wikiS3Escape(first ? wikiS3Short(first.text, 50) : '没有待查事项')}</strong></div>
 <div><b>规划与收据</b>${link || '<small>这次只能查看，没有收据页</small>'}<small>已自动读取保存的规划，没有重新生成</small></div></section>`;
}

function wikiS3DraftLine(revisionNumber) {
 return revisionNumber ? '<p class="ws3-draft" role="status">这是人工规划草案：由你修改，还没有经过科学审查，也没有执行研究。</p>' : '';
}

function wikiS3Overview(model, state) {
 const cards = wikiS3Cards.map(([key, title]) => {
  const value = model.overview[key];
  const body = value ? value.map(text => wikiS3Para(text)).join('') : '';
  const gap = value ? '' : `<p class="ws3-gap">还缺：规划没有写“${title}”。</p>`;
  return `<article class="ws3-ov${state.flash === 'card:' + key ? ' ws3-flash' : ''}" data-s3-card="${key}"><h3>${title}</h3>${body}${gap}</article>`;
 }).join('');
 const open = state.unknowns ? ' open' : '';
 const checks = model.unknowns.length
  ? `<ul>${model.unknowns.map(item => `<li>${wikiS3Escape(item.text)}${item.location && wikiS3JumpTarget(model, item.location) ? ` <button type="button" class="ws3-link" data-s3-jump="${wikiS3Escape(item.location)}">跳到对应位置</button>` : ''}</li>`).join('')}</ul>`
  : '<p>没有待查事项</p>';
 return `<section class="ws3-block" data-s3-overview><div class="ws3-head"><h2>计划总览</h2>${model.unknowns.length ? `<span class="ws3-pending">${model.unknowns.length} 项待查</span>` : ''}</div>
 <div class="ws3-cards">${cards}</div>
 <details class="ws3-unknowns${state.flash === 'unknowns' ? ' ws3-flash' : ''}" data-s3-unknown-list${open}><summary>完整规划与待查事项</summary><p class="ws3-note">待查事项不是已解决事项。</p>${checks}</details></section>`;
}

function wikiS3Materials(view, model) {
 const rows = [];
 if (model.strict) {
  const uses = (model.plan.question_plans || []).flatMap(item => item.resource_uses || []);
  for (const use of uses) {
   const resource = model.resources.find(item => item.resource_id === use.resource_id);
   if (resource) rows.push({name:use.resource_id, use:wikiS3Text(use.purpose) || wikiS3Missing,
    status:wikiS3Availability[resource.availability] || wikiS3Availability.unknown, basis:wikiS3Text(resource.fitness)});
  }
 } else if (model.row && typeof v93QuestionResourceUses === 'function') {
  for (const use of v93QuestionResourceUses(view, model.row.question_ref)) {
   const resource = use.resource || {}, ref = use.resource_ref || {};
   if (!wikiS3Text(resource.name)) continue;
   rows.push({name:resource.name, use:wikiS3Text(ref.purpose || resource.purpose) || wikiS3Missing,
    status:wikiS3Availability[resource.status] || wikiS3Availability.unknown,
    basis:[wikiS3Text(resource.status), wikiS3Text(ref.fit_status)].filter(Boolean).join(' · ') || null});
  }
 }
 const table = rows.length
  ? `<div class="ws3-scroll" role="region" tabindex="0" aria-label="材料用途对照表"><table><thead><tr><th scope="col">材料</th><th scope="col">用途</th><th scope="col">可用性</th><th scope="col">依据</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${wikiS3Escape(row.name)}</th><td>${wikiS3Escape(row.use)}</td><td><span class="ws3-avail">${row.status}</span></td><td>${row.basis ? `<details><summary>查看依据</summary><p>${wikiS3Escape(row.basis)}</p></details>` : '<span class="ws3-muted">没有记录</span>'}</td></tr>`).join('')}</tbody></table></div>`
  : '<p class="ws3-muted">这个问题没有已对应的资源，可用性仍待确认。</p>';
 return `<section class="ws3-block" data-s3-materials><h2>材料用途对照表</h2><p class="ws3-note">只显示已明确对应的资源；材料线索不等于已对应或已可用。</p>${table}<p><button type="button" class="ws3-link" data-s3-tab="materials">上传或查看完整材料</button></p></section>`;
}

function wikiS3Field(cell) {
 if (!cell || (Array.isArray(cell) && !cell.length)) return `<em class="ws3-muted">${wikiS3Missing}</em>`;
 return (Array.isArray(cell) ? cell : [cell]).map(item => wikiS3Para(item.text)).join('');
}

function wikiS3StepCard(step, state) {
 const open = state.selected === step.id;
 const flash = state.flash === 'step:' + step.id ? ' ws3-flash' : '';
 return `<article class="ws3-step${open ? ' ws3-open' : ''}${flash}" data-s3-step="${step.id}">
 <button type="button" class="ws3-step-head" data-s3-step-pick="${step.id}" aria-expanded="${open}"><span class="ws3-num">${step.number}</span><strong>${wikiS3Escape(step.title)}</strong><span class="ws3-toggle">${open ? '收起' : '展开'}</span></button>
 ${open ? `<div class="ws3-step-body"><p class="ws3-why"><b>为什么做</b> ${step.why ? wikiS3Escape(step.why) : `<em class="ws3-muted">${wikiS3Missing}</em>`}</p>
 <div class="ws3-io"><div><h4>输入</h4>${wikiS3Field(step.inputs)}</div><div><h4>操作</h4>${wikiS3Field(step.operation)}</div><div><h4>产出</h4>${wikiS3Field(step.outputs)}</div><div><h4>判据</h4>${wikiS3Field(step.criteria)}</div></div>
 <p class="ws3-route"><b>去向</b> ${wikiS3Escape(step.next?.length ? '继续：' + step.next.map(id => '步骤 ' + (Number(id.slice(1)) + 1)).join('、') : '结束')}${step.branch ? '；受阻时走退路 ' + wikiS3Escape(wikiS3Short(step.branch, 40)) : ''}</p>
 <p class="ws3-actual"><b>实际产出</b> 还没有：规划还没有执行。</p></div>` : ''}</article>`;
}

function wikiS3FlowBoard(model, state) {
 if (!model.steps.length) return '';
 const rows = model.steps.map((step, index) => {
  const selected = state.selected === step.id ? ' ws3-sel' : '';
  const branch = step.branch
   ? `<span class="ws3-edge" aria-hidden="true">受阻时</span><button type="button" class="ws3-fnode ws3-branch" data-s3-step-pick="${step.id}"><span class="ws3-kind" aria-hidden="true">↳</span><span class="ws3-badge">${String.fromCharCode(65 + model.steps.slice(0, index).filter(item => item.branch).length)}</span>${wikiS3Escape(wikiS3Short(step.branch, 40))}</button>` : '';
  const arrow = index + 1 < model.steps.length ? '<span class="ws3-down" aria-hidden="true">↓</span>' : '';
  return `<div class="ws3-row"><div class="ws3-main"><button type="button" class="ws3-fnode ws3-mainnode${selected}" data-s3-step-pick="${step.id}" aria-pressed="${state.selected === step.id}"><span class="ws3-kind" aria-hidden="true">${wikiS3Kinds.method[0]}</span><span class="ws3-num">${step.number}</span>${wikiS3Escape(step.title)}</button>${arrow}</div><div class="ws3-side">${branch}</div></div>`;
 }).join('');
 return `<div class="ws3-board" data-s3-flow>${rows}</div>`;
}

function wikiS3Relations(model) {
 const out = [];
 model.steps.forEach(step => (step.next || []).forEach(id => {
  const to = model.steps.find(item => item.id === id);
  if (to) out.push({from:step.title, to:to.title, condition:null, source:model.strict ? step.location + '/depends_on' : step.location});
 }));
 const guide = typeof v94 !== 'undefined' && v94.status === 'ready' && v94.source === 'authored' ? v94.guide : null;
 for (const graph of guide ? [guide.flow, guide.loop] : []) {
  const title = new Map(graph.nodes.map(node => [node.id, node.title]));
  for (const edge of graph.edges) out.push({from:title.get(edge.from), to:title.get(edge.to), condition:edge.label,
   source:edge.sources.map(item => item.pointer).join('、')});
 }
 return out;
}

function wikiS3Diagram(app, model, state) {
 const guide = typeof v94 !== 'undefined' ? v94 : null;
 const authored = guide?.status === 'ready' && guide.source === 'authored' ? guide.guide : null;
 const loopEdges = authored?.loop.edges.length || 0;
 const hasText = !!(model.row && wikiS3Text(model.row.method) || model.strict && model.plan.designs?.length);
 const modes = [['flow', '研究流程', model.steps.length > 0 || !!authored],
  ['loop', '反馈循环', loopEdges > 0], ['excerpt', '原文摘录', hasText]];
 if (!modes.find(([key, , ok]) => key === state.drawing && ok)) state.drawing = modes.find(([, , ok]) => ok)?.[0] || 'flow';
 const seg = `<div class="ws3-seg" role="group" aria-label="图解画法">${modes.map(([key, label, ok]) =>
  `<button type="button" data-s3-draw="${key}" aria-pressed="${state.drawing === key}"${ok ? '' : ' disabled'}>${label}（拟议）${ok ? '' : '<small>这份规划没有提供</small>'}</button>`).join('')}</div>`;
 let board = '', caption = '';
 if (state.drawing === 'loop' && authored && typeof v94Graph === 'function') {
  board = `<div data-v94-guide>${v94Graph(authored.loop, true, false)}</div>`;
  caption = '箭头表示计划中的回访关系；还没有运行迭代。';
 } else if (state.drawing === 'excerpt') {
  const paragraphs = model.strict ? (model.plan.designs || []).map(item => item.procedure) : String(model.row?.method || '').split(/\n\s*\n/);
  board = `<div class="ws3-excerpt">${paragraphs.map(wikiS3Text).filter(Boolean).map(text => `<blockquote>${wikiS3Para(text)}</blockquote>`).join('')}</div>`;
  caption = '下面是当前版本的原文摘录，完整内容和待查事项仍可展开。原文顺序不表示因果或反馈关系。';
 } else if (model.steps.length) {
  board = wikiS3FlowBoard(model, state);
  caption = '顺序表示规划怎么组织；各步骤还没有执行。';
 } else if (authored && typeof v94Graph === 'function') {
  board = `<div data-v94-guide>${v94Graph(authored.flow, false, false)}</div>`;
  caption = '顺序表示规划怎么组织；各步骤还没有执行。';
 }
 const legend = `<ul class="ws3-legend" aria-label="节点类型">${Object.values(wikiS3Kinds).map(([icon, name]) => `<li><span aria-hidden="true">${icon}</span>${name}</li>`).join('')}</ul>`;
 const relations = wikiS3Relations(model);
 const detail = `<details class="ws3-rel"><summary>完整关系与来源（${relations.length}）</summary>${relations.length
  ? `<ul>${relations.map(item => `<li>${wikiS3Escape(item.from)} → ${wikiS3Escape(item.to)}${item.condition ? ' · 条件：' + wikiS3Escape(item.condition) : ''} · 出自 ${wikiS3Escape(item.source)}</li>`).join('')}</ul>`
  : '<p>未提供步骤之间的关系</p>'}</details>`;
 let failed = '';
 if (guide?.status === 'failed') failed = `<div class="ws3-alert ws3-warn" role="status"><p>图解没有通过读取或来源核对；已保存的规划仍然可以看。</p><button type="button" class="hs-button" data-v94-read>重新读取图解</button><details><summary>读取详情</summary><p>${wikiS3Escape(guide.error)}</p></details></div>`;
 else if (guide?.status === 'loading') failed = '<p class="ws3-note ws3-run" role="status">正在读取同版本图解。</p>';
 return {seg, board, caption, legend, detail, failed};
}

function wikiS3Steps2(model, state) {
 if (state.drawing === 'excerpt' || !model.steps.length) {
  const text = model.strict ? '' : wikiS3Text(model.row?.method);
  return `<section class="ws3-steps" aria-label="已记录的方法说明"><h3>已记录的方法说明</h3>${text ? `<div class="ws3-method">${wikiS3Para(text)}</div>` : '<p class="ws3-muted">规划没有结构化的步骤，也没有方法说明。</p>'}</section>`;
 }
 const main = model.steps;
 const branches = main.filter(step => step.branch);
 return `<section class="ws3-steps" aria-label="步骤列表"><h3>主线（${main.length} 步）</h3>${main.map(step => wikiS3StepCard(step, state)).join('')}
 ${branches.length ? `<h3>退路（${branches.length} 条）</h3><ul class="ws3-fallbacks">${branches.map((step, index) => `<li><span class="ws3-badge">${String.fromCharCode(65 + index)}</span>步骤 ${step.number} 受阻时：${wikiS3Escape(step.branch)}</li>`).join('')}</ul>` : ''}</section>`;
}

function wikiS3Guide(app, model, state) {
 const parts = wikiS3Diagram(app, model, state);
 const quant = typeof v96Section === 'function' ? v96Section(v93.view, typeof v94SelectedRevision === 'function' ? v94SelectedRevision(v93.view) : null) : '';
 return `${quant ? `<section class="ws3-block" data-s3-quant><h2>量化输入</h2><p class="ws3-note">图表显示的是来源提供的数值，不代表已经通过科学验证。<span class="ws3-ntag">研究结果</span></p>${quant}</section>` : ''}
 <section class="ws3-block" data-s3-guide><h2>步骤和流程</h2>${parts.failed}${parts.seg}
 <div class="ws3-guide">${parts.board ? `<div class="ws3-graph">${parts.board}<p class="ws3-caption">${parts.caption}</p>${parts.legend}${parts.detail}</div>` : `<div class="ws3-graph"><p class="ws3-muted">规划没有给出可画的步骤。</p>${parts.legend}${parts.detail}</div>`}${wikiS3Steps2(model, state)}</div></section>`;
}

function wikiS3Table(model, review, state) {
 if (!review) {
  return `<section class="ws3-block" data-s3-review><h2>计划评审</h2><p class="ws3-muted">还没有：页面这次没有读到对这份规划的评审。后台只在保存评审时才有记录，读取规划的接口目前不返回它。</p></section>`;
 }
 const reviewer = review.reviewer?.kind === 'human-record' ? '真人记录' : review.reviewer?.kind === 'synthetic' ? '合成样例' : '系统';
 const rows = review.findings.map(item => {
  const verdict = wikiS3Verdicts[item.status] || ['?', item.status, 'unk'];
  const location = item.revision?.location || item.plan_locations?.[0];
  const target = wikiS3JumpTarget(model, location);
  const advice = item.revision?.action
   ? (target ? `<button type="button" class="ws3-link ws3-jump" data-s3-jump="${wikiS3Escape(location)}">${wikiS3Escape(item.revision.action)}</button>` : wikiS3Escape(item.revision.action))
   : item.missing_information ? `需要补：${wikiS3Escape(item.missing_information.needed)}（问谁：${wikiS3Escape(item.missing_information.owner)}）`
   : `<em class="ws3-muted">${item.revision === undefined ? wikiS3Missing : '没有'}</em>`;
  return `<tr><th scope="row">${wikiS3Escape(wikiS3Axes[item.axis] || item.axis)}</th><td><span class="ws3-verdict ws3-v-${verdict[2]}"><span aria-hidden="true">${verdict[0]}</span> ${wikiS3Escape(verdict[1])}</span></td><td>${wikiS3Escape(item.reason)}</td><td>${advice}</td></tr>`;
 });
 const pass = review.findings.filter(item => item.status === 'adequate').length;
 return `<section class="ws3-block" data-s3-review><div class="ws3-head"><h2>计划评审</h2><span class="ws3-by">评审者：${reviewer}</span></div>
 <div class="ws3-scroll" role="region" tabindex="0" aria-label="计划评审表"><table><thead><tr><th scope="col">维度</th><th scope="col">结论</th><th scope="col">为什么</th><th scope="col">修改建议</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>
 <p class="ws3-total">通过 ${pass} / ${review.findings.length}<span class="ws3-ntag">工程测试</span></p></section>`;
}

function wikiS3Decision(noPlan = false) {
 const why = noPlan === true ? '现在还不能做这一步：还没有计划。' : typeof noPlan === 'string' ? noPlan : null;
 const choices = [['accept', '接受计划'], ['revise', '按建议修改后再评审'], ['back', '退回 Stage 2 重选']];
 return `<section class="ws3-decide" data-s3-decision><span class="ws3-label">你的决定</span><h2>这份计划怎么处理？</h2>
 <p class="ws3-note">接受也不会启动实验。系统的评审不是你的选择。</p>
 ${choices.map(([key, label]) => `<label class="ws3-choice"><input type="radio" name="s3-decision" value="${key}" disabled> ${label}</label>`).join('')}
 <button type="button" class="hs-button" disabled>确认</button>
 <p class="ws3-why-off">${why ? why : '现在还不能做这一步：页面读不到对计划的正式决定入口，Stage 3 交接和决定还没有接通。想改计划，用上面的「评语与修订」。'}</p></section>`;
}

function wikiS3TechDetails(view) {
 const rows = [['project_ref', view?.project_ref], ['input_version', view?.input_version], ['revision', view?.revision],
  ['brief_sha256', view?.brief_sha256], ['plan_manifest_sha256', view?.job?.plan_manifest_sha256],
  ['job_request_sha256', view?.job?.request_sha256], ['plan_kind', view?.plan?.kind],
  ['schema_version', view?.plan?.schema_version], ['direction_intent_sha256', view?.direction_intent_sha256]]
  .filter(([, value]) => value !== undefined && value !== null);
 return `<details class="ws3-tech"><summary>本页技术细节</summary><dl>${rows.map(([name, value]) => `<dt>${name}</dt><dd>${wikiS3Escape(value)}</dd>`).join('')}</dl></details>`;
}

function wikiS3MaterialsTab(view) {
 const context = typeof v94fContext === 'function' ? v94fContext() : null;
 const state = context && typeof v94fState === 'function' ? v94fState(context) : null;
 const bound = state ? state.records.filter(row => row.record.kind === 'revision' && (row.record.material_refs || []).length) : [];
 const files = bound.flatMap(row => row.record.material_refs.map(ref =>
  `<li><strong>${wikiS3Escape(ref.name)}</strong> · ${wikiS3Escape(ref.bytes)} 字节 · 人工草案 v${wikiS3Escape(row.record.revision_number)} · 关联的问题：${wikiS3Escape(ref.question_ref)}（未审阅）
  <button type="button" class="hs-button" data-v95-material-download="${wikiS3Escape(ref.file_id)}" data-v95-receipt="${wikiS3Escape(row.receipt_sha256)}">核对并下载完整文件</button></li>`));
 return `<section class="ws3-block" data-s3-materials-tab><h2>这个版本的完整材料</h2>
 <p>大材料以原文件保存，最多 128 MiB；规划只保存摘要、版本和文件指纹，不会自动发给模型。</p>
 <p class="ws3-note">文件保存后，点「保存人工草案」才会绑定到这个问题和这个版本。选择文件的入口目前在「计划与评审」的「评语与修订」里：选「资料与参考」字段后出现。</p>
 ${files.length ? `<h3>已绑定的文件</h3><ul class="ws3-files">${files.join('')}</ul>` : '<p class="ws3-muted">这个版本还没有完整材料。</p>'}
 <p class="ws3-note">文件关联不等于已阅读、获准使用或科学接受。</p></section>`;
}

// DESIGN 8.13, Stage 3 state table. States shared with Stage 2 reuse its wording with "Stage 3".
function wikiS3ConnectionLine(m) {
 const line = (tone, tag, text, buttons = []) => ({tone, tag, text, buttons});
 const reason = String(m.code || '');
 if (m.phase === 'waiting') return line('run', '正在核对', '正在核对这个课题的接通记录');
 if (!m.unknown && !m.connected && !v93Identity()) return line('warn', '缺正式选择', '还缺这个课题当前版本的正式选择和核对过的选择回执。请先在 Stage 2 选定方向', [{label:'前往 Stage 2', stage:2}]);
 if (!m.unknown && m.action === 'reconnect') return line('warn', '未接通', 'Stage 3 的规划登记已保存；上次如果是强行关闭，这次启动后会先显示『未接通』，点『重新接通』即可恢复，不会重复执行任何步骤，也不会新增记录。', [{label:'重新接通', attr:'reconnect', primary:true}]);
 if (!m.unknown && m.action === 'connect') return line('wait', '可以接通', '这个课题还没有接通 Stage 3。可以登记当前配置，登记不会启动研究', [{label:'接通本课题', attr:'connect', primary:true}]);
 if (!m.unknown && /profile-unavailable$/.test(reason)) return line('warn', '缺运行配置', '这次启动没有提供这一段的运行配置。请在原目录用核对过的配置重开', [{label:'去连接与设置', page:'settings'}]);
 if (!m.unknown && typeof v9StaticStage3Read === 'function' && v9StaticStage3Read()) return line('idle', '只能看旧规划', '可以查看原配置下这个课题已保存的 Stage 3 规划，不能生成新的', [{label:'查看已保存的规划', read:true}]);
 if (m.connected) return line('done', '已接通', '这个课题已接通');
 const shared = wikiS2ConnectionLine(m);
 return {...shared, text:String(shared.text).replace(/Stage 2/g, 'Stage 3')};
}

// DESIGN 8.13 connection block for Stage 3 (same component as Stage 2; one GET read via v9ConnectionModel).
function wikiS3ConnBlock(app) {
 if (typeof v9ConnectionModel !== 'function' || typeof wikiS2ConnectionLine !== 'function') return '';
 const m = v9ConnectionModel(app);
 if (!m) return '';
 const row = wikiS3ConnectionLine(m);
 const blocked = button => button.attr && button.attr !== 'read' ? (!m.canWrite || m.writing) : button.attr === 'read' ? (m.reading || m.writing) : false;
 const why = typeof wikiS2Why === 'function' ? wikiS2Why(m) : '现在还不能做这一步';
 const buttons = row.buttons.map(button => {
  const data = button.attr ? `data-v9-connection="${button.attr}" data-connection-basis="${wikiS3Escape(m.token)}"` : button.read ? 'data-v93-read' : button.stage ? `data-stage="${button.stage}"` : `data-page="${button.page}"`;
  const off = blocked(button);
  return `<span><button type="button" class="hs-button${button.primary ? ' hs-button-primary' : ''}" ${data} ${off ? 'disabled' : ''}>${wikiS3Escape(button.label)}</button>${off ? `<small class="wiki-s2-reason">${wikiS3Escape(why)}</small>` : ''}</span>`;
 }).join('');
 const detail = m.code ? `<details class="wiki-s2-tech"><summary>技术细节</summary><code>${wikiS3Escape(m.code)}</code></details>` : '';
 return `<section class="wiki-s2-conn" data-wiki-s3-conn aria-label="本课题的 Stage 3"><h2 tabindex="-1">本课题的 Stage 3</h2>
  <div class="wiki-s2-conn-row" data-tone="${row.tone}"><span class="wiki-s2-st" data-tone="${row.tone}">${wikiS3Escape(row.tag)}</span><p>${wikiS3Escape(row.text)}</p><div class="wiki-s2-actions">${buttons}</div></div>${detail}</section>`;
}

function wikiS3Page(app, base) {
 const basis = v93Identity();
 const view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 const feedback = typeof v94fContext === 'function' ? v94fContext(app) : null;
 const feedbackState = feedback && typeof v94fState === 'function' ? v94fState(feedback) : null;
 const revision = feedbackState && typeof v94fRevision === 'function' ? v94fRevision(feedbackState) : null;
 const plan = revision?.record.plan || view?.plan;
 const model = view ? wikiS3Model(view, plan) : null;
 const state = wikiS3State(app, model);
 const connected = typeof v9ConnectionConnected === 'function' && v9ConnectionConnected('stage3-planning');
 const panel = !(connected && view?.plan) ? wikiS3ConnBlock(app) : '';
 const tabs = `<div class="ws3-tabs" role="tablist" aria-label="Stage 3">${Object.entries(wikiS3Tabs).map(([key, label]) =>
  `<button type="button" role="tab" id="ws3-tab-${key}" aria-selected="${key === state.tab}" tabindex="${key === state.tab ? 0 : -1}" data-s3-tab="${key}">${label}</button>`).join('')}</div>`;
 let body;
 if (state.tab === 'materials') body = wikiS3MaterialsTab(view);
 else if (!model) {
  const basis = v93Identity();
  const reason = basis && v93.busy ? '正在读取保存记录' : basis && v93Matches(v93.errorBasis, basis) && v93.error ? '现在还不能做这一步：已保存的规划没有读到，先重新读取。' : '现在还不能做这一步：还没有计划。';
  body = wikiS3ReadLine(app, model) + wikiS3Decision(reason);
 }
 else {
  const panelHtml = feedback && feedbackState ? v94fHtml(feedback, feedbackState) : '';
  body = `${wikiS3ReadLine(app, model)}${wikiS3SummaryRow(app, model, revision?.record.revision_number)}${wikiS3DraftLine(revision?.record.revision_number)}
  ${wikiS3Overview(model, state)}${wikiS3Materials(view, model)}${wikiS3Guide(app, model, state)}${wikiS3Table(model, wikiS3Review(view), state)}
  ${feedback ? `<section class="ws3-block" data-s3-feedback>${wikiS3FeedbackLead(feedback, feedbackState, revision)}${panelHtml}</section>` : ''}
  ${wikiS3Decision()}${typeof v93PublicArchive === 'function' ? `<details class="ws3-archive"><summary>已发布的研究设计案例</summary>${v93PublicArchive()}</details>` : ''}${wikiS3TechDetails(view)}`;
 }
 return `${wikiS3Heading()}${panel}<div data-wiki-s3-record>${typeof wikiHarnessRecord === 'function' ? wikiHarnessRecord() : ''}</div>
 <section data-wiki-s3 aria-label="研究计划与评审">${tabs}<div role="tabpanel" aria-labelledby="ws3-tab-${state.tab}">${body}</div></section>`;
}

function wikiS3FeedbackLead(context, state, revision) {
 // Parent version and receipt are internal identities (2.6): they go in the technical details, not the text.
 const version = revision ? `当前规划 v${wikiS3Escape(revision.record.revision_number)} · 人工修订版` : '当前规划 v1 · 原始规划';
 const tech = revision ? `<details class="ws3-tech"><summary>技术细节</summary><dl><dt>父版本</dt><dd><code>v1</code></dd><dt>修订收据</dt><dd><code>已保存</code></dd></dl></details>` : '';
 return `<p class="ws3-version" data-s3-version><b>${version}</b></p>${tech}`;
}

// ---- Hook-up: the page replaces the Stage 3 body only when this module is active ----

const wikiS3Later = laterStage;
laterStage = function(app) {
 if (!wikiS3Active(app)) return wikiS3Later(app);
 if (!v93Identity()) wikiS3Later(app); // earlier chain still starts its reads; its markup is not used
 return wikiS3Page(app, null);
};

function wikiS3AutoRead(app) {
 const basis = v93Identity();
 if (!basis || v93.busy || v93Matches(v93.basis, basis) || (v93Matches(v93.errorBasis, basis) && v93.error)) return;
 const key = JSON.stringify([basis, rt.epoch]);
 if (app.wikiS3?.autoKey === key) return;
 app.wikiS3 = {...(app.wikiS3 || {}), autoKey:key};
 // One GET per project version; a failure keeps the explicit retry button instead of looping.
 Promise.resolve().then(() => v93ReadSaved(app, basis));
}

const wikiS3After = v7AfterRender;
v7AfterRender = function(app) {
 wikiS3After(app);
 if (!wikiS3Active(app)) return;
 const keep = app.wikiS3?.autoKey;
 const view = v93.view, basis = v93Identity();
 const shell = app.el.querySelector('[data-wiki-shell]');
 const connected = typeof v9ConnectionConnected === 'function' && v9ConnectionConnected('stage3-planning');
 if (shell && connected && view?.plan && v93Matches(v93.basis, basis) && !shell.querySelector('[data-s3-conn-tag]')) {
  shell.querySelector('dt')?.insertAdjacentHTML('afterend', '<span class="ws3-tag" data-s3-conn-tag>已接通 · 计划已保存</span>');
 }
 const flash = app.wikiS3?.flash;
 if (flash) {
  const target = app.el.querySelector(`[data-s3-step="${flash.slice(5)}"],[data-s3-card="${flash.slice(5)}"],[data-s3-unknown-list]`);
  target?.scrollIntoView?.({block:'center'});
  setTimeout(() => { if (app.wikiS3?.flash === flash) app.wikiS3.flash = null; }, 1500);
 }
 if (app.wikiS3) app.wikiS3.autoKey = keep ?? app.wikiS3.autoKey;
 wikiS3AutoRead(app);
};

document.addEventListener('click', event => {
 const app = apps[0], state = app?.wikiS3;
 if (!state || !app.el.contains(event.target)) return;
 const button = event.target.closest('[data-s3-tab],[data-s3-draw],[data-s3-step-pick],[data-s3-jump],[data-s3-unknowns]');
 if (!button || button.disabled || !button.closest('[data-wiki-s3]')) return;
 const data = button.dataset;
 if (data.s3Tab) state.tab = data.s3Tab;
 else if (data.s3Draw) state.drawing = data.s3Draw;
 else if (data.s3StepPick) state.selected = state.selected === data.s3StepPick ? null : data.s3StepPick;
 else if ('s3Unknowns' in data) { state.unknowns = true; state.flash = 'unknowns'; } // the attribute is empty, so test presence
 else if (data.s3Jump) {
  const model = wikiS3Model(v93.view, v93.view?.plan);
  const target = model && wikiS3JumpTarget(model, data.s3Jump);
  if (!target) return;
  if (target.startsWith('step:')) state.selected = target.slice(5);
  if (target === 'unknowns') state.unknowns = true;
  state.flash = target;
 }
 livePaint();
});

document.addEventListener('keydown', event => {
 const tab = event.target.closest?.('[role="tab"][data-s3-tab]'), state = apps[0]?.wikiS3;
 if (!tab || !state || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
 const keys = Object.keys(wikiS3Tabs);
 state.tab = keys[(keys.indexOf(tab.dataset.s3Tab) + (event.key === 'ArrowRight' ? 1 : keys.length - 1)) % keys.length];
 event.preventDefault(); livePaint();
 apps[0].el.querySelector('#ws3-tab-' + state.tab)?.focus({preventScroll:true});
});

document.addEventListener('toggle', event => {
 const list = event.target.matches?.('[data-s3-unknown-list]') ? event.target : null;
 if (list && apps[0]?.wikiS3) apps[0].wikiS3.unknowns = list.open;
}, true);

apps[0].wikiS3Enabled = true;
