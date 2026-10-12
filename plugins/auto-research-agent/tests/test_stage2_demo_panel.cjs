/* Synthetic DOM only; actual HTTP/SQLite/controller are covered in Python. */
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), vm = require("node:vm"), path = require("node:path");
const sourcePath=process.argv[2] || path.join(__dirname,"../references/research-workspace/examples/stage2-demo-panel.js");
const source=fs.readFileSync(sourcePath,"utf8");
const hostSource=fs.readFileSync(path.resolve(path.dirname(sourcePath),"../../../cli/research_workspace_native/web/atlas-host.js"),"utf8");
const credentialPosition=hostSource.indexOf("  const credential =");
assert.ok(credentialPosition>0,"actual host initialization prefix required");
const hostInitialization=hostSource.slice(0,credentialPosition)+"\n})();";
const nodes = n => [n,...n.children.flatMap(nodes)], tick = () => new Promise(r=>setImmediate(r));
class Element {
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.handlers={};this._text="";this.dataset={};}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}set textContent(v){this._text=String(v);this.replaceChildren();}
  get isConnected(){return !!this.parent;}
  append(...children){children.forEach(n=>{n.parent=this;this.children.push(n);});}
  replaceChildren(...children){this.children.forEach(n=>n.parent=null);this.children=[];this.append(...children);}
  setAttribute(){}addEventListener(name,fn){this.handlers[name]=fn;}
  async click(){if(!this.disabled)await this.handlers.click?.();}
  set innerHTML(_){throw Error("unsafe HTML");}
}
const hash="a".repeat(64), secret="synthetic-memory-only-credential";
async function mount({row=null,loss=false,current="stage2",enabled=true,bootstrap=true}={}){
  const html=new Element("html"),content=new Element("main");html.lang="en";html.dataset.atlasStage="2";html.append(content);
  const document={documentElement:html,createElement:t=>new Element(t),getElementById:id=>id==="atlas-content"?content:null};
  const calls=[],observers=[],server={row};
  const view=()=>({key:"run-repository-stage2-v1",case_sha256:hash,index_sha256:hash,action:server.row});
  const window={WORKSPACE_HOST:{credential:secret,current_case:current}};
  // Execute the actual host initialization prefix before its DOM rendering.
  if(bootstrap)window.WORKSPACE_STAGE2_DEMO={credential:secret,project_ref:current,enabled};
  vm.runInNewContext(hostInitialization,{window});
  assert.equal(window.WORKSPACE_HOST,undefined);
  vm.runInNewContext(source,{document,window,MutationObserver:class{constructor(f){observers.push(f);}observe(){}},
    fetch:async(url,opts)=>{calls.push({url,...opts});assert.equal(opts.headers.Authorization,"Bearer "+secret);assert.ok(!url.includes(secret));
      if(opts.method==="POST"){
        assert.deepEqual(JSON.parse(opts.body),{key:"run-repository-stage2-v1",case_sha256:hash,index_sha256:hash,confirmed:true});
        server.row={status:"completed",outcome:"succeeded",result:{adapter_calls:["research","extract","review:challenger","review:feasibility","resolve"]}};
        if(loss)throw Error("response lost after commit");
      }
      return {ok:true,json:async()=>JSON.parse(JSON.stringify(view()))};
    }});
  await tick();
  assert.equal(window.WORKSPACE_STAGE2_DEMO,undefined);
  return {html,content,calls,server,observers,all:()=>nodes(content),buttons:()=>nodes(content).filter(n=>n.tagName==="BUTTON")};
}
(async()=>{
  const stage1=await mount({current:"case"});assert.equal(stage1.calls.length,0);
  for(const options of [{enabled:false},{bootstrap:false},{current:"another-project"}]){
    const rejected=await mount(options);assert.equal(rejected.calls.length,0);assert.equal(rejected.buttons().length,0);
  }
  const live=await mount();assert.equal(live.calls.length,1);assert.equal(live.calls[0].method,undefined);
  live.html.dataset.atlasStage="1";live.observers.forEach(f=>f());assert.equal(live.content.children[0].hidden,true);assert.equal(live.buttons()[0].disabled,true);
  live.html.dataset.atlasStage="2";live.observers.forEach(f=>f());assert.equal(live.content.children[0].hidden,false);assert.equal(live.calls.length,1);
  assert.equal(live.buttons()[0].disabled,true);
  const confirm=live.all().find(n=>n.tagName==="INPUT");confirm.checked=true;confirm.handlers.change();
  await live.buttons()[0].click();assert.equal(live.calls.filter(c=>c.method==="POST").length,1);
  assert.equal(live.buttons()[0].disabled,true);assert.equal(live.all().filter(n=>n.tagName==="LI").length,5);
  await live.buttons()[1].click();assert.equal(live.calls.filter(c=>c.method==="POST").length,1);
  live.html.lang="zh-Hans";live.observers.forEach(f=>f());assert.ok(live.content.textContent.includes("本阶段尚未完成"));
  assert.equal(live.calls.filter(c=>c.method==="POST").length,1);
  const reloaded=await mount({row:live.server.row});assert.equal(reloaded.calls.length,1);assert.equal(reloaded.buttons()[0].disabled,true);
  const lost=await mount({loss:true});lost.all().find(n=>n.tagName==="INPUT").checked=true;lost.all().find(n=>n.tagName==="INPUT").handlers.change();
  await lost.buttons()[0].click();assert.equal(lost.buttons()[0].disabled,true);assert.ok(lost.content.textContent.includes("Response unverified"));
  await lost.buttons()[1].click();assert.equal(lost.calls.filter(c=>c.method==="POST").length,1);assert.equal(lost.buttons()[0].disabled,true);
  for(const [row,label]of[[{status:"execution-unknown",outcome:"timeout-unknown"},"Outcome unknown"],[{status:"failed",outcome:"failed"},"Worker failed"]]){
    const state=await mount({row});assert.ok(state.content.textContent.includes(label));assert.equal(state.buttons()[0].disabled,true);assert.equal(state.calls.filter(c=>c.method==="POST").length,0);
  }
  console.log("Stage2 demo: host bootstrap consumed, independent demo bootstrap consumed; mount/reload/reconnect GET-only, fixed confirmed once POST, lost response no resend, failure/unknown distinct, 5 unit flow, translation PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});
