/* Synthetic six-stage DOM; no browser, research, user choice or network. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
class Element{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.hidden=false;this.attrs={};this._text='';}append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=xs;}setAttribute(k,v){this.attrs[k]=v;}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}set textContent(v){this._text=String(v);this.children=[];}}
const elements=new Map(),all=n=>[n,...n.children.flatMap(all)];
for(let i=1;i<=6;i++)for(const suffix of ['', '-title','-status','-operations','-result-state'])elements.set('project-stage-'+i+suffix,new Element('section'));
for(let i=1;i<=6;i++)elements.set('project-stage-nav-'+i,new Element('button'));
const document={createElement:tag=>new Element(tag),getElementById:id=>elements.get(id),querySelectorAll:()=>[],addEventListener(){}};
const window={RESEARCH_PROJECTS:{stage2_selection_projects:['current-project']},dispatchEvent(){}};
vm.runInNewContext(source,{document,window,CustomEvent:class{constructor(type,o){this.type=type;this.detail=o.detail;}}});
const project={project_ref:'current-project',input_version:1,revision:2,brief_sha256:'1'.repeat(64)};
const contract={kind:'HarnessUiProjectView',schema_version:'1.0.0',identity:{...project},stages:{}};
for(let i=1;i<=6;i++)contract.stages[i]={stage:String(i),input:{...project},status:i<3?'saved':'planned',connected:false,accepted:false,execution_authorized:false,expected_outputs:[],artifacts:[],attempts:[],pending_questions:[],approvals:[],metrics:{}};
const target=()=>elements.get('project-stage-2-result-state');const links=()=>all(target()).filter(x=>x.tagName==='A');
for(const [language,label]of[['en','Review directions and choose'],['zh-Hans','比较方向并选择'],['zh-Hant','比較方向並選案']]){
 window.ResearchProjectStages.render({project,contract,language});elements.get('project-stage-nav-2').onclick();assert.equal(elements.get('project-stage-2').hidden,false);assert.equal(links().length,1,'configured Stage2 must expose its current-project comparison entry');assert.equal(links()[0].href,'/project-stage2-selection.html#current-project');assert.equal(links()[0].textContent,label);
}
window.ResearchProjectStages.render({project,contract:{...contract,identity:{...project,input_version:2}}});assert.equal(links().length,0,'stale contract must not show entry');
window.RESEARCH_PROJECTS.stage2_selection_projects=[];window.ResearchProjectStages.render({project,contract});assert.equal(links().length,0,'unconfigured project must not show entry');
window.ResearchProjectStages.clear();assert.equal(links().length,0,'clearing project removes previous entry');
console.log('Three-language current-project navigation and stale/unconfigured/clear refusal PASS; no network/model/selection');
