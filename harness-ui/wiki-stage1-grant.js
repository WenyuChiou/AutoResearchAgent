// Wiki V1 Stage 1 run grant (DESIGN 8.6 case 4c, 8.7 quota bar). Loaded after wiki-stage1-ops.js.
// The researcher writes the authorization words and ticks the consent boxes here; nothing is inferred from
// the launch limits. Reads use GET stage1-run-grant (never writes); the only write is POST stage1-run-grant.
const WSG_LIMIT_NAMES = [['model_calls', '模型调用'], ['search_calls', '检索'], ['source_reads', '读取来源'], ['rounds', '轮数'], ['seconds', '总秒数']];
const WSG_OPS = [
 ['query', '检索（联网搜索公开文献）'], ['source', '取原文（读取公开来源）'], ['analyze-full-paper', '模型阅读全文'],
 ['records', '整理记录'], ['delivery', '生成交付']];
const WSG_REASONS = {
 'stage1-run-grant-zero-limits': '这次启动的运行上限是 0（或没有可用秒数），不会创建运行许可。要真实运行，需带非零的 --run-limits 重新启动。',
 'stage1-run-grant-not-enabled': '这次启动没有开启整轮运行（--enable-stage1-run，需要内容模型和公开来源），所以不能创建运行许可。',
 'stage1-run-grant-scope-not-ready': '这个课题还没有确认范围或检索计划，先确认范围。',
 'stage1-run-grant-renewal-refused': '这个版本已经有运行许可（有效、已过期或已撤销都算），不会续期或重复创建。',
 'stage1-run-grant-verification-required': '已保存的运行许可没有通过核对，暂时不能创建新的。'};
const WSG_STATUS = {active: ['done', '有效'], expired: ['block', '已过期'], revoked: ['err', '已撤销'], stale: ['block', '绑定的是旧版本'],
 invalid: ['err', '记录核对不通过'], 'clock-regressed': ['err', '时钟倒退，已停用'], none: ['idle', '还没有']};
const WSG_MAX_BYTES = 4096; // what the service accepts for an authorization reason
const WSG_LEASE = {open: '未用完', expired: '已过期', revoked: '已撤销', unreadable: '读不到租约记录', 'clock-regressed': '时钟倒退，已停用'};
const WSG_GRANT_REASONS = {'stage1-run-grant-ambiguous': '有不止一份许可对得上当前版本，服务没有选其中一份', 'stage1-run-grant-verification-required': '已保存的运行许可没有通过核对'};
const wsgForms = new Map();

function wsgFormFor(ref) {
 let form = wsgForms.get(ref);
 if (!form) {
  form = {ref, words: '', confirmed: false, ops: null, seconds: '', actions: '64', search: false, source: false,
   key: null, busy: false, result: null, reasons: {}};
  wsgForms.set(ref, form);
 }
 return form;
}
function wsgLimits() { return rt.meta?.run_limits || null; }
function wsgPositive(value) { return Number.isSafeInteger(value) && value > 0; }
function wsgZero() {
 const limits = wsgLimits();
 return !limits || !wsgPositive(limits.seconds) || !Object.values(limits).some(wsgPositive);
}
function wsgBytes(text) { return new TextEncoder().encode(text || '').length; }
// Every authorization card has its own reason box and its own confirmation: one reason is never reused.
const WSG_REASON_BUTTONS = {
 'authorize-plan': '[data-real-action="authorize-plan"]',
 'query-authorize': '[data-real-action="query-authorize"]',
 'followup-authorize': '[data-v7-workflow="followup-authorize"]'};
const WSG_REASON_TITLES = {
 'authorize-plan': '只授权这一次检索规划（Codex 规划查询，不检索）',
 'query-authorize': '只授权这一次已保存查询',
 'followup-authorize': '只授权这一次内容问答'};
