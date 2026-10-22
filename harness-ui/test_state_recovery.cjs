const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const packetText = JSON.stringify({kind: 'Stage2Packet', sources: [], evidence: [],
  candidates: [{candidate_id: 'candidate-1', version: 1, evidence_ids: []}]});
const packetHash = hash(packetText);
const material = (id, project) => ({id, project_ref: project, stage: 2,
  packet_path: 'synthetic-original', sha256: packetHash});
const materials = [material('packet-a', 'project-A'), material('packet-b', 'project-B'),
  material('packet-c', 'project-A')];

function display(storage = new Map()) {
  const listeners = [];
  const context = {stage1: () => '', stage2: () => '', laterStage: () => '',
    v7AfterRender: () => {}, m9Card: () => '', rt: {ref: 'project-A'},
    apps: [{stage: 2, lang: 'en'}], livePaint: () => {}, rl: (zh, en) => en,
    sessionStorage: {getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    document: {addEventListener: (type, handler) => listeners.push({type, handler})},
    canonicalHash: async text => hash(text)};
  context.canonicalOldRequest = async url => {
    const entry = materials.find(item => item.id === decodeURIComponent(url.split('/').pop()));
    assert.ok(entry, 'only synthetic packet GETs are allowed');
    return {kind: 'V9ValidatedPacketView', project_ref: entry.project_ref,
      material_id: entry.id, packet_text: packetText, packet_file_sha256: packetHash,
      execution_authorized: false, cards: []};
  };
  vm.createContext(context);
  for (const file of ['stage2_display.js', 'v9-materials.js', 'v9-continuation.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context, {filename: file});
  }
  const run = code => vm.runInContext(code, context);
  context.n2 = run('n2');
  context.syntheticCatalog = {materials, drafts: [], operations: []};
  run('m9.catalog = syntheticCatalog');
  return {context, run, storage, listeners};
}

async function reviewDraftRecovery() {
  const env = display();
  await env.run("p9Open('packet-a')");
  env.run("n2.draft='candidate-1';n2.note='Human review A';n2SaveDraft()");
  assert.equal(env.run('n2.draftStatus'), 'local-only');
  const key = env.run('n2DraftKey()');
  await env.run("p9Open('packet-a')");
  assert.equal(env.run('n2.draft'), 'candidate-1');
  assert.equal(env.run('n2.note'), 'Human review A');
  const reloaded = display(env.storage);
  await reloaded.run("p9Open('packet-a')");
  assert.equal(reloaded.run('n2.note'), 'Human review A');
  assert.equal(reloaded.run('n2DraftKey()'), key);
  reloaded.context.rt.ref = 'project-B';
  await reloaded.run("p9Open('packet-b')");
  assert.equal(reloaded.run('n2.draft'), null);
  assert.equal(reloaded.run('n2.note'), '');
  assert.notEqual(reloaded.run('n2DraftKey()'), key);
  reloaded.run("n2.draft='candidate-1';n2.note='Human review B';n2SaveDraft()");
  reloaded.context.rt.ref = 'project-A';
  await reloaded.run("p9Open('packet-c')");
  assert.equal(reloaded.run('n2.draft'), null);
  await reloaded.run("p9Open('packet-a')");
  assert.equal(reloaded.run('n2.note'), 'Human review A');
  reloaded.run('n2SaveDraft(true)');
  await reloaded.run("p9Open('packet-a')");
  assert.equal(reloaded.run('n2.draft'), null);
  reloaded.context.rt.ref = 'project-B';
  await reloaded.run("p9Open('packet-b')");
  assert.equal(reloaded.run('n2.note'), 'Human review B');
}

async function staleComparison(change, expectedError) {
  const env = display();
  await env.run("p9Open('packet-a')");
  env.run("n2.model.sourceById.set('source-1',{});n2.papers=['source-current'];n2.routes=[]");
  const draft = {id: 'packet-a', project_ref: 'project-A', source_sha256: packetHash,
    revision: 1, selection: {packet_sha256: packetHash, source_ids: ['source-1'],
      candidates: [{candidate_id: 'candidate-1', version: 1}]}};
  env.context.syntheticCatalog.drafts = [draft];
  let resolve;
  env.context.canonicalOldRequest = url => {
    assert.equal(url, '/api/v9/materials');
    return new Promise(done => { resolve = done; });
  };
  const handler = env.listeners.find(item => item.type === 'click' &&
    String(item.handler).includes('data-n9-choice-save')).handler;
  const pending = handler({target: {closest: () => ({dataset: {n9ChoiceRestore: 'packet-a'}})}});
  assert.equal(typeof resolve, 'function');
  change(env, draft);
  resolve(env.context.syntheticCatalog);
  await pending;
  if (expectedError) {
    assert.equal(env.run('m9.error'), expectedError);
    assert.deepEqual(Array.from(env.context.n2.papers), ['source-current']);
    assert.deepEqual(Array.from(env.context.n2.routes), []);
  } else {
    assert.equal(env.run('m9.error'), '');
    assert.deepEqual(Array.from(env.context.n2.papers), ['source-1']);
    assert.deepEqual(Array.from(env.context.n2.routes), ['candidate-1']);
  }
}


function savedResultLayout() {
  const context = {
    rt: {ref: 'view:synthetic', list: [{project_ref: 'view:synthetic', topic: 'Synthetic'}]},
    apps: [{stage: 1, lang: 'en', previewResultsOpen: {1: true, 2: true}}],
    document: {addEventListener() {}}, v7AfterRender() {}, m9Card() {},
    liveRequest() { throw Error('Layout checks must not fetch'); },
    liveRefresh() {}, livePaint() {}, livePost() {},
    stage1() { return ''; }, stage2() { return ''; }, laterStage() { return '<main data-planned></main>'; },
    otherPage() {}, realChromeStatus() {}, canonicalStage2Mount() {},
    rows: () => [], liveGraph: () => '<div data-synthetic-graph></div>',
    liveDetails: () => '', liveLibrary: () => '',
    canonicalStage2Validate: () => ({ok: true}),
    canonicalStage2Render: () => '<main data-synthetic-comparison></main>',
    n2Render: () => '', liveTop: () => '', rl: (zh, en) => en,
    rx: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'renderer/src/canonical-runs.js'), 'utf8'), context);
  context.rt.savedRun = {payload: {index: {papers: [], claims: []}},
    binding: {fixture: true}, entry: {label: 'Synthetic source'}};
  const original = JSON.stringify(context.rt.savedRun);
  for (const stage of [1, 2]) {
    context.apps[0].stage = stage;
    const html = context['stage' + stage](context.apps[0]);
    assert.ok(html.includes('class="lp-results"'), 'saved result remains available');
    assert.ok(html.indexOf('class="lp-results"') < html.indexOf('class="lp-operations'),
      'saved results must precede saved operations');
    assert.match(html, /<details[^>]*class="lp-operations[^>]*>/);
    const operation = html.match(/<details[^>]*class="lp-operations[^>]*>/)[0];
    assert.ok(!/\sopen(?:\s|>)/.test(operation), 'saved operations start collapsed');
    assert.ok(html.includes('data-live-action="refresh"'), 'saved reload remains available');
    for (const requestedOpen of [true, false, true]) {
      context.apps[0].previewOps = {[stage]: requestedOpen};
      const rerendered = context['stage' + stage](context.apps[0]);
      const disclosure = rerendered.match(/<details[^>]*class="lp-operations[^>]*>/)[0];
      assert.equal(/\sopen(?:\s|>)/.test(disclosure), requestedOpen,
        'saved operations retain the requested state after render');
    }
    context.apps[0].previewOps = {};
  }
  assert.equal(JSON.stringify(context.rt.savedRun), original);
  for (const file of ['v9-i18n.js', 'v9-workbench.js']) {
    context.n2 = {meta: {}, model: null};
    context.n2Gap = () => ''; context.n2Views = {}; context.n2Active = () => true;
    vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context);
  }
  context.n2Render = () => '<main class="lp-results" data-imported-result></main>';
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'v9-materials.js'), 'utf8'), context);
  for (const stage of [1, 2]) {
    context.apps[0].stage = stage;
    const html = context['stage' + stage](context.apps[0]);
    assert.ok(html.indexOf('class="lp-results"') < html.indexOf('data-n9-material-panel'),
      'material registration follows the reading result');
    assert.ok(html.includes('data-n9-upload'), 'upload remains available on demand');
  }
  context.apps[0].stage = 3;
  const planned = context.laterStage(context.apps[0]);
  assert.ok(planned.indexOf('data-planned') < planned.indexOf('data-n9-material-panel'),
    'planned-stage purpose precedes material registration');
}

