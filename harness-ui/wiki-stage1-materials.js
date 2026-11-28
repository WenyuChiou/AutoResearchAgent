// Wiki V1 Stage 1 "材料" tab (DESIGN 8.12). Loaded after wiki-stage1-ops.js.
// The upload / register / verify / draft machinery stays in v9-materials.js; this tab frames it with the
// designed wording and moves that panel into place. Nothing here talks to the service.
wikiS1Tabs.materials = '材料';

function wsMaterialFiles() {
 const files = rt.atlas?.files;
 return Array.isArray(files) ? files : [];
}
function wsMaterialsDownloads() {
 // Same names as the project files page; the checked download lives there (8.1), so this links to it.
 const files = wsMaterialFiles();
 if (!files.length) return '<p class="wiki-s1-muted">文献包还没有生成，这里还没有可下载的文件。</p>';
 let note = 0;
 return `<ul class="ws-m9-list">${files.map(file => `<li><b>${/\.md$/.test(file.path || '') ? '逐篇笔记 ' + (++note) : '参考文献 BibTeX'}</b><small>v${esc(rt.overview?.project?.input_version ?? '未提供')}</small></li>`).join('')}</ul>
 <p class="wiki-s1-muted">下载前会核对原文件；核对不过时写「保存的文件和记录不一致」。<button type="button" class="hs-button" data-page="files">去项目文件下载</button></p>`;
}
function wsMaterialsTab(app) {
 if (wsReadonly()) return `<section class="wiki-s1-card" data-wiki-ops="materials"><h2>材料</h2>${wsArchiveNote}</section>`;
 return `<section class="wiki-s1-card ws-materials" data-wiki-ops="materials" aria-label="材料">
 <div data-ws-materials-slot></div></section>`;
}
const wsMaterialsPrevResults = wikiS1Results;
wikiS1Results = function (app) {
 const html = wsMaterialsPrevResults(app);
 if (!wsOpsActive(app) || app.wikiS1?.tab !== 'materials' || html.includes('data-wiki-ops-root')) return html;
 return html.replace(/(<div role="tabpanel"[^>]*>)[\s\S]*(<\/div>\s*<\/section>\s*)$/, (all, open, close) => open + wsMaterialsTab(app) + close);
};
const wsMaterialsPrevAfter = v7AfterRender;
v7AfterRender = function (app) {
 wsMaterialsPrevAfter(app);
 if (!wsOpsActive(app)) return;
 const panel = app.el.querySelector('.n9-materials'), slot = app.el.querySelector('[data-ws-materials-slot]');
 if (!panel) return;
 if (slot) { slot.append(panel); panel.hidden = false; panel.open = true; }
 else panel.hidden = true;
};

