// ---------- Stage 3 「按修改稿重新生成计划」 (interface: stage3-replan-interface-1127.md; DESIGN 8.0 wording, 8.13) ----------
// Backend (project_stage3_replan.py, project_stage3_http.py): the same prepare | run | inspect routes as the first plan,
// with mode "replan-from-revision". GET stage3/planning carries view.replan = {available, reason, request, job, ...};
// replan.request is the body to send (already holding its key; request_sha256 only once the job exists).
//   prepare: freezes the displayed revision, saves the intent, ZERO model calls. Its body must NOT carry request_sha256.
//   run: needs request_sha256 + confirmed:true, answers 202, then calls the planning model ONCE.
//   inspect: read-only. recover: only where the Host says recovery_pin_available (replan.job / replan.attempts[]); it attaches the
//   already saved result and never resends. The page offers it with its own tick.
// Every refusal is a 4xx written before anything (no checkpoint, no journal); a run refused after the intent
// (revision or decision changed) ends as job outcome "refused-before-call" and never calls the model.
// The edit list shown before the confirmation is the Host's frozen replan.job.revision_input.changes (no list before prepare).
// Older attempts (replan.attempts[]: prepared, refused-before-call, failed, result unknown) stay readable in a history block.
// State is the same shape as wiki-stage3-plan-request.js (review-stage3-plan-request-1127): busy per topic, an unknown
// run outcome per topic, a tick bound to one prepared request_sha256 (and to the edit list shown), nothing resent.
const wikiS3RpMode = 'replan-from-revision';
const wikiS3RpLabel = '按修改稿重新生成计划';
const wikiS3RpFields = [['analysis', '分析'], ['design', '实验设计'], ['interpretation', '结果判读'], ['materials', '资料与参考'],
 ['method', '方法'], ['minimum_deliverable', '最小交付'], ['validation', '验证']]; // sorted by field name, like the backend
const wikiS3RpGeneric = '服务拒绝了这一步，原因代码在技术细节里。';
// Interface table §4 and the shared Stage 3 codes; looked up through a Map so a code like "constructor" is just unknown.
const wikiS3RpCodes = new Map([
 ['stage3-replan-direction-mode-unsupported', '方向意图阶段（还没选定方向）不支持按修改稿重新生成，请先在 Stage 2 选定方向。'],
 ['stage3-replan-revision-required', '还没有手工修订稿，请先用「评语与修订」改计划。'],
 ['stage3-decision-revision-ambiguous', '这份计划有两份并列的修订稿，请先在其中一份基础上继续修订。'],
 ['stage3-replan-revision-changed', '修订稿已经变了（你发的不是当前显示的那份，或准备之后又改过），请刷新后重新决定。'],
 ['stage3-replan-decision-required', '需要先对这份修订稿选择「按建议修改后再评审」。'],
 ['stage3-replan-decision-differs', '这个决定是针对旧的修订稿做的，请对当前这份重新决定。'],
 ['stage3-replan-decision-superseded', '你后来对这份修订稿做了别的决定，不能再按它重新生成计划；如要重新规划，请先重新选择「按建议修改后再评审」。'],
 ['stage3-replan-plan-unreadable', '有一份更新的计划暂时读不出来（通常是系统升级后缺少可信校验值），先不能按这一版再生成，请联系维护者。'],
 ['stage3-decision-newer-plan-unreadable', '有一份更新的计划还读不出来，不能接受这一版；请等维护者恢复那份计划后再决定。'],
 ['stage3-replan-key-payload-differs', '这个操作编号已被另一份内容占用，没有执行；请刷新后再试。'],
 ['stage3-replan-mode-required', '这份作业是按修改稿生成的，只能用「按修改稿重新生成」运行；这次的请求方式不对。'],
 ['stage3-job-not-prepared', '这份作业还没有准备好，请先点「准备」。'],
 ['stage3-planning-unconfigured', '这次启动没有提供规划配置，不能生成计划。'],
 ['stage3-project-version-differs', '课题的版本已经变了，请刷新后再试。'],
 ['stage3-current-selection-required', '需要先有已保存的 Stage 2 选择。'],
 ['stage3-replan-input-too-large', '修订稿加来源材料超过规划上下文上限（48,000 字节）；不会截断，请精简修订稿。'],
 ['stage3-replan-key-differs', '请求编号的校验不对，页面和后台的版本可能不一致；请刷新后再试。'],
 ['stage3-replan-key-reserved', '这个编号留给按修改稿重新生成，普通的「请求生成计划」不能用。'],
 ['stage3-replan-mode-invalid', '请求的格式不对，页面和后台的版本可能不一致。'],
 ['stage3-replan-receipt-invalid', '请求里的回执格式不对，页面和后台的版本可能不一致。'],
 ['intake-fields-invalid', '请求缺少或多了字段，页面和后台的版本可能不一致。'],
 ['explicit-stage3-planning-required', '需要你明确确认后才能运行。'],
 ['credential-rejected', '凭据不对；请从首页用这次启动的地址重新打开。'],
 ['cross-site-rejected', '请求来源不对；请在本机页面里操作。'],
 ['stage3-planning-project-busy', '这个课题的另一次 Stage 3 保存正在进行；稍后再试。'],
 ['stage3-planning-input-rejected', '同时有另一次保存；请重新读取后再试。'],
 ['stage3-planning-body-bound-exceeded', '请求太大，没有执行。'],
 ['stage3-replan-history-ambiguous', '这份计划后面有两份并列的新计划（按修改稿生成），页面停在较早的一份，无法判断该显示哪一份。请联系维护者。'],
 ['trusted-stage3-recovery-pin-required', '后台没有这份作业的可信固定值，不能恢复；请联系维护者。'],
 ['stage3-replan-job-unreadable', '这份重新生成的作业这次读不出来。请联系维护者。']
]);
function wikiS3RpCode(code) { return typeof code === 'string' && wikiS3RpCodes.has(code) ? wikiS3RpCodes.get(code) : wikiS3RpGeneric; }
const wikiS3RpRefusedText = '这次生成在调用模型之前被拒绝（修订稿或决定刚刚变了），没有花额度。请刷新后按当前的修订稿和决定重新请求生成。';