function wsgReasonFor(action) {
 const form = wsgFormFor(rt.ref);
 return form.reasons[action] || (form.reasons[action] = {words: '', confirmed: false});
}
function wsgReasonGate(action) {
 const reason = wsgReasonFor(action);
 if (!reason.words.trim()) return '先写下你的授权理由（原话）';
 if (wsgBytes(reason.words) > WSG_MAX_BYTES) return `授权理由超过 ${WSG_MAX_BYTES} 字节`;
 if (!reason.noConfirm && !reason.confirmed) return '先勾选「我确认只授权这一件事」';
 return '';
}
// The words for one authorization, verbatim; empty unless written and confirmed on that card.
function wsgActionWords(action) {
 return wsgReasonGate(action) ? '' : wsgReasonFor(action).words;
}
function wsgClearReason(action) {
 delete wsgFormFor(rt.ref).reasons[action];
}
function wsgLang(app) { return app?.lang || 'zh'; }
function wsgText(app, zh, en, tw) { return ({zh, en, tw})[wsgLang(app)] || zh; }

// What the researcher ticked at scope confirmation. A lane is only consented when ticked and the launch allows it.
function wsgScopeConsent() {
 const form = wsgFormFor(rt.ref), limits = wsgLimits() || {};
 return {
  external_search: form.search === true && wsgPositive(limits.seconds) && wsgPositive(limits.search_calls),
  public_source_read: form.source === true && wsgPositive(limits.seconds) && wsgPositive(limits.source_reads),
  browser_fallback: false};
}
function wsgFmtTime(value) {
 const at = typeof value === 'number' ? value * 1000 : Date.parse(value);
 return Number.isFinite(at) ? new Date(at).toLocaleString('zh-CN', {hour12: false}) : '未提供';
}
function wsgDuration(seconds) {
 if (!Number.isFinite(seconds)) return '未提供';
 if (seconds <= 0) return '0 秒';
 const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), rest = Math.floor(seconds % 60);
 return [hours ? hours + ' 小时' : '', minutes ? minutes + ' 分' : '', !hours && rest ? rest + ' 秒' : ''].filter(Boolean).join(' ');
}

// ---------- scope page: explicit consent boxes (replaces "limit > 0 means consent") ----------
function wsgConsentRow(field, key, label, count, detail) {
 const form = wsgFormFor(rt.ref), limits = wsgLimits(), allowed = wsgPositive(limits?.seconds) && wsgPositive(count);
 const why = allowed ? '' : '这次启动的这项上限是 0，不能勾选；要用需带非零的 --run-limits 重新启动';
 return `<label class="ws-check"><input type="checkbox" data-wsg-consent="${field}" ${form[key] && allowed ? 'checked' : ''} ${allowed ? '' : 'disabled'}>
 <span><b>${label}</b>：${detail(count, limits?.seconds)}${why ? `<small class="ws-why" role="note">${esc(why)}</small>` : ''}</span></label>`;
}
function wsgConsentCard() {
 const limits = wsgLimits();
 const zero = wsgZero();
 return `<section class="decide ws-decide ws-grant-consent" data-wsg-consent-card><span class="ws-label">同意项（由你勾选）</span>
 <h2>这个课题允许联网吗</h2>
 <p>下面两项不勾，课题保存后就不会联网检索，也不能用它们创建运行许可。勾了不等于马上开始，只是把「同意」写进课题。</p>
 ${zero ? '<p class="ws-blocked">这次启动的运行上限是 0：两项都不能勾，课题只能做不花额度的步骤。</p>' : ''}
 ${wsgConsentRow('external_search', 'search', '同意外部检索', limits?.search_calls,
  (n, s) => `勾选表示：这个课题可以联网检索公开文献，最多 <code>${esc(n)}</code> 次检索，总共最多 <code>${esc(s)}</code> 秒（来自这次启动的上限）`)}
 ${wsgConsentRow('public_source_read', 'source', '同意读取公开来源', limits?.source_reads,
  (n, s) => `勾选表示：可以读取公开来源的原文，最多 <code>${esc(n)}</code> 次，总共最多 <code>${esc(s)}</code> 秒（来自这次启动的上限）`)}
 </section>`;
}

