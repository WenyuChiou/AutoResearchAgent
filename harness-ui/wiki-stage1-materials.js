// Wiki V1 Stage 1 "材料" tab (DESIGN 8.12). Loaded after wiki-stage1-ops.js.
// The upload / register / verify / draft machinery stays in v9-materials.js; this tab frames it with the
// designed wording and moves that panel into place. Nothing here talks to the service.
wikiS1Tabs.materials = '材料';

function wsMaterialFiles() {
 const files = rt.atlas?.files;
 return Array.isArray(files) ? files : [];
}
function wsMaterialsDownloads() {
 const files = wsMaterialFiles();
 const why = '现在还不能做这一步：后台还没有文献包文件的下载接口';
 if (!files.length) return '<p class="wiki-s1-muted">文献包还没有生成，这里还没有可下载的文件。</p>';
 return `<table class="ws-table"><thead><tr><th scope="col">文件</th><th scope="col">版本</th><th scope="col">大小</th><th scope="col">操作</th></tr></thead><tbody>${files.map(file => `<tr><td>${esc(file.name ?? file.path ?? file.file_ref ?? '未提供')}</td><td>${esc(file.version ?? (file.sha256 ? file.sha256.slice(0, 12) : '未提供'))}</td><td>${esc(file.size ?? file.bytes ?? '未提供')}</td><td>${wsBtn('下载', 'data-ws-download', why)}</td></tr>`).join('')}</tbody></table>`;
}
function wsMaterialsTab(app) {
 if (wsReadonly()) return `<section class="wiki-s1-card" data-wiki-ops="materials"><h2>材料</h2>${wsArchiveNote}</section>`;
 return `<section class="wiki-s1-card ws-materials" data-wiki-ops="materials" aria-label="材料">
 <p class="ws-strip">手动登记的材料保留原件、版本和所属阶段。登记后可以恢复、核验、准备接续；<b>不会自动标记为已读、已纳入或已批准</b>。</p>
 <h3>加入文件</h3>
 <p class="wiki-s1-muted">每个文件最多 128 MiB；压缩包按原样保存，不解包、不执行。上传完成后写「文件已按原始字节保存，没有启动研究」。中断后重新选同一个文件才能续传。</p>
 <div data-ws-materials-slot></div>
 <h3>文件下载与导出</h3>
 <p class="wiki-s1-muted">文献包里的版本化文件（文献图谱、论文目录、逐篇笔记、BibTeX）。下载前要核验原文件；核验不过时写「保存的文件和记录不一致」。</p>
 ${wsMaterialsDownloads()}
 <p class="ws-note">上传被拒绝时，上面的材料区会写明原因；文件不会被改动。</p></section>`;
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
