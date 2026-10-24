/* Synthetic delayed UI responses; no network, human choice or model. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.hidden=false;this.checked=false;this.disabled=false;this._text='';}append(...xs){this.children.push(...xs);if(this.tagName==='SELECT'&&!this.value&&xs[0])this.value=xs[0].value||xs[0].textContent;}replaceChildren(...xs){this.children=xs;}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}set textContent(v){this._text=String(v);this.children=[];}}
const ids=['language','project','cards','planning','planning-link','planning-summary','choice','submit','receipt','status','planning-input','actor','message','rationale','conditions','unresolved','confirmed'];
const els=new Map(ids.map(x=>[x,new Element(x==='project'||x==='language'?'select':'div')]));els.get('language').value='en';
const pending=[],selected={value:'A',dataset:{version:'1'}};
const document={documentElement:{},getElementById:id=>els.get(id),querySelectorAll:()=>[],querySelector:()=>selected,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
const fetch=(url,opts)=>new Promise((resolve,reject)=>pending.push({url,opts,resolve,reject}));
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{document,window:{RESEARCH_PROJECTS:{credential:'synthetic-only',stage2_selection_projects:['A','B']}},location:{hash:''},fetch,crypto:{randomUUID:()=> 'synthetic-key'},console});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const response=(call,v)=>call.resolve({ok:true,json:async()=>v});
const view=ref=>({revision:1,input_version:1,brief_sha256:ref,delivery_manifest_sha256:ref,workflow_head_sha256:ref,snapshot_sha256:ref,selection_status:'unrecorded',selection_receipt:null,planning_status:'pending',eligible:[{candidate_id:ref,candidate_version:1}],cards:{cards:[{candidate_question:'Direction '+ref,candidate_id:ref,candidate_version:1,suggested_approach:'Synthetic',closest_prior_work:{review:null},contribution:[],scientific_questions:[],requirements:[],unmapped_resources:[],limitations:[],alternatives:[],next_checks:[]}]}});
const switchTo=ref=>{els.get('project').value=ref;return els.get('project').onchange();};
async function main(){
 assert.equal(pending[0].url,'/api/projects/A/stage2/selection');
 switchTo('B');response(pending[1],view('B'));await tick();assert.match(els.get('cards').textContent,/Direction B/);
 response(pending[0],view('A'));await tick();assert.match(els.get('cards').textContent,/Direction B/,'late A success must never replace current B');assert.doesNotMatch(els.get('cards').textContent,/Direction A/);
 switchTo('A');const stale=pending.at(-1);switchTo('B');response(pending.at(-1),view('B'));await tick();const prior=els.get('status').textContent;stale.reject(new Error('late-A-error'));await tick();assert.equal(els.get('status').textContent,prior,'late error must not replace current status');
 switchTo('A');response(pending.at(-1),view('A'));await tick();els.get('confirmed').checked=true;els.get('actor').value='synthetic-user';els.get('message').value='Choose this version';els.get('rationale').value='Fixture';
 const submitted=els.get('choice').onsubmit({preventDefault(){}});const post=pending.at(-1);assert.equal(post.url,'/api/projects/A/stage2/select');assert.equal(post.opts.method,'POST');switchTo('B');response(pending.at(-1),view('B'));await tick();response(post,{status:'saved'});await tick();await submitted;assert.match(els.get('cards').textContent,/Direction B/,'late post must not refresh prior project under B');assert.equal(pending.at(-1).url,'/api/projects/B/stage2/selection','late submit must not fetch using a mutable project selector');
 console.log('Delayed success/error and captured-project submission PASS; no network/model/real human choice');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
