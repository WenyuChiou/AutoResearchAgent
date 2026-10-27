/* Synthetic delayed UI responses; no network, human choice or model. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.hidden=false;this.checked=false;this.disabled=false;this._text='';}append(...xs){this.children.push(...xs);if(this.tagName==='SELECT'&&!this.value&&xs[0])this.value=xs[0].value||xs[0].textContent;}replaceChildren(...xs){this.children=xs;}scrollIntoView(){this.scrolled=true;}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}set textContent(v){this._text=String(v);this.children=[];}}
const ids=['language','project','project-context','cards','planning','planning-link','return-cards','planning-summary','choice','submit','submit-and-start','receipt','status','planning-input','actor','message','rationale','conditions','unresolved','confirmed'];
const els=new Map(ids.map(x=>[x,new Element(x==='project'||x==='language'?'select':'div')]));els.get('language').value='en';
const pending=[],selected={value:'A',dataset:{version:'1'}};
const document={documentElement:{},getElementById:id=>els.get(id),querySelectorAll:()=>[],querySelector:()=>selected,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
const fetch=(url,opts)=>url==="/api/projects"?Promise.resolve({ok:true,json:async()=>({projects:[{project_ref:"A",topic:"Research project A"},{project_ref:"B",topic:"Research project B"}]})}):new Promise((resolve,reject)=>pending.push({url,opts,resolve,reject}));
const source=fs.readFileSync(process.argv[2],'utf8'),location={hash:''},history={replaceState(_state,_title,url){location.hash=url;}};
const context={document,window:{RESEARCH_PROJECTS:{credential:'synthetic-only',stage2_selection_projects:['A','B']}},location,history,fetch,crypto:{randomUUID:()=> 'synthetic-key'},console};
vm.runInNewContext(source,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const response=(call,v)=>call.resolve({ok:true,json:async()=>v});
const view=ref=>({project_ref:ref,revision:1,input_version:1,brief_sha256:ref,delivery_manifest_sha256:ref,workflow_head_sha256:ref,snapshot_sha256:ref,selection_status:'unrecorded',selection_receipt:null,planning_status:'pending',eligible:[{candidate_id:ref,candidate_version:1}],cards:{cards:[{candidate_question:'Direction '+ref,candidate_id:ref,candidate_version:1,suggested_approach:'Synthetic',closest_prior_work:{review:null},contribution:[],scientific_questions:[],requirements:[],unmapped_resources:[],limitations:[],alternatives:[],next_checks:[]}]}});
const switchTo=ref=>{els.get('project').value=ref;return els.get('project').onchange();};
async function main(){
 assert.equal(pending[0].url,'/api/projects/A/stage2/selection');
 switchTo('B');response(pending[1],view('B'));await tick();assert.match(els.get('cards').textContent,/Direction B/);assert.match(els.get('project-context').textContent,/Research project B.*Input version: 1/);
 response(pending[0],view('A'));await tick();assert.match(els.get('cards').textContent,/Direction B/,'late A success must never replace current B');assert.doesNotMatch(els.get('cards').textContent,/Direction A/);
 switchTo('A');const stale=pending.at(-1);switchTo('B');response(pending.at(-1),view('B'));await tick();const prior=els.get('status').textContent;stale.reject(new Error('late-A-error'));await tick();assert.equal(els.get('status').textContent,prior,'late error must not replace current status');
 switchTo('A');response(pending.at(-1),view('A'));await tick();els.get('confirmed').checked=true;els.get('actor').value='synthetic-user';els.get('message').value='Choose this version';els.get('rationale').value='Fixture';
 const submitted=els.get('choice').onsubmit({preventDefault(){}});const post=pending.at(-1);assert.equal(post.url,'/api/projects/A/stage2/select');assert.equal(post.opts.method,'POST');switchTo('B');response(pending.at(-1),view('B'));await tick();response(post,{status:'saved'});await tick();await submitted;assert.match(els.get('cards').textContent,/Direction B/,'late post must not refresh prior project under B');assert.equal(pending.at(-1).url,'/api/projects/B/stage2/selection','late submit must not fetch using a mutable project selector');
 const saved={...view('B'),selection_status:'recorded',eligible:[],planning_input:{legacy_candidates:[],questions:[],selection_conditions:[],unresolved:[]}};
 switchTo('B');response(pending.at(-1),saved);await tick();assert.equal(location.hash,'#B');assert.equal(els.get('planning-link').href,'#B');assert.equal(els.get('return-cards').href,'#B');
 let prevented=0;els.get('planning-link').onclick({preventDefault(){prevented++;}});els.get('return-cards').onclick({preventDefault(){prevented++;}});assert.equal(prevented,2);assert.equal(els.get('planning').scrolled,true);assert.equal(els.get('cards').scrolled,true);assert.equal(location.hash,'#B','section links must preserve the current project identity');
 els.get('project').value='';els.get('project').children=[];vm.runInNewContext(source,context);assert.equal(pending.at(-1).url,'/api/projects/B/stage2/selection','reload must retain the saved project hash');response(pending.at(-1),saved);await tick();assert.equal(els.get('project').value,'B');assert.equal(els.get('choice').hidden,true);assert.equal(els.get('planning-link').hidden,false);
 console.log('Delayed success/error and captured-project submission PASS; no network/model/real human choice');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
