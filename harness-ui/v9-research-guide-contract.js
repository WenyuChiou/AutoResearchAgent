// Display-only annotations for an existing plan; never a planning or execution input.
const v94Pin = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const v94Object = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) &&
 Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
function v94Require(ok, code) { if (!ok) throw Error('research-guide-' + code); }
function v94Text(value, max) { return typeof value === 'string' && value.trim().length > 0 && value.length <= max; }
function v94PlanBinding(view) {
 if (view?.plan?.kind !== 'Stage3DirectionPlanningResult' || !v94Pin(view.direction_intent_sha256) ||
     !v94Pin(view.job?.plan_manifest_sha256) || !Array.isArray(view.plan.question_plans)) return null;
 return {project_ref:view.project_ref, input_version:view.input_version,
  direction_intent_sha256:view.direction_intent_sha256, plan_manifest_sha256:view.job.plan_manifest_sha256};
}
function v94GuideName(view) {
 const binding = v94PlanBinding(view);
 return binding ? 'stage3-research-' + binding.plan_manifest_sha256 + '.json' : null;
}
function v94ValidateGuide(guide, view) {
 const binding = v94PlanBinding(view);
 v94Require(binding && v94Object(guide, ['kind','version','project_ref','input_version','direction_intent_sha256','plan_manifest_sha256','question_ref','flow','loop','materials','baselines']), 'shape');
 v94Require(guide.kind === 'Stage3ResearchPresentation' && guide.version === 1, 'kind');
 v94Require(Object.keys(binding).every(key => guide[key] === binding[key]), 'binding');
 const index = view.plan.question_plans.findIndex(row => row.question_ref === guide.question_ref);
 v94Require(index >= 0 && v94Text(guide.question_ref, 240), 'question');
 const prefix = '/question_plans/' + index + '/';
 function sources(items) {
  v94Require(Array.isArray(items) && items.length > 0 && items.length <= 3, 'sources');
  for (const source of items) {
   v94Require(v94Object(source, ['pointer','quote']) && v94Text(source.quote, 2200) &&
    typeof source.pointer === 'string' && source.pointer.startsWith(prefix), 'source-shape');
   const field = source.pointer.slice(prefix.length);
   v94Require(/^(method|materials|design|analysis|validation|interpretation|minimum_deliverable|unknowns\/(0|[1-9][0-9]?))$/.test(field), 'source-pointer');
   const value = field.split('/').reduce((object, key) => object?.[key], view.plan.question_plans[index]);
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
function v94ChooseMaterial(catalog, view) {
 v94Require(Array.isArray(catalog?.materials) && catalog.materials.length <= 1000, 'catalog');
 const matches = catalog.materials.filter(item => item.project_ref === view.project_ref && item.stage === 3 && item.name === v94GuideName(view));
 if (!matches.length) return null;
 v94Require(matches.length === 1, 'ambiguous');
 const item = matches[0];
 v94Require(item.kind === 'manual-file' && item.status === 'registered' && typeof item.id === 'string' &&
  /^file-[a-f0-9]{32}$/.test(item.id) && v94Pin(item.sha256) && Number.isSafeInteger(item.bytes) && item.bytes > 0 && item.bytes <= 65536, 'material');
 return item;
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