// ---------- run tab: words box, limits, validity, creation ----------
function wsgOpsAllowed(project) {
 const consent = project?.settings?.consent || {}, budgets = project?.settings?.budgets || {};
 return {
  query: consent.external_search === true && budgets.search_calls > 0 ? '' : '课题没勾「同意外部检索」，或检索额度是 0',
  source: consent.public_source_read === true && budgets.source_reads > 0 ? '' : '课题没勾「同意读取公开来源」，或读取额度是 0',
  'analyze-full-paper': budgets.model_calls > 0 ? '' : '课题的模型调用额度是 0',
  records: '', delivery: ''};
}
function wsgSelectedOps(project) {
 const form = wsgFormFor(rt.ref), allowed = wsgOpsAllowed(project);
 const base = form.ops || WSG_OPS.map(o => o[0]).filter(id => !allowed[id]);
 return base.filter(id => !allowed[id]);
}
function wsgSubmitGate(summary, project) {
 const form = wsgFormFor(rt.ref);
 if (wsgReadonlyNow()) return '这是历史归档，不能在这里改';
 const lock = typeof wsLock === 'function' ? wsLock() : '';
 if (lock) return lock;
 if (form.busy) return '正在提交，请稍等';
 if (!summary.grant_creation?.available) return WSG_REASONS[summary.grant_creation?.reason] || '现在不能创建运行许可';
 if (!form.words.trim()) return '请先写下你的授权理由（原话）';
 if (wsgBytes(form.words) > WSG_MAX_BYTES) return `授权理由超过 ${WSG_MAX_BYTES} 字节`;
 if (!wsgSelectedOps(project).length) return '至少选一项要做的操作';
 const max = summary.grant_creation.max_seconds, seconds = Number(form.seconds || max);
 if (!Number.isSafeInteger(seconds) || seconds < 1 || seconds > max) return `最长秒数要是 1 到 ${max} 的整数`;
 const actions = Number(form.actions);
 if (!Number.isSafeInteger(actions) || actions < 1 || actions > 512) return '动作数上限要是 1 到 512 的整数';
 if (!form.confirmed) return '请先勾选确认';
 return '';
}
function wsgReadonlyNow() { return typeof wsReadonly === 'function' && !!wsReadonly(); }
function wsgLimitsTable(limits, caption) {
 return `<table class="ws-limits"><caption>${esc(caption)}</caption><thead><tr>${WSG_LIMIT_NAMES.map(([, name]) => `<th scope="col">${name}</th>`).join('')}</tr></thead>
 <tbody><tr>${WSG_LIMIT_NAMES.map(([key]) => `<td><code>${esc(limits?.[key] ?? '未提供')}</code></td>`).join('')}</tr></tbody></table>`;
}
function wsgExisting(run) {
 const [kind, label] = WSG_STATUS[run.status] || WSG_STATUS.none;
 if (run.status === 'none') return '<p class="wiki-s1-muted">这个版本还没有运行许可。</p>';
 const rows = [];
 if (run.limits) rows.push(wsgLimitsTable(run.limits, '这份许可的上限'));
 const facts = [];
 if (run.operations) facts.push(['能做的操作', run.operations.map(id => (WSG_OPS.find(o => o[0] === id) || [id, id])[1]).join('、')]);
 if (run.max_actions != null) facts.push(['动作数', `${run.actions_used ?? 0} / ${run.max_actions}`]);
 if (run.expires_at != null) facts.push(['有效到', wsgFmtTime(run.expires_at) + (run.status === 'active' ? `（还剩 ${wsgDuration(run.remaining_seconds)}）` : '')]);
 if (run.lease?.state) facts.push(['许可租约', WSG_LEASE[run.lease.state] || '服务给了没见过的状态（原值见下方）']);
 if (run.user_input) facts.push(['你当时写的理由', run.user_input]);
 if (run.status === 'stale') facts.push(['说明', `这个课题换了版本，旧版本的 ${run.stale_count ?? ''} 份许可不再适用，不会续期`]);
 if (run.reason) facts.push(['说明', WSG_GRANT_REASONS[run.reason] || wsPlain(run.reason)]);
 const raw = wsRaw([run.reason, run.lease?.state && !WSG_LEASE[run.lease.state] ? run.lease.state : null]);
 return `<p>${wsTag(kind, label)}</p>${rows.join('')}<dl class="ws-grant-facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${raw}`;
}
function wsgResultNote(form) {
 const result = form.result;
 if (!result) return '';
 if (result.ok) return `<div class="ws-ok" role="status">${wsTag('done', '已创建')} ${result.replayed ? '同一个请求已保存过，没有重复创建。' : '运行许可已保存。'}有效到 ${esc(wsgFmtTime(result.expires_at))}。这只是授权，没有开始运行。</div>`;
 const extra = result.recorded ? ' 这次尝试已作为失败记录保存，重试会用新的请求键。' : ' 没有写入任何东西。';
 return `<div class="live-error ws-err" role="alert">${wsTag('err', '被拒绝')} ${esc(result.reason || '服务没有给出原因')}${extra}</div>`;
}
function wsgFormHtml(summary, project) {
 const form = wsgFormFor(rt.ref), allowed = wsgOpsAllowed(project), chosen = new Set(wsgSelectedOps(project));
 const max = summary.grant_creation.max_seconds, gate = wsgSubmitGate(summary, project);
 const bytes = wsgBytes(form.words);
 return `<div class="ws-grant-form">
 <label class="ws-wide ws-grant-words">只用于创建这份运行许可的授权理由（原话，必填，原样保存）<textarea data-wsg-words rows="3" placeholder="例如：我授权这一轮 Stage 1 只在上限内检索和读取，到上限就停。">${esc(form.words)}</textarea>
 <small data-wsg-count>${bytes > WSG_MAX_BYTES ? `超过 ${WSG_MAX_BYTES} 字节` : `${bytes} / ${WSG_MAX_BYTES} 字节。这句话只用于创建许可，不会用到别的授权。`}</small></label>
 <fieldset class="ws-grant-ops"><legend>这份许可允许做什么</legend>${WSG_OPS.map(([id, name]) => `<label class="ws-check"><input type="checkbox" data-wsg-op="${id}" ${chosen.has(id) ? 'checked' : ''} ${allowed[id] ? 'disabled' : ''}> <span>${esc(name)}${allowed[id] ? `<small class="ws-why" role="note">${esc(allowed[id])}</small>` : ''}</span></label>`).join('')}</fieldset>
 <div class="ws-grid"><label>最长总秒数（最多 ${esc(max)}）<input data-wsg-seconds type="number" min="1" max="${esc(max)}" value="${esc(form.seconds || max)}"></label>
 <label>动作数上限（最多 512）<input data-wsg-actions type="number" min="1" max="512" value="${esc(form.actions)}"></label></div>
 <p class="wiki-s1-muted">有效期最长 ${esc(wsgDuration(max))}（取这次启动的秒数上限、课题保存的秒数和服务的 3 小时上限里最小的）。过期不会自动续期。</p>
 <label class="ws-check"><input type="checkbox" data-wsg-confirm ${form.confirmed ? 'checked' : ''}> <span>我确认：这份许可只在上面的上限内、对这个课题的这个版本和这份检索计划有效。选方向和对评审的决定仍然由我本人做。</span></label>
 <div class="ws-actions">${wsBtn('创建 Stage 1 运行许可', 'data-wsg-submit', gate, 'hs-button-primary')}</div></div>`;
}
function wsgCardHtml() {
 const project = rt.overview?.project, cache = rt.wsg;
 const head = '<div class="ws-head"><h3>运行许可与授权理由</h3><small>创建许可只是授权，不会开始运行，也不会调用模型或检索。</small></div>';
 if (!project) return '';
 const limits = wsgLimits();
 const launch = limits ? wsgLimitsTable(limits, '这次启动的运行上限（许可不能超过它）') : '<p class="wiki-s1-muted">没有读到这次启动的运行上限。</p>';
 let body;
 if (wsgZero()) {
  body = `<div class="ws-quota ws-quota-gray" data-wsg-state="zero"><b>不能创建</b><span>${esc(WSG_REASONS['stage1-run-grant-zero-limits'])}</span></div>
  <div class="ws-actions">${wsBtn('创建 Stage 1 运行许可', 'data-wsg-submit', WSG_REASONS['stage1-run-grant-zero-limits'], 'hs-button-primary')}</div>`;
 } else if (!cache || cache.state === 'loading') body = '<p class="wiki-s1-muted" data-wsg-state="loading">正在读取运行许可状态…</p>';
 else if (cache.state === 'error') body = `<div class="live-error ws-err" role="alert" data-wsg-state="error">${wsTag('err', '没读到')} ${esc(cache.reason || '读取运行许可状态失败')}</div>`;
 else {
  const summary = cache.value, form = wsgFormFor(rt.ref);
  const consent = summary.consent || {}, stage1 = consent.stages?.stage1;
  const line = !consent.present ? '这次启动没有带同意书（逐步授权照常可用）' : consent.valid ? `同意书有效${stage1?.covered ? '，覆盖 Stage 1' : '，但没覆盖 Stage 1'}，有效到 ${wsgFmtTime(consent.expires_at)}` : `同意书用不了：${(typeof wsConsentBlocks === 'object' && wsConsentBlocks[consent.reason]?.[1]) || wsPlain(consent.reason)}`;
  body = `<p class="wiki-s1-muted" data-wsg-state="read">${esc(line)}</p>${consent.reason && !consent.valid && consent.present ? wsRaw(consent.reason) : ''}${wsgExisting(summary.run_grant || {status: 'none'})}${wsgResultNote(form)}
  ${summary.grant_creation?.available ? wsgFormHtml(summary, project) : `<div class="ws-quota ws-quota-gray"><b>现在不能创建</b><span>${esc(WSG_REASONS[summary.grant_creation?.reason] || summary.grant_creation?.reason || '服务没有给出原因')}</span></div>
  <div class="ws-actions">${wsBtn('创建 Stage 1 运行许可', 'data-wsg-submit', WSG_REASONS[summary.grant_creation?.reason] || '现在不能创建运行许可', 'hs-button-primary')}</div>`}`;
 }
 return `<section class="wiki-s1-card ws-rungrant" data-wsg-card aria-label="运行许可">${head}${launch}${body}</section>`;
}

