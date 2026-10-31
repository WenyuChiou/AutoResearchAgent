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
function v94Graph(graph,isLoop){
 const index=new Map(graph.nodes.map((node,i)=>[node.id,i]));
 const nodeHtml=(node,i,position='')=>`<article class="n94-node" data-n94-node="${i}" data-n94-ref="${rx(node.id)}"${position}>${graph.edges.filter(edge=>edge.to===node.id).map(edge=>`<p class="n94-route-condition"><span aria-hidden="true">↳ </span>${rx(edge.label)}</p>`).join('')}<div class="n94-node-kind">${v94Icon(node.kind)}<span>${v94Kind(node.kind)}</span></div><h4>${rx(node.title)}</h4><p>${rx(node.detail)}</p>${v94Sources(node.sources)}</article>`;
 // Placement follows authored array order; only the supplied edges express relationships.
 const columns=isLoop?2:3;
 const nodes=graph.nodes.map((node,i)=>nodeHtml(node,i,` style="grid-column:${Math.floor(i/columns)%2?columns-i%columns:1+i%columns};grid-row:${Math.floor(i/columns)+1}"`)).join('');
 const relations=graph.edges.map(edge=>`<li data-n94-edge data-n94-from="${index.get(edge.from)}" data-n94-to="${index.get(edge.to)}"><p><strong>${rx(graph.nodes[index.get(edge.from)].title)}</strong><span class="n94-relation-arrow" aria-hidden="true"> → </span><span>${rx(edge.label)}</span><span class="n94-relation-arrow" aria-hidden="true"> → </span><strong>${rx(graph.nodes[index.get(edge.to)].title)}</strong></p>${v94Sources(edge.sources)}</li>`).join('');
 const heading=isLoop?rl('反馈循环（拟议）','Proposed feedback loop','回饋循環（擬議）'):rl('研究流程（拟议）','Proposed research flow','研究流程（擬議）');
  return `<section class="n94-graph"><h3>${heading}</h3><p class="n94-caption">${isLoop?rl('箭头表示计划中的回访关系；尚未运行迭代。','Arrows show planned feedback relationships; no iterations have been run.','箭頭表示計畫中的回訪關係；尚未執行迭代。'):rl('箭头表示作者整理的研究关系；各步骤和条件尚待核验。','Arrows show authored research relationships; steps and conditions still require verification.','箭頭表示作者整理的研究關係；各步驟與條件尚待核驗。')}</p><div class="n94-board${isLoop?' n94-loop-grid':''}"><svg class="n94-connectors" aria-hidden="true" focusable="false"></svg>${nodes}</div>${relations?`<details class="n94-relations"><summary>${rl('完整关系与来源','Complete relationships and sources','完整關係與來源')} <span>(${graph.edges.length})</span></summary><ul>${relations}</ul></details>`:`<p class="n94-caption">${rl('未提供步骤之间的关系。','No relationships between steps are provided.','未提供步驟之間的關係。')}</p>`}</section>`;
}
function v94GuideHtml(guide){
 const materials=guide.materials.map(item=>`<article class="n94-material"><h4>${v94Icon('material')}${rx(item.name)}</h4><dl><dt>${rl('预期用途','Intended use','預期用途')}</dt><dd>${rx(item.use)}</dd><dt>${rl('待核验','Still to verify','待核驗')}</dt><dd>${rx(item.gap)}</dd></dl>${v94Sources(item.sources)}</article>`).join('');
 const baselines=guide.baselines.map(item=>`<article class="n94-baseline"><h4>${v94Icon('comparison')}${rx(item.name)}</h4><dl><dt>${rl('比较变化','Comparison change','比較變化')}</dt><dd>${rx(item.change)}</dd><dt>${rl('比较目的','Comparison purpose','比較目的')}</dt><dd>${rx(item.purpose)}</dd></dl>${v94Sources(item.sources)}</article>`).join('');
 return `<section class="n94-guide"><header class="n94-intro"><p class="n94-eyebrow">${rl('研究规划导读','Research planning guide','研究規劃導讀')}</p><h2>${rl('从问题走向可检验的研究','From question to a testable study','從問題走向可檢驗的研究')}</h2><p>${rl('作者整理的规划导读 · 仅为拟议，尚未执行。请结合完整原规划审阅。','Authored planning guide · proposed, not run. Review it alongside the complete original plan.','作者整理的規劃導讀 · 僅為擬議，尚未執行。請結合完整原規劃審閱。')}</p></header>${v94Graph(guide.flow,false)}${v94Graph(guide.loop,true)}<section class="n94-materials"><h3>${rl('材料线索与用途','Material leads and uses','材料線索與用途')}</h3><p class="n94-caption">${rl('以下仅为待核验的材料线索，不代表已映射或已可用资源。','These are material leads requiring verification; they do not establish mapped or available resources.','以下僅為待核驗的材料線索，不代表已映射或已可用資源。')}</p><div class="n94-records">${materials||`<p>${rl('未提供材料线索。','No material leads are provided.','未提供材料線索。')}</p>`}</div></section><section class="n94-baselines"><h3>${rl('基线与对照（拟议）','Proposed baselines and comparisons','基線與對照（擬議）')}</h3><p class="n94-caption">${rl('以下对照尚未运行，不代表实验结果或验证通过。','These comparisons have not been run; they are not results or completed validation.','以下對照尚未執行，不代表實驗結果或驗證通過。')}</p><div class="n94-records">${baselines||`<p>${rl('未提供基线或对照。','No baselines or comparisons are provided.','未提供基線或對照。')}</p>`}</div></section></section>`;
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
