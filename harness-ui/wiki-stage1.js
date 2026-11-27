// Wiki V1 Stage 1. Only project-bound persisted output is projected here.
const wikiS1Tabs = {sources:'来源与图谱', evidence:'证据', synthesis:'跨文献综合'};
const wikiS1Groups = ['#6fb7e9','#e2a23b','#3fbf9a','#d98bb5','#e6803a','#a99be0'];
// Saved coverage rows may carry only a question (often in English). Never show "undefined".
function wikiS1GroupTitle(row, i) {
 const text = typeof row?.description === 'string' && row.description.trim() || typeof row?.title === 'string' && row.title.trim();
 return text || `需求 ${i + 1}`;
}
const wikiS1Decisions = {include:'纳入', exclude:'排除', pending:'待定', missing:'未提供'};
const wikiS1Relations = {supports:'支持', partial:'部分支持', contradicts:'不支持', pending:'待判断',
 unclear:'不明确', unverifiable:'无法核对', unverified:'未核对', context:'背景信息'};
const wikiS1Checks = {all:'全部', supports:'✓ 支持', partial:'◐ 部分支持', contradicts:'✕ 不支持', unchecked:'○ 未核对'};

function wikiS1Active(app) {
 return app.wikiS1Enabled === true && app.page === 'workspace' && app.stage === 1 && app.lang === 'zh';
}

function wikiS1Index() {
 const atlas = rt.atlas, index = atlas?.payload?.index, project = rt.overview?.project;
 if (!index || !Array.isArray(index.papers) || !Array.isArray(index.claims)) return null;
 if (canonicalReadonly()) return wikiHomeArchiveBound(rt.ref) && rt.savedRun.payload.index === index ? index : null;
 const receipt = rt.overview?.stage1?.delivery?.canonical_package;
 if (!project || !receipt || project.project_ref !== rt.ref || atlas.project_ref !== rt.ref ||
     atlas.input_version !== project.input_version || atlas.revision !== project.revision ||
     atlas.artifact_ref !== receipt.artifact_ref || atlas.manifest_sha256 !== receipt.manifest_sha256) return null;
 return index;
}

function wikiS1State(app, index) {
 const key = JSON.stringify([rt.ref, rt.atlas?.payload?.index_sha256 ?? null]);
 if (app.wikiS1?.key !== key) {
  app.wikiS1 = {key, tab:'sources', group:'', check:'all', mode:3, labels:true, related:true, more:false};
 }
 const state = app.wikiS1;
 if (!index) return state;
 state.groups = (index.coverage || []).map((row,i) => ({
  id:row.need_id, title:wikiS1GroupTitle(row, i), question:typeof row.question === 'string' ? row.question : '',
  works:new Set(Array.isArray(row.work_ids) ? row.work_ids : []), color:wikiS1Groups[i % wikiS1Groups.length]
 }));
 const screen = new Map();
 for (const row of index.screening || []) {
  const key = JSON.stringify([row.work_id,row.version_id]);
  const prior = screen.get(key);
  if (!prior || row.observed_at >= prior.observed_at) screen.set(key,row);
 }
 const claims = new Map();
 for (const row of index.claims) {
  const key = JSON.stringify([row.work_id,row.version_id]);
  if (!claims.has(key)) claims.set(key,[]);
  claims.get(key).push(row);
 }
 state.sources = index.papers.map((paper,i) => {
  const key = JSON.stringify([paper.work_id,paper.version_id]);
  return {paper, number:i+1, groups:state.groups.filter(group=>group.works.has(paper.work_id)),
   decision:screen.get(key), claims:claims.get(key)||[]};
 });
 wikiS1SyncSelection(state);
 return state;
}

function wikiS1VisibleSources(state) {
 const group = state.groups.find(row=>row.id===state.group);
 return group ? state.sources.filter(row=>group.works.has(row.paper.work_id)) : state.sources;
}

function wikiS1SyncSelection(state) {
 const visible = wikiS1VisibleSources(state);
 if (state.selected && visible.some(row=>row.paper.work_id===state.selected)) return;
 state.selected = visible[0]?.paper.work_id;
 state.focus = state.selected ? {kind:'paper',key:state.selected} : null;
 state.check = 'all';
}

