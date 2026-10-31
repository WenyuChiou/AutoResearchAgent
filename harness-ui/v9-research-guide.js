// Read an optional, byte/source-bound visual guide through the existing material API.
// This module only issues GETs. Accepted plan, selection and scientific state are untouched.
const v94 = {key:null, status:'idle', guide:null, error:'', controller:null, dispose:null};
function v94Key(view, basis, epoch = rt.epoch) {
 const binding = v94PlanBinding(view);
 return binding && basis ? JSON.stringify([basis, binding, epoch]) : null;
}
function v94Current(view, basis, epoch) {
 return epoch === rt.epoch && apps.some(app => app.page === 'workspace' && app.stage === 3) &&
  v93Matches(basis, v93Identity()) && v93Matches(basis, v93.basis) && v93.view === view;
}
async function v94Load(view, basis, epoch) {
 const key = v94Key(view, basis, epoch), controller = new AbortController();
 v94.controller?.abort(); Object.assign(v94, {key, controller, status:'loading', guide:null, error:''});
 livePaint();
 const timeout = setTimeout(() => controller.abort(), 20000);
 try {
  const catalog = await v94FetchJson('/api/v9/materials', 524288, controller.signal);
  const item = v94ChooseMaterial(catalog, view);
  const guide = item ? v94ValidateGuide(await v94FetchJson('/api/v9/files/' + item.id, 65536, controller.signal, item), view) : null;
  if (!v94Current(view, basis, epoch) || v94.key !== key || v94.controller !== controller) return;
  v94.guide = guide; v94.status = guide ? 'ready' : 'absent';
 } catch (error) {
  if (!v94Current(view, basis, epoch) || v94.controller !== controller) return;
  v94.status = 'failed'; v94.error = error?.name === 'AbortError' ? 'research-guide-read-timeout' : String(error?.message || error);
 } finally {
  clearTimeout(timeout);
  if (v94Current(view, basis, epoch) && v94.controller === controller) { v94.controller = null; livePaint(); }
 }
}
const v94OriginalSummary = v93SavedPlanSummary;
v93SavedPlanSummary = function(view) {
 const original = v94OriginalSummary(view), key = v94Key(view, v93Identity());
 if (!original || !key) return original;
 if (v94.key === key && v94.status === 'ready') {
  const count = view.plan.question_plans.reduce((sum, row) => sum + (Array.isArray(row.unknowns) ? row.unknowns.length : 0), 0);
  const question = view.direction_context?.questions?.find(row => row.question_ref === v94.guide.question_ref);
  return `<section class="n9-guide-question"><h2>${rx(question?.text || v94.guide.question_ref)}</h2><p>${rl('以下图解只说明这个问题；原规划、其他问题与全部待查事项保留在下方。','The guide covers this question only. The original plan, other questions and all open checks remain below.','以下圖解只說明這個問題；原規劃、其他問題與全部待查事項保留在下方。')}</p></section><div data-v94-guide>${v94GuideHtml(v94.guide)}</div><details class="n9-plan-details"><summary>${rl('完整原规划与待查事项','Complete saved plan and open checks','完整原規劃與待查事項')} · ${count}</summary>${original}</details>`;
 }
 const status = v94.key === key ? v94.status : 'idle';
 const message = status === 'loading' ? rl('正在读取图解，不会生成研究。','Reading the visual guide; no research will be generated.','正在讀取圖解，不會生成研究。') :
  status === 'failed' ? rl('图解未通过读取或来源核对；下方保留原规划。','The visual guide could not be read or source-verified. The original plan remains below.','圖解未通過讀取或來源核對；下方保留原規劃。') :
  rl('本版本尚未登记研究图解；下方是已保存的完整规划。','No research visual guide is registered for this version. The saved plan is below.','本版本尚未登記研究圖解；下方是已保存的完整規劃。');
 return `<section class="n9-guide-state"><p role="status">${message}</p>${status === 'failed' ? `<details><summary>${rl('读取详情','Read details','讀取詳情')}</summary><p>${rx(v94.error)}</p></details>` : ''}<button class="hs-button" data-v94-read ${status === 'loading' ? 'disabled' : ''}>${rl('重新读取图解','Reload visual guide','重新讀取圖解')}</button></section>${original}`;
};
const v94After = v7AfterRender;
v7AfterRender = function(app) {
 v94After(app); v94.dispose?.(); v94.dispose = null;
 const view = v93.view, basis = v93Identity(), key = app.page === 'workspace' && app.stage === 3 && v93Matches(basis, v93.basis) ? v94Key(view, basis) : null;
 if (!key) { v94.controller?.abort(); Object.assign(v94, {key:null, guide:null, status:'idle', controller:null}); return; }
 const target = app.el.querySelector('[data-v94-guide]');
 if (target && typeof v94ConnectGuide === 'function') v94.dispose = v94ConnectGuide(target);
 if (v94.key !== key) v94Load(view, basis, rt.epoch);
};
document.addEventListener('click', event => {
 if (!event.target.closest('[data-v94-read]') || v94.status === 'loading') return;
 const view = v93.view, basis = v93Identity();
 if (v94Key(view, basis) && v94Current(view, basis, rt.epoch)) { v94Load(view, basis, rt.epoch); livePaint(); }
});
