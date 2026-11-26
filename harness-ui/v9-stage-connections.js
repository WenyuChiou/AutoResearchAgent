// Discover only the current project. GET /connections does not include its input or revision.
const v9ConnectionStages = {2: 'stage2-controller', 3: 'stage3-planning'};
const v9ConnectionFields = ['project_ref', 'project_id', 'input_version', 'brief_sha256', 'revision'];
let v9ConnectionView = null, v9ConnectionWriting = false;
const v9ConnectionHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

function v9ConnectionBasis(project) {
  if (canonicalReadonly() || !project || project.project_ref !== rt.ref ||
      typeof project.project_ref !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(project.project_ref) ||
      typeof project.project_id !== 'string' || !project.project_id ||
      !(Number.isSafeInteger(project.input_version) && project.input_version > 0 ||
        typeof project.input_version === 'string' && project.input_version.trim() === project.input_version &&
        project.input_version.length > 0 && project.input_version.length <= 128) ||
      !Number.isSafeInteger(project.revision) || project.revision < 0 ||
      !v9ConnectionHash(project.brief_sha256)) return null;
  return Object.fromEntries(v9ConnectionFields.map(key => [key, project[key]]));
}
function v9ConnectionCurrent(view) {
  const basis = v9ConnectionBasis(rt.overview?.project), app = apps[0];
  return !!view && view === v9ConnectionView && !rt.loading && rt.epoch === view.epoch &&
    app?.page === 'workspace' && v9ConnectionStages[app.stage] === view.stage &&
    basis && v9ConnectionFields.every(key => basis[key] === view.basis[key]);
}
function v9ConnectionConnected(stage) {
  const view = v9ConnectionView;
  return v9ConnectionCurrent(view) && view.stage === stage && !view.error && !view.rejection &&
    !v9ConnectionPending() && view.row?.status === 'connected';
}
function v9ConnectionPending() {
  return rt.pending?.ref === rt.ref && rt.pending.path === projectPath(rt.ref, 'connections');
}
function v9ConnectionCanWrite() {
  try {
    return !rt.loading && !rt.busy && !rt.pending && !rt.controlHeld &&
      sessionStorage.getItem('v7-pending-action') === null && typeof globalThis.navigator?.locks?.request === 'function';
  } catch { return false; }
}
function v9LegacyConnection(stage) {
  const view=v9ConnectionView;
  return v9ConnectionCurrent(view) && view.stage===stage && view.legacyMissing && !v9ConnectionPending();
}
function v9AllowsCandidateRequest() {
  return v9ConnectionConnected('stage2-controller') || v9LegacyConnection('stage2-controller');
}
function v9ContinuationConflict() {
  return typeof wikiStage2State!=='undefined' && wikiStage2State?.error==='stage2-continuation-result-not-current' &&
    JSON.stringify(wikiStage2Basis())===JSON.stringify(wikiStage2State.basis);
}
async function v9ReadConnection(view) {
  const {basis, stage} = view;
  let response, missing;
  try { response = await liveRequest(projectPath(basis.project_ref, 'connections')); }
  catch (error) { if (error.status !== 404) throw error; missing = error; }
  // The initial overview came from liveRefresh. Bracket discovery with another overview.
  const fresh = v9ConnectionBasis((await liveRequest(projectPath(basis.project_ref, 'overview')))?.project);
  if (!v9ConnectionCurrent(view) || !fresh || !v9ConnectionFields.every(key => fresh[key] === basis[key]))
    throw Error('connection-project-binding-mismatch');
  if (missing) { view.legacyMissing = true; throw missing; }
  if (response?.project_ref !== basis.project_ref || response.execution_authorized !== false)
    throw Error('connection-project-binding-mismatch');
  const row = response.connections?.[stage];
  if (!Number.isSafeInteger(basis.input_version) && row?.profile_sha256 !== null) throw Error('connection-project-binding-mismatch');
  if (!row) throw Error('stage-connection-interface-unavailable');
  if ((row.reason != null && ['connected','connectable'].includes(row.status)) ||
      !['connectable', 'connected', 'consent-required', 'unavailable'].includes(row.status) ||
      (row.reason !== null && typeof row.reason !== 'string') ||
      (row.profile_sha256 !== null && !v9ConnectionHash(row.profile_sha256)) ||
      (row.status === 'connectable' && !v9ConnectionHash(row.profile_sha256)) ||
      (row.status === 'connected' && row.profile_sha256 !== null &&
        (!v9ConnectionHash(row.connection_id) || typeof row.receipt_id !== 'string' || !row.receipt_id)) ||
      (row.status === 'connected' && row.profile_sha256 === null &&
        (row.connection_id !== null || row.receipt_id !== null)) ||
      (row.status !== 'connected' && (row.connection_id !== null || row.receipt_id !== null)))
    throw Error('stage-connection-response-invalid');
  return row;
}
async function v9ConnectionRead(view) {
  if (!v9ConnectionCurrent(view) || view.reading) return;
  view.reading = true; view.legacyMissing=false; view.row = null; view.error = ''; livePaint();
  try { view.row = await v9ReadConnection(view); }
  catch (error) { view.error = error.message; view.http = error.status; }
  finally { view.reading = false; if (v9ConnectionCurrent(view)) livePaint(); }
}
function v9ConnectionReason(code, http) {
  if (code === 'stage2-continuation-activation-required')
    return rl('还差本项目的 Stage 2 启用同意。请查看本版启用记录并确认原提议。','Stage 2 needs your consent. Review this version’s activation record and confirm its original offer.');
  if (code === 'stage2-controller-current-input-required')
    return rl('还缺本课题已接收的 Stage 2 输入包和接收回执。请先查看 Stage 1 交付。','The current Stage 2 input packet and receiving receipt are required. Check the Stage 1 delivery.');
  if (code === 'stage3-current-selection-required')
    return rl('还缺本课题当前版本的正式选案和已核验的选案回执。','A verified formal selection and receipt for this version are required.');
  if (/^stage[23]-(controller|planning)-profile-unavailable$/.test(code))
    return rl('这次启动没有提供本阶段的运行配置。请在原项目目录用已核验的配置重开。','This launch lacks the stage configuration. Reopen the original project directory with the verified configuration.');
  if (code === 'stage2-continuation-result-not-current' || /^(?:connection-project-binding-mismatch|(?:stage[23]|stage-connection)-[a-z0-9-]*(?:binding-differs|project-stale|connection-differs|path-mismatch|current-input-differs|native-input-differs|receipt-differs))$/.test(code))
    return rl('本次核对与原记录不一致。若搬过目录，请回原物理目录，用原已核配置重开，先只读核对项目、整数输入版本、原包和回执。原路径无法恢复时保留记录，等待经核验的迁移入口。请勿重新执行、换请求键或手改回执。','The binding differs. If files moved, reopen the original physical directory with the verified configuration. Check the project, integer input version, original packet and receipt using read-only requests. If the path cannot be restored, retain the records for a verified migration. Do not rerun, change keys or edit receipts.');
  if (http === 404 || code === 'stage-connection-interface-unavailable')
    return rl('这次启动没有提供本阶段接通接口，暂时无法核验。','This launch does not expose the stage connection interface.');
  if (code === 'project-lock-busy' || code === 'project-lock-failed')
    return rl('暂时无法取得跨标签页项目锁。请稍后只读复核。','The project lock is unavailable. Check the saved state again later.');
  if (http === 403 || code === 'cross-site-rejected' || code === 'credential-rejected')
    return rl('访问被拒绝。请用原项目的已认证页面查看记录。','Access was refused. Check the records in the original authenticated project page.');
  return rl('原记录暂时无法核验。请保留现有记录，查看技术详情后再只读复核。','The original record could not be verified. Retain it and check the technical details before reading again.');
}
function v9ConnectionPanel(app) {
  if (app !== apps[0] || app.page !== 'workspace' || canonicalReadonly() || !rt.ref) return '';
  const stage = v9ConnectionStages[app.stage], basis = v9ConnectionBasis(rt.overview?.project);
  if (!stage) return '';
  const heading = 'Stage ' + app.stage + ' · ' + rl('本课题接通状态','Project connection');
  if (!basis || rt.loading) return '<section class="hs-panel"><h2>'+heading+'</h2><p>'+rl('等待核对本课题、整数输入版本和摘要。','Waiting for a verified project, integer input version and brief digest.')+'</p></section>';
  if (!v9ConnectionCurrent(v9ConnectionView)) {
    const next = {epoch: rt.epoch, basis, stage, reading: false, row: null, error: ''};
    v9ConnectionView = next;
    queueMicrotask(() => v9ConnectionRead(next));
  }
  const view = v9ConnectionView, row = view.row;
  const code = view.rejection || view.error || row?.reason, unknown = v9ConnectionPending();
  let message = rl('正在核对本课题的接通记录。','Checking this project’s saved connection.');
  if (unknown) message = rl('上次登记结果仍为 Unknown。保留原请求键和记录，当前接口缺少可核对该请求的回执。这里只能查询。','The last registration remains Unknown. Its key and record are retained. This interface lacks a verifiable request receipt. Only readback is available.');
  else if (view.rejection || view.error || row?.status === 'consent-required' || row?.status === 'unavailable') message = v9ConnectionReason(code, view.http);
  else if (row?.status === 'connected') message = rl('本课题已接通。已核对接通登记；执行与交付须另查原记录。','This project is connected. Registration was verified. Execution and delivery have separate records.');
  else if (row?.status === 'connectable') message = rl('本课题还没有接通。可以登记当前配置，登记不会启动研究。','This project is ready to connect. Registering the current configuration does not start research.');
  const token = rx(JSON.stringify([stage, view.epoch, ...Object.values(basis)]));
  const button = (action, label, disabled) => `<button type="button" class="hs-button" data-v9-connection="${action}" data-connection-basis="${token}" ${disabled?'disabled':''}>${label}</button>`;
  const controls = !unknown && !(stage==='stage2-controller'&&v9ContinuationConflict()) && !view.rejection && !view.error && row?.status === 'connectable'
    ? button('connect', rl('接通本课题','Connect this project'), !v9ConnectionCanWrite() || v9ConnectionWriting) : '';
  const lockHint = controls && typeof globalThis.navigator?.locks?.request !== 'function'
    ? rl('此浏览器缺少跨标签页项目锁，仅可查看。','This browser lacks cross-tab project locks. Readback is available.') : '';
  return `<section class="hs-panel" data-v9-connection-panel><h2>${heading}</h2><p role="status">${message} ${lockHint}</p>${controls}
    ${button('read', rl('重新核对接通记录','Check connection again'), view.reading || v9ConnectionWriting)}
    ${code ? '<details><summary>'+rl('技术详情','Technical details')+'</summary><code>'+rx(code)+'</code></details>' : ''}</section>`;
}
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-v9-connection]'), view = v9ConnectionView;
  if (!button || button.disabled || !v9ConnectionCurrent(view) || !apps[0].el.contains(button) ||
      button.dataset.connectionBasis !== JSON.stringify([view.stage, view.epoch, ...Object.values(view.basis)]) ||
      view.reading || v9ConnectionWriting) return;
  if (button.dataset.v9Connection === 'read') { view.rejection = ''; return v9ConnectionRead(view); }
  if (button.dataset.v9Connection !== 'connect' || !v9ConnectionCanWrite() ||
      view.stage==='stage2-controller' && v9ContinuationConflict() || view.rejection || view.error || view.row?.status !== 'connectable') return;
  const {basis, stage, row} = view;
  v9ConnectionWriting = true; livePaint();
  try {
    await navigator.locks.request('ara.stage2.transaction.v1.'+basis.project_ref, {mode:'exclusive', ifAvailable:true}, async lock => {
      if (!lock) throw Error('project-lock-busy');
      if (!v9ConnectionCurrent(view) || !v9ConnectionCanWrite()) return;
      const fresh = await v9ReadConnection(view);
      if (!v9ConnectionCurrent(view) || !v9ConnectionCanWrite()) return;
      view.row = fresh;
      if (fresh.status !== 'connectable' || stage==='stage2-controller' && v9ContinuationConflict()) return;
      if (fresh.profile_sha256 !== row.profile_sha256) throw Error('stage-connection-profile-differs');
      await livePost('connections', {revision:basis.revision, input_version:basis.input_version,
        brief_sha256:basis.brief_sha256, stage, profile_sha256:fresh.profile_sha256, confirmed:true}, basis.project_ref);
      // livePost refreshes overview and advances the epoch, and retains unknown intents.
      const next = v9ConnectionView;
      if (v9ConnectionCurrent(next) && next.stage === stage &&
          ['project_ref','project_id','input_version','brief_sha256'].every(key => basis[key] === next.basis[key])) {
        if (rt.error) { next.rejection = rt.error; next.error = rt.error; next.row = null; }
        else if (next === view) await v9ConnectionRead(next);
      }
    });
  } catch (error) {
    if (v9ConnectionCurrent(view)) { view.row = null; view.error = error.message || 'project-lock-failed'; view.http = error.status; }
  } finally { v9ConnectionWriting = false; livePaint(); }
});
