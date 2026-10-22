const assert=require('node:assert/strict');
require('./test_state_recovery.cjs');
require('./test_stage2_reader.cjs');
require('./test_source_metadata.cjs');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const sha='a'.repeat(64);
const original='原始问题 <script>';
const route={candidate:{candidate_id:'synthetic-route',version:1,question:original},assessment:null};
const before=JSON.stringify(route);
const context={apps:[{lang:'en'}],p9:{shown:null},n2:{meta:{packet_json_sha256:sha}},
 n9TranslationBundle:{packets:[{packet_file_sha256:sha,fields:[{candidate_id:'synthetic-route',version:1,path:'candidate.question',source:original,translations:{en:'Translated question <script>',zh:'简体问题',tw:original}}]}]},
 n2Same:(a,b)=>JSON.stringify(a)===JSON.stringify(b),n2Gap:()=>'',
 n9Missing:()=> 'Not supplied',rx:x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
 n2Short:(x,n)=>String(x).slice(0,n),rl:(zh,en,tw)=>({zh,en,tw})[context.apps[0].lang]};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'v9-route-language.js'),'utf8'),context);
assert.equal(context.n9RouteTranslation(route,'candidate.question').value,'Translated question <script>');
let html=context.n9RouteText(route,'candidate.question');
assert.ok(html.includes('Translated question &lt;script&gt;')&&html.includes('原始问题 &lt;script&gt;'));
assert.ok(!html.includes('<script>'));
context.apps[0].lang='zh';
assert.equal(context.n9RouteTranslation(route,'candidate.question').value,'简体问题');
context.apps[0].lang='tw';
assert.equal(context.n9RouteTranslation(route,'candidate.question').value,original);
context.n2.meta.packet_json_sha256='b'.repeat(64);
assert.equal(context.n9RouteTranslation(route,'candidate.question').available,false);
context.p9.shown={view:{packet_file_sha256:sha}};
assert.equal(context.n9RouteTranslation(route,'candidate.question').available,true);
assert.equal(context.n9RouteTranslation({...route,candidate:{...route.candidate,version:2}},'candidate.question').available,false);
assert.equal(context.n9RouteTranslation({...route,candidate:{...route.candidate,question:'edited source'}},'candidate.question').available,false);
// A different topic can reuse the same candidate ID without reusing its words.
const other={candidate:{candidate_id:'synthetic-route',version:1,question:'Second topic'},assessment:null};
context.n9TranslationBundle.packets.push({packet_file_sha256:'b'.repeat(64),fields:[
 {candidate_id:'synthetic-route',version:1,path:'candidate.question',source:'Second topic',translations:{en:'Second topic translation'}}]});
context.p9.shown=null;
context.apps[0].lang='en';
assert.equal(context.n9RouteTranslation(other,'candidate.question').value,'Second topic translation');
assert.equal(context.n9RouteTranslation(route,'candidate.question').available,false);
context.apps[0].lang='zh';
assert.equal(context.n9RouteTranslation(other,'candidate.question').available,false);
assert.ok(context.n9RouteText(other,'candidate.question').includes('此字段译文未提供'));
assert.equal(JSON.stringify(route),before);
console.log('Route language checks passed: locale switch, original disclosure, HTML escaping, packet/version/source rejection, imported identity, two-topic isolation, missing-locale disclosure, immutable originals.');
