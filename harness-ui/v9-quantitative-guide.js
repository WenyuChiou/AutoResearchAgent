// Optional quantitative sidecars share the existing read-only material transport.
const v96 = {key:null, view:null, status:'idle', model:null, error:'', controller:null};
async function v96Load(view, basis, epoch, revision = v94SelectedRevision(view)) {
 const key = v94Key(view, basis, epoch, revision), controller = new AbortController();
 v96.controller?.abort(); Object.assign(v96, {key, view, controller, status:'loading', model:null, error:''});
 livePaint();
 const timeout = setTimeout(() => controller.abort(), 20000);
 try {
  const catalog = await v94FetchJson('/api/v9/materials', 524288, controller.signal);
   if (!v94Current(view, basis, epoch, revision) || v96.controller !== controller) return;
   controller.signal.throwIfAborted();
  const item = v96ChooseQuant(catalog, view, revision);
  let model = null;
  if (item) {
   const guide = v96ValidateQuant(await v94FetchJson('/api/v9/files/' + item.id, 131072, controller.signal, item), view, revision);
   const materials = v96SourceMaterials(catalog, guide), documents = new Map();
   for (const [id, material] of materials) {
     if (!v94Current(view, basis, epoch, revision) || v96.controller !== controller) return;
     controller.signal.throwIfAborted();
    documents.set(id, await v94FetchJson('/api/v9/files/' + material.id, 524288, controller.signal, material));
   }
    controller.signal.throwIfAborted();
    model = v96ProjectQuant(guide, documents);
  }
  if (!v94Current(view, basis, epoch, revision) || v96.key !== key || v96.controller !== controller) return;
  v96.model = model; v96.status = model ? 'ready' : 'absent';
 } catch (error) {
  if (!v94Current(view, basis, epoch, revision) || v96.controller !== controller) return;
  v96.status = 'failed'; v96.error = error?.name === 'AbortError' ? 'quantitative-guide-read-timeout' : String(error?.message || error);
 } finally {
  clearTimeout(timeout);
  if (v94Current(view, basis, epoch, revision) && v96.controller === controller) { v96.controller = null; livePaint(); }
 }
}
function v96Section(view, revision) {
 const key = v94Key(view, v93Identity(), rt.epoch, revision);
 if (!key || v96.key !== key || v96.view !== view || v96.status === 'idle' || v96.status === 'absent') return '';
 if (v96.status === 'ready') return '<div data-v96-quant></div>';
 const text = v96.status === 'loading' ?
  rl('正在核对同版本数值材料。','Checking numerical materials for this version.','正在核對同版本數值材料。') :
  rl('数值材料未通过读取或来源核对；原规划仍可查看。','Numerical materials could not be read or source-verified. The saved plan remains available.','數值材料未通過讀取或來源核對；原規劃仍可查看。');
 return '<section class="n96-read-state"><p role="status">' + text + '</p>' + (v96.status === 'failed' ?
  '<details><summary>' + rl('读取详情','Read details','讀取詳情') + '</summary><p>' + rx(v96.error) + '</p></details>' +
  '<button type="button" class="hs-button" data-v96-read>' + rl('重新读取数值材料','Reload numerical materials','重新讀取數值材料') + '</button>' : '') + '</section>';
}
const v96OriginalGuideSection = v94GuideSection;
v94GuideSection = function(view, revision, original = '') {
 return v96OriginalGuideSection(view, revision, original) + v96Section(view, revision);
};
const v96After = v7AfterRender;
v7AfterRender = function(app) {
 v96After(app);
 const view = v93.view, basis = v93Identity(), revision = v94SelectedRevision(view);
 const key = app.page === 'workspace' && app.stage === 3 && v93Matches(basis, v93.basis) ? v94Key(view, basis, rt.epoch, revision) : null;
 if (!key) { v96.controller?.abort(); Object.assign(v96, {key:null, view:null, status:'idle', model:null, error:'', controller:null}); return; }
 if (v96.key !== key || v96.view !== view) { v96Load(view, basis, rt.epoch, revision); return; }
 const target = app.el.querySelector('[data-v96-quant]');
 if (target && v96.status === 'ready' && v96.model && v94Current(view, basis, rt.epoch, revision)) v96MountQuant(target, v96.model, document.documentElement.lang);
};
document.addEventListener('click', event => {
 if (!event.target.closest('[data-v96-read]') || v96.status === 'loading') return;
 const view = v93.view, basis = v93Identity(), revision = v94SelectedRevision(view);
 if (v94Key(view, basis, rt.epoch, revision) && v94Current(view, basis, rt.epoch, revision)) v96Load(view, basis, rt.epoch, revision);
});
