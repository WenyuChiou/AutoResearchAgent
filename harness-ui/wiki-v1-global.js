// Wiki V1 global pages (DESIGN 8.1, 8.2, 8.5, 8.22): 项目文件、操作历史、连接与设置, Simplified Chinese only.
// Read only. The pages show what the page already read (rt.atlas, rt.history, rt.overview, rt.meta); the only
// requests here are GETs of a delivery file the user asks to open or download (the existing file endpoint).
// The previous page content stays in the document for its handlers and is hidden by wiki-v1.css.
const v1gStageName = {1:'文献与证据', 2:'比较与选方向', 3:'研究计划与评审'};
const v1gGuideKey = 'wiki-v1-guide-closed';

function v1gOn(app) { return typeof v1On === 'function' && v1On(app) && ['files', 'history', 'settings'].includes(app.page); }

function v1gTime(value) {
 const at = typeof value === 'string' ? new Date(value) : null;
 if (!at || Number.isNaN(at.getTime())) return '未提供';
 const two = n => String(n).padStart(2, '0');
 return `${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}
function v1gTag(tone, text) { return `<span class="v1-st s-${tone}">${esc(text)}</span>`; }
function v1gHead(title, sub) {
 return `<div class="v1-head" data-v1-head><p class="v1-eyebrow">全局页</p><h1>${title}</h1><p class="v1-sub">${sub}</p></div>`;
}
function v1gTech(rows, open, flash) {
 const shown = rows.filter(([, value]) => value !== undefined && value !== null && value !== '');
 return `<details class="v1-tech" data-v1g-tech ${open ? 'open' : ''}><summary>本页技术细节</summary><dl>${shown.map(([key, value, id]) => `<dt class="${id && id === flash ? 'flash' : ''}" ${id ? `data-v1g-raw-row="${esc(id)}"` : ''}>${esc(key)}</dt><dd class="${id && id === flash ? 'flash' : ''}"><code>${esc(typeof value === 'string' ? value : JSON.stringify(value))}</code></dd>`).join('') || '<dt>记录</dt><dd>还没有读取到</dd>'}</dl></details>`;
}

// The five states of 8.1, shared by the three pages. Returns markup for the page body when not "success".
function v1gState(app, empty) {
 const reload = '<button type="button" class="v1-btn sm" data-v1-reload>重新读取</button>';
 if (!rt.ref) return `<p class="v1-empty">还没有打开课题。先在首页打开或新建一个课题，这里才会有内容。 <button type="button" class="v1-link" data-v1-home>去首页</button></p>`;
 const p = rt.overview?.project;
 const archive = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref);
 if (p && p.project_ref !== rt.ref) return `<div class="v1-alert warn" role="status"><div><b>当前课题和${app.page === 'settings' ? '连接记录' : app.page === 'history' ? '操作记录' : '文件记录'}不一致，已拒绝显示。</b><span>重新读取当前课题后再看；不会沿用别的课题的内容。</span></div>${reload}</div>`;
 if (!p && !archive && rt.loading) return '<p class="v1-empty v1-muted" role="status">正在读取保存记录</p>';
 if (!p && !archive && rt.error) return `<div class="v1-alert err" role="alert"><div><b>读取失败。</b><span>已经读到的内容没有丢；原因在本页技术细节里。</span></div>${reload}</div>`;
 if (!p && !archive) return `<p class="v1-empty">${empty} ${reload}</p>`;
 return '';
}
function v1gErrorBar() {
 return rt.error && (rt.overview || rt.savedRun) ? `<div class="v1-alert err" role="alert"><div><b>读取失败。</b><span>下面是上次读到的内容；原因在本页技术细节里。</span></div><button type="button" class="v1-btn sm" data-v1-reload>重新读取</button></div>` : '';
}

// ---------------- 项目文件 (8.1) ----------------
// The service has no unified file list yet (8.1 needs a backend list). Shown: the delivery files the Stage 1
// package already lists (BibTeX and per-paper notes, with checksums) and, for archives, the parts of the saved view.
function v1gFiles() {
 const archive = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref);
 const p = rt.overview?.project;
 const version = archive ? '归档' : p ? 'v' + p.input_version : '未提供';
 const origin = typeof v1CurrentRow === 'function' ? v1CurrentRow()?.origin || 'unknown' : 'unknown';
 const originTag = `<span class="v1-origin ${origin}">${v1OriginNames[origin]}</span>`;
 const rows = [];
 if (archive) {
  const index = rt.savedRun?.payload?.index || {};
  const notes = rt.savedRun?.payload?.note_paths;
  if (Array.isArray(index.papers)) rows.push({id:'papers', name:'论文目录', count:`${index.papers.length} 篇`, stage:1, preview:'papers'});
  if (index.bibliography) rows.push({id:'bib', name:'参考文献 BibTeX', count:'', stage:1, preview:'bib'});
  if (notes && typeof notes === 'object') rows.push({id:'notes', name:'逐篇笔记', count:`${Object.keys(notes).length} 篇`, stage:1, preview:'notes'});
  if (rt.savedRun?.payload?.stage2) rows.push({id:'stage2', name:'Stage 2 候选包', count:'', stage:2, preview:'stage2'});
 } else {
  const files = Array.isArray(rt.atlas?.files) ? rt.atlas.files : [];
  if (rt.atlas?.payload?.index?.papers) rows.push({id:'papers', name:'论文目录', count:`${rt.atlas.payload.index.papers.length} 篇`, stage:1, preview:'papers'});
  let note = 0;
  files.forEach((file, i) => {
   const md = /\.md$/.test(file.path || '');
   rows.push({id:'f' + i, index:i, name:md ? `逐篇笔记 ${++note}` : '参考文献 BibTeX', count:'', stage:1, file});
  });
 }
 const state = v1gState(apps[0], '这个课题还没有保存的文件。第一段交付后这里会出现文献图谱、论文目录、笔记和 BibTeX。');
 const open = apps[0].v1gOpen;
 const body = state || (!rows.length ? '<p class="v1-empty">这个课题还没有保存的文件。第一段交付后这里会出现文献图谱、论文目录、笔记和 BibTeX。</p>' : `<div class="v1-files-wrap">
  <div class="v1-table-wrap"><table class="v1-table v1-files"><thead><tr><th scope="col">文件</th><th scope="col">属于哪一段</th><th scope="col">版本</th><th scope="col">来历</th><th scope="col">保存时间</th><th scope="col"><span class="v1-vh">操作</span></th></tr></thead><tbody>
  ${rows.map(row => {
   const bad = row.file && apps[0].v1gBad?.[row.file.sha256];
   const failed = row.file ? v1gFileFailure(row.file) : null;
   const downloadWhy = bad ? '保存的文件和记录不一致，不能下载' : !row.file ? (archive ? '归档没有随附这份原件，只能在页面里看' : '后台还没有这份文件的原件下载接口') : '';
   return `<tr class="${open === row.id ? 'sel' : ''}"><th scope="row"><b>${esc(row.name)}</b>${row.count ? `<small>${esc(row.count)}</small>` : ''}${archive ? '<small>只读</small>' : ''}</th><td>Stage ${row.stage}</td><td class="n">${esc(version)}</td><td>${originTag}</td><td class="n">未提供</td>
    <td class="acts"><button type="button" class="v1-btn sm" data-v1g-open="${esc(row.id)}" ${row.file ? `data-v1g-file="${row.index}"` : ''}>打开</button><button type="button" class="v1-btn sm" ${row.file ? `data-v1g-download="${row.index}"` : ''} ${downloadWhy ? 'disabled' : ''}>下载</button>${downloadWhy ? `<small class="v1-reason">${downloadWhy}</small>` : ''}${failed ? `<small class="v1-reason" role="status">${failed.download ? '这次没有下载成功' : '这次没有读出来'}，可以再试一次</small><details class="v1-env-raw"><summary>技术细节</summary><code>${esc(failed.code)}</code></details>` : ''}</td></tr>`;
  }).join('')}</tbody></table></div>${open ? v1gPreview(rows.find(row => row.id === open)) : ''}</div>`);
 const tech = [['项目标识', rt.ref], ['输入版本', p?.input_version], ['保存次数（revision）', p?.revision], ['文献包清单校验值', rt.atlas?.manifest_sha256 || rt.savedRun?.binding?.manifest_sha256],
  ...rows.filter(row => row.file).map(row => [row.file.path, row.file.sha256])];
 return `${v1gHead('项目文件', '这个课题已保存的文件，每份带版本。下载的是原件，不做转换。')}${v1gErrorBar()}${body}
  <p class="v1-hint">后台还没有统一的文件清单，这里先列出页面已能读到的交付文件（文献包里的 BibTeX 和逐篇笔记、论文目录）。Stage 2 的候选包、Stage 3 的规划交付后也会出现在这里。历史归档课题的文件标「只读」。</p>
  ${v1gTech(tech)}`;
}
function v1gPreview(row) {
 if (!row) return '';
 let text = '', meta = '';
 const index = rt.savedRun?.payload?.index || rt.atlas?.payload?.index || {};
 if (row.file) {
  const file = rt.file?.file_ref === row.file.file_ref ? rt.file : null;
  const failed = v1gFileFailure(row.file);
  text = file ? file.content : apps[0].v1gLoading === row.file.file_ref ? '正在读取这份文件…' : failed?.download ? '刚才下载没有成功；保存的文件没有变，可以再点一次「下载」。' : failed ? '这份文件这次没有读出来；保存的文件没有变，可以再点一次「打开」。' : '这份文件还没有读出来。';
  meta = `${row.file.path} · ${row.file.mime === 'application/x-bibtex' ? 'BibTeX' : 'Markdown'} 文本`;
 } else if (row.preview === 'papers') {
  text = (index.papers || []).map((paper, i) => `${i + 1}. ${paper.title || '标题未提供'}${paper.year ? '（' + paper.year + '）' : ''}`).join('\n');
  meta = `${(index.papers || []).length} 篇；按保存顺序`;
 } else if (row.preview === 'bib') {
  const bib = index.bibliography;
  text = typeof bib === 'string' ? bib : JSON.stringify(bib, null, 2);
  meta = '保存的书目记录';
 } else {
  meta = '这份内容不是文本文件，只显示元信息。';
  text = row.preview === 'notes' ? `${row.count}的笔记位置已保存；笔记正文在 Stage 1 页每篇论文的小卡里看。` : '候选包的内容在 Stage 2 页看。';
 }
 return `<aside class="v1-preview" data-v1g-preview aria-label="文件预览"><div class="v1-preview-head"><b>${esc(row.name)}</b><button type="button" class="v1-link" data-v1g-close>关闭预览</button></div><small>${esc(meta)} · 只读</small><pre>${esc(String(text).slice(0, 200000))}</pre></aside>`;
}
function v1gFileFailure(file) {
 const e = apps[0].v1gFileError;
 return e && e.ref === rt.ref && file && e.file === file.file_ref ? e : null;
}
async function v1gSha(text) {
 return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function v1gReadFile(index) {
 const f = rt.atlas?.files?.[index], path = typeof liveAtlasPath === 'function' ? liveAtlasPath() : null;
 if (!f || !path) throw Error('file-unavailable');
 const ref = rt.ref, epoch = rt.epoch;
 const value = await liveRequest(path + `/files/${f.file_ref}/${f.sha256}`);
 if (ref !== rt.ref || epoch !== rt.epoch) throw Error('project-changed');
 return {f, file:value.file};
}
document.addEventListener('click', async event => {
 const app = apps[0];
 if (!v1gOn(app)) return;
 const button = event.target.closest('[data-v1g-open],[data-v1g-download],[data-v1g-close],[data-v1g-raw],[data-v1g-filter],[data-v1g-guide]');
 if (!button || button.disabled || !app.el.contains(button)) return;
 event.preventDefault();
 event.stopImmediatePropagation();
 const data = button.dataset;
 if (data.v1gClose !== undefined) { app.v1gOpen = null; livePaint(); return; }
 if (data.v1gFilter) { app.v1gFilter = data.v1gFilter; livePaint(); return; }
 if (data.v1gRaw) { app.v1gRaw = data.v1gRaw; livePaint(); requestAnimationFrame(() => app.el.querySelector('[data-v1g-tech] .flash')?.scrollIntoView({block:'center'})); return; }
 if (data.v1gGuide !== undefined) {
  try { localStorage.removeItem(v1gGuideKey); } catch (_) { /* Browser storage may be off. */ }
  app.v1gGuideShown = true; livePaint(); return;
 }
 if (data.v1gOpen) {
  app.v1gOpen = data.v1gOpen;
  if (data.v1gFile !== undefined) {
   const f = rt.atlas?.files?.[Number(data.v1gFile)];
   app.v1gLoading = f?.file_ref; livePaint();
   // A failed file read stays on this page (review P2-2): writing it to rt.error made the home page refuse to open topics.
   try { const {file} = await v1gReadFile(Number(data.v1gFile)); rt.file = file; app.v1gFileError = null; }
   catch (error) { app.v1gFileError = {ref:rt.ref, file:f?.file_ref, code:error.message}; }
   app.v1gLoading = null;
  }
  livePaint(); return;
 }
 if (data.v1gDownload !== undefined) {
  // Download the exact saved text after checking it against the recorded checksum; no conversion.
  try {
   const {f, file} = await v1gReadFile(Number(data.v1gDownload));
   if (file.sha256 !== f.sha256 || await v1gSha(file.content) !== f.sha256) { (app.v1gBad ||= {})[f.sha256] = true; livePaint(); return; }
   const dot = file.filename.lastIndexOf('.'), version = rt.overview?.project?.input_version;
   const name = dot > 0 ? `${file.filename.slice(0, dot)}-v${version}${file.filename.slice(dot)}` : `${file.filename}-v${version}`;
   const blob = new Blob([file.content], {type:f.mime || 'text/plain'}), url = URL.createObjectURL(blob), a = document.createElement('a');
   a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
   // A later success clears this file's earlier failure note (review P2-a).
   if (v1gFileFailure(f)) { app.v1gFileError = null; livePaint(); }
  } catch (error) {
   const f = rt.atlas?.files?.[Number(data.v1gDownload)];
   app.v1gFileError = {ref:rt.ref, file:f?.file_ref, code:error.message, download:true}; livePaint();
  }
 }
}, true);

// ---------------- 操作历史 (8.1) ----------------
// Only the project's saved action history (GET /history) is readable now; a unified timeline needs the backend.
const v1gKinds = {
 create:['新建了课题', 0], submit:['保存了范围', 1], compile:['生成检索规划', 1], 'model-authorization':['授权了一次模型调用', 1], 'model-operation':['请求了一次模型调用', 1],
 'model-retirement':['结束了一条模型记录', 1], 'stage1-source-authorize':['授权了一次来源获取', 1], 'stage1-source-execute':['执行了一次来源获取', 1],
 'stage1-source-recover-owner':['恢复了来源获取', 1], 'stage1-reading-registry':['保存了阅读审阅', 1], 'stage1-claim':['保存了证据审阅', 1],
 'stage1-produce-records':['生成了 Stage 1 交付', 1], 'stage2-activate':['启用了本课题的 Stage 2', 2], 'stage1-screening':['保存了筛选决定', 1],
 'stage1-coverage':['保存了覆盖决定', 1], 'stage1-checkpoint':['做了一次交付检查', 1], 'stage1-expansion-authorize':['授权了一次引用扩展', 1], 'stage1-expansion-execute':['执行了一次引用扩展', 1]
};
function v1gResult(row) {
 if (row.status === 'saved' || row.status === 'completed' || row.status === 'result-observed') return ['done', '成功'];
 if (row.status === 'known-unsent' || row.replayed === true) return ['block', '被拦下'];
 if (row.status === 'failed') return ['err', '出错'];
 return ['block', '结果未确认'];
}
function v1gHistory() {
 const app = apps[0];
 const actions = rt.history?.project_ref === rt.ref && Array.isArray(rt.history.actions) ? rt.history.actions : [];
 const rows = actions.map(row => {
  const [what, stage] = v1gKinds[row.kind] || ['做了一次操作（' + (row.kind ? '类型见原始记录' : '类型未提供') + '）', null];
  const [tone, result] = v1gResult(row);
  return {id:row.key || row.request_sha256 || String(row.recorded_at), at:row.recorded_at, time:v1gTime(row.recorded_at), stage, what, who:'你', tone, result, raw:row};
 }).sort((a, b) => String(b.at).localeCompare(String(a.at)));
 if (rt.pending && rt.pending.ref === rt.ref && !rows.some(row => row.id === rt.pending.body?.key)) {
  rows.unshift({id:rt.pending.body?.key || 'pending', at:'', time:'刚才', stage:null, what:'一次提交（这个页面发出的）', who:'你', tone:'block', result:'结果未确认', pending:true, raw:{key:rt.pending.body?.key, path:rt.pending.path}});
 }
 const filters = [['all', '全部', () => true], ['mine', '你做的', row => row.who === '你'], ['block', '被拦下', row => row.result === '被拦下'], ['err', '出错', row => row.result === '出错'], ['unknown', '结果未确认', row => row.result === '结果未确认']];
 const choice = filters.find(([key]) => key === app.v1gFilter) || filters[0];
 const shown = rows.filter(choice[2]);
 const archive = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref);
 const empty = '这个课题还没有操作记录。你做的每一次保存、授权和决定都会出现在这里。';
 const state = v1gState(app, empty);
 const body = state || (archive ? '<p class="v1-empty">这是历史归档，归档里没有保存操作记录。</p>' : !rows.length ? `<p class="v1-empty">${empty}</p>` : `
  <div class="v1-chips" role="group" aria-label="筛选">${filters.map(([key, label, test]) => `<button type="button" class="v1-chip" data-v1g-filter="${key}" aria-pressed="${choice[0] === key}">${label} <b>${rows.filter(test).length}</b></button>`).join('')}</div>
  <div class="v1-table-wrap"><table class="v1-table v1-history"><thead><tr><th scope="col">时间</th><th scope="col">哪一段</th><th scope="col">做了什么</th><th scope="col">谁做的</th><th scope="col">结果</th><th scope="col"><span class="v1-vh">原始记录</span></th></tr></thead><tbody>
  ${shown.map(row => `<tr><td class="n">${esc(row.time)}</td><td>${row.stage ? 'Stage ' + row.stage : '—'}</td><td>${esc(row.what)}</td><td>${row.who}</td><td>${v1gTag(row.tone, row.result)}</td><td>${row.pending ? '<button type="button" class="v1-link" data-v1-recover>核对上次提交</button>' : `<button type="button" class="v1-link" data-v1g-raw="${esc(row.id)}">看原始记录</button>`}</td></tr>`).join('') || `<tr><td colspan="6" class="v1-muted">这一类还没有记录。</td></tr>`}
  </tbody></table></div>`);
 const tech = [['项目标识', rt.ref], ...rows.map(row => [row.time + ' · ' + row.what, row.raw, row.id])];
 return `${v1gHead('操作历史', '你做的每一次保存、授权和决定，以及被拦下或出错的每一次。新的在上。')}
  <p class="v1-note" role="note">这里先显示已能读取的记录：这个课题保存的操作回执。Stage 3 的规划收据和各段 Harness 记录还没有汇总到这里。</p>
  ${v1gErrorBar()}${body}${v1gTech(tech, !!app.v1gRaw, app.v1gRaw)}`;
}

// ---------------- 连接与设置 (8.1, 8.2, 8.22, 8.5) ----------------
function v1gDiagnostics() {
 if (typeof connectionDiagnostics !== 'function') return null;
 return connectionDiagnostics({ref:rt.ref, project:rt.overview?.project, models:rt.overview?.models, offers:rt.overview?.model_offers,
  error:rt.error, writeHeld:!!(rt.pending || rt.controlHeld)}, Date.now());
}
const v1gReasons = {
 held:'有结果未确认的写入，先核对原来的提交', stale:'项目输入已经变了，需要重新读取这一版的许可', expired:'许可已到期，需要原操作者重新确认，不能自动续期',
 'unknown-expiry':'有效期无法核实，不能当作有效许可', exhausted:'调用上限已用完，不能自动追加', provider:'模型连接没有就绪，请本机操作者检查启动配置',
 refused:'服务拒绝了这份许可，请看原来的操作回执', unknown:'无法核实', confirmable:'可以确认'
};
const v1gFixes = {
 credential:'从同一个 Wiki 首页重新打开，不要复制旧地址。', origin:'回到原来的 Wiki 地址，不要混用端口、别名或直接打开文件。',
 'read-failed':'当前课题的回应缺失或不匹配，请重新选择课题并刷新；确认前不沿用旧课题的状态。', provider:'模型连接没有就绪：请本机操作者检查启动配置。',
 permission:'去本课题的操作入口确认范围、上限和到期时间，再由你本人确认。', 'unknown-write':'到原来操作的地方读回执；不要换一个新请求重新提交，也不要因为刷新了页面再执行一次。'
};
function v1gQuota(d) {
 const b = d?.budgets || {}, limits = rt.meta?.run_limits || {};
 const num = value => Number.isSafeInteger(value) && value >= 0;
 const pick = key => num(b[key]) ? b[key] : num(limits[key]) ? limits[key] : null;
 const calls = pick('model_calls'), search = pick('search_calls'), seconds = pick('seconds');
 if (![calls, search, seconds].some(value => value !== null)) return '<div class="v1-quota none"><span class="v1-qk">额度</span>没有整轮同意书；每一步的上限写在那一步的授权卡里。</div>';
 const zero = [calls, search, seconds].every(value => value === 0);
 return `<div class="v1-quota ${zero ? 'none' : ''}"><span class="v1-qk">额度</span><span>模型调用 上限 <b>${calls ?? '未提供'}</b></span><span>检索 上限 <b>${search ?? '未提供'}</b></span><span>每次最多 <b>${seconds ?? '未提供'}</b> 秒</span><em class="v1-ntag">工程记录</em>${zero ? '<span class="v1-qnote">这次启动的上限都是 0：不会调用模型，也不会检索。</span>' : ''}</div>
  <small class="v1-small">已用次数：服务没有报告，未提供。项目资源上限（不是金额）。已预留模型调用：${num(d?.callsReserved) ? d.callsReserved : '未提供'}。已报告金额（不是费用上限）：${typeof d?.monetaryCost === 'number' ? d.monetaryCost : '未提供'}。货币上限：未提供。</small>`;
}
function v1gSettings() {
 const app = apps[0];
 const d = v1gDiagnostics();
 const p = rt.overview?.project;
 const ok = d && d.binding === 'current';
 const reload = '<button type="button" class="v1-btn sm" data-v1-reload>重新读取状态</button>';
 const archive = typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(rt.ref);
 const none = archive ? '<span class="v1-muted">归档没有这一项</span>' : rt.loading ? '<span class="v1-muted">正在读取，不调用模型</span>' : '<span class="v1-muted">还没有读取到</span>';
 const chat = !ok ? none : d.permission === 'none' ? v1gTag('block', '还没有') : d.permission === 'confirmable' ? v1gTag('done', '可以确认，但它不是运行许可') :
  d.permission === 'held' ? v1gTag('block', '先核对上次提交') : d.permission === 'blocked' ? v1gTag('block', '已保存的许可现在不可用') : v1gTag('idle', '无法核实');
 const chatNote = !ok ? '' : d.permission === 'none' ? '对话许可由本机操作者在页面外准备；这一页不签发、不续期。' : d.permission === 'blocked' ? (d.permits.map(row => v1gReasons[row.reason]).filter(Boolean)[0] || '原因见逐项许可') : d.permission === 'held' ? v1gReasons.held : '有效期和上限见下面的逐项许可。';
 const run = !ok ? none : d.researchAuthorized === true ? v1gTag('done', '有，上限见下') : d.researchAuthorized === false ? v1gTag('idle', '没有') : v1gTag('idle', '无法核实');
 const expiry = !ok ? none : !d.permits.length ? '<span class="v1-muted">没有许可，所以没有有效期</span>' : d.permits.some(row => row.reason === 'unknown-expiry') ? v1gTag('idle', '有效期无法核实') : esc(d.permits.map(row => v1gTime(row.expiresAt)).join('、'));
 const rows = [
  ['当前课题', ok ? esc(d.topic || '标题未提供') : archive ? esc(v1ProjectTitle() || '标题未提供') : none, ok ? '输入版本在本页技术细节里' : archive ? '这是历史归档：只读，不连接 Codex，没有许可和额度。' : rt.ref ? '当前课题的回应缺失或不匹配，请重新选择课题并刷新；确认前不沿用旧课题的状态' : '还没有打开课题。'],
  ['模型连接', !ok ? none : d.provider === 'registered' ? v1gTag('done', '已登记') : d.provider === 'absent' ? v1gTag('idle', '还没有登记') : v1gTag('idle', '无法核实'), ok ? (d.provider === 'registered' ? '这个课题已登记模型连接。已登记不代表已登录。' : d.provider === 'absent' ? '这个课题还没有登记模型连接。已登记也不代表已登录。' : '服务没有给出模型连接记录。') : ''],
  ['登录', !ok ? none : d.authentication === 'verified' ? v1gTag('done', '服务报告已登录') : d.authentication === 'not-authenticated' ? v1gTag('block', '服务报告未登录') : v1gTag('idle', '无法核实登录状态'), '登录在 Codex 自己的界面完成，这里不会要你输入密钥；也不从历史记录推断。'],
  ['对话许可<small>用于右侧 Codex 对话</small>', chat, chatNote],
  ['运行许可<small>用于检索、阅读、规划</small>', run, '对话许可不能当运行许可用，反过来也不行。'],
  // Archives have no limits at all; the launch limits (0/0/0) belong to live topics only (review P2-4).
  ['额度', archive ? none : `<div>${v1gQuota(d)}</div>`, archive ? '归档只读，不调用模型、不检索。' : null],
  ['有效期', expiry, ok && d.permits.length ? '到期后需要原操作者重新确认，不会自动续期。' : '']
 ];
 const permits = ok && d.permits.length ? `<details class="v1-fold"><summary>逐项许可（${d.permits.length} 项）</summary><ul class="v1-permits">${d.permits.map(row => `<li><b>${row.operation === 'Unknown' ? '未提供' : esc(row.operation)}</b> ${v1gTag(row.reason === 'confirmable' ? 'done' : row.reason === 'unknown' ? 'idle' : 'block', v1gReasons[row.reason] || '无法核实')} 到期 ${esc(v1gTime(row.expiresAt))} · 调用上限 ${row.maxCalls ?? '未提供'} 次 · 时长上限 ${row.maxSeconds ?? '未提供'} 秒</li>`).join('')}</ul></details>` : `<p class="v1-small v1-muted">逐项许可：${ok ? '这个课题现在没有逐项许可。' : '还没有读取到。'}</p>`;
 const fix = archive || !rt.ref || rt.loading ? '' : d ? v1gFixes[d.recovery] : '';
 const conn = `<section class="v1-panel" data-v1g-block="conn"><div class="v1-panel-head"><h2>连接、许可与额度</h2>${reload}</div>
  <div class="v1-table-wrap"><table class="v1-table v1-kv"><thead><tr><th scope="col">名称</th><th scope="col">现在怎样</th><th scope="col">说明</th></tr></thead><tbody>
  ${rows.map(([name, value, note]) => note === null ? `<tr><th scope="row">${name}</th><td colspan="2">${value}</td></tr>` : `<tr><th scope="row">${name}</th><td>${value}</td><td>${esc(note || '')}</td></tr>`).join('')}</tbody></table></div>
  ${permits}${fix ? `<div class="v1-fix"><b>怎么处理：</b>${esc(fix)}</div>` : ''}
  <p class="v1-small v1-muted">每一行都只读已有记录：不探测登录、不读个人会话、不调用模型、不检索。</p></section>`;
 const step = (name, tone, text) => `<li class="${tone}"><b>${name}</b>${v1gTag(tone === 'ok' ? 'done' : tone === 'bad' ? 'block' : 'idle', tone === 'ok' ? '通过' : tone === 'bad' ? '没通过' : '无法核实')}<span>${esc(text)}</span></li>`;
 const codex = `<section class="v1-panel" id="v1-connect-codex" data-v1g-block="codex"><div class="v1-panel-head"><h2>连接 Codex 的四步检查</h2><span class="v1-hint">只读检查，不替你改系统设置。</span></div>
  <ol class="v1-checks">
   ${step('装了 Codex', 'unk', '后台还没有提供 Codex 版本检查，这里不能判断装没装、版本在不在已验证范围。')}
   ${step('已登录', !ok ? 'unk' : d.authentication === 'verified' ? 'ok' : d.authentication === 'not-authenticated' ? 'bad' : 'unk', !ok ? '还没有读取到。' : d.authentication === 'verified' ? '服务报告已登录。登录在 Codex 自己的界面完成。' : d.authentication === 'not-authenticated' ? '服务报告未登录。请在 Codex 自己的界面登录，这里不会要你贴任何密钥。' : '服务没有报告登录状态，不从历史推断。登录在 Codex 自己的界面完成。')}
   ${step('权限配置', 'unk', '后台还没有提供权限配置检查，这里不能判断。')}
   ${step('本课题登记了模型连接', !ok ? 'unk' : d.provider === 'registered' ? 'ok' : d.provider === 'absent' ? 'bad' : 'unk', !ok ? '还没有读取到。' : d.provider === 'registered' ? '已登记。' : d.provider === 'absent' ? '没有登记。请本机操作者在启动配置里给这个课题登记模型连接。' : '服务没有给出记录。')}
  </ol></section>`;
 const lang = `<section class="v1-panel" data-v1g-block="lang"><h2>界面语言</h2>
  <select class="v1-field" data-language aria-label="界面语言"><option value="zh" selected>简体中文</option><option value="tw">繁體中文（部分内容未翻译）</option><option value="en">English（部分内容未翻译）</option></select>
  <p class="v1-hint">只换界面。论文标题、引文和你写的内容保持原文，缺译文的会标出来。</p></section>`;
 const stage = app.stage <= 3 ? `Stage ${app.stage} · ${v1gStageName[app.stage]}` : `Stage ${app.stage}`;
 const topic = `<section class="v1-panel" data-v1g-block="topic"><h2>当前课题</h2>
  ${rt.ref ? `<p>${esc((typeof v1ProjectTitle === 'function' && v1ProjectTitle()) || '标题未提供')}</p><p class="v1-hint">现在在 ${esc(stage)}。项目标识和输入版本在本页技术细节里。</p>` : '<p class="v1-muted">还没有打开课题。</p>'}
  <details class="v1-fold" data-v1g-block="env"><summary>环境自检（后台还没有提供结果）</summary><ul class="v1-permits">${['Git', 'Python 版本', '长路径设置', '短目录可写', '依赖', '端口', 'Codex 是否安装和登录'].map(name => `<li><b>${name}</b> ${v1gTag('idle', '无法核实')} 启动自检的结果还不能在页面里读取。</li>`).join('')}</ul></details></section>`;
 const tech = [['项目标识', rt.ref], ['输入版本', p?.input_version], ['保存次数（revision）', p?.revision], ['对话许可的原名', '内容任务许可（content task permit）'], ['运行许可的原名', '科研运行许可（research execution permission）'],
  ['材料来源与版本', typeof m9 !== 'undefined' && m9.catalog ? `已登记材料 ${(m9.catalog.materials || []).filter(m => m.project_ref === rt.ref).length} 份` : '未读取'], ['Harness 版本', rt.meta?.harness_head], ['这次启动的运行上限', rt.meta?.run_limits], ['读取错误', rt.error || null]];
 const failed = rt.error && !rt.loading ? '<div class="v1-alert err" role="alert"><div><b>连接状态读取失败。</b><span>下面是上次读到的值；原因在本页技术细节里。</span></div><button type="button" class="v1-btn sm" data-v1-reload>重新读取状态</button></div>' : '';
 return `${v1gHead('连接与设置', '这一页只读已有记录：不探测登录、不读个人会话、不调用模型、不检索，也不在这里改许可。')}${failed}
  ${conn}${codex}<div class="v1-two">${lang}${topic}</div>
  <p class="v1-hint">范围、额度和运行操作请到对应阶段确认；这里不改许可。</p>
  <div class="v1-row"><button type="button" class="v1-btn" data-page="workspace">返回工作台</button>${reload}<button type="button" class="v1-link" data-v1g-guide>重新显示首次引导</button>${app.v1gGuideShown ? '<small class="v1-muted" role="status">已重新打开。回到首页就能看到首次引导。</small>' : ''}</div>
  ${v1gTech(tech)}`;
}

const v1gPreviousPage = otherPage;
otherPage = function (app) {
 const html = v1gPreviousPage(app);
 if (!v1gOn(app)) return html;
 const page = app.page === 'files' ? v1gFiles() : app.page === 'history' ? v1gHistory() : v1gSettings();
 return `<div class="v1-page" data-v1-global="${app.page}">${page}</div>${html}`;
};

// The home guide's "连接 Codex" opens this page at the four-step check (8.5, 8.2).
document.addEventListener('click', event => {
 if (!event.target.closest?.('[data-wiki-home-codex]')) return;
 setTimeout(() => apps[0].el.querySelector('#v1-connect-codex')?.scrollIntoView({block:'start'}), 120);
}, true);

// ---------------- 环境提示条 (8.22) ----------------
// Only what the page itself can tell: it was not opened from the Wiki service (no service bootstrap, or the
// service refused this address as another origin, alias or port). Missing vendor files stop the service before
// any page loads, and port changes, a second running copy and the Codex version are known only to the launcher.
function v1gEnvAlerts() {
 const boot = window.RESEARCH_PROJECTS;
 const refused = ['origin-or-host-rejected', 'cross-site-rejected'].includes(rt.error);
 if (location.protocol === 'file:' || !boot || typeof boot.credential !== 'string' || refused) {
  return [{tone:'warn', title:'这个页面不是从 Wiki 服务打开的。', sub:'请运行启动脚本，用它打印的地址打开；不要直接双击 HTML 文件，也不要换别名或端口。', raw:refused ? rt.error : !boot ? 'no-service-bootstrap' : 'file-or-missing-credential'}];
 }
 return [];
}
// ---------------- 英文、繁体：仍是旧版界面的说明 (acceptance S-1) ----------------
// V1 is Simplified Chinese only for now. In English and Traditional Chinese the old interface is shown; say so at the top,
// in that language, with a way to the new interface. The button changes the language through the page's own language
// select, so the saved language, the address and the repaint all follow the normal path.
const v1gLegacyTexts = {
 en:{title:'This language still uses the old interface, and it has fewer features.', sub:'For the new interface, switch to Simplified Chinese.', button:'Switch to Simplified Chinese (简体中文)'},
 tw:{title:'這個語言目前仍是舊版介面，功能不全。', sub:'新版介面請切換到簡體中文。', button:'切換到簡體中文（简体中文）'}
};
function v1gLegacyNote(app) {
 const text = Object.hasOwn(v1gLegacyTexts, app.lang) ? v1gLegacyTexts[app.lang] : null;
 const content = app === apps[0] ? app.el.querySelector?.('.hs-content') : null;
 if (!text || !content || content.querySelector?.('[data-v1-legacy-note]')) return;
 content.insertAdjacentHTML('afterbegin', `<div class="v1-lang-note" data-v1-legacy-note role="note"><div><b>${esc(text.title)}</b> <span>${esc(text.sub)}</span></div><button type="button" class="hs-button" data-v1g-lang-zh>${esc(text.button)}</button></div>`);
}
document.addEventListener('click', event => {
 if (!event.target.closest?.('[data-v1g-lang-zh]')) return;
 const select = apps[0]?.el?.querySelector?.('select[data-language]');
 if (!select) return;
 select.value = 'zh';
 select.dispatchEvent(new Event('change', {bubbles:true}));
}, true);

const v1gPrevRender = render;
render = function (app) {
 v1gPrevRender(app);
 if (!app.el.dataset.v1) { v1gLegacyNote(app); return; }
 // The Codex chat drawer (wiki-chat.js) owns the right-edge tab; no second placeholder tag is drawn here.
 const content = app.el.querySelector('.hs-content');
 const alerts = v1gEnvAlerts();
 if (!content || !alerts.length) return;
 content.insertAdjacentHTML('afterbegin', alerts.map(a => `<div class="v1-alert v1-env ${a.tone}" role="alert" data-v1-env><div><b>${esc(a.title)}</b><span>${esc(a.sub)}</span></div><details class="v1-env-raw"><summary>技术细节</summary><code>${esc(a.raw)}</code></details></div>`).join(''));
};
const v1gPrevAfter = v7AfterRender;
v7AfterRender = function (app) {
 v1gPrevAfter(app);
 const content = app.el.querySelector('.hs-content'), env = content?.querySelector(':scope > [data-v1-env]');
 if (env && content.firstElementChild !== env) content.prepend(env);
};

// The runtime paints once when it loads, before the Wiki modules are installed. With a slow Host the first read
// can take many seconds, and until it returns that first paint (the previous page layout) stayed on screen.
// Paint again now that every module is in place, so the V1 shell shows its "正在读取" state from the start.
if (typeof v1On === 'function' && v1On(apps[0])) livePaint();
