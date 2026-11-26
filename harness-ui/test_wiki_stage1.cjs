const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const paper = {work_id:'work-a', version_id:'v1', title:'<a> paper', year:2024};
const claim = {work_id:'work-a', version_id:'v1', text:'<b> observation',
  relation:'supports', locator:'characters 4:8', start:4, end:8, quote:'<q> text',
  core_event:{payload:{verifier:{actor_type:'agent'}}}};
const index = {papers:[paper], claims:[claim,{...claim,version_id:'v0'}],
  screening:[{work_id:'work-a',version_id:'v1',status:'include',observed_at:'2026-01-02'},
             {work_id:'work-a',version_id:'v1',status:'pending',observed_at:'2026-01-01'}],
  coverage:[{need_id:'need',description:'Saved group',work_ids:['work-a']}]};
const receipt = {artifact_ref:'receipt',manifest_sha256:'saved-hash'};
const project = {project_ref:'project-a',input_version:1,revision:2};
const rt = {ref:project.project_ref,overview:{project,stage1:{delivery:{canonical_package:receipt}}},
  atlas:{...receipt,...project,payload:{index,index_sha256:'index-pin'}}};
const ctx = vm.createContext({
 rt, URL, canonicalReadonly:()=>false,
 esc:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
});
const source = fs.readFileSync(path.join(__dirname,'wiki-stage1.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('const wikiS1CanonicalResults')),ctx);
assert.equal(ctx.wikiS1Index(),index);
rt.atlas.revision--;
assert.equal(ctx.wikiS1Index(),null,'previous-version result must not be displayed');
rt.atlas.revision++;
const state = ctx.wikiS1State({},index);
assert.equal(state.sources[0].claims.length,1,'same work with different version does not contribute evidence');
assert.equal(state.sources[0].decision.status,'include');
assert.equal(ctx.wikiS1Check(claim),'unchecked','the saved relation is not a human check');
assert.equal(ctx.wikiS1Check({...claim,core_event:{payload:{verifier:{actor_type:'human'}}}}),'supports');
const evidence = ctx.wikiS1Evidence(index,state);
assert.match(evidence,/保存文本第 4–8 字符/);
assert.match(evidence,/&lt;q&gt; text/);
assert.doesNotMatch(evidence,/<q> text/);
assert.match(ctx.wikiS1Synthesis(state),/当前交付没有跨文献综合记录/);
assert.match(ctx.wikiS1Synthesis(state),/1 \/ 1/);
console.log('PASS Stage 1 bound projection, source/version pairing, evidence state, locator, escaping and missing synthesis.');
