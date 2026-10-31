/* Synthetic presentation checks; existing submission/recovery suites retain their original semantics. */
'use strict';
const assert=require('node:assert/strict');
const {harness,descendants}=require('./test_project_stage2_selection_embedded.cjs');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const cards=Array.from({length:4},(_,i)=>({
 candidate_id:'direction-'+i,candidate_version:i+1,candidate_question:'Question '+i,
 suggested_approach:'Method '+i,closest_prior_work:{review:null},contribution:[],
 scientific_questions:[{question:{text:'SQ '+i,intended_claim:'Bounded claim'},resource_mapping_status:'unmapped',resource_uses:[]}],
 requirements:['Required '+i],unmapped_resources:[{name:'Material '+i,status:'unknown',limitations:['Access unresolved '+i]}],
 limitations:['Limit '+i],alternatives:[],next_checks:['Check '+i]
}));
(async()=>{
 const f=harness({empty:true,cards});await tick();
 const articles=f.els.get('cards').children;assert.equal(articles.length,4);
 for(const [i,a]of articles.entries()){
  const d=a.children.find(n=>n.tagName==='DETAILS');assert.ok(d);assert.equal(d.open,false);
  assert.match(a.textContent,new RegExp('Question '+i));assert.match(a.textContent,new RegExp('Method '+i));
  assert.match(d.textContent,new RegExp('SQ '+i));assert.match(d.textContent,new RegExp('Access unresolved '+i));
  const label=descendants(a).find(n=>n.tagName==='LABEL');assert.match(label.textContent,new RegExp('Question '+i+'.*v'+(i+1)));
 }
 assert.equal(f.els.get('choice').hidden,true);assert.equal(f.els.get('formal-panel').hidden,true);
 assert.match(f.els.get('decision-context').textContent,/4.*0/);
 const checks=descendants(f.els.get('cards')).filter(n=>n.name==='tentative-direction');
 checks[2].checked=true;checks[2].onchange();
 assert.match(f.els.get('preference-summary').textContent,/1.*Question 2.*v3/);
 assert.match(f.els.get('chosen-directions').textContent,/Question 2.*v3/);
 let focused=false;f.els.get('intent-message').focus=()=>{focused=true;};
 f.els.get('review-preference').onclick();assert.equal(f.els.get('intent-panel').open,true);assert.ok(focused);
 f.els.get('intent-message').value='Keep the evidence unknown';
 for(const lang of ['en','zh-TW','zh-CN']){
  f.handle.setLanguage(lang);
  assert.match(f.els.get('preference-summary').textContent,/Question 2.*v3/);
  assert.equal(f.els.get('intent-message').value,'Keep the evidence unknown');
  assert.equal(descendants(f.els.get('cards')).filter(n=>n.name==='tentative-direction'&&n.checked).length,1);
  assert.equal(f.els.get('formal-panel').hidden,true);
 }
 assert.equal(f.writes.length,0);
  const formal=harness();await tick();
  const radio=descendants(formal.els.get('cards')).find(n=>n.name==='direction');
  radio.checked=true;radio.onchange();
  let actorFocused=false;formal.els.get('actor').focus=()=>{actorFocused=true;};
  formal.els.get('review-preference').onclick();
  assert.equal(formal.els.get('formal-panel').hidden,false);
  assert.equal(formal.els.get('formal-panel').open,true);assert.ok(actorFocused);
  for(const lang of ['en','zh-TW','zh-CN']){
   formal.handle.setLanguage(lang);
   assert.match(formal.els.get('preference-summary').textContent,/Bounded question.*v1/);
   assert.equal(descendants(formal.els.get('cards')).filter(n=>n.name==='direction'&&n.checked).length,1);
  }
  assert.equal(formal.writes.length,0);
 console.log('Comparison summaries, complete collapsed evidence, accessible version labels, preference focus and locale preservation PASS; zero POST/model');
})().catch(e=>{console.error(e);process.exitCode=1;});