function wikiS1Check(claim) {
 const verifier = claim.core_event?.payload?.verifier;
 // A recorded relation alone is an observation. Only explicit human checks with a source span count here.
 return verifier?.actor_type === 'human' && claim.locator &&
  ['supports','partial','contradicts'].includes(claim.relation) ? claim.relation : 'unchecked';
}

function wikiS1Metrics(index, state) {
 const claims = state.sources.flatMap(row=>row.claims);
 const located = claims.filter(row=>row.locator).length;
 const evaluated = claims.filter(row=>wikiS1Check(row)!=='unchecked').length;
 const included = state.sources.filter(row=>row.decision?.status==='include').length;
 const count = (amount,total) => index ? `<strong>${amount}</strong>${total !== undefined ? ' / '+total : ''}` : '<strong class="wiki-s1-none">还没有</strong>';
 const cells = [
  [count(included,state.sources.length),'来源已纳入','分母是这份交付的文献数','工程记录'],
  [count(located),'条证据定位','有保存出处位置的证据条目','工程记录'],
  [count(evaluated,claims.length),'证据已核对','核对后才能当作研究依据','研究结果'],
  [count(state.groups.length),'个需求分组','一篇文献可以属于多个分组','工程记录']
 ];
 return `<div class="wiki-s1-metrics">${cells.map(([value,title,note,tag])=>`<div><div>${value} <b>${title}</b></div><small>${note}</small><span class="${tag==='研究结果'?'wiki-s1-res':''}">${tag}</span></div>`).join('')}</div>`;
}

function wikiS1PaperMeta(row) {
 return [row.paper.year,row.paper.venue].filter(value=>value && !/^unknown/i.test(String(value))).map(esc).join(' · ');
}

function wikiS1SourceList(state) {
 const group = state.groups.find(row=>row.id===state.group);
 const sources = wikiS1VisibleSources(state);
 const counts = Object.entries(wikiS1Decisions).map(([key,label]) =>
  [label,sources.filter(row=>(row.decision?.status || 'missing')===key).length]);
 return `<div class="wiki-s1-chips" role="group" aria-label="按需求分组筛选">
 <button type="button" data-s1-group="" aria-pressed="${!group}">全部 ${state.sources.length}</button>
 ${state.groups.map(row=>`<button type="button" data-s1-group="${esc(row.id)}" title="${esc(row.question || row.title)}" aria-pressed="${row===group}"><i style="--s1-color:${row.color}"></i>${esc(row.title)} ${row.works.size}</button>`).join('')}
 </div><p class="wiki-s1-muted">筛选结果 · ${counts.filter(([label,count])=>label!=='未提供'||count).map(([label,count])=>label+' '+count).join(' · ')}（共 ${sources.length} 篇）</p>
 <div class="wiki-s1-list" ${sources.length>=30?'data-s1-long-list':''}>${sources.map(row=>`<button type="button" data-s1-paper="${esc(row.paper.work_id)}" aria-pressed="${row.paper.work_id===state.selected}">
 <span class="wiki-s1-muted">${row.number}</span><span><strong>${esc(row.paper.title)}</strong><small>${wikiS1PaperMeta(row)} ${row.groups.map(g=>`<span><i style="--s1-color:${g.color}"></i>${esc(g.title)}</span>`).join(' ')} · ${row.claims.length} 条证据</small></span>
 <span class="wiki-s1-decision">${wikiS1Decisions[row.decision?.status] || wikiS1Decisions.missing}</span></button>`).join('') || '<p>这个分组没有来源。</p>'}</div>`;
}

function wikiS1Selected(state) {
 const row = wikiS1VisibleSources(state).find(item=>item.paper.work_id===state.selected);
 if (!row) return '<p>当前分组没有可查看的来源。</p>';
 return `<article class="wiki-s1-selection"><small>已选中 · 来源 ${row.number}</small><h3>${esc(row.paper.title)}</h3>
 <p>${wikiS1PaperMeta(row)}</p><button type="button" class="hs-button" data-s1-tab="evidence">看这篇的证据</button></article>`;
}

