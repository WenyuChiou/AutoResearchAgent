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
vm.runInContext(source.slice(source.indexOf('function wikiS1Select('),source.indexOf('const wikiS1After')),ctx);
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

const list = {innerHTML:'',querySelectorAll:()=>[]};
const card = {};
const graph = {setFocus(focus){this.focus=focus;},setMode(mode){this.mode=mode;}};
const app = {el:{querySelector:selector=>selector==='[data-s1-list]'?list:card,querySelectorAll:()=>[]},v7Spatial:graph};
const grouped = {
 papers:['a','b'].map(key=>({work_id:key,version_id:'1',title:'Paper '+key})),
 coverage:['a','b'].map(key=>({need_id:key,description:'Group '+key,work_ids:[key]})),
 claims:['a','b'].map(key=>({work_id:key,version_id:'1',text:'Claim '+key}))
};
grouped.coverage.push({need_id:'empty',description:'Empty group',work_ids:[]});
ctx.wikiS1State(app,grouped).check='supports';
ctx.wikiS1Filter(app,'b');
assert.deepEqual([...list.innerHTML.matchAll(/data-s1-paper="(.*?)"/g)].map(match=>match[1]),['b']);
assert.match(list.innerHTML,/data-s1-paper="b" aria-pressed="true"/);
assert.match(card.innerHTML,/Paper b/);
assert.equal(graph.focus.key,'b');
assert.equal(app.wikiS1.check,'all');
assert.match(ctx.wikiS1Evidence(grouped,app.wikiS1),/Claim b/);
assert.doesNotMatch(ctx.wikiS1Evidence(grouped,app.wikiS1),/Claim a|Paper a/);
for (const mode of [2,3]) {
 ctx.wikiS1SetMode(app,mode);
 assert.equal(graph.mode,mode);
 assert.equal(app.wikiS1.group,'b');
 assert.equal(app.wikiS1.selected,'b');
 assert.equal(graph.focus.key,'b');
}
ctx.wikiS1Filter(app,'empty');
assert.equal(app.wikiS1.selected,undefined);
assert.equal(graph.focus,null);
assert.match(list.innerHTML,/这个分组没有来源/);
assert.match(card.innerHTML,/当前分组没有可查看的来源/);
assert.match(ctx.wikiS1Evidence(grouped,ctx.wikiS1State(app,grouped)),/当前分组没有可查看的来源/);
assert.doesNotMatch(ctx.wikiS1Evidence(grouped,app.wikiS1),/Claim [ab]/);
ctx.wikiS1Filter(app,'');
assert.equal(app.wikiS1.selected,'a');

const landing = {work_id:'work-1',version_id:'1',title:'Engineering fixture',url:'https://example.invalid/paper-landing'};
const metadata = {work_id:'work-1',version_id:'1',source_id:null,locator:null,relation:'pending',text:'Discovery metadata only',quote:null};
const missing = {papers:[landing],sources:[],claims:[metadata],coverage:[]};
const renderEvidence = value => ctx.wikiS1Evidence(value,ctx.wikiS1State({},value));
assert.match(renderEvidence(missing),/原文链接未提供/);
assert.doesNotMatch(renderEvidence(missing),/<a |paper-landing/);
const sourceRecord = {source_id:'source-1',work_id:'work-1',version_id:'1',receipt:{source_url:'https://example.invalid/bound-source'}};
const located = {...metadata,source_id:'source-1',locator:'characters 1:4',start:1,end:4};
assert.match(renderEvidence({...missing,sources:[sourceRecord],claims:[located]}),/href="https:\/\/example\.invalid\/bound-source"/);
assert.doesNotMatch(renderEvidence({...missing,sources:[{...sourceRecord,version_id:'2'}],claims:[located]}),/<a /);
assert.doesNotMatch(renderEvidence({...missing,sources:[sourceRecord],claims:[{...metadata,source_id:'source-1'}]}),/<a /);
console.log('PASS Stage 1 disjoint/empty groups, dimension retention, and bound evidence URLs.');
