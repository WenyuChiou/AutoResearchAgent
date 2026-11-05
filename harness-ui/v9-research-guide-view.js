/* Authored research guide only. The caller validates the guide against its saved plan. */
function v94Icon(kind){
 const paths={question:'M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5m0 4h.01',material:'M5 4h11l3 3v13H5zM15 4v4h4M8 12h8M8 16h6',decision:'m12 3 9 9-9 9-9-9zM12 8v5m0 3h.01',method:'M8 3h8M10 3v7L4 20h16l-6-10V3M8 14h8',comparison:'M5 6h14M5 12h14M5 18h14M8 3v6m8 0v6m-5 0v6',validation:'m5 12 4 4L19 6M4 3h16v18H4z',output:'M5 3h14v18H5zM8 8h8M8 12h8M8 16h5',fallback:'M19 7H9a5 5 0 0 0 0 10h3M9 3 5 7l4 4'};
 return `<svg class="n94-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${paths[kind]||paths.method}"/></svg>`;
}
function v94Kind(kind){
 const labels={question:rl('问题','Question','問題'),material:rl('材料','Material','材料'),decision:rl('条件判断','Qualification','條件判斷'),method:rl('方法','Method','方法'),comparison:rl('比较','Comparison','比較'),validation:rl('验证','Validation','驗證'),output:rl('交付','Output','交付'),fallback:rl('替代路径','Fallback','替代路徑')};
 return labels[kind]||labels.method;
}
function v94Sources(sources){
 return `<details class="n94-sources"><summary>${rl('来源原文','Source text','來源原文')} <span>(${sources.length})</span></summary>${sources.map(s=>`<blockquote><p>${rx(s.quote)}</p><cite>${rx(s.pointer)}</cite></blockquote>`).join('')}</details>`;
}
function v94Graph(graph,isLoop,reading=false){
 const index=new Map(graph.nodes.map((node,i)=>[node.id,i]));
 const fieldTitles=reading?{materials:rl('材料','Materials','材料'),method:rl('方法','Method','方法'),design:rl('设计','Design','設計'),validation:rl('验证','Validation','驗證'),analysis:rl('分析','Analysis','分析'),interpretation:rl('结果判读','Interpretation','結果判讀'),minimum_deliverable:rl('交付','Deliverable','交付')}:{};
 const nodeHtml=(node,i,position='')=>{
  const incoming=graph.edges.filter(edge=>edge.to===node.id),outgoing=graph.edges.filter(edge=>edge.from===node.id);
  const next=outgoing.map(edge=>`<li>${rx(graph.nodes[index.get(edge.to)].title)} · ${rx(edge.label)}</li>`).join('');
  return `<article class="n94-node" data-n94-node="${i}" data-n94-ref="${rx(node.id)}"${position}>${incoming.map(edge=>`<p class="n94-route-condition"><span aria-hidden="true">↳ </span>${rx(edge.label)}</p>`).join('')}<div class="n94-node-kind">${v94Icon(node.kind)}<span>${isLoop?'':(i+1)+' · '}${v94Kind(node.kind)}</span></div><h4>${rx(fieldTitles[node.id]||node.title)}</h4>${v94Disclosure(rl('查看这一步','Read this step','查看這一步'),`<p>${rx(node.detail)}</p>${next?`<p><strong>${rl('接续步骤','Next steps','接續步驟')}</strong></p><ul>${next}</ul>`:''}${v94Sources(node.sources)}`)}</article>`;
 };
 // Placement follows authored array order; only the supplied edges express relationships.
 const columns=isLoop?2:3;
 const nodes=graph.nodes.map((node,i)=>nodeHtml(node,i,` style="grid-column:${Math.floor(i/columns)%2?columns-i%columns:1+i%columns};grid-row:${Math.floor(i/columns)+1}"`)).join('');
 const relations=graph.edges.map(edge=>`<li data-n94-edge data-n94-from="${index.get(edge.from)}" data-n94-to="${index.get(edge.to)}"><p><strong>${rx(graph.nodes[index.get(edge.from)].title)}</strong><span class="n94-relation-arrow" aria-hidden="true"> → </span><span>${rx(edge.label)}</span><span class="n94-relation-arrow" aria-hidden="true"> → </span><strong>${rx(graph.nodes[index.get(edge.to)].title)}</strong></p>${v94Sources(edge.sources)}</li>`).join('');
 const feedback=isLoop&&graph.edges.length>0;
 const heading=reading?(isLoop?rl('方法原文顺序','Method in source order','方法原文順序'):rl('当前研究规划','Current research plan','目前研究規劃')):
  feedback?rl('反馈循环（拟议）','Proposed feedback loop','回饋循環（擬議）'):
  isLoop?rl('已记录的方法说明','Recorded method notes','已記錄的方法說明'):rl('研究流程（拟议）','Proposed research flow','研究流程（擬議）');
 if(reading)return `<section class="n94-graph"><h3>${heading}</h3><p class="n94-caption">${rl('以下为当前版本的原文摘录；完整内容与待查事项仍可展开。原文顺序不表示因果或反馈关系。','Excerpts from the current version. Expand the complete text and open checks below. Source order does not establish causal or feedback relationships.','以下為目前版本的原文摘錄；完整內容與待查事項仍可展開。原文順序不表示因果或回饋關係。')}</p><div class="n94-board${isLoop?' n94-loop-grid':''}"><svg class="n94-connectors" aria-hidden="true" focusable="false"></svg>${nodes}</div></section>`;
  const caption=feedback?rl('箭头表示计划中的回访关系；尚未运行迭代。','Arrows show planned feedback relationships; no iterations have been run.','箭頭表示計畫中的回訪關係；尚未執行迭代。'):
   rl('箭头表示作者整理的研究关系；各步骤和条件尚待核验。','Arrows show authored research relationships; steps and conditions still require verification.','箭頭表示作者整理的研究關係；各步驟與條件尚待核驗。');
  return `<section class="n94-graph"><h3>${heading}</h3>${relations?`<p class="n94-caption">${caption}</p>`:''}<div class="n94-board${isLoop?' n94-loop-grid':''}"><svg class="n94-connectors" aria-hidden="true" focusable="false"></svg>${nodes}</div>${relations?`<details class="n94-relations"><summary>${rl('完整关系与来源','Complete relationships and sources','完整關係與來源')} <span>(${graph.edges.length})</span></summary><ul>${relations}</ul></details>`:`<p class="n94-caption">${rl('未提供步骤之间的关系。','No relationships between steps are provided.','未提供步驟之間的關係。')}</p>`}</section>`;
}
function v94Disclosure(label,html){
 return html?`<details class="n94-disclosure"><summary>${label}</summary>${html}</details>`:'';
}
function v94Field(label,value){
 return typeof value==='string'&&value.trim()?v94Disclosure(label,`<p>${rx(value)}</p>`):'';
}
function v94GuideHtml(guide,{reading=false,question=null,row=null,resources=[],version=null,canComment=false}={}){
 const compare=guide?.baselines??[],leads=guide?.materials??[];
 const authoredQuestion=reading?null:guide?.flow.nodes.find(node=>node.kind==='question');
 const title=authoredQuestion?.detail||question?.text||rl('已保存的研究问题','Saved research question','已保存的研究問題');
 const unknowns=Array.isArray(row?.unknowns)?row.unknowns.filter(value=>typeof value==='string'&&value.trim()):[];
 const conditions=unknowns.map(value=>{
  const title=value.split(/[：:]/u,1)[0].trim();
  const characters=Array.from(title||value.trim());
  return characters.length<=80?characters.join(''):characters.slice(0,79).join('')+'…';
 });
 const feasibility=unknowns.length?rl(`${unknowns.length} 项条件待确认`,`${unknowns.length} ${unknowns.length===1?'condition':'conditions'} to check`,`${unknowns.length} 項條件待確認`):
  rl('仍需确认资料与设计是否可行','Confirm that the data and design are feasible','仍需確認資料與設計是否可行');
 const availability=new Map([
  ['available',rl('已记录可用','Recorded as available','已記錄可用')],
  ['restricted',rl('存取有限制','Access is restricted','存取有限制')],
  ['unavailable',rl('目前不可用','Unavailable','目前不可用')],
  ['not-applicable',rl('不适用','Not applicable','不適用')],
 ]);
 const resourceRows=resources.map(({resource,resource_ref:use})=>`<li><strong>${rx(resource.name)}</strong> · ${availability.get(resource.status)??rl('待核验','To verify','待核驗')}<p>${rx(use?.purpose||resource.purpose||rl('用途待确认','Use to verify','用途待確認'))}</p></li>`).join('');
 const materials=leads.map(item=>`<article><h4>${v94Icon('material')}${rx(item.name)}</h4><p>${rx(item.use)}</p><p><strong>${rl('待核验','Still to verify','待核驗')}</strong> ${rx(item.gap)}</p>${v94Sources(item.sources)}</article>`).join('');
 const comparisons=compare.map(item=>`<article><h4>${v94Icon('comparison')}${rx(item.name)}</h4><p>${rx(item.change)}</p><p>${rx(item.purpose)}</p>${v94Sources(item.sources)}</article>`).join('');
 const comparisonDesign=v94Field(rl('查看已保存的比较条件','Read the saved comparison conditions','查看已保存的比較條件'),row?.design);
 const noComparisons=rl('未提供基线或对照。','No baselines or comparisons are provided.','未提供基線或對照。');
 const hasFeedback=!reading&&!!guide?.loop.edges.length;
 const primaryGraph=hasFeedback?guide.loop:guide?.flow;
 const firstStep=primaryGraph?.nodes[0];
 const secondary=hasFeedback?v94Disclosure(rl('查看规划与交付顺序','View planning and delivery sequence','查看規劃與交付順序'),v94Graph(guide.flow,false)):
  guide?.loop.nodes.length?v94Disclosure(reading?rl('查看方法原文顺序','Read the method in source order','查看方法原文順序'):
   rl('查看已记录的方法说明','Read the recorded method notes','查看已記錄的方法說明'),v94Graph(guide.loop,true,reading)):'';
 const output=question?.object||(!reading&&guide?.flow.nodes.find(node=>node.kind==='output')?.title);
 return `<section class="n94-guide">
  <header class="n94-intro" data-n94-design="question">
   <p class="n94-eyebrow">${rl('研究方向摘要','Research direction','研究方向摘要')}${version===null?'':` · ${rl('草案','Draft','草案')} ${rx(version)}`}</p>
   <h2>${rx(title)}</h2>
   <p class="n94-feasibility">${rl('规划草案','Planning draft','規劃草案')} · ${feasibility}</p>
   ${firstStep?`<p><strong>${rl('流程起点','Where the study starts','流程起點')}</strong> ${rx(reading?v94Kind(firstStep.kind):firstStep.title)}</p>`:''}
   ${conditions.length?`<p><strong>${rl('先确认','Check first','先確認')}</strong> ${conditions.slice(0,3).map(rx).join(' · ')}</p>`:''}
   ${title===question?.text?'':v94Field(rl('查看原研究问题','Read the original research question','查看原研究問題'),question?.text)}
   ${question?.intended_claim?`<p><strong>${rl('能回答什么','What it can answer','能回答什麼')}</strong> ${rx(question.intended_claim)}</p>`:''}
   ${compare.length?`<p><strong>${rl('主要对照','Main comparison','主要對照')}</strong> ${rx(compare[0].change)}</p>`:''}
   ${comparisonDesign}
   ${comparisons?v94Disclosure(rl('查看基线与对照','View baselines and comparisons','查看基線與對照'),`<p>${rl('以下对照尚未运行。','These comparisons have not been run.','以下對照尚未執行。')}</p><div class="n94-records">${comparisons}</div>`):comparisonDesign?'':`<p>${noComparisons}</p>`}
  </header>
  <section data-n94-design="flow">
   <h3>${rl('研究设计与流程','Study design and flow','研究設計與流程')}</h3>
   ${firstStep?'':`<p>${rl('目前没有可显示的流程图。','A flow diagram is currently unavailable.','目前沒有可顯示的流程圖。')}</p>`}
   ${primaryGraph?v94Graph(primaryGraph,hasFeedback,reading):v94Field(rl('查看已保存的方法','Read the saved method','查看已保存的方法'),row?.method)}
   ${secondary}
  </section>
  <section data-n94-design="materials">
   <h3>${rl('资料与可行性','Data and feasibility','資料與可行性')}</h3>
   ${resourceRows?`<ul class="n94-resource-status">${resourceRows}</ul>`:`<p>${rl('本问题没有已对应的资源，资料可用性仍待确认。','No resources are mapped to this question. Availability still needs checking.','本問題沒有已對應的資源，資料可用性仍待確認。')}</p>`}
   ${conditions.length?`<ul class="n94-open-checks">${conditions.map(value=>`<li>${rx(value)}</li>`).join('')}</ul>`:''}
   ${v94Disclosure(rl('查看材料线索与依据','View material leads and sources','查看材料線索與依據'),`<p>${rl('材料线索不代表已对应或已可用资源。','Material leads do not establish mapped or available resources.','材料線索不代表已對應或已可用資源。')}</p>${materials?`<div class="n94-records">${materials}</div>`:`<p>${rl('未提供材料线索。','No material leads are provided.','未提供材料線索。')}</p>`}`)}
   ${v94Field(rl('查看资料要求原文','Read the data requirements','查看資料要求原文'),row?.materials)}
   ${v94Field(rl('查看如何验证','Read how to validate the design','查看如何驗證'),row?.validation)}
   ${unknowns.length?v94Disclosure(rl('查看完整待查事项','Read the complete open checks','查看完整待查事項'),`<ul>${unknowns.map(value=>`<li>${rx(value)}</li>`).join('')}</ul>`):''}
  </section>
  <section data-n94-design="next">
   <h3>${rl('预期产出与下一步','Expected outputs and next steps','預期產出與下一步')}</h3>
   ${output?`<p><strong>${rl('预期产出','Expected output','預期產出')}</strong> ${rx(output)}</p>`:''}
   ${v94Field(rl('查看计划交付物','Read the planned deliverables','查看計畫交付物'),row?.minimum_deliverable)}
   <p>${canComment?rl('核对资料条件后，可通过「评语与修订」提出修改或说明缺件。','After checking data conditions, use Comment or revise to propose changes or record missing material.','核對資料條件後，可透過「評語與修訂」提出修改或說明缺件。'):
    rl('核对待查事项，并查看已保存的完整规划。','Review the open checks and the complete saved plan.','核對待查事項，並查看已保存的完整規劃。')}</p>
   <p>${rl('规划仍是草案，研究尚未执行。','The design is a draft. The study has not been run.','規劃仍是草案，研究尚未執行。')}</p>
  </section>
 </section>`;
}
function v94ConnectGuide(target){
 const graphs=Array.from(target.querySelectorAll('.n94-graph'));
 const draw=()=>graphs.forEach(graph=>{
  const board=graph.querySelector('.n94-board'),svg=board.querySelector('.n94-connectors'),bounds=board.getBoundingClientRect();
  const nodes=Array.from(board.querySelectorAll('[data-n94-node]')).map(node=>{
   const r=node.getBoundingClientRect();return {left:r.left-bounds.left,right:r.right-bounds.left,top:r.top-bounds.top,bottom:r.bottom-bounds.top,x:r.left-bounds.left+r.width/2,y:r.top-bounds.top+r.height/2};
  });
  svg.setAttribute('viewBox',`0 0 ${Math.max(bounds.width,1)} ${Math.max(bounds.height,1)}`);
  svg.innerHTML=Array.from(graph.querySelectorAll('[data-n94-edge]')).map(edge=>{
   const a=nodes[Number(edge.dataset.n94From)],b=nodes[Number(edge.dataset.n94To)];if(!a||!b)return '';
   let points;
   if(Math.abs(a.y-b.y)<Math.min(a.bottom-a.top,b.bottom-b.top)/2&&a.x!==b.x){
    const blocked=nodes.some(c=>c!==a&&c!==b&&c.x>Math.min(a.x,b.x)&&c.x<Math.max(a.x,b.x)&&c.top<a.bottom&&c.bottom>a.top);
    if(blocked){const gutter=Math.max(a.bottom,b.bottom)+18,ax=a.x-20,bx=b.x+20;points=[[ax,a.bottom],[ax,gutter],[bx,gutter],[bx,b.bottom+5]];}
    else{const right=b.x>a.x;points=[[right?a.right:a.left,a.y],[right?b.left-5:b.right+5,b.y]];}
   }else if(b.top>=a.bottom){
    const middle=(a.bottom+b.top)/2;points=[[a.x,a.bottom],[a.x,middle],[b.x,middle],[b.x,b.top-5]];
   }else{
    const lane=Math.min(a.left,b.left)-12;points=[[a.left,a.y],[lane,a.y],[lane,b.y],[b.left-5,b.y]];
   }
   const skipsRow=nodes.some(c=>c!==a&&c!==b&&c.top>=Math.min(a.bottom,b.bottom)&&c.bottom<=Math.max(a.top,b.top));
   const crossesCard=points.slice(1).some((p,i)=>nodes.some(c=>c!==a&&c!==b&&Math.min(points[i][0],p[0])<c.right&&Math.max(points[i][0],p[0])>c.left&&Math.min(points[i][1],p[1])<c.bottom&&Math.max(points[i][1],p[1])>c.top));
   if(skipsRow||crossesCard||b.top<a.top){
    // Leave and enter through row gutters; long/return edges stay outside every card.
    const left=Math.min(...nodes.map(c=>c.left)),right=Math.max(...nodes.map(c=>c.right));
    const leftLane=left-Math.min(12,Math.max(4,left/2)),rightLane=right+Math.min(12,Math.max(4,(bounds.width-right)/2));
    const lane=Math.abs(a.x-leftLane)+Math.abs(b.x-leftLane)<=Math.abs(a.x-rightLane)+Math.abs(b.x-rightLane)?leftLane:rightLane;
    const exit=Math.max(...nodes.filter(c=>c.top<a.bottom&&c.bottom>a.top).map(c=>c.bottom))+12;
    const entry=Math.min(...nodes.filter(c=>c.top<b.bottom&&c.bottom>b.top).map(c=>c.top))-12;
    points=[[a.x,a.bottom],[a.x,exit],[lane,exit],[lane,entry],[b.x,entry],[b.x,b.top-5]];
   }
   const end=points[points.length-1],before=points[points.length-2],angle=Math.atan2(end[1]-before[1],end[0]-before[0]);
   const arrow=[-0.55,0.55].map(offset=>[end[0]-8*Math.cos(angle+offset),end[1]-8*Math.sin(angle+offset)]);
   return `<path d="M${points.map(p=>p.join(',')).join(' L')} M${arrow[0].join(',')} L${end.join(',')} L${arrow[1].join(',')}"/>`;
  }).join('');
 });
 draw();
 const observer=typeof ResizeObserver==='function'?new ResizeObserver(draw):null;
 graphs.forEach(graph=>observer?.observe(graph.querySelector('.n94-board')));
 if(typeof window!=='undefined')window.addEventListener('resize',draw);
 return ()=>{observer?.disconnect();if(typeof window!=='undefined')window.removeEventListener('resize',draw);};
}
