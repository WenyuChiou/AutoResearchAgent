/* Synthetic presentation checks only; no scientific or browser execution. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),test=require('node:test'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'v9-research-guide-view.js'),'utf8');
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function renderer(locale='en',extra={}){
 const ctx={rx:escape,rl:(zh,en,tw)=>({zh,en,tw}[locale]),...extra};vm.createContext(ctx);vm.runInContext(source,ctx);return ctx;
}
function guide(size=8){
 const sources=[{pointer:'/question_plans/0/method',quote:'Original source → exact research language.'}];
 const kinds=['question','material','decision','method','fallback','comparison','validation','output'];
 const nodes=Array.from({length:size},(_,i)=>({id:'node-'+i,kind:kinds[i%8],title:'研究标题 '+i,detail:'Complete research detail '+i,sources}));
 const edges=(size===8?[[0,1],[1,2],[2,3],[2,4],[3,5],[5,6],[6,7]]:nodes.slice(1).map((_,i)=>[i,i+1])).map(([from,to],i)=>({from:nodes[from].id,to:nodes[to].id,label:'Exact condition '+i,sources}));
 const loopNodes=nodes.slice(0,4).map((node,i)=>({...node,id:'loop-'+i,title:'Loop title '+i}));
 const loopEdges=loopNodes.map((node,i)=>({from:node.id,to:loopNodes[(i+1)%loopNodes.length].id,label:'Feedback '+i,sources}));
 return {flow:{nodes,edges},loop:{nodes:loopNodes,edges:loopEdges},materials:Array.from({length:5},(_,i)=>({name:'Lead '+i,use:'Proposed use '+i,gap:'Verify access '+i,sources})),baselines:Array.from({length:4},(_,i)=>({name:'Baseline '+i,change:'Change '+i,purpose:'Purpose '+i,sources}))};
}
test('preserves every node, branch, loop relation and lead without mutating input',()=>{
 const input=guide(),before=JSON.stringify(input),html=renderer().v94GuideHtml(input);
 assert.equal(JSON.stringify(input),before);assert.equal((html.match(/data-n94-node=/g)||[]).length,12);
 assert.equal((html.match(/data-n94-edge /g)||[]).length,11);
 for(const graph of [input.flow,input.loop]){
  for(const node of graph.nodes)for(const value of [node.title,node.detail,node.id])assert.ok(html.includes(escape(value)));
  for(const edge of graph.edges)assert.ok(html.includes(escape(edge.label)));
 }
 assert.match(html,/data-n94-from="2" data-n94-to="3"/);assert.match(html,/data-n94-from="2" data-n94-to="4"/);
 assert.match(html,/data-n94-ref="node-4"[^>]*><p class="n94-route-condition"><span aria-hidden="true">↳ <\/span>Exact condition 3<\/p>/);
 assert.match(html,/data-n94-from="3" data-n94-to="0"/);
 assert.match(html,/data-n94-ref="node-2" style="grid-column:3;grid-row:1"/);assert.match(html,/data-n94-ref="node-3" style="grid-column:3;grid-row:2"/);
 for(const row of [...input.materials,...input.baselines])for(const [key,value] of Object.entries(row))if(key!=='sources')assert.ok(html.includes(escape(value)));
 assert.match(html,/do not establish mapped or available resources/);assert.match(html,/comparisons have not been run/);
});
test('all sources are complete, keyboard-native disclosures initially closed',()=>{
 const html=renderer().v94GuideHtml(guide());
 assert.equal((html.match(/<details class="n94-sources">/g)||[]).length,32);
 assert.equal((html.match(/<details class="n94-relations">/g)||[]).length,2);
 assert.match(html,/<details class="n94-relations"><summary>Complete relationships and sources <span>\(7\)<\/span><\/summary><ul><li data-n94-edge /);
 assert.doesNotMatch(html,/<details[^>]*\bopen(?:\s|>)/);
 assert.equal((html.match(/Original source → exact research language\./g)||[]).length,32);
 assert.equal((html.match(/<cite>\/question_plans\/0\/method<\/cite>/g)||[]).length,32);
});
test('every payload string remains inert, including IDs, relation labels and quotes',()=>{
 const input=guide(),attack='<img src=x onerror="unsafe()"> & \'quoted\'';
 for(const graph of [input.flow,input.loop]){
  const ids=new Map(graph.nodes.map(node=>[node.id,node.id+attack]));
  graph.nodes.forEach(node=>{node.id=ids.get(node.id);node.title+=attack;node.detail+=attack;});
  graph.edges.forEach(edge=>{edge.from=ids.get(edge.from);edge.to=ids.get(edge.to);edge.label+=attack;});
 }
 for(const row of [...input.materials,...input.baselines])for(const key of Object.keys(row))if(key!=='sources')row[key]+=attack;
 input.flow.nodes[0].sources[0]={pointer:'/path/'+attack,quote:attack};
 const html=renderer().v94GuideHtml(input);
 assert.doesNotMatch(html,/<img|<script|onerror="unsafe/);assert.ok(html.includes(escape(attack)));
 assert.ok(html.includes(escape(input.flow.nodes[0].id)));assert.ok(html.includes(escape('/path/'+attack)));
 for(const graph of [input.flow,input.loop])for(const edge of graph.edges)assert.ok(html.includes(escape(edge.label)));
});
test('three interface locales retain original research language and not-run boundaries',()=>{
 const expected={en:['Research planning guide','Proposed research flow','Material leads and uses','proposed, not run','Complete relationships and sources'],zh:['研究规划导读','研究流程（拟议）','材料线索与用途','尚未执行','完整关系与来源'],tw:['研究規劃導讀','研究流程（擬議）','材料線索與用途','尚未執行','完整關係與來源']};
 for(const locale of Object.keys(expected)){
  const html=renderer(locale).v94GuideHtml(guide());for(const label of expected[locale])assert.ok(html.includes(label));
  assert.ok(html.includes('研究标题 0'));assert.ok(html.includes('Exact condition 0'));
 }
});
test('bounded larger graphs and empty optional records retain all content',()=>{
 const input=guide(12);input.flow.edges.push(...input.flow.edges.slice(0,7));input.materials=[];input.baselines=[];
 const html=renderer().v94GuideHtml(input);assert.equal((html.match(/data-n94-node=/g)||[]).length,16);
 assert.equal((html.match(/data-n94-edge /g)||[]).length,22);
 assert.match(html,/No material leads are provided/);assert.match(html,/No baselines or comparisons are provided/);
 input.flow={nodes:[input.flow.nodes[0]],edges:[]};assert.match(renderer().v94GuideHtml(input),/No relationships between steps are provided/);
});
test('connector cleanup releases measurements and resize listener',()=>{
 let draws=0,observes=0,disconnects=0,removed=0,listener;
 const rect=(left,top)=>({left,top,right:left+100,bottom:top+80,width:100,height:80});
 const svg={setAttribute(){},set innerHTML(value){draws++;assert.match(value,/<path d="M/);assert.doesNotMatch(value,/NaN|undefined/);}};
 const board={getBoundingClientRect:()=>({left:0,top:0,width:300,height:240}),querySelector:()=>svg,querySelectorAll:()=>[0,1].map(i=>({getBoundingClientRect:()=>rect(30,i*140)}))};
 const graph={querySelector:()=>board,querySelectorAll:()=>[{dataset:{n94From:'0',n94To:'1'}}]};
 const ctx=renderer('en',{ResizeObserver:class{constructor(draw){this.draw=draw;}observe(){observes++;}disconnect(){disconnects++;}},window:{addEventListener(name,fn){listener=fn;},removeEventListener(name,fn){assert.equal(fn,listener);removed++;}}});
 const cleanup=ctx.v94ConnectGuide({querySelectorAll:()=>[graph]});assert.equal(draws,1);assert.equal(observes,1);listener();assert.equal(draws,2);
 cleanup();assert.equal(disconnects,1);assert.equal(removed,1);
});
test('wide same-row connections route around intervening cards and remeasure after reflow',()=>{
 let narrow=false,markup='';const rect=(left,top)=>({left,top,right:left+100,bottom:top+80,width:100,height:80});
 const svg={setAttribute(){},set innerHTML(value){markup=value;}};
 const board={getBoundingClientRect:()=>({left:0,top:0,width:500,height:400}),querySelector:()=>svg,querySelectorAll:()=>[0,1,2].map(i=>({getBoundingClientRect:()=>narrow?rect(30,i*140):rect(30+i*140,10)}))};
 const graph={querySelector:()=>board,querySelectorAll:()=>[{dataset:{n94From:'2',n94To:'0'}}]};let resize;
 const ctx=renderer('en',{window:{addEventListener(name,fn){resize=fn;},removeEventListener(){}}});
 const cleanup=ctx.v94ConnectGuide({querySelectorAll:()=>[graph]});assert.match(markup,/M340,90 L340,108 L100,108 L100,95/);
 narrow=true;resize();assert.match(markup,/M80,360 L80,372 L18,372 L18,-12 L80,-12 L80,-5/);assert.doesNotMatch(markup,/NaN|undefined/);cleanup();
});
test('qualification-to-fallback skips and loop returns never cross nonendpoint cards',()=>{
 const cases=[
  {positions:[[30,20],[170,20],[310,20],[310,160],[170,160],[30,160],[30,300],[170,300]],from:2,to:7,width:460,height:430},
  {positions:Array.from({length:8},(_,i)=>[30,20+i*140]),from:2,to:7,width:180,height:1200},
  {positions:[[30,20],[170,20],[170,160],[30,160]],from:3,to:0,width:320,height:280}
 ];
 for(const c of cases){
  let markup='';const cards=c.positions.map(([left,top])=>({left,top,right:left+100,bottom:top+80,width:100,height:80}));
  const svg={setAttribute(){},set innerHTML(value){markup=value;}};
  const board={getBoundingClientRect:()=>({left:0,top:0,width:c.width,height:c.height}),querySelector:()=>svg,querySelectorAll:()=>cards.map(card=>({getBoundingClientRect:()=>card}))};
  const graph={querySelector:()=>board,querySelectorAll:()=>[{dataset:{n94From:String(c.from),n94To:String(c.to)}}]};
  const cleanup=renderer().v94ConnectGuide({querySelectorAll:()=>[graph]});
  const points=markup.match(/d="M([^"]+?) M/)[1].split(' L').map(pair=>pair.split(',').map(Number));
  assert.ok(points.every(p=>p.every(Number.isFinite)));assert.ok(points.some(p=>p[0]<Math.min(...cards.map(r=>r.left))||p[0]>Math.max(...cards.map(r=>r.right))));
  for(let i=1;i<points.length;i++)for(let j=0;j<cards.length;j++)if(j!==c.from&&j!==c.to){
   const [p,q,r]=[points[i-1],points[i],cards[j]];assert.ok(p[0]===q[0]||p[1]===q[1]);
   assert.equal(Math.min(p[0],q[0])<r.right&&Math.max(p[0],q[0])>r.left&&Math.min(p[1],q[1])<r.bottom&&Math.max(p[1],q[1])>r.top,false,`segment ${i} crosses card ${j}`);
  }
  assert.equal(points.at(-2)[1]<cards[c.to].top,true);cleanup();
 }
});