async function main() {
  const checks = [
    ['saved-result hierarchy and on-demand operations/materials', savedResultLayout],
    ['save/revalidate/reload and project/material-scoped draft recovery', reviewDraftRecovery],
    ['restore exact current comparison', () => staleComparison(() => {}, null)],
    ['reject project switch during catalog read', () => staleComparison(env => {
      env.context.rt.ref = 'project-B';
    }, 'comparison-display-changed')],
    ['reject same-project material switch during catalog read', () => staleComparison(env => {
      env.run("p9.shown={id:'packet-c'};p9.epoch++");
    }, 'comparison-display-changed')],
    ['reject display model replacement during catalog read', () => staleComparison(env => {
      env.context.n2.model = {...env.context.n2.model};
    }, 'comparison-display-changed')],
    ['reject forged project binding', () => staleComparison((env, draft) => {
      draft.project_ref = 'project-B';
    }, 'saved-comparison-binding-differs')],
    ['reject changed source binding', () => staleComparison((env, draft) => {
      draft.source_sha256 = 'f'.repeat(64);
    }, 'saved-comparison-binding-differs')],
  ];
  let failed = 0;
  for (const [name, check] of checks) {
    try { await check(); console.log('PASS', name); }
    catch (error) { failed++; console.error('FAIL', name, error); }
  }
  console.log(JSON.stringify({kind: 'synthetic-actual-source-state-regression',
    tests: checks.length, failures: failed, browser_acceptance: false, research_execution: false}));
  if (failed) process.exitCode = 1;
}

main().catch(error => { console.error(error); process.exitCode = 1; });
