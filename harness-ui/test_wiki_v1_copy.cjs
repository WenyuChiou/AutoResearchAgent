'use strict';
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = name => readFileSync(join(__dirname, name), 'utf8');
const line = (name, start) => {
  const code = source(name).split('\n').find(value=>value.trimStart().startsWith(start));
  assert.ok(code, start);
  return code.trim();
};
const escape = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;');
const presentation = () => vm.createContext({rl:zh=>zh, rx:escape});
const stage2 = () => {
  const ctx = presentation();
  ctx.rt = {ref:'project-fixture', overview:{project:{project_ref:'project-fixture',
    input_version:1, brief_sha256:'a'.repeat(64), brief:{original_description:'Fixture'}}}};
  const script = source('stage2_display.js');
  vm.runInContext(script.slice(script.indexOf('function wikiStage2Basis('),script.indexOf('\nstage2 = function')),ctx);
  return ctx;
};

test('the ordinary later-stage status uses the reader label', () => {
  const renderer = 'renderer/src/base.js';
  const labels = line(renderer, 'structurePreview:').split(',attemptVersion:')[0];
  const ctx = vm.createContext({li:()=>0, esc:escape, translated:(_app,values)=>values?.[0],
    stageFeedback:()=>'', bottomAssistant:()=>''});
  const functions = ['function t(app,key)','function laterStage(app)','function laterImprovement(app)'];
  vm.runInContext('const words={'+labels+'};const laterStageDefs={'+line(renderer,'3:{subtitle:')+'};'+
    functions.map(name=>line(renderer,name)).join('\n'),ctx);
  const rendered = vm.runInContext("laterStage({stage:3,lang:'zh'})",ctx);
  assert.match(rendered,/<span class="hs-status">还没接通<\/span>/);
  assert.match(rendered,/<p>未提供<\/p>/);
  assert.match(rendered,/本次规划及上一版本还没有关联/);
  assert.doesNotMatch(rendered,/planned \/ unconnected|>Unknown|attempt \/ parent version/);
  assert.match(rendered,/ResearchRun\(run_id, versions, input_refs\)/);
});

test('the actual Stage 2 status display uses the system recommendation labels', () => {
  const ctx = presentation();
  vm.runInContext(source('v9-i18n.js')+'\n'+line('v9-workbench.js','function n9Status('),ctx);
  assert.equal(vm.runInContext("n9Status('recommend')",ctx),'系统建议');
  assert.equal(vm.runInContext("n9Status('park')",ctx),'系统暂缓');
  assert.equal(vm.runInContext("n9Status('revise')",ctx),'待修订');
  assert.equal(vm.runInContext("n9UiLabel('candidate note: recommend / park; Unknown')",ctx),
    'candidate note: recommend / park; Unknown');
});

test('a saved blocked request keeps the original server reason under technical details', () => {
  const ctx = stage2();
  const problem = 'stage2-continuation-original-admission-unavailable';
  const input = {result:{status:'blocked',reason:problem,execution_authorized:false},
    basis:['project-fixture',1],error:''};
  ctx.input = input;
  const displayed = vm.runInContext('wikiStage2Panel(input)',ctx);
  assert.match(displayed,/暂时无法继续/);
  assert.ok(displayed.includes('<details><summary>技术细节</summary><code>'+problem+'</code></details>'));
  assert.equal(input.result.reason,problem);
  assert.equal(input.result.execution_authorized,false);
  assert.equal(input.basis[1],1);
});

test('an HTTP error stays distinct from an absent or saved reason', () => {
  const ctx = stage2();
  ctx.input = {result:{status:'blocked',reason:null},basis:['project-fixture',1],error:''};
  assert.doesNotMatch(vm.runInContext('wikiStage2Panel(input)',ctx),/<summary>技术细节<\/summary>/);
  ctx.input.result.reason = 'original-blocker';
  ctx.input.error = 'stage2-continuation-worker-busy';
  const displayed = vm.runInContext('wikiStage2Panel(input)',ctx);
  assert.match(displayed,/<code>stage2-continuation-worker-busy<\/code>/);
  assert.doesNotMatch(displayed,/original-blocker/);
});

test('the saved reason is text and no foreign project reply reaches the pane', async () => {
  const ctx = stage2();
  const untrusted = '<img src=x onerror=alert(1)>';
  // The reader basis also binds project id, revision and epoch (undefined in this fixture).
  ctx.input = {result:{status:'blocked',reason:untrusted},basis:['project-fixture',1,'a'.repeat(64),undefined,undefined,undefined],error:''};
  const displayed = vm.runInContext('wikiStage2Panel(input)',ctx);
  assert.ok(displayed.includes('<code>&lt;img src=x onerror=alert(1)></code>'));
  assert.doesNotMatch(displayed,/<img /);
  ctx.canonicalReadonly = () => false;
  ctx.apps = [{page:'workspace',stage:2}];
  ctx.projectPath = (ref,tail) => '/' + ref + '/' + tail;
  ctx.livePaint = () => {};
  ctx.liveRequest = async () => ({project_ref:'other-project',input_version:1,
    brief_sha256:'a'.repeat(64),status:'blocked',reason:untrusted});
  const rejected = await vm.runInContext('let wikiStage2State=input; wikiStage2Load(input,false).then(()=>wikiStage2Panel(input))',ctx);
  assert.match(rejected,/<code>project-binding-mismatch<\/code>/);
  assert.doesNotMatch(rejected,/onerror/);
});