const wikiS3Rp = {busy:new Map(), ref:null, error:null, check:null, recoverCheck:null, inspected:null, unknown:new Map(), notRun:new Map(), notice:null, showFailure:false};
function wikiS3RpSync() {
 if (wikiS3Rp.ref !== rt.ref) Object.assign(wikiS3Rp, {ref:rt.ref, error:null, check:null, recoverCheck:null, inspected:null, notice:null, showFailure:false});
}
function wikiS3RpObj(value) { return !!value && typeof value === 'object' && !Array.isArray(value); }

// The edit list is the server's frozen one: revision_input.changes of the prepared job (it is part of the job payload,
// so of the request_sha256 that run is bound to, and of the prompt). The page never recomputes it; before prepare there is none.
function wikiS3RpFrozen(input) {
 if (!wikiS3RpObj(input) || !Array.isArray(input.changes)) return {known:false, changes:[], comments:[], json:''};
 const changes = input.changes.filter(item => wikiS3RpObj(item) && typeof item.question_ref === 'string' && typeof item.field === 'string' && typeof item.researcher_value === 'string');
 return {known:changes.length === input.changes.length, changes, comments:Array.isArray(input.comments) ? input.comments.filter(wikiS3RpObj) : [], json:JSON.stringify(input.changes)};
}
function wikiS3RpEdits(view) { return wikiS3RpFrozen(wikiS3RpState(view).job?.revision_input); }
function wikiS3RpQuestion(view, ref) {
 const hit = list => Array.isArray(list) ? list.find(item => item?.question_ref === ref)?.text : '';
 const text = hit(view?.direction_context?.questions) || hit(view?.plan?.questions);
 return typeof text === 'string' && text.trim() ? text.trim() : '';
}
function wikiS3RpEditsGate(edits) {
 if (!edits.known) return '后台没有给出这份作业冻结的修改清单（revision_input.changes），页面不自己拼，不能确认';
 if (!edits.changes.length) return '后台冻结的修改清单是空的，没有要送出的修改';
 return '';
}
function wikiS3RpRecoverTicked(sha) { return typeof sha === 'string' && !!sha && wikiS3Rp.recoverCheck === sha; }
function wikiS3RpTicked(job, edits) { return !!job?.request_sha256 && !!edits.known && !!wikiS3Rp.check && wikiS3Rp.check.sha === job.request_sha256 && wikiS3Rp.check.edits === edits.json; }

