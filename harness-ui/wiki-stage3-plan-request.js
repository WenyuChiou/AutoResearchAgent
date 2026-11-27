// ---------- Stage 3 「请求生成计划」 (DESIGN 8.13 Stage 3 lower row; 8.0 wording) ----------
// Backend (project_stage3_http.py / project_stage3_planning.py): GET stage3/planning gives default_request and
// dispatch_action "prepare-then-confirm-run". POST …/prepare saves the planning intent with zero model calls and
// returns the job (status intent-recorded, request_sha256). POST …/run with that request, request_sha256 and
// confirmed:true answers 202 and then makes the one planning call (model). POST …/inspect is read-only; POST
// …/recover needs a recovery pin trusted by the Host (recovery_pin_available) and never dispatches again.
// The request key is fixed by the service, so a repeated prepare or run returns the saved job instead of a second
// dispatch; nothing here retries on its own.
// unknown: a run sent from this page whose answer never came back (network, timeout); kept per topic so leaving and
// returning cannot bring the grant card back. Only a read-only inspect settles it (review P1-2).
// check: the request_sha256 of the prepared job the user ticked for; a different prepare voids it (review P2-2).
const wikiS3Req = {busy:'', error:null, ref:null, check:null, inspected:null, unknown:null};
function wikiS3ReqTicked(job) { return !!job?.request_sha256 && wikiS3Req.check === job.request_sha256; }

