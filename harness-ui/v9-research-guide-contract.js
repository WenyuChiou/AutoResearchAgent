// Display-only annotations for an existing plan; never a planning or execution input.
const v94Pin = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const v94Object = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) &&
 Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
function v94Require(ok, code) { if (!ok) throw Error('research-guide-' + code); }
function v94Text(value, max) { return typeof value === 'string' && value.trim().length > 0 && value.length <= max; }
function v94PlanBinding(view, revision = null) {
 if (view?.plan?.kind !== 'Stage3DirectionPlanningResult' || !v94Pin(view.direction_intent_sha256) ||
     !v94Pin(view.job?.plan_manifest_sha256) || !Array.isArray(view.plan.question_plans)) return null;
 const binding = {project_ref:view.project_ref, input_version:view.input_version,
  direction_intent_sha256:view.direction_intent_sha256, plan_manifest_sha256:view.job.plan_manifest_sha256};
 if (revision !== null) {
  const record = revision?.record, parent = record?.binding, expected = view.feedback?.binding;
  if (!v94Pin(revision?.receipt_sha256) || record?.kind !== 'revision' || !Number.isSafeInteger(record.revision_number) ||
      record.revision_number < 2 || record.plan?.kind !== view.plan.kind || !Array.isArray(record.plan.question_plans) ||
      !expected || !['project_ref','input_version','revision','brief_sha256','parent_plan_manifest_sha256','parent_plan_sha256','plan_request_sha256'].every(key => parent?.[key] === expected[key]) ||
      !['project_ref','input_version','revision','brief_sha256'].every(key => parent[key] === view[key]) ||
      parent.parent_plan_manifest_sha256 !== binding.plan_manifest_sha256 || parent.plan_request_sha256 !== view.job.request_sha256) return null;
  Object.assign(binding, {revision_receipt_sha256:revision.receipt_sha256, revision_number:record.revision_number});
 }
 return binding;
}
function v94GuideName(view, revision = null) {
 const binding = v94PlanBinding(view, revision);
 return binding ? (revision ? 'stage3-revision-' + binding.revision_receipt_sha256 : 'stage3-research-' + binding.plan_manifest_sha256) + '.json' : null;
}
function v94ValidateGuide(guide, view, revision = null) {
 const binding = v94PlanBinding(view, revision);
 const fields = ['kind','version','project_ref','input_version','direction_intent_sha256','plan_manifest_sha256','question_ref','flow','loop','materials','baselines'];
 if (revision) fields.push('revision_receipt_sha256','revision_number');
 v94Require(binding && v94Object(guide, fields), 'shape');
 v94Require(guide.kind === 'Stage3ResearchPresentation' && guide.version === (revision ? 2 : 1), 'kind');
 v94Require(Object.keys(binding).every(key => guide[key] === binding[key]), 'binding');
 const plan = revision ? revision.record.plan : view.plan;
 const index = plan.question_plans.findIndex(row => row.question_ref === guide.question_ref);
 v94Require(index >= 0 && v94Text(guide.question_ref, 240), 'question');
 const prefix = '/question_plans/' + index + '/';
 function sources(items) {
  v94Require(Array.isArray(items) && items.length > 0 && items.length <= 3, 'sources');
  for (const source of items) {
   v94Require(v94Object(source, ['pointer','quote']) && v94Text(source.quote, 2200) &&
    typeof source.pointer === 'string' && source.pointer.startsWith(prefix), 'source-shape');
   const field = source.pointer.slice(prefix.length);
   v94Require(/^(method|materials|design|analysis|validation|interpretation|minimum_deliverable|unknowns\/(0|[1-9][0-9]?))$/.test(field), 'source-pointer');
   const value = field.split('/').reduce((object, key) => object?.[key], plan.question_plans[index]);
   v94Require(typeof value === 'string' && value.includes(source.quote), 'source-quote');
  }
 }
 const kinds = ['question','material','decision','method','comparison','validation','output','fallback'];
 function graph(value, maxNodes) {
  v94Require(v94Object(value, ['nodes','edges']) && Array.isArray(value.nodes) && value.nodes.length > 0 &&
   value.nodes.length <= maxNodes && Array.isArray(value.edges) && value.edges.length <= 18, 'graph');
  const ids = new Set();
  for (const node of value.nodes) {
   v94Require(v94Object(node, ['id','kind','title','detail','sources']) && typeof node.id === 'string' &&
    /^[a-z][a-z0-9_-]{0,40}$/.test(node.id) && !ids.has(node.id) && kinds.includes(node.kind) &&
    v94Text(node.title, 320) && v94Text(node.detail, 420), 'node');
   ids.add(node.id); sources(node.sources);
  }
  const pairs = new Set();
  for (const edge of value.edges) {
   v94Require(v94Object(edge, ['from','to','label','sources']) && ids.has(edge.from) && ids.has(edge.to) &&
    edge.from !== edge.to && v94Text(edge.label, 180) && !pairs.has(edge.from + '/' + edge.to), 'edge');
   pairs.add(edge.from + '/' + edge.to); sources(edge.sources);
  }
 }
 graph(guide.flow, 12); graph(guide.loop, 8);
 for (const [key, fields] of [['materials',['name','use','gap','sources']], ['baselines',['name','change','purpose','sources']]]) {
  v94Require(Array.isArray(guide[key]) && guide[key].length <= 8, key);
  for (const row of guide[key]) {
   v94Require(v94Object(row, fields) && fields.filter(field => field !== 'sources').every(field => v94Text(row[field], 420)), key + '-row');
   sources(row.sources);
  }
 }
 return guide;
}
function v94ChooseMaterial(catalog, view, revision = null) {
 v94Require(Array.isArray(catalog?.materials) && catalog.materials.length <= 1000, 'catalog');
 const matches = catalog.materials.filter(item => item.project_ref === view.project_ref && item.stage === 3 && item.name === v94GuideName(view, revision));
 if (!matches.length) return null;
 v94Require(matches.length === 1, 'ambiguous');
 const item = matches[0];
 v94Require(item.kind === 'manual-file' && item.status === 'registered' && typeof item.id === 'string' &&
  /^file-[a-f0-9]{32}$/.test(item.id) && v94Pin(item.sha256) && Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= 65536, 'material');
 return item;
}
// Read saved text without inventing scientific edges. Authored guides retain
// precedence and their existing byte, version and source validation.
function v94PlanReadingGuide(view, revision = null, questionRef = null) {
 const binding = v94PlanBinding(view, revision), plan = revision ? revision.record?.plan : view?.plan;
 v94Require(binding && Number.isSafeInteger(binding.input_version) && binding.input_version > 0, 'reading-binding');
 const questions = plan.question_plans;
 v94Require(Array.isArray(questions) && questions.length > 0 && questions.length <= 32, 'reading-questions');
 const context = view.direction_context?.questions;
 const eligible = row => v94Text(row?.question_ref, 240) && (!context ||
  (Array.isArray(context) && context.some(item => item.question_ref === row.question_ref)));
 const index = questionRef === null ? questions.findIndex(eligible) : questions.findIndex(row => eligible(row) && row.question_ref === questionRef);
 v94Require(index >= 0, 'reading-question');
 const question = questions[index], prefix = '/question_plans/' + index + '/';
 function excerpt(value, limit) {
  v94Require(typeof value === 'string' && value.trim().length > 0, 'reading-text');
  let text = value.trim().slice(0, limit);
  if (/[\uD800-\uDBFF]$/.test(text)) text = text.slice(0, -1);
  return text;
 }
 const labels = [
  ['materials','material','Materials'], ['method','method','Method'], ['design','comparison','Design'],
  ['validation','validation','Validation'], ['analysis','method','Analysis'],
  ['interpretation','decision','Interpretation'], ['minimum_deliverable','output','Deliverable']
 ];
 const nodes = labels.filter(([field]) => typeof question[field] === 'string' && question[field].trim()).map(([field, kind, title]) => ({
  id:field, kind, title, detail:excerpt(question[field], 400), sources:[{pointer:prefix + field, quote:excerpt(question[field], 2200)}]
 }));
 v94Require(nodes.some(node => node.id === 'method'), 'reading-method');
 // Contiguous groups cover all method lines; source order is not a causal loop.
 const lines = question.method.split('\n'), width = Math.max(1, Math.ceil(lines.length / 8)), steps = [];
 for (let offset = 0; offset < lines.length; offset += width) {
  const text = lines.slice(offset, offset + width).join('\n').trim();
  if (!text) continue;
  steps.push({id:'method-' + steps.length, kind:'method', title:excerpt(text.split('\n')[0], 100),
   detail:excerpt(text, 400), sources:[{pointer:prefix + 'method', quote:excerpt(text, 2200)}]});
 }
 const guide = {kind:'Stage3ResearchPresentation', version:revision ? 2 : 1, ...binding,
  question_ref:question.question_ref, flow:{nodes,edges:[]}, loop:{nodes:steps,edges:[]}, materials:[], baselines:[]};
 return v94ValidateGuide(guide, view, revision);
}
async function v94FetchJson(path, limit, signal, expected) {
 const response = await fetch(path, {headers:{Authorization:'Bearer ' + window.RESEARCH_PROJECTS.credential},
  credentials:'same-origin', cache:'no-store', redirect:'error', signal});
 v94Require(response.ok && response.body, 'read-failed');
 const reader = response.body.getReader(), chunks = []; let length = 0;
 try {
  for (;;) {
   const {value, done} = await reader.read(); if (done) break;
   length += value.byteLength; v94Require(length <= limit, 'byte-limit'); chunks.push(value);
  }
 } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
 const bytes = new Uint8Array(length); let offset = 0;
 for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
 if (expected) {
  v94Require(length === expected.bytes, 'byte-count');
  const pin = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');
  v94Require(pin === expected.sha256, 'hash');
 }
 return JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
}