function wikiS3RpLock() {
 if (rt.loading || v93.busy) return '正在读取保存记录';
 if (rt.busy || wikiS3Rp.busy.has(rt.ref)) return '正在保存，请稍等';
 if (typeof wikiS3Dec !== 'undefined' && wikiS3Dec.busy?.has(rt.ref)) return '正在保存你的决定，请稍等';
 if (rt.pending) return '上次提交的结果还没确认，先核对';
 if (rt.controlHeld) return '有一条回执还没核对，先到操作历史里核对';
 return '';
}
function wikiS3RpState(view) {
 wikiS3RpSync();
 const key = view?.replan?.request?.key;
 const listed = view?.replan?.job && !view.replan.job.error ? view.replan.job : null;
 return {job:listed || (wikiS3Rp.inspected && wikiS3Rp.inspected.key === key ? wikiS3Rp.inspected : null), error:wikiS3Rp.error};
}
// Returns {tone, tag, text, buttons, grant, edits, detail, notice} for the replan spot, or null when there is no saved plan.
function wikiS3RpLine(view) {
 if (!view?.plan) return null;
 const {job, error} = wikiS3RpState(view), replan = view.replan;
 const read = {label:'查看保存状态', act:'read'}, lock = wikiS3RpLock();
 const notice = wikiS3Rp.notice?.ref === rt.ref ? {tag:'已拒绝，没有调用模型', text:wikiS3RpRefusedText} : null;
 const entry = gate => ({label:wikiS3RpLabel, act:'prepare', primary:true, gate});
 const base = {detail:[error?.code, view.replan_error, typeof replan?.error === 'string' ? replan.error : '', replan?.job?.error, replan && replan.available === false ? replan.reason : '', job?.status, job?.outcome].filter(Boolean), notice};
 if (!replan) return {...base, tone:'idle', tag:'还不能生成', text:'现在不能按修改稿重新生成。', buttons:[entry(wikiS3RpCode('stage3-replan-revision-required'))]};
 if (typeof replan.error === 'string') return {...base, tone:'warn', tag:'读不出来', text:'按修改稿重新生成的状态这次读不出来（决定日志校验没有通过）。原计划、评语和已保存的决定没有被改。', buttons:[read]};
 if (replan.job?.error) return {...base, tone:'warn', tag:'读不出来', text:wikiS3RpCode(replan.job.error) + '不会重发；原请求保留。', buttons:[read]};
 if (replan.available !== true) return {...base, tone:'idle', tag:'还不能生成', text:'现在不能按修改稿重新生成，原因见按钮下面的说明。', buttons:[entry(wikiS3RpCode(replan.reason))]};
 const request = replan.request;
 if (!wikiS3RpObj(request) || request.mode !== wikiS3RpMode || typeof request.key !== 'string' || !request.key) return {...base, tone:'warn', tag:'读不出来', text:'后台说可以重新生成，但没有给出可发送的请求，页面不发。', buttons:[read]};
 const edits = wikiS3RpEdits(view), editsGate = wikiS3RpEditsGate(edits), inspect = {label:'只读核对', act:'inspect', gate:lock};
 const mine = wikiS3Rp.unknown.get(rt.ref);
 // Processing only while a submission is really under way (the Host says so, or this page's own request is in flight). A job left in
 // dispatching with none is a result unknown: the call may have gone out (the Host counts dispatching as result_unknown, recover accepts it).
 if (view.submission_in_progress || wikiS3Rp.busy.has(rt.ref)) return {...base, edits, tone:'run', tag:'处理中', text:'正在按修改稿重新生成计划和评审。不需要你操作', buttons:[read]};
 if (job?.status === 'execution-unknown' || job?.status === 'dispatching') {
  const pin = job.recovery_pin_available === true;
  return {...base, edits, tone:'warn', tag:'结果未知', recoverSha:pin ? job.request_sha256 : null,
   text:'上次生成的结果还不清楚：模型可能已经调用过。原请求已保留，不会自动重发；先只读核对' + (pin ? '，也可以从已保存的结果恢复（只挂上已经保存的结果，不会重新生成）' : ''),
   buttons:[inspect, ...(pin ? [{label:'从已保存结果恢复', act:'recover', gate:lock || (wikiS3RpRecoverTicked(job.request_sha256) ? '' : '请先勾选确认')}] : []), read]};
 }
 if (job?.status === 'completed' && job.outcome === 'failed') return {...base, edits, tone:'err', tag:'规划失败', text:'规划已失败，原失败记录会保留', buttons:[{label:'看失败记录', act:'failure'}]};
 if (job?.status === 'completed' && job.outcome === 'refused-before-call') return {...base, edits, tone:'warn', tag:'已拒绝，没有调用模型', text:wikiS3RpRefusedText, buttons:[read], notice:null};
 if (job?.status === 'completed' && job.outcome === 'saved') return {...base, edits, tone:'run', tag:'计划已保存', text:'新计划已保存，正在读取', buttons:[read]};
 // A job in a state this page does not know is never turned into a request button.
 if (job && job.status !== 'intent-recorded') return {...base, edits, tone:'warn', tag:'状态没认出来', text:'这份作业的状态页面不认识，不会发任何请求；状态码在技术细节里', buttons:[read]};
 const unknown = mine && job?.status === 'intent-recorded' && job.request_sha256 === mine.sha ? mine : null;
 if (unknown) return {...base, edits, tone:'warn', tag:'结果未知', detail:[unknown.code, ...base.detail], text:'刚才的生成请求没有收到回答，结果还不清楚：模型可能已经调用过。不会重发；先只读核对', buttons:[inspect, read]};
 if (error && !error.target) {
  const ran = error.act === 'run';
  return {...base, edits, tone:error.refused ? 'warn' : 'err', tag:error.refused ? (ran ? '已拒绝，没有调用模型' : '被拦下') : '出错',
   text:error.refused ? wikiS3RpCode(error.code) + (ran ? '没有调用模型，原来的记录没有变。' : '没有保存任何东西，也没有调用模型。') : '这一步没有完成；已保存的内容没有丢。原因代码在技术细节里，不会自动重发。', buttons:[read]};
 }
 const sub = wikiS3RpObj(view.submission_error) && (view.submission_error.key === undefined || view.submission_error.key === request.key) ? view.submission_error : null;
 const settled = job?.status === 'intent-recorded' && !!job.request_sha256 && wikiS3Rp.notRun.get(rt.ref) === job.request_sha256 && (!sub || sub.request_sha256 === job.request_sha256);
 if (sub && !settled && /deadline-or-io-failed$/.test(String(sub.code || ''))) return {...base, edits, detail:[sub.code, ...base.detail], tone:'warn', tag:'结果未知', text:'上次生成的结果还不清楚：模型可能已经调用过。原请求已保留，不会自动重发；先只读核对', buttons:[...(job?.request_sha256 ? [inspect] : []), read]};
 if (sub && !settled) return {...base, edits, detail:[sub.code, ...base.detail], tone:'warn', tag:'被拦下', text:'上次生成没有完成：' + wikiS3RpCode(sub.code) + '原记录保留，不会自动重试', buttons:[read]};
 if (job?.status === 'intent-recorded') return {...base, edits, tone:'wait', tag:'等你授权',
  text:settled && sub ? '只读核对确认：上次在调用模型之前就停了，没有执行。要生成计划，请重新看过下面的修改并勾选确认' : '请求已准备好（没有调用模型、没有花额度）。看过下面要送给规划模型的每一处修改，确认后才生成计划',
  buttons:[read], grant:{gate:lock || editsGate || (wikiS3RpTicked(job, edits) ? '' : '请先勾选确认')}};
 return {...base, edits, tone:'plain', tag:'还没请求', text:'你的决定是「按建议修改后再评审」，修订稿也改过了。可以按修改稿重新生成计划：先准备（不调用模型、不花额度），准备后后台会给出要送给规划模型的修改清单，你看过再确认', buttons:[entry(lock)]};
}
function wikiS3RpEditsMarkup(view, edits) {
 if (!edits.known) return '<p class="wiki-s1-muted" data-s3-rp-edits-unknown>后台没有给出这份作业冻结的修改清单，页面不自己拼，所以没有清单可看。</p>';
 if (!edits.changes.length) return '<p class="wiki-s1-muted" data-s3-rp-edits-none>后台冻结的修改清单是空的，没有要送出的修改。</p>';
 const label = new Map(wikiS3RpFields);
 const value = (name, text) => `<div class="ws3-rp-val"><span>${name}</span><pre>${text ? wikiS3Escape(text) : '<i>（空）</i>'}</pre></div>`;
 const items = edits.changes.map(change => {
  const title = wikiS3RpQuestion(view, change.question_ref);
  return `<li data-s3-rp-edit><b>问题：</b>${title ? wikiS3Escape(title) + ' ' : ''}<code>${wikiS3Escape(change.question_ref)}</code> · <b>项目：</b>${wikiS3Escape(label.get(change.field) || '（未知项目）')} <code>${wikiS3Escape(change.field)}</code>
   ${value('原值（模型生成的上一版）', change.model_value)}${value('你的修改', change.researcher_value)}</li>`;
 }).join('');
 const comments = edits.comments.length ? `<h4>同时送出的评语（${edits.comments.length}）</h4><ul class="ws3-rp-comments">${edits.comments.map(item => `<li data-s3-rp-comment>${item.question_ref ? `<code>${wikiS3Escape(item.question_ref)}</code> ` : ''}${wikiS3Escape(item.text)}</li>`).join('')}</ul>` : '';
 return `<div class="ws3-rp-edits" data-s3-rp-edits><h4>将送给规划模型的修改（共 ${edits.changes.length} 处）</h4><p class="wiki-s1-muted">这份清单是后台在「准备」时冻结的，「确认」绑定的就是它。只有这些修改和评语算你的输入；修订稿附带的材料引用不会送出，更早几轮修订引用的评语也不会送出。规划模型要在新计划里对每一处写明采纳或不采纳，不保证采纳。</p><ol>${items}</ol>${comments}</div>`;
}