function wikiS3ReqLock() {
 if (rt.loading) return '正在读取保存记录';
 if (rt.busy || wikiS3Req.busy) return '正在保存，请稍等';
 if (rt.pending) return '上次提交的结果还没确认，先核对';
 if (rt.controlHeld) return '有一条回执还没核对，先到操作历史里核对';
 return '';
}
function wikiS3ReqState(view) {
 if (wikiS3Req.ref !== rt.ref) Object.assign(wikiS3Req, {busy:'', error:null, ref:rt.ref, check:null, inspected:null});
 const job = wikiS3Req.inspected?.key === view?.default_request?.key ? wikiS3Req.inspected : view?.job;
 return {job, error:wikiS3Req.error};
}
// Returns {tone, tag, text, buttons, grant, detail} for the lower row, or null when there is nothing to request.
function wikiS3RequestLine(view) {
 if (!view) return v93.busy ? {tone:'run', tag:'正在读取', text:'正在读取规划状态，不会重新生成', buttons:[]} : null;
 if (view.plan) return null; // saved plan: the block collapses into the status bar (8.13)
 const {job, error} = wikiS3ReqState(view);
 const read = {label:'查看保存状态', act:'read'};
 const lock = wikiS3ReqLock();
 // Only what the planning view itself says decides the gate (review P1-3). Planning has its own profile; the run's
 // run_limits do not bind it, so a "planning configured, all run limits 0" start must not lock this entry.
 const configured = view.planning_configured === true && view.dispatch_action === 'prepare-then-confirm-run' && view.default_request;
 const blockers = Array.isArray(view.planning_blockers) ? view.planning_blockers : [];
 const gate = lock || (view.dispatch_action === 'needs-information' ? '还缺规划需要的信息，原因在技术细节里' : !configured ? '这次启动没有提供规划配置，不能生成计划' : '');
 const detail = [error?.code, view.submission_error?.code, job?.status, job?.outcome, ...blockers.map(item => typeof item === 'string' ? item : JSON.stringify(item))].filter(Boolean);
 // The saved job comes first (review P1-1): a submission_error next to an execution-unknown or completed job must
 // not turn an uncertain or finished result into "blocked", nor hide the read-only check.
 if (view.submission_in_progress || job?.status === 'dispatching') return {tone:'run', tag:'处理中', detail, text:'正在生成计划和评审。不需要你操作', buttons:[read]};
 const inspect = {label:'只读核对', act:'inspect', gate:lock};
 if (job?.status === 'execution-unknown') return {tone:'warn', tag:'结果未知', detail,
  text:'上次生成的结果还不清楚。原请求已保留，不会自动重发；先只读核对' + (view.recovery_pin_available ? '，也可以从已保存的结果恢复' : ''),
  buttons:[inspect, ...(view.recovery_pin_available ? [{label:'从已保存结果恢复', act:'recover', gate:lock}] : []), read]};
 if (job?.status === 'completed' && job.outcome === 'failed') return {tone:'err', tag:'规划失败', detail, text:'规划已失败，原失败记录会保留', buttons:[{label:'看失败记录', act:'failure'}]};
 if (job?.status === 'completed' && job.outcome === 'saved') return {tone:'run', tag:'计划已保存', detail, text:'计划已保存，正在读取', buttons:[read]};
 const unknown = wikiS3Req.unknown?.ref === rt.ref && (!job || job.status === 'intent-recorded') && job?.request_sha256 === wikiS3Req.unknown.sha ? wikiS3Req.unknown : null;
 if (unknown) return {tone:'warn', tag:'结果未知', detail:[unknown.code, ...detail],
  text:'刚才的生成请求没有收到回答，结果还不清楚：模型可能已经调用过。不会重发；先只读核对', buttons:[inspect, read]};
 if (error) return {tone:error.refused ? 'warn' : 'err', tag:error.refused ? '被拦下' : '出错', detail,
  text:(error.refused ? '请求被拒绝：服务没有接受这一步，原来的记录没有变。' : '这一步没有完成；已保存的内容没有丢。') + '原因代码在技术细节里，不会自动重发。', buttons:[read]};
 // A timeout or I/O failure after the run was accepted is an unknown outcome (DESIGN 8.0), never "blocked".
 if (view.submission_error && /deadline-or-io-failed$/.test(String(view.submission_error.code || ''))) return {tone:'warn', tag:'结果未知', detail,
  text:'上次生成的结果还不清楚：模型可能已经调用过。原请求已保留，不会自动重发；先只读核对', buttons:[...(job?.request_sha256 ? [inspect] : []), read]};
 if (view.submission_error) return {tone:'warn', tag:'被拦下', detail, text:'上次生成没有完成，原因代码在技术细节里。原记录保留，不会自动重试', buttons:[read]};
 if (job?.status === 'intent-recorded') return {tone:'wait', tag:'等你授权', detail, text:'请求已保存，还没有调用模型。看过下面的授权，确认后才生成计划',
  buttons:[read], grant:{gate:gate || (wikiS3ReqTicked(job) ? '' : '请先勾选确认')}};
 return {tone:'plain', tag:'还没请求', detail, text:'你选的方向已保存。可以请求生成研究计划', buttons:[{label:'请求生成计划', act:'prepare', primary:true, gate}, read]};
}
function wikiS3RequestMarkup(view) {
 const row = wikiS3RequestLine(view);
 if (!row) return '';
 const buttons = row.buttons.map(button => {
  const off = button.gate ? button.gate : '';
  return `<span><button type="button" class="hs-button${button.primary ? ' hs-button-primary' : ''}" data-s3-plan="${button.act}" ${off ? 'disabled' : ''}>${wikiS3Escape(button.label)}</button>${off ? `<small class="wiki-s2-reason">${wikiS3Escape(off)}</small>` : ''}</span>`;
 }).join('');
 const grant = row.grant ? `<section class="ws-grant" data-s3-plan-grant><span class="ws-label">授权：生成研究计划</span>
  <p><b>会做：</b>按你选的方向调用一次模型，生成研究计划和评审，保存到这个课题。<b>不会做：</b>不检索、不读新的来源、不启动实验；失败不会自动重试。</p>
  <p class="wiki-s1-muted">额度：这一步调用一次模型；规划的调用和时长上限后台没有返回给页面。</p>
  <p class="wiki-s1-muted">授权理由：现在的规划接口没有理由这一项，页面不收集。</p>
  <label class="ws-check"><input type="checkbox" data-s3-plan-check ${wikiS3ReqTicked(wikiS3ReqState(view).job) ? 'checked' : ''}> 我确认只授权这一次、这一件事</label>
  <span><button type="button" class="hs-button hs-button-primary" data-s3-plan="run" ${row.grant.gate ? 'disabled' : ''}>确认生成计划</button>${row.grant.gate ? `<small class="wiki-s2-reason">${wikiS3Escape(row.grant.gate)}</small>` : ''}</span></section>` : '';
 const failure = row.tag === '规划失败' && wikiS3Req.showFailure ? `<details class="wiki-s2-tech" open data-s3-plan-failure><summary>失败记录（原样）</summary><pre>${wikiS3Escape(JSON.stringify(wikiS3ReqState(view).job, null, 2))}</pre></details>` : '';
 const detail = row.detail?.length ? `<details class="wiki-s2-tech"><summary>技术细节</summary>${row.detail.map(code => `<code>${wikiS3Escape(code)}</code>`).join(' ')}</details>` : '';
 return `<hr><div class="wiki-s2-conn-row" data-tone="${row.tone}" data-s3-plan-row><span class="wiki-s2-st" data-tone="${row.tone}">${wikiS3Escape(row.tag)}</span><p>${wikiS3Escape(row.text)}</p><div class="wiki-s2-actions">${buttons}</div></div>${grant}${failure}${detail}`;
}
async function wikiS3PlanAction(app, act) {
 const basis = v93Identity(), view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 if (!view || wikiS3Req.busy) return;
 if (act === 'read') { wikiS3Req.error = null; wikiS3Req.inspected = null; return v93ReadSaved(app, basis); } // the re-read shows the saved state
 if (act === 'failure') { wikiS3Req.showFailure = !wikiS3Req.showFailure; return livePaint(); }
 const ref = basis.project_ref, epoch = rt.epoch, job = wikiS3ReqState(view).job;
 const request = {...view.default_request};
 const body = act === 'prepare' ? request : act === 'run' ? {...request, request_sha256:job?.request_sha256, confirmed:true} : {...request, request_sha256:job?.request_sha256};
 if (act !== 'prepare' && !body.request_sha256) return;
 wikiS3Req.busy = act; wikiS3Req.error = null; livePaint();
 try {
  const answer = await liveRequest(projectPath(ref, 'stage3/planning/' + act), body);
  if (epoch !== rt.epoch || ref !== rt.ref) return;
  const returned = answer?.kind === 'ProjectStage3PlanningSubmission' ? answer.job : answer;
  if (!returned || returned.project_ref !== ref || returned.key !== request.key) throw Error('stage3-planning-receipt-differs');
  if (act === 'inspect' || act === 'recover') wikiS3Req.inspected = returned;
  if (act === 'inspect' && wikiS3Req.unknown?.ref === ref) wikiS3Req.unknown = null; // the read-only check answered
  wikiS3Req.check = null;
 } catch (error) {
  const code = String(error.message || error), refused = Number.isInteger(error.status) && error.status >= 400 && error.status < 500;
  // A run without a clear refusal may have reached the model: unknown outcome, the tick is cleared, no resend.
  if (act === 'run') { wikiS3Req.check = null; if (!refused) wikiS3Req.unknown = {ref, sha:body.request_sha256, code}; }
  if (epoch !== rt.epoch || ref !== rt.ref) return;
  if (!(act === 'run' && !refused)) wikiS3Req.error = {code, refused};
 } finally {
  if (wikiS3Req.ref === ref) wikiS3Req.busy = '';
 }
 // Every outcome is followed by a read-only re-read of the saved state.
 if (epoch === rt.epoch && ref === rt.ref) await v93ReadSaved(app, basis);
}
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-s3-plan]');
 if (!button || button.disabled) return;
 const app = apps.find(item => item.el.contains(button));
 if (!app) return;
 event.preventDefault();
 wikiS3PlanAction(app, button.dataset.s3Plan);
});
document.addEventListener('change', event => {
 if (!event.target.matches?.('[data-s3-plan-check]')) return;
 const basis = v93Identity(), view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 wikiS3Req.check = event.target.checked ? wikiS3ReqState(view).job?.request_sha256 || null : null;
 livePaint();
});
