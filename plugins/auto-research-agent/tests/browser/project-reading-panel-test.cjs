/* Current UI source with a tiny DOM and async broker mock. No browser, host,
 * SDK, model, search or network runs; this proves only the specified UI guards. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.resolve(__dirname, '../../cli/research_workspace_native/web');
const hash = 'a'.repeat(64);
const quote = '<synthetic source quote>\nExact second line.';
const project = {project_ref: 'synthetic-A', revision: 1, input_version: 1, brief_sha256: hash};
const context = {project, stage1: {ledger: {state_sha256: hash}}, language: 'en', busy: false, held: false};
const classification = Object.fromEntries(['topic_cluster', 'method', 'geography', 'population', 'data_type', 'domain'].map(key => [key, 'Unknown: not assessed.']));
const findings = Object.fromEntries(['question', 'data', 'method', 'main_findings', 'limitations', 'relevance', 'transferability'].map(key => [key, 'Unknown: not assessed.']));
const reply = {...project, ledger_state_sha256: hash, output_ref: hash, draft_sha256: hash,
  draft: {summary: 'Synthetic draft', classification, findings,
    limitations: [], open_questions: [], evidence: [{source_id: 'synthetic-source', text_sha256: hash,
      start_byte: 0, end_byte: Buffer.byteLength(quote, 'utf8'), quote, claim_id: null}]},
  offers: [{evidence_index: 0, offer_ref: 'claim-synthetic', offer_sha256: hash, source_id: 'synthetic-source', quote, existing_claim_id: null}],
  reading_review_offer: {offer_ref: 'reading-synthetic', offer_sha256: hash},
  stage1_complete: false};

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.style = {}; this.dataset = {};
    this.hidden = false; this.disabled = false; this._value = undefined; this.textContent = '';
  }
  append(node) {this.children.push(node);}
  replaceChildren(...nodes) {this.children = nodes;}
  setAttribute(key, value) {this[key] = value;}
  querySelectorAll(names) {const tags = names.split(','); return flatten(this).filter(node => node !== this && tags.includes(node.tagName));}
  querySelector(names) {return this.querySelectorAll(names)[0] || null;}
  get value() {return this._value !== undefined ? this._value : this.tagName === 'select' && this.children.length ? this.children[0].value : '';}
  set value(value) {this._value = value;}
  set innerHTML(_) {throw Error('unsafe HTML sink');}
  reportValidity() {return true;}
  scrollIntoView() {}
}
function flatten(node) {return [node, ...node.children.flatMap(flatten)];}
function panel() {
  const roots = Object.fromEntries(['reading-card', 'reading-panel', 'reading-title'].map(id => {
    const element = new Element('div'); element.id = id; return [id, element];
  }));
  const sandbox = {window: {}, TextEncoder, document: {
    createElement: tag => new Element(tag),
    getElementById: id => roots[id] || Object.values(roots).flatMap(flatten).find(node => node.id === id) || null
  }};
  vm.runInNewContext(fs.readFileSync(path.join(web, 'projects-reading.js'), 'utf8'), sandbox);
  return {roots, ui: sandbox.window.ResearchProjectReading};
}

async function panelGuards() {
  const {roots, ui} = panel(), saves = [], event = {preventDefault(){}};
  ui.update(context); assert.equal(ui.render(reply, async body => {saves.push(body); return null;}), true);
  assert.equal(saves.length, 0); assert.equal(roots['reading-panel'].querySelectorAll('form').filter(form => form.id === 'reading-claim-form').length, 0);
  assert.equal(roots['reading-panel'].querySelectorAll('details')[0].open, undefined);
  const chooser = roots['reading-panel'].querySelectorAll('select')[0]; chooser.value = '0'; chooser.onchange();
  const form = roots['reading-panel'].querySelectorAll('form').find(node => node.id === 'reading-claim-form'), claim = form.querySelectorAll('textarea')[0];
  const section = form.querySelectorAll('input')[0], [relation, level] = form.querySelectorAll('select');
  assert.equal(claim.value, ''); assert.equal(section.value, ''); assert.equal(relation.value, 'pending'); assert.equal(level.value, 'full-text');
  assert.equal(form.querySelectorAll('blockquote')[0].textContent, quote);
  assert.equal(form.querySelectorAll('blockquote')[0].style.whiteSpace, 'pre-wrap');
  await form.onsubmit(event); assert.equal(saves.length, 0);
  section.value = 'Synthetic section';
  for (const invalid of ['\uD800', '\uDC00', '字'.repeat(1366)]) {
    claim.value = invalid; await form.onsubmit(event); assert.equal(saves.length, 0);
  }
  claim.value = 'User entered claim'; ui.update({...context, held: true});
  await form.onsubmit(event); assert.equal(saves.length, 0); assert.equal(claim.disabled, true);
  ui.update({...context, busy: true}); await form.onsubmit(event); assert.equal(saves.length, 0);
  ui.update(context); await form.onsubmit(event); assert.equal(saves.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(saves[0].review)), {
    claim_text: 'User entered claim', relation: 'pending', evidence_level: 'full-text', section: 'Synthetic section'
  });
  ui.update({...context, project: {...project, input_version: 2}});
  assert.equal(roots['reading-card'].hidden, true); assert.equal(roots['reading-panel'].children.length, 0);
  await form.onsubmit(event); assert.equal(saves.length, 1); assert.equal(ui.render(reply, () => {}), false);
  ui.update({...context, language: 'zh-Hans'}); assert.equal(roots['reading-title'].textContent, '审阅已保存阅读草稿');
  ui.update({...context, language: 'zh-Hant'}); assert.equal(roots['reading-title'].textContent, '審閱已保存閱讀草稿');
  assert.equal(ui.render(null, () => {}), false);
  assert.equal(ui.render({...reply, draft_sha256: 'bad'}, () => {}), false);
  assert.equal(ui.render({...reply, draft: {...reply.draft, summary: 'x'.repeat(262145)}}, () => {}), false);
  assert.equal(ui.render({...reply, draft: {...reply.draft, evidence: [null]}}, () => {}), false);
  console.log('PASS panel: explicit defaults, exact quote, Unicode/UTF-8, held/busy, stale version/language, bounded response');
}

const notesReview = {classification, findings, roles: []};
const notesItem = {project_ref: project.project_ref, input_version: project.input_version, brief_sha256: hash,
  ledger_state_sha256: hash, output_ref: hash, draft_sha256: hash,
  ...reply.reading_review_offer, review: notesReview, confirmed: true};
async function noteGuards() {
  const {roots, ui} = panel(), saves = [], event = {preventDefault(){}};
  ui.update(context); assert.equal(ui.render(reply, () => {throw Error('implicit claim');}, async body => {saves.push(body); return null;}), true);
  const form = roots['reading-panel'].querySelectorAll('form').find(node => node.id === 'reading-notes-form');
  const inputs = form.querySelectorAll('textarea'), confirm = form.querySelectorAll('input')[0];
  assert.equal(roots['reading-panel'].querySelectorAll('details')[1].open, undefined);
  assert.equal(inputs.length, 13); assert.equal(confirm.checked, false); assert.equal(saves.length, 0);
  for (const input of inputs) assert.equal(input.value, 'Unknown: not assessed.');
  await form.onsubmit(event); assert.equal(saves.length, 0, 'explicit checkbox is necessary even when fields are valid');
  confirm.checked = true;
  for (const invalid of ['\uD800', '\uDC00', '字'.repeat(1366)]) {
    inputs[0].value = invalid; await form.onsubmit(event); assert.equal(saves.length, 0);
  }
  inputs[0].value = classification.topic_cluster;
  ui.update({...context, held: true}); await form.onsubmit(event); assert.equal(saves.length, 0); assert.equal(confirm.disabled, true);
  ui.update({...context, busy: true}); await form.onsubmit(event); assert.equal(saves.length, 0);
  ui.update(context); await form.onsubmit(event); assert.equal(saves.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(saves[0])), notesItem, 'exact raw Unknown annotations and empty roles are submitted');
  ui.update({...context, project: {...project, input_version: 2}}); await form.onsubmit(event); assert.equal(saves.length, 1);
  ui.update(context); assert.equal(ui.render({...reply, reading_review_offer: null}, () => {}, async () => {throw Error('no-offer submit');}), true);
  const unavailable = roots['reading-panel'].querySelectorAll('form').find(node => node.id === 'reading-notes-form');
  for (const control of unavailable.querySelectorAll('button,input,textarea')) assert.equal(control.disabled, true);
  unavailable.querySelectorAll('input')[0].checked = true; await unavailable.onsubmit(event);
  console.log('PASS notes: folded form, explicit checkbox, 13 raw Unknown fields, roles0, Unicode/UTF-8, held/busy/no offer, stale version');
}

// Extract the actual submitter rather than copying the production guard into
// the test. Its dependencies are the existing broker and project loader mocks.
const projectSource = fs.readFileSync(path.join(web, 'projects.js'), 'utf8');
function actualFunction(name, next, isAsync = true, nextAsync = next !== 'renderProject') {
  const begin = projectSource.indexOf('  ' + (isAsync ? 'async ' : '') + 'function ' + name + '(');
  const end = projectSource.indexOf('  ' + (nextAsync ? 'async ' : '') + 'function ' + next + '(', begin);
  assert(begin >= 0 && end > begin, 'exact production function boundaries required');
  return projectSource.slice(begin, end) + '\nglobalThis.invoke = ' + name + ';';
}
const review = {claim_text: 'Synthetic reviewed claim', relation: 'pending', evidence_level: 'full-text', section: 'Synthetic section'};
const item = {...project, ledger_state_sha256: hash, output_ref: hash, draft_sha256: hash, ...reply.offers[0], review};
function broker(operation = 'claim') {
  const state = {project: {...project}, generation: 7, busy: false, loading: false, activeJob: false,
    stage1: context.stage1, readingReview: reply};
  let finish, calls = [], posted = [];
  const sandbox = {state, pending: [], rows: (value, name) => value[name],
    identity: () => ({revision: state.project.revision, input_version: state.project.input_version, brief_sha256: state.project.brief_sha256}),
    mutate: async (operation, body, ref) => {
      assert.equal(operation, 'stage1/' + requested); assert.equal(body.confirmed, true); assert.equal(ref, project.project_ref);
      posted.push(JSON.parse(JSON.stringify(body)));
      return new Promise(resolve => {finish = resolve;});
    },
    loadProject: async ref => {calls.push(ref);}
  };
  const requested = operation, notes = operation === 'reading-review';
  vm.runInNewContext(actualFunction(notes ? 'submitReadingReview' : 'submitReadingClaim', notes ? 'submitCoverage' : 'submitReadingReview'), sandbox);
  return {state, calls, posted, submit: () => sandbox.invoke(notes ? notesItem : item), finish: () => finish({status: 'saved'})};
}
async function saveRaces() {
  for (const operation of ['claim', 'reading-review']) {
    const active = broker(operation), saved = active.submit(); active.finish(); await saved;
    assert.deepEqual(active.calls, ['synthetic-A'], 'same project identity may refresh after save');
    if (operation === 'reading-review') assert.deepEqual(active.posted[0], {
      revision: 1, input_version: 1, brief_sha256: hash, ledger_state_sha256: hash,
      output_ref: hash, draft_sha256: hash, offer_ref: 'reading-synthetic', offer_sha256: hash,
      review: notesReview, confirmed: true
    }, 'registry POST body has only the identity, sealed draft/offer and explicit review');
    const switched = broker(operation), waiting = switched.submit();
    // Exact loadProject(B) entrance: generation advances and loading begins,
    // while overview B has not arrived and state.project still names A.
    switched.state.generation += 1; switched.state.loading = true;
    assert.equal(switched.state.project.project_ref, 'synthetic-A');
    switched.finish(); assert.equal((await waiting).status, 'saved');
    assert.deepEqual(switched.calls, [], 'A must not refresh and take back B while B is loading');
    for (const change of [{project_ref: 'synthetic-B'}, {input_version: 2}, {brief_sha256: 'b'.repeat(64)}]) {
      const altered = broker(operation), pending = altered.submit(); altered.state.project = {...altered.state.project, ...change};
      altered.finish(); await pending; assert.deepEqual(altered.calls, [], 'changed project identity must not refresh A');
    }
  }
  console.log('PASS brokers: claim/notes exact body and same-identity refresh; A pending / B starts / A saved; ref, input version and brief changes');
}

async function registryIntent() {
  for (const [operation, kind, semantic] of [
    ['reading-review', 'stage1-reading-registry', {output_ref: hash, draft_sha256: hash, offer_ref: 'reading-synthetic', offer_sha256: hash, review: notesReview}],
    ['prepare-delivery', 'stage1-produce-records', {checkpoint_event_id: 'synthetic-checkpoint'}]
  ]) {
  const hashed = [], remembered = [], posts = [], forgotten = [];
  const sandbox = {state: {busy: false, loading: false}, pending: [], key: () => 'synthetic-ui-key',
    buttons(){}, notice(){}, t: key => key,
    requestHash: async (kind, body) => {hashed.push({kind, body: JSON.parse(JSON.stringify(body))}); return hash;},
    remember: row => remembered.push(row), forget: key => forgotten.push(key),
    route: (ref, operation) => ({ref, operation}), request: async (route, body) => {posts.push({route, body}); return {status: 'saved'};}
  };
  vm.runInNewContext(actualFunction('mutate', 'renderProject'), sandbox);
  const body = {revision: 1, input_version: 1, brief_sha256: hash, ledger_state_sha256: hash, ...semantic, confirmed: true};
  await sandbox.invoke('stage1/' + operation, body, project.project_ref);
  assert.equal(hashed.length, 1); assert.equal(hashed[0].kind, kind);
  assert.deepEqual(hashed[0].body, {...body, key: 'synthetic-ui-key'});
  assert.equal(remembered[0].kind, kind); assert.equal(posts.length, 1);
  assert.equal(posts[0].route.operation, 'stage1/' + operation); assert.deepEqual(forgotten, ['synthetic-ui-key']);
  assert.equal(Object.keys(body).some(key => /entry.*sha/i.test(key)), false, 'no extra registry-entry digest enters request hashing');
  }
  console.log('PASS intents: actual mutate registry/produce-records kinds, exact bodies, one POST each, no extra entry SHA');
}

async function preparationGuard() {
  const nodes = new Map(), calls = [], posts = [];
  const valid = {ledger: {state_sha256: hash}, checkpoint: {current: true, event_id: 'synthetic-checkpoint'}, saved_records_connected: true};
  let finish, expectedOperation = 'stage1/prepare-delivery';
  const sandbox = {state: {project: {...project, brief: {}}, stage1: valid, generation: 2, busy: false, loading: false, activeJob: false, modelOffers: []},
    pending: [], bootstrap: {models: false}, window: {}, document: {querySelectorAll: () => []},
    $: id => {if (!nodes.has(id)) {const node = new Element('div'); node.append(new Element('button')); nodes.set(id, node);} return nodes.get(id);},
    availableStage2: () => false, availableDelivery: () => null,
    identity: () => ({revision: 1, input_version: 1, brief_sha256: hash}),
    mutate: async (operation, body) => {assert.equal(operation, expectedOperation); posts.push(JSON.parse(JSON.stringify(body))); return new Promise(resolve => {finish = resolve;});},
    loadProject: async ref => calls.push(ref)
  };
  vm.runInNewContext(actualFunction('availableSavedPreparation', 'renderSources', false, false), sandbox);
  vm.runInNewContext(actualFunction('buttons', 'openReadingDraft', false), sandbox);
  sandbox.invoke(); assert.equal(nodes.get('ledger-prepare').disabled, false);
  for (const stage1 of [{...valid, ledger: null}, {...valid, checkpoint: {current: false}}, {...valid, saved_records_connected: false}]) {
    sandbox.state.stage1 = stage1; sandbox.invoke(); assert.equal(nodes.get('ledger-prepare').disabled, true);
  }
  sandbox.state.stage1 = valid; sandbox.state.busy = true; sandbox.invoke(); assert.equal(nodes.get('ledger-prepare').disabled, true);
  sandbox.state.busy = false;
  const begin = projectSource.indexOf('  async function ledger(operation) {'), end = projectSource.indexOf('  $("ledger-init").onclick', begin);
  assert(begin >= 0 && end > begin); vm.runInNewContext(projectSource.slice(begin, end) + '\nglobalThis.invoke = ledger;', sandbox);
  const saved = sandbox.invoke('prepare-delivery'); finish({status: 'saved'}); await saved;
  assert.deepEqual(posts[0], {revision: 1, input_version: 1, brief_sha256: hash, confirmed: true, ledger_state_sha256: hash, checkpoint_event_id: 'synthetic-checkpoint'});
  assert.deepEqual(calls, ['synthetic-A']);
  const waiting = sandbox.invoke('prepare-delivery'); sandbox.state.generation += 1; sandbox.state.loading = true;
  finish({status: 'saved'}); await waiting; assert.deepEqual(calls, ['synthetic-A'], 'preparation must not reclaim A while B loads');
  sandbox.state.loading = false;
  expectedOperation = 'stage1/recover-delivery';
  const offer = {status: 'ready-for-saved-records-registration', producer_key: 'saved-producer', producer_request_sha256: hash, records_sha256: hash, checkpoint_event_id: 'synthetic-checkpoint'};
  sandbox.state.stage1 = {...valid, saved_records_recovery: {revision: sandbox.state.project.revision, offers: [offer]}};
  const recovered = sandbox.invoke('prepare-delivery'); finish({status: 'saved'}); await recovered;
  assert.deepEqual(posts[2], {...posts[0], producer_key: 'saved-producer', producer_request_sha256: hash, records_sha256: hash});
  sandbox.state.stage1.saved_records_recovery.revision += 1;
  expectedOperation = 'stage1/prepare-delivery';
  const stale = sandbox.invoke('prepare-delivery'); finish({status: 'saved'}); await stale;
  assert.deepEqual(posts[3], posts[0], 'stale recovery offer must not select another saved producer');
  console.log('PASS prepare: actual button disabled without current checkpoint/connection, exact saved body, late project guard');
}

const sourceReply = {...project, source_mode: 'saved-source-review', work_ref: 'authored-work', version_id: 'v1',
  ledger_state_sha256: hash, source_snapshot_sha256: hash,
  sources: [{source_id: 'authored-source', text_sha256: hash}], claims: [{claim_id: 'authored-claim', quote}],
  claim_ids: ['authored-claim'], classification, findings, roles: [],
  reading_review_offer: {offer_ref: 'source-reading-synthetic', offer_sha256: hash}};
async function sourceNotesGuards() {
  for (const language of ['en', 'zh-Hans', 'zh-Hant']) {
    const {roots, ui} = panel(), saves = [], event = {preventDefault(){}};
    let finish; ui.update({...context, language});
    assert.equal(ui.renderSource(sourceReply, async item => {saves.push(JSON.parse(JSON.stringify(item))); return new Promise(resolve => {finish = resolve;});}), true);
    assert.equal(saves.length, 0); assert(!roots['reading-title'].textContent.includes('draft'));
    const sourceTitle = roots['reading-title'].textContent;
    ui.update({...context, language, busy:true}); assert.equal(roots['reading-title'].textContent,sourceTitle);
    ui.update({...context, language});
    const form = roots['reading-panel'].querySelectorAll('form')[0], inputs = form.querySelectorAll('textarea');
    for (const input of inputs.slice(0, 13)) assert.equal(input.value, 'Unknown: not assessed.');
    const checks = form.querySelectorAll('input'), confirm = checks.at(-1);
    assert.equal(confirm.checked, false); assert.equal(checks.slice(0, -1).some(input => input.checked), false);
    await form.onsubmit(event); assert.equal(saves.length, 0);
    confirm.checked = true; checks[0].checked = true; inputs[13].value = 'Authored source-bound role reason';
    await form.onsubmit(event); assert.equal(saves.length, 0, 'role without claim evidence cannot be submitted');
    checks[1].checked = true; const pendingSave = form.onsubmit(event);
    await form.onsubmit(event); assert.equal(saves.length, 1, 'second click during save cannot submit again');
    assert.deepEqual(saves[0], {...project, ledger_state_sha256: hash, work_ref: 'authored-work', source_snapshot_sha256: hash,
      offer_ref: 'source-reading-synthetic', offer_sha256: hash, confirmed: true,
      review: {classification, findings, roles: [{role: 'classic', reason: inputs[13].value, claim_ids: ['authored-claim']}]}});
    ui.update({...context, language, project: {...project, input_version: 2}});
    finish({status:'saved'}); await pendingSave;
    assert.equal(roots['reading-card'].hidden, true, 'late save cannot restore stale source annotations');
    assert.equal(ui.renderSource(sourceReply, () => {}), false);
  }
  const {ui} = panel(); ui.update(context);
  assert.equal(ui.renderSource({...sourceReply, source_snapshot_sha256:'bad'}, () => {}), false);
  assert.equal(ui.renderSource({...sourceReply, roles:[{role:'classic',reason:'unknown',claim_ids:['foreign']}]}, () => {}), false);
  assert.equal(ui.renderSource({...sourceReply, claims:[{claim_id:'authored-claim',quote:null}]}, () => {}), true, 'unavailable source quotations remain Unknown');
  assert.equal(ui.renderSource({...sourceReply, sources:[null]}, () => {}), false);
  assert.equal(ui.renderSource({...sourceReply, claims:[]}, () => {}), false);
  console.log('PASS source notes: trilingual raw Unknown, explicit source/role claims, double-click, late version and invalid bindings');
}
async function sourceBroker() {
  const posted = [], state = {project:{...project}, generation:1, stage1:context.stage1, readingReview:sourceReply};
  const sandbox = {state,pending:[], identity:()=>({...project}), mutate:async (operation,body,ref)=>{posted.push({operation,body:JSON.parse(JSON.stringify(body)),ref});return {status:'saved'};},loadProject:async ()=>{}};
  vm.runInNewContext(actualFunction('submitReadingReview','submitCoverage'),sandbox);
  const item = {...project, ledger_state_sha256:hash, work_ref:'authored-work',source_snapshot_sha256:hash,
    offer_ref:'source-reading-synthetic',offer_sha256:hash,review:notesReview,confirmed:true};
  await sandbox.invoke({...item,source_snapshot_sha256:'b'.repeat(64)}); assert.equal(posted.length,0);
  await sandbox.invoke(item); assert.equal(posted.length,1);
  assert.equal(posted[0].operation,'stage1/reading-review'); assert.equal('output_ref' in posted[0].body,false);
  assert.equal('draft_sha256' in posted[0].body,false); assert.equal(posted[0].body.source_snapshot_sha256,hash);
  console.log('PASS source broker: exact saved-source body, no invented draft identity, changed snapshot refuses');
}
(async () => {await panelGuards(); await noteGuards(); await saveRaces(); await registryIntent(); await preparationGuard(); await sourceNotesGuards(); await sourceBroker(); console.log('PASS: project reading panel focused UI mock only');})()
  .catch(error => {console.error(error); process.exitCode = 1;});