// DESIGN 2.5「平面视图提示」, 3.2: shown only while the view was switched to 2D automatically, on every repaint.
const wikiS1FlatText = '已切换到平面视图。这台电脑显示 3D 不够流畅。内容和选中的论文都没有变。';
function wikiS1FlatNotice(state) {
 if (state.graphLost) return '<div class="wiki-s1-fallback" data-s1-fallback role="status">图形没有加载出来；可以用左边的来源清单，内容没有变。</div>';
 if (!state.auto2d) return '<div class="wiki-s1-fallback" data-s1-fallback role="status" hidden></div>';
 return `<div class="wiki-s1-fallback" data-s1-fallback role="status"><span>${wikiS1FlatText}${state.no3d ? '这台电脑现在打不开 3D。' : ''}</span><button type="button" class="hs-button" data-s1-keep3d>仍然用 3D</button></div>`;
}
function wikiS1Keep3d() { try { return sessionStorage.getItem('wiki-s1-keep3d') === '1'; } catch (_) { return false; } }
function wikiS1AutoFlat(app, graph) {
 const state = app.wikiS1;
 if (!graph || state.mode !== 2) { try { graph?.setMode(2); } catch (_) { return; } }
 state.mode = 2; state.auto2d = true; state.autoDone = true;
 for (const button of app.el.querySelectorAll('[data-s1-mode]')) button.setAttribute('aria-pressed', String(Number(button.dataset.s1Mode) === 2));
 const note = app.el.querySelector('[data-s1-fallback]');
 if (note) note.outerHTML = wikiS1FlatNotice(state);
}
// About 2 s of 3D below 20 frames per second (after the layout settles) switches to 2D once (5.2 第二批 降级).
function wikiS1WatchFrames(app, graph) {
 const state = app.wikiS1;
 if (state.autoDone || state.mode !== 3 || wikiS1Keep3d()) return;
 const key = app.v7SpatialKey;
 setTimeout(() => {
  if (app.v7Spatial !== graph || app.v7SpatialKey !== key || state.mode !== 3 || state.autoDone || document.visibilityState !== 'visible') return;
  let frames = 0;
  const start = performance.now();
  const tick = now => {
   if (app.v7Spatial !== graph || state.mode !== 3 || document.visibilityState !== 'visible') return;
   frames++;
   if (now - start < 2000) { requestAnimationFrame(tick); return; }
   if (frames / ((now - start) / 1000) < 20 && !wikiS1Keep3d()) wikiS1AutoFlat(app, graph);
  };
  requestAnimationFrame(tick);
 }, 1500);
}

function wikiS1Graph(state) {
 return `<section class="wiki-s1-card wiki-s1-graph"><h2>文献星图</h2>
 <div class="wiki-s1-tools">
 <div role="group" aria-label="星图维度">${[3,2].map(mode=>`<button type="button" data-s1-mode="${mode}" aria-pressed="${state.mode===mode}">${mode}D</button>`).join('')}</div>
 <button type="button" data-s1-graph="all">查看全图</button><button type="button" data-s1-graph="focus">聚焦所选</button>
 <label><input type="checkbox" data-s1-labels ${state.labels?'checked':''}>显示标签</label>
 <details data-s1-more ${state.more?'open':''}><summary>更多</summary><div>
  <button type="button" data-s1-graph="fit">适应窗口</button><button type="button" data-s1-graph="expand">展开画布</button>
  <label><input type="checkbox" data-s1-related ${state.related?'checked':''}>显示相似线</label>
  <p class="wiki-s1-muted">节点按需求分组着色。核对状态可在证据页查看。</p>
  <p class="wiki-s1-muted">Tab 进入节点，Enter 或空格选中。拖动旋转或平移，滚轮缩放。</p>
 </div></details>
 </div>${wikiS1FlatNotice(state)}
 <div class="wiki-s1-atlas" data-wiki-s1-atlas></div>
 <p class="wiki-s1-muted">颜色表示分组。相似线来自相同的已保存需求，距离不表示证据强弱。</p>
 <div data-s1-selected>${wikiS1Selected(state)}</div></section>`;
}

