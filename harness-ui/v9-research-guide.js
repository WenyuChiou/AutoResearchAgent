// Read an optional, byte/source-bound visual guide through the existing material API.
// This module only issues GETs. Accepted plan, selection and scientific state are untouched.
const v94 = {key:null, view:null, status:'idle', guide:null, source:null, error:'', controller:null, dispose:null};
function v94SelectedRevision(view) {
 if (typeof v94fContext !== 'function') return null;
 const context = v94fContext();
  const state = context?.view === view ? v94fState(context) : null;
  return state ? v94fRevision(state) : null;
}
function v94Key(view, basis, epoch = rt.epoch, revision = v94SelectedRevision(view)) {
 const binding = v94PlanBinding(view, revision);
 return binding && basis ? JSON.stringify([basis, binding, epoch]) : null;
}
function v94Current(view, basis, epoch, revision = null) {
 return epoch === rt.epoch && apps.some(app => app.page === 'workspace' && app.stage === 3) &&
  v93Matches(basis, v93Identity()) && v93Matches(basis, v93.basis) && v93.view === view &&
  (v94SelectedRevision(view)?.receipt_sha256 || null) === (revision?.receipt_sha256 || null);
}
async function v94Load(view, basis, epoch, revision = v94SelectedRevision(view)) {
 const key = v94Key(view, basis, epoch, revision), controller = new AbortController();
 v94.controller?.abort(); Object.assign(v94, {key, view, controller, status:'loading', guide:null, source:null, error:''});
 livePaint();
 const timeout = setTimeout(() => controller.abort(), 20000);
 try {
  const catalog = await v94FetchJson('/api/v9/materials', 524288, controller.signal);
  const item = v94ChooseMaterial(catalog, view, revision);
  const guide = item ? v94ValidateGuide(await v94FetchJson('/api/v9/files/' + item.id, 65536, controller.signal, item), view, revision) : v94PlanReadingGuide(view, revision);
  if (!v94Current(view, basis, epoch, revision) || v94.key !== key || v94.controller !== controller) return;
  v94.guide = guide; v94.source = item ? 'authored' : 'plan-excerpts'; v94.status = 'ready';
 } catch (error) {
  if (!v94Current(view, basis, epoch, revision) || v94.controller !== controller) return;
  v94.status = 'failed'; v94.error = error?.name === 'AbortError' ? 'research-guide-read-timeout' : String(error?.message || error);
 } finally {
  clearTimeout(timeout);
  if (v94Current(view, basis, epoch, revision) && v94.controller === controller) { v94.controller = null; livePaint(); }
 }
}
function v94GuideSection(view, revision, original = '') {
 const key = v94Key(view, v93Identity(), rt.epoch, revision);
 if (!key) return original;
 const status = v94.key === key && v94.view === view ? v94.status : 'idle';
 const guide = status === 'ready' ? v94.guide : null;
 const plan = revision ? revision.record.plan : view.plan;
 const questions = Array.isArray(view.direction_context?.questions) ? view.direction_context.questions : [];
 const row = plan.question_plans[v94PlanQuestionIndex(plan, view.direction_context?.questions, guide?.question_ref ?? null)];
 const question = questions.find(item => item.question_ref === row?.question_ref);
 const resources = row ? v93QuestionResourceUses(view,row.question_ref).filter(use => typeof use?.resource?.name === 'string') : [];
 const design = v94GuideHtml(guide, {reading:guide !== null && v94.source === 'plan-excerpts', question, row, resources,
  version:revision?.record.revision_number ?? null, canComment:typeof v94fContext==='function'&&v94fContext()?.view===view});
 const message = status === 'loading' ? rl('正在读取同版本图解。','Reading the diagram for this version.','正在讀取同版本圖解。') :
  status === 'failed' ? rl('图解未通过读取或来源核对；已保存的规划仍可查看。','The diagram could not be read or source-verified. The saved plan is still available.','圖解未通過讀取或來源核對；已保存的規劃仍可查看。') : '';
 const state = message ? '<section class="n9-guide-state"><p role="status">'+message+'</p>'+(status === 'failed' ?
  '<details><summary>'+rl('读取详情','Read details','讀取詳情')+'</summary><p>'+rx(v94.error)+'</p></details><button type="button" class="hs-button" data-v94-read>'+rl('重新读取图解','Reload visual guide','重新讀取圖解')+'</button>' : '')+'</section>' : '';
 const saved = original ? '<details class="n9-plan-details"><summary>'+
  (revision ? rl('查看原始规划版本','View the original planning version','查看原始規劃版本') :
   rl('完整原规划与待查事项','Complete saved plan and open checks','完整原規劃與待查事項'))+'</summary>'+original+'</details>' : '';
 return '<div data-v94-guide>'+design+'</div>'+state+saved;
}
const v94OriginalSummary = v93SavedPlanSummary;
v93SavedPlanSummary = function(view) {
 return v94GuideSection(view, v94SelectedRevision(view), v94OriginalSummary(view));
};
const v94After = v7AfterRender;
v7AfterRender = function(app) {
 v94After(app); v94.dispose?.(); v94.dispose = null;
 const view = v93.view, basis = v93Identity(), key = app.page === 'workspace' && app.stage === 3 && v93Matches(basis, v93.basis) ? v94Key(view, basis) : null;
 if (!key) { v94.controller?.abort(); Object.assign(v94, {key:null, view:null, guide:null, source:null, status:'idle', controller:null}); return; }
 const target = app.el.querySelector('[data-v94-guide]');
 if (target && typeof v94ConnectGuide === 'function') v94.dispose = v94ConnectGuide(target);
 if (v94.key !== key || v94.view !== view) v94Load(view, basis, rt.epoch);
};
document.addEventListener('click', event => {
 if (!event.target.closest('[data-v94-read]') || v94.status === 'loading') return;
 const view = v93.view, basis = v93Identity();
 if (v94Key(view, basis) && v94Current(view, basis, rt.epoch, v94SelectedRevision(view))) { v94Load(view, basis, rt.epoch); livePaint(); }
});
