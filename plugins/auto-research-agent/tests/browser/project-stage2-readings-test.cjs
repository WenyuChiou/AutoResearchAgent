/* Actual reading-entry source with authored DOM, never network or action work. */
'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const refs = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.text=''; this.hidden=false; this.attributes={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; this.text=''; }
  get textContent() { return this.text+this.children.map(c=>c.textContent).join('\n'); }
  set textContent(v) { this.replaceChildren(); this.text=String(v); }
  set innerHTML(_) { throw Error('source text must remain literal'); }
  setAttribute(k,v) { this.attributes[k]=String(v); }
}
const area=new Element(), language={value:'en'}, handlers={}, effects=[];
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
const get=id=>id==='project-stage-2-result-state'?area:id==='language'?language:descendants(area).find(n=>n.id===id)||null;
const deny=()=>{effects.push('forbidden');throw Error('reading entry attempted a side effect');};
const window={RESEARCH_PROJECTS:{stage2_readings:refs},addEventListener:(n,f)=>{handlers[n]=f;}};
const document={getElementById:get,createElement:tag=>new Element(tag)};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../../cli/research_workspace_native/web/projects-stage2-readings.js'),'utf8'),{window,document,fetch:deny,XMLHttpRequest:deny,WebSocket:deny,localStorage:{getItem:deny,setItem:deny},setTimeout:deny});
const render=()=>handlers['research-project-stage']({detail:{stage:2}}), clone=v=>JSON.parse(JSON.stringify(v));
const links=()=>descendants(area).filter(n=>n.tagName==='a');
for(const lang of ['en','zh-Hans','zh-Hant']) {
  language.value=lang;window.RESEARCH_PROJECTS.stage2_readings=clone(refs);render();render();
  assert.equal(links().length,1,'repeated navigation does not duplicate links');
  assert.equal(links()[0].href,'/project-stage2-readings/saved-report/index.html');
  assert.equal(links()[0].textContent,refs[0].label,'label remains literal source text');
  assert(!get('project-stage2-independent-readings').hidden);
  const mutations=[r=>{r.ref='../foreign';},r=>{r.url='https://foreign.invalid/';},r=>{r.url='/api/projects/select';},r=>{r.stage1_lineage_attested=true;},r=>{r.selection_authority=true;},r=>{r.execution_authorized=true;},r=>{r.reading_only=false;},r=>{r.binding_sha256='bad';},r=>{r.kind='fixture';},r=>{r.source_kind='same-stage1';}];
  for(const mutate of mutations){const changed=clone(refs);mutate(changed[0]);window.RESEARCH_PROJECTS.stage2_readings=changed;render();assert.equal(links().length,0);assert(get('project-stage2-independent-readings').hidden);}
  window.RESEARCH_PROJECTS.stage2_readings=[...clone(refs),...clone(refs)];render();assert.equal(links().length,0,'duplicates reject');
}
window.RESEARCH_PROJECTS.stage2_readings=[];render();assert.equal(links().length,0);
assert.equal(effects.length,0);
console.log(JSON.stringify({kind:'OrdinaryStage2ReadingEntryChecks',languages:3,refusals:33,side_effects:0}));
