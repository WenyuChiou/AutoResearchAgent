"""Exercise Stage 1 saved-material rendering and the guarded adapter click path."""

from pathlib import Path
import shutil
import subprocess
import unittest


CHECK = r"""
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');

const ref = 'project-a';
const material = {project_ref: ref, id: 'file-'+'a'.repeat(32), sha256:'b'.repeat(64),
  stage:1, bytes:4156, name:'Table 12.csv', kind:'manual-file', status:'registered'};
const note = {id:material.id, project_ref:ref, source_sha256:material.sha256, note:'Provided URL and CSV description'};
const brief = 'c'.repeat(64);
const ledger = 'd'.repeat(64);
const requestHash = 'e'.repeat(64);
const actionKey = 'host-allocated-action';
const clone = value => JSON.parse(JSON.stringify(value));
const stored = () => {
  const state = new Map();
  return {state, getItem:k=>state.get(k)??null, setItem:(k,v)=>state.set(k,v)};
};
const sharedLocks = () => {
  const held = new Set();
  return {request:async(name,options,callback)=>{
    if(held.has(name)) return callback(null);
    held.add(name);
    try { return await callback({name}); } finally { held.delete(name); }
  }};
};
const simulatedReceipt = intent => ({...intent, status:'saved', candidate_event_id:'e000019',
  execution_authorized:false, provenance:'provided', identity_status:'unverified',
  screening_status:'not-screened', reading_evidence:null});

function renderer(storage=stored(), locks=sharedLocks()) {
  const handlers = {};
  const writes = [];
  const project = {project_ref:ref,input_version:1,revision:8,brief_sha256:brief};
  const stage1 = {project_ref:ref,input_version:1,revision:8,ledger:{valid:true,state_sha256:ledger}};
  const noop = () => '';
  const env = {material, note, console, crypto, localStorage:storage, navigator:{locks}, apps:[{stage:1}],
    rt:{ref,overview:{project,stage1}}, document:{addEventListener(type,handle){
      if(type === 'click' && String(handle).includes('n9CandidateSubmit')) handlers.admission=handle;
    }},
    n2Render:noop,stage1:noop,stage2:noop,laterStage:noop,v7AfterRender:noop,livePaint:noop,n9UiLabel:value=>value,
    rl:(_,english)=>english, rx:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    canonicalOldRequest:() => {throw Error('Unexpected stock Wiki request');}};
  const ctx = vm.createContext(env);
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, {filename:process.argv[2]});
  const evaluate = text => vm.runInContext(text,ctx);
  evaluate('m9.catalog={materials:[material],drafts:[note],operations:[]};');
  const adapter={offer:binding=>({...binding, operation:'admit-saved-candidate', execution_authorized:false,
    offer_ref:'engineering-offer', key:actionKey, request_sha256:requestHash}),
    submit:async intent=>{writes.push(clone(intent));return simulatedReceipt(intent);},
    read:async intent=>simulatedReceipt(intent)};
  const render=()=>evaluate('m9Card(material)');
  const action=(data)=>handlers.admission({target:{closest:()=>({dataset:data,isConnected:true})}});
  const submitButton = () => ({n9CandidateSubmit:material.id,n9CandidateOffer:'engineering-offer',
    n9CandidateKey:actionKey,n9CandidateRequest:requestHash,
    n9CandidateBinding:evaluate('JSON.stringify(m9SourceBinding(m9SourceScope(material)))')});
  const readButton = () => ({n9CandidateRead:material.id,
    n9CandidateScope:evaluate('JSON.stringify(m9SourceScope(material))')});
  const connect=(transport=adapter)=>{ctx.transport=transport;evaluate('m9Admission.transport=transport');};
  return {ctx, storage, project, stage1, writes, render, action, adapter, connect, submitButton, readButton,evaluate};
}

(async () => {
  const missing=renderer();
  assert.match(missing.render(), /data-n9-source-info/);
  assert.match(missing.render(), /Input version at upload<\/dt><dd>Not recorded/);
  assert.match(missing.render(), /Current project input version<\/dt><dd>1 · number/);
  assert.match(missing.render(), /Provided URL and CSV description/);
  assert.match(missing.render(), /no candidate admission capability available/);
  await missing.action(missing.submitButton());
  assert.equal(missing.storage.state.size,0);
  missing.connect({offer:missing.adapter.offer,submit:missing.adapter.submit});
  assert.match(missing.render(), /no candidate admission capability available/);
  await missing.action(missing.submitButton());
  assert.deepEqual(missing.writes,[]);

  const old=renderer();
  old.connect();
  const stale=old.submitButton();
  old.project.input_version=old.stage1.input_version='1';
  await old.action(stale);
  assert.deepEqual(old.writes,[]);
  old.ctx.rt.ref='project-b';
  await old.action(stale);
  assert.deepEqual(old.writes,[]);
  old.ctx.rt.ref=ref;
  assert.match(old.render(), /1 · string/);
  await old.action(old.submitButton());
  assert.equal(old.writes[0].input_version,'1');
  assert.match(old.render(), /Candidate source registered · e000019 · unverified · not-screened/);

  const broken=renderer();
  broken.connect({...broken.adapter,offer:binding=>({...broken.adapter.offer(binding),ledger_state_sha256:brief})});
  assert.match(broken.render(), /No bound admission offer/);
  await broken.action(broken.submitButton());
  assert.deepEqual(broken.writes,[]);

  const missingHash=renderer();
  missingHash.connect({...missingHash.adapter,offer:binding=>({...missingHash.adapter.offer(binding),request_sha256:null})});
  assert.match(missingHash.render(), /No bound admission offer/);
  await missingHash.action(missingHash.submitButton());
  assert.deepEqual(missingHash.writes,[]);
  const noLock=renderer(stored(),null);
  noLock.connect();
  assert.match(noLock.render(), /operation lock is unavailable/);
  await noLock.action(noLock.submitButton());
  assert.deepEqual(noLock.writes,[]);

  const quota=renderer();
  quota.connect();
  quota.storage.setItem=()=>{throw Error('QuotaExceededError');};
  await quota.action(quota.submitButton());
  assert.deepEqual(quota.writes,[]);
  assert.match(quota.render(), /browser storage. Nothing was submitted/);

  const common=stored(), locks=sharedLocks();
  // Both documents can have rendered "available" before either executes its callback.
  const tabA=renderer(common,locks), tabB=renderer(common,locks);
  tabA.connect(); tabB.connect();
  assert.match(tabA.render(), /data-n9-candidate-key/);
  assert.match(tabB.render(), /data-n9-candidate-key/);
  await Promise.all([tabA.action(tabA.submitButton()),tabB.action(tabB.submitButton())]);
  assert.equal(tabA.writes.length+tabB.writes.length,1);
  assert.equal(JSON.parse([...common.state.values()][0]).key,actionKey);

  let takeLock;
  const moved=renderer(stored(),{request:async(_name,_options,callback)=>{
    await new Promise(resolve=>{takeLock=resolve;});
    await callback({});
  }});
  moved.connect();
  const inflight=moved.action(moved.submitButton());
  moved.project.input_version=moved.stage1.input_version='1';
  takeLock();
  await inflight;
  assert.deepEqual(moved.writes,[]);

  let initial;
  const pending=renderer();
  pending.connect({...pending.adapter,submit:async intent=>{
    initial=clone(intent);
    throw Error('ENGINEERING_CONTROL: outcome unavailable');
  }});
  const click=pending.submitButton();
  await Promise.all([pending.action(click),pending.action(click)]);
  assert.equal(pending.storage.state.size,1);
  assert.deepEqual(clone(JSON.parse([...pending.storage.state.values()][0])),initial);
  assert.equal(initial.key,actionKey);
  assert.equal(initial.request_sha256,requestHash);
  assert.match(pending.render(), /Outcome unconfirmed/);
  const reopened=renderer(pending.storage);
  let reads=0;
  reopened.connect({...reopened.adapter,read:async intent=>{
    assert.deepEqual(clone(intent),initial);
    ++reads;
    return {...simulatedReceipt(intent),project_ref:reads===1?'project-b':ref,
      request_sha256:reads===2?brief:requestHash};
  }});
  await reopened.action(reopened.submitButton());
  assert.deepEqual(reopened.writes,[]);
  await reopened.action(reopened.readButton());
  assert.match(reopened.render(), /Outcome unconfirmed/);
  await reopened.action(reopened.readButton());
  assert.match(reopened.render(), /Outcome unconfirmed/);
  await reopened.action(reopened.readButton());
  assert.match(reopened.render(), /Candidate source registered · e000019/);
  assert.equal(reads,3);
  assert.equal(JSON.parse([...reopened.storage.state.values()][0]).key,initial.key);
  reopened.project.brief_sha256=ledger;
  assert.doesNotMatch(reopened.render(), /Candidate source registered/);
  await reopened.action(reopened.readButton());
  assert.equal(reads,3);
  reopened.project.brief_sha256=brief;
  reopened.ctx.neighbor={...material,id:'file-'+'d'.repeat(32)};
  const other=reopened.evaluate('m9SourceScope(neighbor)');
  const marker=reopened.evaluate('m9IntentKey(m9SourceScope(neighbor))');
  reopened.storage.setItem(marker,JSON.stringify({...initial,...other}));
  assert.doesNotMatch(reopened.evaluate('m9Card(neighbor)'), /Candidate source registered/);
  console.log('PASS Stage 1 provenance, no capability, stale typed bindings, receipt identity and no resend');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


class SavedMaterialWikiTests(unittest.TestCase):
    def test_stage1_saved_material_action(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the Wiki renderer tests")
        source = Path(__file__).with_name("v9-materials.js")
        result = subprocess.run(
            [node, "-", str(source)],
            input=CHECK,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS Stage 1 provenance", result.stdout)