// ---------- hooks into the existing Stage 1 page (nothing in wiki-stage1-ops.js is edited) ----------
function wsgKey() { const p = rt.overview?.project; return JSON.stringify([rt.ref, p?.input_version, p?.revision]); }
async function wsgLoad(force = false) {
 const key = wsgKey(), ref = rt.ref;
 if (!ref || !rt.overview?.project || wsgZero() || (!force && rt.wsg?.key === key)) return;
 rt.wsg = {key, state: 'loading'};
 let next;
 try {
  const response = await fetch(projectPath(ref, 'stage1-run-grant'), {headers: {Authorization: 'Bearer ' + window.RESEARCH_PROJECTS.credential}, cache: 'no-store', credentials: 'same-origin'});
  const value = await response.json().catch(() => ({}));
  next = response.ok ? {key, state: 'read', value} : {key, state: 'error', reason: value.reason || value.error || 'HTTP ' + response.status};
 } catch (error) { next = {key, state: 'error', reason: String(error.message || error)}; }
 if (ref !== rt.ref || wsgKey() !== key) return;
 rt.wsg = next;
 livePaint();
}
async function wsgSubmit() {
 const project = rt.overview?.project, cache = rt.wsg, form = wsgFormFor(rt.ref);
 if (!project || cache?.state !== 'read' || wsgSubmitGate(cache.value, project)) return;
 const max = cache.value.grant_creation.max_seconds, ref = rt.ref;
 form.key = form.key || 'wsg-' + (globalThis.crypto?.randomUUID?.() || String(Date.now()) + Math.random().toString(16).slice(2));
 form.busy = true; form.result = null; livePaint();
 const body = {key: form.key, input_version: project.input_version, brief_sha256: project.brief_sha256,
  plan_manifest_sha256: project.plan?.manifest_sha256, user_input: form.words, confirmed: true, operations: wsgSelectedOps(project),
  max_seconds: Number(form.seconds || max), max_actions: Number(form.actions)};
 try {
  const response = await fetch(projectPath(ref, 'stage1-run-grant'), {method: 'POST', cache: 'no-store', credentials: 'same-origin',
   headers: {Authorization: 'Bearer ' + window.RESEARCH_PROJECTS.credential, 'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const value = await response.json().catch(() => ({}));
  form.result = response.ok ? {ok: true, replayed: value.replayed, expires_at: value.expires_at}
   : {ok: false, reason: value.reason || value.error || 'HTTP ' + response.status, recorded: value.recorded_as_failed === true};
  form.key = null; // an answer arrived; the next attempt is a new request
 } catch (error) {
  form.result = {ok: false, reason: '没连上服务，结果不确定：先刷新看运行许可状态，不要重复提交', recorded: false};
 }
 form.busy = false;
 if (ref !== rt.ref) return;
 await wsgLoad(true);
 livePaint();
}
const wsgPrevScopePage = wsScopePage;
wsScopePage = function (app) {
 const html = wsgPrevScopePage(app);
 if (wsReadonly()) return html;
 const marker = '<section class="decide ws-decide"';
 const at = html.indexOf(marker);
 return at < 0 ? html : html.slice(0, at) + wsgConsentCard() + html.slice(at);
};
const wsgPrevRunTab = wsRunTab;
wsRunTab = function (app) {
 const html = wsgPrevRunTab(app);
 const marker = '<div class="ws-ps-head">';
 const at = html.indexOf(marker);
 return at < 0 ? html : html.slice(0, at) + wsgCardHtml() + html.slice(at);
};
function wsgPatchSubmit(app) {
 const cache = rt.wsg, project = rt.overview?.project;
 const button = app.el.querySelector('[data-wsg-submit]');
 if (!button || cache?.state !== 'read' || !project) return;
 const reason = wsgSubmitGate(cache.value, project);
 button.disabled = !!reason;
 const why = button.parentElement.querySelector('.ws-why');
 if (why) { why.textContent = reason; why.hidden = !reason; }
}
function wsgBoxHtml(app, action, needsConfirm) {
 const reason = wsgReasonFor(action), bytes = wsgBytes(reason.words);
 return `<div class="ws-reason" data-wsg-reason="${action}"><label>你的授权理由（原话，必填）<textarea data-wsg-reason-words="${action}" rows="2">${esc(reason.words)}</textarea>
 <small data-wsg-reason-count="${action}">${bytes > WSG_MAX_BYTES ? `超过 ${WSG_MAX_BYTES} 字节` : `${bytes} / ${WSG_MAX_BYTES} 字节`}</small></label>
 ${needsConfirm ? `<label class="ws-check"><input type="checkbox" data-wsg-reason-confirm="${action}" ${reason.confirmed ? 'checked' : ''}> <span>我确认：${esc(WSG_REASON_TITLES[action])}。理由只用于这一次，提交后清空。</span></label>` : '<small>理由只用于这一次，提交后清空。</small>'}
 <small class="ws-why" data-wsg-reason-why="${action}" role="note"></small></div>`;
}
function wsgApplyReasonGate(root, action) {
 for (const box of root.querySelectorAll(`[data-wsg-reason="${action}"]`)) {
  const button = box.parentElement.querySelector(WSG_REASON_BUTTONS[action]);
  if (!button) continue;
  const reason = wsgReasonGate(action);
  button.disabled = button.dataset.wsgBase === '1' || !!reason;
  const why = box.querySelector(`[data-wsg-reason-why="${action}"]`);
  why.textContent = reason; why.hidden = !reason;
  const count = box.querySelector(`[data-wsg-reason-count="${action}"]`), bytes = wsgBytes(wsgReasonFor(action).words);
  count.textContent = bytes > WSG_MAX_BYTES ? `超过 ${WSG_MAX_BYTES} 字节` : `${bytes} / ${WSG_MAX_BYTES} 字节`;
  const field = box.querySelector('[data-wsg-reason-words]');
  if (field && field !== document.activeElement && field.value !== wsgReasonFor(action).words) field.value = wsgReasonFor(action).words;
  const tick = box.querySelector('[data-wsg-reason-confirm]');
  if (tick) tick.checked = wsgReasonFor(action).confirmed;
 }
}
function wsgInjectReasons(app) {
 if (typeof wsReadonly === 'function' && wsReadonly()) return;
 // The plan card used to say the authorization has no reason item; it does now, and the box below collects it.
 for (const line of app.el.querySelectorAll('[data-ws-grant="plan"] p.wiki-s1-muted')) if (line.textContent.includes('授权理由：现在的授权接口没有理由')) line.hidden = true;
 for (const [action, selector] of Object.entries(WSG_REASON_BUTTONS)) {
  for (const button of app.el.querySelectorAll(selector)) {
   if (button.dataset.wsgPrepared === '1' || button.closest('[hidden]')) continue; // retired old controls stay untouched
   button.dataset.wsgPrepared = '1';
   const anchor = button.closest('.ws-actions') || button.closest('.ws-btn') || button;
   if (wsgLang(app) !== 'zh') {
    // The reason box lives on the Simplified Chinese page; here the button is off and says so (no fake entry).
    button.disabled = true;
    const note = document.createElement('small');
    note.className = 'ws-why';
    note.dataset.wsgLangNote = action;
    note.textContent = wsgText(app, '', 'Authorizing needs a reason box that only the Simplified Chinese page has. Switch the language to Simplified Chinese to authorize.', '授權需要填寫理由，理由框只在簡體中文頁面。請切換到簡體中文再授權。');
    anchor.after(note);
    continue;
   }
   button.dataset.wsgBase = button.disabled ? '1' : '0';
   // The plan card already has its own confirmation box; do not ask twice.
   const needsConfirm = !button.closest('[data-ws-grant]');
   wsgReasonFor(action).noConfirm = !needsConfirm;
   anchor.insertAdjacentHTML('beforebegin', wsgBoxHtml(app, action, needsConfirm));
   wsgApplyReasonGate(app.el, action);
  }
 }
 if (wsgLang(app) !== 'zh') {
  for (const button of app.el.querySelectorAll('[data-live-action="confirm"]')) {
   if (button.dataset.wsgPrepared === '1') continue;
   button.dataset.wsgPrepared = '1';
   const note = document.createElement('small');
   note.className = 'ws-why';
   note.textContent = wsgText(app, '', 'External search and public source consent can only be given on the Simplified Chinese page. Saving the scope here gives no search consent.', '外部檢索與公開來源的同意只能在簡體中文頁面勾選。在這裡保存範圍不會給出任何檢索同意。');
   (button.closest('.ws-btn') || button).after(note);
  }
 }
}
const wsgPrevAfter = v7AfterRender;
v7AfterRender = function (app) {
 wsgPrevAfter(app);
 wsgInjectReasons(app);
 if (!wsOpsActive(app) || !app.el.querySelector('[data-wiki-s1]')) return;
 if (app.el.querySelector('[data-wsg-card]')) wsgLoad();
};
document.addEventListener('input', event => {
 const target = event.target, app = apps[0];
 if (app && target.matches?.('[data-wsg-reason-words]')) {
  wsgReasonFor(target.dataset.wsgReasonWords).words = target.value;
  wsgApplyReasonGate(app.el, target.dataset.wsgReasonWords);
  return;
 }
 if (!app || !target.closest?.('[data-wsg-card]')) return;
 const form = wsgFormFor(rt.ref);
 if (target.matches('[data-wsg-words]')) {
  form.words = target.value;
  const count = target.parentElement.querySelector('[data-wsg-count]'), bytes = wsgBytes(form.words);
  if (count) count.textContent = bytes > WSG_MAX_BYTES ? `超过 ${WSG_MAX_BYTES} 字节` : `${bytes} / ${WSG_MAX_BYTES} 字节。这句话只用于创建许可，不会用到别的授权。`;
 } else if (target.matches('[data-wsg-seconds]')) form.seconds = target.value;
 else if (target.matches('[data-wsg-actions]')) form.actions = target.value;
 else return;
 wsgPatchSubmit(app);
});
document.addEventListener('change', event => {
 const target = event.target, form = wsgFormFor(rt.ref);
 if (target.matches?.('[data-wsg-reason-confirm]') && apps[0]) {
  wsgReasonFor(target.dataset.wsgReasonConfirm).confirmed = target.checked;
  wsgApplyReasonGate(apps[0].el, target.dataset.wsgReasonConfirm);
  return;
 }
 if (target.matches?.('[data-wsg-consent]')) {
  form[target.dataset.wsgConsent === 'external_search' ? 'search' : 'source'] = target.checked;
  livePaint();
 } else if (target.matches?.('[data-wsg-confirm]')) { form.confirmed = target.checked; livePaint(); }
 else if (target.matches?.('[data-wsg-op]')) {
  const chosen = new Set(wsgSelectedOps(rt.overview?.project));
  if (target.checked) chosen.add(target.dataset.wsgOp); else chosen.delete(target.dataset.wsgOp);
  form.ops = [...chosen];
  livePaint();
 }
});
document.addEventListener('click', event => {
 const button = event.target.closest?.('[data-wsg-submit]');
 if (button && !button.disabled) wsgSubmit();
});