// ---------- Wiki V1 materials panel for Stage 1 and 2 (DESIGN 8.12, 8.14; shots/new-s1-materials.png) ----------
// Same data attributes and handlers as v9-materials.js / v9-continuation.js (upload, refresh, download original,
// prepare, open packet, inspect, export, draft save, packet import); only the layout and wording follow the design.
const wsM9Previous = m9Panel;
const wsM9Accept = '.pdf,.json,.jsonl,.md,.txt,.csv,.tsv,.bib,.zip,.docx,.png,.jpg,.xlsx';
const wsM9Refusals = /exceeds|unsupported|invalid-file|mismatch|invalid-chunk|incomplete|upload-not-active|revision|conflict|differs/;
const wsM9Errors = [
 [/exceeds-128|capacity-exceeded/, '超过 128 MiB，文件没有保存。'],
 [/unsupported-material-extension/, '不收这种文件，只收：pdf、json、jsonl、md、txt、csv、tsv、bib、zip、docx、png、jpg、xlsx。'],
 [/invalid-file-name/, '文件名不能用，请改名后再传。'],
 [/uploaded-bytes-hash-mismatch|invalid-chunk/, '这不是同一个文件，不能接着传。取消后重新上传。'],
 [/upload-incomplete|upload-not-active/, '上一次上传还在收尾，请先读取保存状态。'],
 [/revision|conflict/, '这份草稿已经被改过，请重新读取后再保存。'],
 [/download-hash-differs|material-file-differs/, '保存的文件和记录不一致，不能下载。'],
 [/packet|source|incoming|project-binding/, '候选包没有通过核验：目录、来源文件、课题或候选版本和记录不一致。原材料和失败记录保留。']
];
function wsM9Error(code) {
 const hit = wsM9Errors.find(([pattern]) => pattern.test(String(code)));
 return hit ? hit[1] : '这次没有完成，原材料和失败记录保留。';
}
function wsM9Size(bytes) {
 if (!Number.isSafeInteger(bytes) || bytes < 0) return '未提供';
 return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MiB' : bytes >= 1024 ? Math.round(bytes / 1024) + ' KiB' : bytes + ' B';
}
function wsM9Time(value) { return typeof v1gTime === 'function' ? v1gTime(value) : String(value || '未提供'); }
function wsM9Status(m) {
 if (m.kind === 'manual-file' && m.status === 'registered') return [wsTag('idle', '待处理'), '还没有自动提取、筛选或阅读'];
 if (m.kind === 'manual-file' && m.status === 'uploading') return [wsTag('block', '上传没有完成'), '重新选同一个文件才能接着传。已传的部分保留。'];
 if (m.status === 'aborted') return [wsTag('idle', '已取消上传'), ''];
 if (m.kind === 'manual-stage2-packet' && m.status === 'registered') return [wsTag('done', '已核验'), '候选包的来源文件都核对过'];
 if (m.kind === 'saved-delivery') return [wsTag('done', '已保存交付'), '原来的判断保留，接续另建状态'];
 return [wsTag('idle', '状态见原始记录'), ''];
}
function wsM9Row(m) {
 const busy = m9.busy ? '正在保存，请稍等' : '';
 const op = m9.catalog?.operations?.find(o => o.material_id === m.id);
 const [tag, note] = wsM9Status(m);
 const actions = [];
 if (m.kind === 'manual-file' && m.status === 'registered') actions.push(wsBtn('下载原件', `data-n9-file="${esc(m.id)}"`, ''));
 else if (m.kind === 'manual-file') actions.push(wsBtn('下载原件', '', '上传完成后才能下载原件'));
 if (m.stage === 2 && m.packet_path) {
  actions.push(wsBtn('读取并显示这份材料', `data-n9-open-packet="${esc(m.id)}"`, busy));
  actions.push(wsBtn('建立接续快照', `data-n9-prepare="${esc(m.id)}"`, busy || (op ? '已经建立过快照' : '')));
  if (op?.status === 'prepared') actions.push(wsBtn('核验并恢复工作流', `data-n9-inspect="${esc(op.id)}"`, ''));
 }
 actions.push(wsBtn('导出接续请求', `data-n9-export="${esc(m.id)}"`, ''));
 const opLine = op ? `<p class="ws-m9-op">${op.status === 'prepared' ? wsTag('done', '已保存工作流快照') + ' 接下来需要独立评审输入和执行设置；没有启动模型、研究或独立评审。' : wsTag('block', '操作还没确认') + ' 请读取原状态。'}</p>` :
  (m.stage === 2 && m.packet_path ? '<p class="ws-m9-op wiki-s1-muted">建立接续快照：保存当前工作流的状态，不启动模型、研究或独立评审。</p>' : '');
 return `<tr><th scope="row">${esc(m.name)}</th><td>Stage ${esc(m.stage)}</td><td class="n">${wsM9Size(m.bytes)}</td><td class="n">未提供</td><td class="n">${esc(wsM9Time(m.registered_at))}</td>
  <td>${tag}${note ? `<small class="ws-m9-note">${esc(note)}</small>` : ''}</td><td class="ws-m9-acts">${actions.join('')}${opLine}</td></tr>`;
}
function wsM9Continue(materials) {
 if (!materials.length) return '<p class="wiki-s1-muted">先登记一份材料，才能保存接续草稿。</p>';
 return materials.map(m => {
  const draft = m9Draft(m);
  return `<div class="ws-m9-draft"><p><b>${esc(m.name)}</b>${draft ? ' ' + wsTag('done', '草稿已保存') : ''}</p>
   <label>希望接续到<select data-n9-target="${esc(m.id)}">${[1, 2, 3, 4, 5, 6].map(stage => `<option value="${stage}" ${(m9.target[m.id] ?? draft?.target_stage ?? m.stage) === stage ? 'selected' : ''}>Stage ${stage}${stage > 3 ? '（未开放）' : ''}</option>`).join('')}</select></label>
   <label>用途、希望补充的问题或待审路线<textarea rows="3" maxlength="4000" data-n9-note="${esc(m.id)}">${esc(m9.notes[m.id] ?? draft?.note ?? '')}</textarea></label>
   ${wsBtn('保存接续草稿', `data-n9-save="${esc(m.id)}"`, m9.busy ? '正在保存，请稍等' : '')}<small class="wiki-s1-muted">保存目标阶段不等于该阶段已获准执行。</small></div>`;
 }).join('');
}
// Why 「核验并登记候选包」 cannot be used right now (acceptance S-4). A saved archive, a saved sample and a launch without a
// Stage 2 run configuration cannot register a packet: the click used to send POST /api/v9/import-packet and get a 409.
function wsM9ImportGate(app) {
 const ref = typeof rt !== 'undefined' ? rt.ref : null;
 if (typeof wikiHomeArchiveBound === 'function' && wikiHomeArchiveBound(ref)) return '这是历史归档，不能在这里改';
 if (typeof canonicalReadonly === 'function' && canonicalReadonly()) return '这是保存的样例，不能在这里改';
 const conn = typeof v9ConnectionModel === 'function' ? v9ConnectionModel(app) : null;
 if (conn?.phase === 'ready' && /profile-unavailable$/.test(String(conn.code || ''))) return '这次启动没有提供 Stage 2 的运行配置，不能登记候选包';
 if (![m9.sourcePath, m9.importPath, m9.packetHash].every(value => String(value || '').trim())) return '请先填好上面的三项';
 return '';
}
function wsM9ImportButton(app) {
 return wsBtn('核验并登记候选包', 'data-n9-action="import"', m9.busy ? '正在核对原文件和来源，请稍等' : wsM9ImportGate(app));
}
// Typing in the three fields only stores the value (v9-materials.js); the button was judged once at render, so it stayed
// grey after the last field was filled. Re-judge it on every input and replace only that button: no repaint, so the field
// being typed in keeps its focus and caret.
document.addEventListener('input', event => {
 const field = event.target?.matches?.('[data-n9-field]') ? event.target.dataset.n9Field : null;
 if (!field || typeof apps === 'undefined') return;
 m9[field] = event.target.value;
 const button = apps[0]?.el?.querySelector?.('[data-n9-action="import"]'), wrap = button?.closest?.('.ws-btn');
 if (wrap) wrap.outerHTML = wsM9ImportButton(apps[0]);
}, true);
m9Panel = function (app) {
 if (!(typeof v1On === 'function' && v1On(app) && app.page === 'workspace' && (app.stage === 1 || app.stage === 2))) return wsM9Previous(app);
 const materials = m9Current();
 const loading = !m9.catalog && !m9.error;
 const status = n9Message(m9.status);
 const refused = m9.error && wsM9Refusals.test(m9.error);
 const progress = m9.busy ? `<div class="ws-m9-line">${wsTag('run', '上传中')}<span>${esc(status || '正在保存，请稍等')}</span></div>` :
  m9.error ? `<div class="ws-m9-line ws-m9-bad">${wsTag(refused ? 'block' : 'err', refused ? '被拦下' : '出错')}<span>${esc(wsM9Error(m9.error))}</span>${wsBtn('读取保存状态', 'data-n9-action="refresh"', '')}<details class="ws-tech"><summary>技术细节</summary><code>${esc(m9.error)}</code></details></div>` :
  status ? `<div class="ws-m9-line">${wsTag('done', '已保存')}<span>${esc(status)}</span></div>` : '';
 const unread = !m9.catalog && !!m9.error; // the saved list was not read: neither "none" nor a count is known
 const table = loading ? '<p class="wiki-s1-muted">正在读取保存记录</p>' : unread ? '<p class="wiki-s1-muted">这次没有读到已保存的材料，原因写在上面；已保存的文件没有变。</p>' : !materials.length ? '<p class="wiki-s1-muted">这个课题在这一段还没有登记材料。</p>' :
  `<div class="ws-m9-wrap"><table class="ws-table ws-m9-table"><thead><tr><th scope="col">文件</th><th scope="col">所属阶段</th><th scope="col">大小</th><th scope="col">版本</th><th scope="col">登记时间</th><th scope="col">状态</th><th scope="col"><span class="wiki-home-visually-hidden">操作</span></th></tr></thead><tbody>${materials.map(wsM9Row).join('')}</tbody></table></div>`;
 const files = app.stage === 1 && typeof wsMaterialsDownloads === 'function' ? wsMaterialsDownloads() :
  '<p class="wiki-s1-muted">这一段的交付文件（候选包原报告、评语、资源补件、全部原始文件）还不能在这里下载：后台还没有交付文件的下载接口。</p>';
 const importFold = app.stage === 2 ? `<details class="ws-m9-card ws-m9-import" data-s2-import><summary>接入其他候选包（本地已解包）· 高级</summary>
  <p class="wiki-s1-muted">使用 Harness 原有的候选包格式；目录要放在配置的接入目录里；核对全部来源字节，原有科学规则不放宽。</p>
  <p class="wiki-s1-muted">接入别的候选包的内容不会冒充本课题的 Stage 2，血缘按原包保留，页面用来历标签区分。</p>
  <div class="ws-m9-fields"><label>来源文件目录<input data-n9-field="sourcePath" value="${esc(m9.sourcePath)}"></label>
  <label>候选包清单文件（packet.json）的位置<input data-n9-field="importPath" value="${esc(m9.importPath)}"></label>
  <label>清单文件的校验值（SHA-256）<input data-n9-field="packetHash" value="${esc(m9.packetHash)}"></label></div>
  <small class="wiki-s1-muted">现在的核验接口要这三项；校验由服务做，结果写在上面。</small>
  ${wsM9ImportButton(app)}</details>` : '';
 return `<div class="n9-materials ws-m9" data-n9-material-panel>
  <section class="ws-m9-card"><div class="ws-m9-head"><h3>加入文件</h3><label class="ws-m9-pick ${m9.busy ? 'off' : ''}">选择阶段材料<input type="file" multiple data-n9-upload aria-label="选择阶段材料" accept="${wsM9Accept}" ${m9.busy ? 'disabled' : ''}></label></div>
   <p class="wiki-s1-muted">你自己登记的材料保留原件、版本和所属阶段。登记后可以恢复、核验、准备接续；不会自动标记为已读、已纳入或已批准。每个文件最多 128 MiB；压缩包按原样保存，不解包、不执行。</p>
   ${m9.busy ? '<small class="ws-why">正在保存，请稍等</small>' : ''}${progress}</section>
  <section class="ws-m9-card ws-m9-flush"><div class="ws-m9-head"><h3>已保存的材料</h3><small class="wiki-s1-muted">${loading ? '正在读取' : unread ? '没有读到' : materials.length ? materials.length + ' 份。文件已按原始字节保存，没有启动研究。' : '还没有登记材料。'}</small></div>${table}
   <p class="wiki-s1-muted ws-m9-foot">同名同内容再传一次会写「已经登记过，没有重复」；超过 128 MiB 写「超过 128 MiB」；别的课题的材料不会出现在这里。</p></section>
  ${importFold}
  <div class="ws-m9-two"><section class="ws-m9-card"><h3>${app.stage === 1 ? '文献包里的文件' : '这一段的交付文件'}</h3>${files}</section>
  <section class="ws-m9-card"><h3>接着往后用</h3>${wsM9Continue(materials)}</section></div>
 </div>`;
};

// Provided-material registration (v9-stage1-provided.js) shown under a registered Stage 1 upload (DESIGN 8.12).
// It records the uploaded bytes and the researcher's identity claim only: no query, model, screening or reading.
const wsProvidedPrevRow = wsM9Row;
wsM9Row = function (m) {
 const row = wsProvidedPrevRow(m);
 if (typeof s1ProvidedForm !== 'function') return row;
 const form = s1ProvidedForm(m);
 return form ? row + `<tr class="ws-m9-provided"><td colspan="7">${form}</td></tr>` : row;
};