// Older attempts (replan.attempts[], read-only): shown even after a new decision changed the key. A result-unknown one is
// only checked read-only; recovery (attach the saved result, never a resend) is offered only where the Host says
// recovery_pin_available, with its own tick. Nothing here can start a run.
function wikiS3RpAttempts(view) {
 const list = Array.isArray(view?.replan?.attempts) ? view.replan.attempts : [];
 const current = view?.replan?.request?.key;
 return list.filter(item => wikiS3RpObj(item) && typeof item.key === 'string' && typeof item.request_sha256 === 'string' && item.key !== current);
}
function wikiS3RpAttemptRow(item, lock) {
 const unknown = item.result_unknown === true, pin = unknown && item.recovery_pin_available === true;
 const buttons = unknown ? [{label:'只读核对', act:'inspect', gate:lock}, ...(pin ? [{label:'从已保存结果恢复', act:'recover', gate:lock || (wikiS3RpRecoverTicked(item.request_sha256) ? '' : '请先勾选确认')}] : [])] : [];
 let tone = 'warn', tag, text;
 if (wikiS3RpObj(item.job) && typeof item.job.error === 'string') { tag = '读不出来'; text = wikiS3RpCode(item.job.error) + '不会重发。'; }
 else if (unknown) { tag = '结果未知'; text = '调用可能已经发出、额度可能已经花掉；只能只读核对，不会重发' + (pin ? '，也可以从已保存的结果恢复（只挂上已经保存的结果）' : '') + '。'; }
 else if (item.outcome === 'refused-before-call') { tag = '已拒绝，没有调用模型'; text = '这次在调用模型之前被拒绝，没有花额度。'; }
 else if (item.outcome === 'failed') { tone = 'err'; tag = '规划失败'; text = '这次调用过模型，规划失败；失败记录保留。'; }
 else if (item.status === 'intent-recorded') { tone = 'wait'; tag = '已准备，没运行'; text = '这份作业只准备过，没有调用模型。'; }
 else { tag = '状态没认出来'; text = '这份旧作业的状态页面不认识，不会发任何请求。'; }
 return {tone, tag, text, buttons, recoverSha:pin ? item.request_sha256 : null};
}
function wikiS3RpRecoverBox(sha) {
 return `<label class="ws-check" data-s3-rp-recover><input type="checkbox" data-s3-rp-recover-check data-s3-rp-sha="${wikiS3Escape(sha)}" ${wikiS3RpRecoverTicked(sha) ? 'checked' : ''}> 我确认：只把已经保存的结果挂上，不会重新生成，也不会再调用模型</label>`;
}
function wikiS3RpHistory(view) {
 const items = wikiS3RpAttempts(view), omitted = Number.isSafeInteger(view?.replan?.attempts_omitted) ? view.replan.attempts_omitted : 0;
 if (!items.length && !omitted) return '';
 const lock = wikiS3RpLock();
 const err = wikiS3Rp.error?.target ? `<div class="wiki-s2-conn-row" data-tone="warn" data-s3-rp-history-error><span class="wiki-s2-st" data-tone="warn">${wikiS3Rp.error.refused ? '被拦下' : '出错'}</span><p>${wikiS3Escape(wikiS3Rp.error.refused ? wikiS3RpCode(wikiS3Rp.error.code) + '没有重发，原记录没有变。' : '这一步没有完成；原记录没有变，不会自动重发。')}</p></div><details class="wiki-s2-tech"><summary>技术细节</summary><code>${wikiS3Escape(wikiS3Rp.error.code)}</code></details>` : '';
 const rows = items.map(item => {
  const row = wikiS3RpAttemptRow(item, lock);
  const buttons = row.buttons.map(button => `<span><button type="button" class="hs-button" data-s3-rp="${button.act}" data-s3-rp-target="${wikiS3Escape(item.key)}" ${button.gate ? 'disabled' : ''}>${wikiS3Escape(button.label)}</button>${button.gate ? `<small class="wiki-s2-reason" data-s3-rp-why>${wikiS3Escape(button.gate)}</small>` : ''}</span>`).join('');
  const frozen = wikiS3RpFrozen(item.revision_input);
  const list = frozen.known && frozen.changes.length ? `<details class="wiki-s2-tech"><summary>当时冻结的修改清单（${frozen.changes.length} 处，只读）</summary>${wikiS3RpEditsMarkup(view, frozen)}</details>` : '';
  const codes = [item.key, item.status, item.outcome].filter(code => typeof code === 'string' && code);
  return `<li data-s3-rp-attempt="${wikiS3Escape(item.key)}"><div class="wiki-s2-conn-row" data-tone="${row.tone}"><span class="wiki-s2-st" data-tone="${row.tone}">${wikiS3Escape(row.tag)}</span><p>${wikiS3Escape(row.text)}</p><div class="wiki-s2-actions">${buttons}</div></div>${row.recoverSha ? wikiS3RpRecoverBox(row.recoverSha) : ''}${list}<details class="wiki-s2-tech"><summary>技术细节</summary>${codes.map(code => `<code>${wikiS3Escape(code)}</code>`).join(' ')}</details></li>`;
 }).join('');
 return `<div class="ws3-rp-history" data-s3-rp-history><h4>以前按修改稿生成的作业（只读，共 ${items.length} 份）</h4>${omitted ? `<p class="wiki-s1-muted">另有 ${omitted} 份更早的没有列出。</p>` : ''}${err}<ul>${rows}</ul></div>`;
}
function wikiS3RpMarkup(view) {
 const row = wikiS3RpLine(view);
 if (!row) return '';
 const buttons = row.buttons.map(button => {
  const off = button.gate || '';
  return `<span><button type="button" class="hs-button${button.primary ? ' hs-button-primary' : ''}" data-s3-rp="${button.act}" ${off ? 'disabled' : ''}>${wikiS3Escape(button.label)}</button>${off ? `<small class="wiki-s2-reason" data-s3-rp-why>${wikiS3Escape(off)}</small>` : ''}</span>`;
 }).join('');
 const job = wikiS3RpState(view).job;
 const notice = row.notice ? `<div class="wiki-s2-conn-row" data-tone="warn" data-s3-rp-notice><span class="wiki-s2-st" data-tone="warn">${wikiS3Escape(row.notice.tag)}</span><p>${wikiS3Escape(row.notice.text)}</p></div>` : '';
 const showEdits = row.edits && row.tag === '等你授权';
 // After the grant stage the same frozen list stays readable (what was or would have been sent).
 const frozen = !showEdits && row.edits?.known && row.edits.changes.length ? `<details class="wiki-s2-tech" data-s3-rp-frozen><summary>当时冻结的修改清单（${row.edits.changes.length} 处，只读）</summary>${wikiS3RpEditsMarkup(view, row.edits)}</details>` : '';
 const recoverBox = row.recoverSha ? wikiS3RpRecoverBox(row.recoverSha) : '';
 const grant = row.grant ? `<section class="ws-grant" data-s3-rp-grant><span class="ws-label">授权：按修改稿重新生成计划</span>
  <p><b>会做：</b>把上面列出的修改和评语，连同你修改后的计划，交给规划模型调用一次，重新生成研究计划和评审。新计划保存后会替换页面上显示的计划，原来的计划、评语、修订和决定保留为历史。<b>不会做：</b>不检索、不读新的来源、不带修订稿附的材料、不启动实验；失败不会自动重试。</p>
  <p class="wiki-s1-muted">额度：准备这一步没有调用模型；确认后这一步调用一次模型，规划的调用和时长上限后台没有返回给页面。</p>
  <p class="wiki-s1-muted">授权理由：现在的规划接口没有理由这一项，页面不收集。</p>
  <label class="ws-check"><input type="checkbox" data-s3-rp-check ${wikiS3RpTicked(job, row.edits) ? 'checked' : ''}> 我看过上面每一处修改，确认只授权这一次、这一件事</label>
  <span><button type="button" class="hs-button hs-button-primary" data-s3-rp="run" ${row.grant.gate ? 'disabled' : ''}>确认按修改稿生成计划</button>${row.grant.gate ? `<small class="wiki-s2-reason" data-s3-rp-why>${wikiS3Escape(row.grant.gate)}</small>` : ''}</span></section>` : '';
 const failure = row.tag === '规划失败' && wikiS3Rp.showFailure ? `<details class="wiki-s2-tech" open data-s3-rp-failure><summary>失败记录（原样）</summary><pre>${wikiS3Escape(JSON.stringify(job, null, 2))}</pre></details>` : '';
 const detail = row.detail?.length ? `<details class="wiki-s2-tech"><summary>技术细节</summary>${row.detail.map(code => `<code>${wikiS3Escape(code)}</code>`).join(' ')}</details>` : '';
 return `<div class="ws3-replan" data-s3-replan><h3>${wikiS3RpLabel}</h3>${notice}<div class="wiki-s2-conn-row" data-tone="${row.tone}" data-s3-rp-row><span class="wiki-s2-st" data-tone="${row.tone}">${wikiS3Escape(row.tag)}</span><p>${wikiS3Escape(row.text)}</p><div class="wiki-s2-actions">${buttons}</div></div>${showEdits ? wikiS3RpEditsMarkup(view, row.edits) : ''}${recoverBox}${grant}${frozen}${failure}${detail}${wikiS3RpHistory(view)}</div>`;
}
// Notices shown above the decision block whatever the latest decision is: a newer plan that cannot be read, and the
// interface's own reason texts (§7). The error code stays in the technical details; an unknown code gets the generic text.
const wikiS3RpUnreadable = new Map([
 ['stage3-replan-plan-environment-changed', '有一份更新的计划（按修改稿生成）因为系统升级暂时读不出来，计划本身没有损坏。下面显示的是它之前的那一版；请联系维护者为它补上校验值后即可恢复。'],
 ['stage3-replan-plan-data-damaged', '有一份更新的计划（按修改稿生成）的保存数据对不上，可能被改动或丢失，已停止使用它。下面显示的是它之前的那一版；请联系维护者检查。']
]);
function wikiS3RpNotices(view) {
 if (!view) return '';
 const line = (text, codes) => `<div class="wiki-s2-conn-row" data-tone="warn" data-s3-rp-unreadable><span class="wiki-s2-st" data-tone="warn">读不出来</span><p>${wikiS3Escape(text)}</p></div>${codes.filter(Boolean).length ? `<details class="wiki-s2-tech"><summary>技术细节</summary>${codes.filter(Boolean).map(code => `<code>${wikiS3Escape(code)}</code>`).join(' ')}</details>` : ''}`;
 let out = '';
 const rows = Array.isArray(view.unreadable_plans) ? view.unreadable_plans.filter(wikiS3RpObj) : [];
 for (const item of rows) {
  const known = typeof item.error === 'string' && wikiS3RpUnreadable.has(item.error);
  out += line((known ? wikiS3RpUnreadable.get(item.error) : '有一份更新的计划（按修改稿生成）暂时读不出来，原因代码在技术细节里。下面显示的是它之前的那一版；请联系维护者。')
   + ' 你仍可以写评语、修订和做决定，但暂时不能接受这一版，也不能再按修改稿生成。', [item.error, item.error_class, item.key, item.request_sha256]);
 }
 if (!rows.length && view.host_decision?.newer_plan_unreadable === true) out += line(wikiS3RpCode('stage3-decision-newer-plan-unreadable'), []);
 if (typeof view.replan_error === 'string') out += line(wikiS3RpCode(view.replan_error), [view.replan_error]);
 return out ? `<div class="ws3-rp-notices" data-s3-rp-notices>${out}</div>` : '';
}

