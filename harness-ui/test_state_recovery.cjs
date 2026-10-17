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

async function main() {
  const checks = [
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