function wikiS1Evidence(index, state) {
 const row = wikiS1VisibleSources(state).find(item=>item.paper.work_id===state.selected);
 if (!row) return '<section class="wiki-s1-card"><h2>证据</h2><p>当前分组没有可查看的来源。</p></section>';
 if (!row.claims.length) return '<section class="wiki-s1-card"><h2>证据</h2><p>这篇文献还没有保存的证据。</p></section>';
 const sourceById = new Map((index.sources || []).map(source=>[source.source_id,source]));
 const claims = row.claims.filter(claim=>state.check==='all'||wikiS1Check(claim)===state.check);
 return `<section class="wiki-s1-card"><h2>证据 · ${esc(row.paper.title)}</h2>
 <p class="wiki-s1-muted">${wikiS1PaperMeta(row)} · ${row.claims.length} 条保存证据 <button type="button" class="hs-button" data-s1-tab="sources">换一篇</button></p>
 <div class="wiki-s1-chips" role="group" aria-label="按核对状态筛选">${Object.entries(wikiS1Checks).map(([key,label])=>`<button type="button" data-s1-check="${key}" aria-pressed="${key===state.check}">${label} ${key==='all'?row.claims.length:row.claims.filter(claim=>wikiS1Check(claim)===key).length} / ${row.claims.length}</button>`).join('')}</div>
 ${claims.map(claim=>{
  const check = wikiS1Check(claim), verifier = claim.core_event?.payload?.verifier;
  const located = Number.isSafeInteger(claim.start) && Number.isSafeInteger(claim.end) && claim.start < claim.end;
  const savedSource = sourceById.get(claim.source_id);
  let url;
  if (located && claim.source_id && savedSource?.work_id===claim.work_id && savedSource.version_id===claim.version_id) {
   try {
    const parsed = new URL(savedSource.receipt?.final_url || savedSource.receipt?.source_url || savedSource.source_url);
    if (['http:','https:'].includes(parsed.protocol)) url = parsed.href;
   } catch (_) { /* Missing or invalid bound source URL. */ }
  }
  return `<article class="wiki-s1-claim" data-s1-claim>
   <div><b data-s1-review="${check}">${wikiS1Checks[check]}</b><p class="wiki-s1-muted">${check==='unchecked'?'没有保存的人工核对结论':'记录标明由人工核对'}${verifier?.actor_type==='agent'?' · 有代理记录':''}</p></div>
   <div><strong>${esc(claim.text || '主张未提供')}</strong><blockquote>${esc(claim.quote || '引文原文未提供')}</blockquote>
   ${wikiS1Relations[claim.relation] ? `<small>保存时标注为：${wikiS1Relations[claim.relation]}</small>` : ''}</div>
   <div><b>出处位置</b><p>${located ? '保存文本第 '+claim.start+'–'+claim.end+' 字符' : '出处位置未提供'}</p>
   ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开原文网页</a>` : '<small>原文链接未提供</small>'}
   <details><summary>查看原记录</summary><pre class="live-record">${esc(JSON.stringify(claim,null,2))}</pre></details></div>
  </article>`;
 }).join('') || '<p role="status">这一类没有记录。</p>'}</section>`;
}

function wikiS1Synthesis(state) {
 return `<div class="wiki-s1-columns wiki-s1-synthesis"><section class="wiki-s1-card"><h2>每个需求有多少文献</h2>
 <p class="wiki-s1-muted">一篇文献可以属于多个需求。</p>
 ${state.groups.length ? state.groups.map(group=>`<div class="wiki-s1-bar"><span>${esc(group.title)}</span>
 <progress max="${state.sources.length || 1}" value="${group.works.size}" aria-label="${esc(group.title)}" style="--s1-color:${group.color}"></progress><small>${group.works.size} / ${state.sources.length}</small></div>`).join('') : '<p>需求分组未提供。</p>'}
 </section><section class="wiki-s1-card"><h2>文献合起来说明了什么</h2><p class="wiki-s1-muted">当前交付没有跨文献综合记录。</p>
 <div class="wiki-s1-synthesis-grid">${['多篇一致','互相矛盾','还没人做'].map(title=>`<section><h3>${title}</h3><p>未提供</p></section>`).join('')}</div></section></div>`;
}

function wikiS1Results(app) {
 const index = wikiS1Index();
 const state = wikiS1State(app,index);
 let panel = '<section class="wiki-s1-card"><h2>文献与证据</h2><p>当前项目还没有可读取的文献交付。</p></section>';
 if (index) {
  if (state.tab==='evidence') panel = wikiS1Evidence(index,state);
  else if (state.tab==='synthesis') panel = wikiS1Synthesis(state);
  else panel = `<div class="wiki-s1-columns"><section class="wiki-s1-card"><h2>来源清单</h2><div data-s1-list>${wikiS1SourceList(state)}</div></section>${state.sources.length?wikiS1Graph(state):'<section class="wiki-s1-card"><h2>文献星图</h2><p>这一份交付没有可绘制的文献。</p></section>'}</div>`;
 }
 return `<section data-wiki-s1 aria-label="文献与证据结果">
 ${wikiS1Metrics(index,index?state:{sources:[],groups:[]})}
 <div class="wiki-s1-tabs" role="tablist" aria-label="文献与证据">${Object.entries(wikiS1Tabs).map(([key,label])=>`<button type="button" role="tab" id="wiki-s1-${key}" aria-selected="${key===state.tab}" tabindex="${key===state.tab?0:-1}" aria-controls="wiki-s1-panel" data-s1-tab="${key}">${label}</button>`).join('')}</div>
 <div role="tabpanel" id="wiki-s1-panel" aria-labelledby="wiki-s1-${state.tab}">${panel}</div>
 </section>`;
}

function wikiS1LiveResults(app) {
 // Keep the original results target so live operations can still insert their controls.
 const results=wikiS1Results(app);
 return results+`<details class="lp-results" data-local-results="1" data-wiki-s1-output ${app.wikiS1.outputs?'open':''}><summary><strong>保存输出与文献审阅</strong></summary><div class="lp-result-body">${liveFiles()}</div></details>`;
}

const wikiS1CanonicalResults = canonicalStage1Results;
canonicalStage1Results = app => wikiS1Active(app) ? wikiS1Results(app) : wikiS1CanonicalResults(app);

function wikiS1Select(app, key, fromGraph=false) {
 const state = app.wikiS1;
 const row = state.sources.find(item=>item.paper.work_id===key);
 if (!row) return;
 state.selected = key;
 state.focus = {kind:'paper',key};
 if (state.group && !row.groups.some(group=>group.id===state.group)) state.group = '';
 state.check = 'all';
 app.v7Spatial?.setFocus(state.focus);
 const list = app.el.querySelector('[data-s1-list]');
 if (!list) return;
 const scroll = list.querySelector('.wiki-s1-list')?.scrollTop || 0;
 list.innerHTML = wikiS1SourceList(state);
 const selected = list.querySelector('[data-s1-paper][aria-pressed="true"]');
 const scroller = list.querySelector('.wiki-s1-list');
 if (fromGraph && selected && scroller.hasAttribute('data-s1-long-list')) scroller.scrollTop = selected.offsetTop - scroller.offsetTop;
 else scroller.scrollTop = scroll;
 if (!fromGraph) selected?.focus({preventScroll:true});
 app.el.querySelector('[data-s1-selected]').innerHTML = wikiS1Selected(state);
}

function wikiS1MountAtlas(app, host) {
 const state = app.wikiS1;
 const papers = state.sources.map(({paper,groups})=>{
  const topics=groups.map(group=>group.title), raw=paper.classification?.method;
  const methods=(Array.isArray(raw)?raw:[raw]).filter(value=>typeof value==='string'&&value.trim()&&!/^unknown/i.test(value));
  return {...paper,key:paper.work_id,topics,coverage_topics:topics,methods};
 });
 const topicColors = Object.fromEntries(state.groups.map(group=>[group.title,group.color]));
 const paperAliases = Object.fromEntries(state.sources.map(row=>[row.paper.work_id,String(row.number)]));
 const note = app.el.querySelector('[data-s1-fallback]');
 const mount = mode => AtlasSpatial.mount(host,{papers,model:AtlasModel,three:window.V7Three,theme:'dark',
   mode,topicColors,paperAliases,showLabels:state.labels,focus:state.focus || null,
   extraLinks:state.related?liveSharedNeedLinks(papers):[],language:'zh-Hans',
   onSelect:selection=>{
    if (selection.kind==='paper') wikiS1Select(app,selection.key,true);
    else if (selection.kind==='topic') {
     const group=state.groups.find(row=>row.title===selection.key);
     if (group) wikiS1Filter(app,group.id);
    }
   }});
 let graph;
 try { graph = mount(state.mode); }
 catch (error) {
  host.dataset.wikiS1GraphError = String(error.message);
  if (state.mode===3) {
   try {
    graph=mount(2);
    state.no3d=true;
    wikiS1AutoFlat(app,graph);
   } catch (_) { /* The native flat view may also require graphics support. */ }
  }
  if (!graph) {
   state.graphLost=true;
   if (note) note.outerHTML=wikiS1FlatNotice(state);
   host.hidden=true;
  }
 }
 app.v7SpatialKey=v7Key(app);
 app.v7Spatial=graph;
 host.v7Diagnostics=()=>graph?.diagnostics();
 for (const button of app.el.querySelectorAll('[data-s1-graph],[data-s1-labels],[data-s1-related]')) button.disabled=!graph;
 wikiS1WatchFrames(app,graph);
}

function wikiS1SetMode(app,mode,graph=app.v7Spatial) {
 if (!graph) return;
 graph.setMode(mode);
 app.wikiS1.mode=mode;
 for (const button of app.el.querySelectorAll('[data-s1-mode]')) button.setAttribute('aria-pressed',String(Number(button.dataset.s1Mode)===mode));
}

function wikiS1Filter(app, id) {
 const state=app.wikiS1, group=state.groups.find(row=>row.id===id);
 const previous=state.selected;
 state.group=group?.id || '';
 wikiS1SyncSelection(state);
 if (state.selected && state.selected===previous) {
  state.focus=group ? {kind:'topic',key:group.title} : {kind:'paper',key:state.selected};
 }
 app.v7Spatial?.setFocus(state.focus);
 const list=app.el.querySelector('[data-s1-list]');
 list.innerHTML=wikiS1SourceList(state);
 app.el.querySelector('[data-s1-selected]').innerHTML=wikiS1Selected(state);
 [...list.querySelectorAll('[data-s1-group]')].find(button=>button.dataset.s1Group===state.group)?.focus({preventScroll:true});
}

const wikiS1After = v7AfterRender;
v7AfterRender = function(app) {
 wikiS1After(app);
 const panel=app.el.querySelector('[data-wiki-s1]'), shell=app.el.querySelector('[data-wiki-shell]');
 if (!panel || !shell || !wikiS1Active(app)) return;
 const badge=app.el.querySelector('.hs-preview');
 if (badge) badge.textContent='Wiki V1 · 本地记录';
 if (!shell.nextElementSibling?.matches('[data-wiki-record]')) {
  shell.insertAdjacentHTML('afterend',wikiHarnessRecord(typeof v1S1Record==='function'?v1S1Record():undefined));
  shell.nextElementSibling.after(panel);
  const heading=app.el.querySelector('.hs-heading');
  if (heading?.querySelector('h1')) {
   const topic = rt.overview?.project?.brief?.original_description || rt.savedRun?.entry?.label;
   heading.querySelector('.hs-eyebrow').textContent='Stage 1 · 文献与证据';
   heading.querySelector('h1').textContent=topic || '文献与证据';
   if (topic && heading.querySelector('h1 + p')?.textContent===topic) heading.querySelector('h1 + p').remove();
  }
  const index=wikiS1Index();
  const info=shell.querySelectorAll('dd');
  if (index && shell.dataset.shellState==='saved') {
   info[0].textContent += `。已保存 ${index.papers.length} 篇文献、${index.claims.length} 条证据。`;
  }
  const project=rt.overview?.project;
  if ((project?.project_ref===rt.ref && project?.execution_authorized===false) || wikiHomeArchiveBound(rt.ref)) {
   info[2].textContent += '。当前没有研究执行授权。';
  }
  const chooser=app.el.querySelector('.lp-topic,.canonical-project-switch');
  if (chooser && rt.ref) {
   const details=document.createElement('details');
   details.className='hs-panel wiki-s1-project';
   details.innerHTML='<summary>切换项目</summary>';
   chooser.before(details);
   details.append(chooser);
   panel.after(details);
  }
 }
 const host=panel.querySelector('[data-wiki-s1-atlas]');
 if (host && !host.v7Diagnostics) wikiS1MountAtlas(app,host);
};

function wikiS1ChangeTab(app, tab, focus=true) {
 app.wikiS1.tab=tab;
 livePaint();
 if (focus) app.el.querySelector('#wiki-s1-'+tab)?.focus({preventScroll:true});
}

document.addEventListener('click',event=>{
 const button=event.target.closest('[data-s1-tab],[data-s1-group],[data-s1-paper],[data-s1-mode],[data-s1-check],[data-s1-graph],[data-s1-keep3d]');
 const app=apps[0], state=app.wikiS1;
 if (!button || button.disabled || !state || !button.closest('[data-wiki-s1]')) return;
 const data=button.dataset;
 if (data.s1Tab) wikiS1ChangeTab(app,data.s1Tab);
 else if (data.s1Group!==undefined) wikiS1Filter(app,data.s1Group);
 else if (data.s1Paper) wikiS1Select(app,data.s1Paper);
 else if (data.s1Check) {
  state.check=data.s1Check;livePaint();
  app.el.querySelector('[data-s1-check][aria-pressed="true"]')?.focus({preventScroll:true});
 } else if (data.s1Mode) {
  // A manual choice is the user's; the automatic notice goes away and does not come back this time.
  state.auto2d=false; state.autoDone=true;
  if (app.v7Spatial) { wikiS1SetMode(app,Number(data.s1Mode)); app.el.querySelector('[data-s1-fallback]').hidden=true; }
  else { state.mode=Number(data.s1Mode);livePaint(); }
 } else if (data.s1Keep3d!==undefined) {
  try { sessionStorage.setItem('wiki-s1-keep3d','1'); } catch (_) { /* Session preference only. */ }
  try {
   if (!app.v7Spatial) throw Error('no-graph');
   wikiS1SetMode(app,3); state.auto2d=false; state.no3d=false;
   app.el.querySelector('[data-s1-fallback]').outerHTML=wikiS1FlatNotice(state);
  } catch (_) { state.no3d=true; app.el.querySelector('[data-s1-fallback]').outerHTML=wikiS1FlatNotice(state); }
 } else if (data.s1Graph==='focus') {
  if (state.selected) app.v7Spatial?.setFocus({kind:'paper',key:state.selected});
  app.v7Spatial?.fitFocus();
 } else if (data.s1Graph==='expand') {
  app.el.querySelector('[data-spatial-navigation="expand"]')?.click();
 } else {
  if (data.s1Graph==='all') { state.focus=null;app.v7Spatial?.setFocus(null); }
  app.v7Spatial?.fit();
 }
});

document.addEventListener('change',event=>{
 const app=apps[0], state=app.wikiS1;
 if (event.target.matches('[data-s1-labels]')) { state.labels=event.target.checked;app.v7Spatial?.setLabels(state.labels); }
 if (event.target.matches('[data-s1-related]')) { state.related=event.target.checked;livePaint(); }
});
document.addEventListener('toggle',event=>{
 if (!event.target.isConnected) return;
 if (event.target.matches('[data-s1-more]') && event.target.isConnected) apps[0].wikiS1.more=event.target.open;
 if (event.target.matches('[data-wiki-s1-output]')) apps[0].wikiS1.outputs=event.target.open;
},true);
document.addEventListener('keydown',event=>{
 const tab=event.target.closest('[role="tab"][data-s1-tab]');
 if (!tab || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
 const keys=Object.keys(wikiS1Tabs), index=keys.indexOf(tab.dataset.s1Tab);
 const next=event.key==='Home'?0:event.key==='End'?keys.length-1:
  (index+(event.key==='ArrowRight'?1:keys.length-1))%keys.length;
 event.preventDefault();
 wikiS1ChangeTab(apps[0],keys[next]);
});
apps[0].wikiS1Enabled = true;