async function wikiS3RpAction(app, act, target = '') {
 const basis = v93Identity(), view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 if (!view || wikiS3Rp.busy.has(basis.project_ref)) return; // one request per topic: a double click sends one
 wikiS3RpSync();
 if (act === 'read') { wikiS3Rp.error = null; wikiS3Rp.inspected = null; wikiS3Rp.notice = null; return v93ReadSaved(app, basis); }
 if (act === 'failure') { wikiS3Rp.showFailure = !wikiS3Rp.showFailure; return livePaint(); }
 // The gate is checked again right before sending: the button may have been drawn before the state changed.
 // An older attempt (history block) can only be checked read-only or recovered; never run or prepared.
 const attempt = target ? wikiS3RpAttempts(view).find(item => item.key === target) : null;
 if (target && (!attempt || !['inspect', 'recover'].includes(act))) return;
 const row = attempt ? wikiS3RpAttemptRow(attempt, wikiS3RpLock()) : wikiS3RpLine(view);
 const offered = row?.buttons.find(button => button.act === act);
 if (act === 'run' ? !(row?.tag === '等你授权' && row.grant && !row.grant.gate) : !offered || offered.gate) return;
 const ref = basis.project_ref, epoch = rt.epoch, job = wikiS3RpState(view).job;
 let request;
 if (attempt) {
  const {key, request_sha256, ...source} = wikiS3RpObj(view.default_request) ? view.default_request : {};
  const input = attempt.revision_input;
  if (!key || !wikiS3RpObj(input)) return;
  request = {...source, mode:wikiS3RpMode, key:attempt.key, decision_receipt_sha256:input.decision_receipt_sha256, plan_revision_receipt_sha256:input.plan_revision_receipt_sha256};
 } else { const {request_sha256, ...rest} = view.replan.request; request = rest; } // prepare must not carry request_sha256
 const sha = attempt ? attempt.request_sha256 : job?.request_sha256;
 const body = act === 'prepare' ? request : act === 'run' ? {...request, request_sha256:sha, confirmed:true} : {...request, request_sha256:sha};
 if (act !== 'prepare' && !body.request_sha256) return;
 wikiS3Rp.busy.set(ref, act); wikiS3Rp.error = null; if (act === 'prepare') wikiS3Rp.notice = null; livePaint();
 try {
  const answer = await liveRequest(projectPath(ref, 'stage3/planning/' + act), body);
  if (epoch !== rt.epoch || ref !== rt.ref) return;
  const returned = answer?.kind === 'ProjectStage3PlanningSubmission' ? answer.job : answer;
  if (!returned || returned.project_ref !== ref || returned.key !== body.key) throw Error('stage3-planning-receipt-differs');
  // The unknown / not-run / inspected marks belong to the current request only; an older attempt only gets its re-read.
  if (!attempt && (act === 'inspect' || act === 'recover')) wikiS3Rp.inspected = returned;
  if (!attempt && act === 'inspect') wikiS3Rp.unknown.delete(ref); // the read-only check answered
  if (!attempt && act === 'inspect' && returned.status === 'intent-recorded' && returned.request_sha256) wikiS3Rp.notRun.set(ref, returned.request_sha256);
  else if (!attempt && act === 'inspect') wikiS3Rp.notRun.delete(ref);
  if (act === 'run') wikiS3Rp.notRun.delete(ref);
  if (act === 'run' && returned.status === 'completed' && returned.outcome === 'refused-before-call') wikiS3Rp.notice = {ref, key:body.key};
  wikiS3Rp.check = null; wikiS3Rp.recoverCheck = null;
 } catch (error) {
  const code = String(error.message || error), refused = Number.isInteger(error.status) && error.status >= 400 && error.status < 500;
  // A run without a clear refusal may have reached the model: unknown outcome, the tick is cleared, no resend.
  if (act === 'recover') wikiS3Rp.recoverCheck = null;
  if (act === 'run') { wikiS3Rp.check = null; wikiS3Rp.notRun.delete(ref); if (!refused) wikiS3Rp.unknown.set(ref, {sha:body.request_sha256, code}); }
  if (epoch !== rt.epoch || ref !== rt.ref) return;
  if (!(act === 'run' && !refused)) wikiS3Rp.error = {code, refused, act, target:attempt ? attempt.key : ''};
 } finally {
  wikiS3Rp.busy.delete(ref);
 }
 // Every outcome is followed by a forced read-only re-read of the saved state.
 if (epoch === rt.epoch && ref === rt.ref) await v93ReadSaved(app, basis, true);
}
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-s3-rp]');
 if (!button || button.disabled) return;
 const app = apps.find(item => item.el.contains(button));
 if (!app) return;
 event.preventDefault();
 wikiS3RpAction(app, button.dataset.s3Rp, button.dataset.s3RpTarget || '');
});
document.addEventListener('change', event => {
 if (!event.target.matches?.('[data-s3-rp-recover-check]')) return;
 const sha = event.target.dataset?.s3RpSha, basis = v93Identity(), view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 // Only a request_sha256 the page itself lists (the current job or an older attempt) can be ticked.
 const known = [wikiS3RpState(view).job?.request_sha256, ...wikiS3RpAttempts(view).map(item => item.request_sha256)];
 wikiS3Rp.recoverCheck = event.target.checked && typeof sha === 'string' && known.includes(sha) ? sha : null;
 livePaint();
});
document.addEventListener('change', event => {
 if (!event.target.matches?.('[data-s3-rp-check]')) return;
 const basis = v93Identity(), view = basis && v93Matches(v93.basis, basis) ? v93.view : null;
 const job = wikiS3RpState(view).job, edits = wikiS3RpEdits(view);
 wikiS3Rp.check = event.target.checked && job?.request_sha256 && edits.known ? {sha:job.request_sha256, edits:edits.json} : null;
 livePaint();
});
